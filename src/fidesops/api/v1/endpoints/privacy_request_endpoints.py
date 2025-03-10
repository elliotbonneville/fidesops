import io
import csv

import logging
from collections import defaultdict
from datetime import date, datetime
from starlette.responses import StreamingResponse
from typing import List, Optional, Union, DefaultDict, Dict, Set, Callable, Any

from fastapi import APIRouter, Body, Depends, Security, HTTPException
from fastapi_pagination import Page, Params
from fastapi_pagination.bases import AbstractPage
from fastapi_pagination.ext.sqlalchemy import paginate
from pydantic import conlist
from sqlalchemy.orm import Session, Query
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_424_FAILED_DEPENDENCY,
)

from fidesops import common_exceptions
from fidesops.api import deps
from fidesops.api.v1 import scope_registry as scopes
from fidesops.api.v1 import urn_registry as urls
from fidesops.api.v1.scope_registry import (
    PRIVACY_REQUEST_READ,
    PRIVACY_REQUEST_REVIEW,
)
from fidesops.api.v1.urn_registry import (
    REQUEST_PREVIEW,
    PRIVACY_REQUEST_RESUME,
    PRIVACY_REQUEST_APPROVE,
    PRIVACY_REQUEST_DENY,
)
from fidesops.common_exceptions import (
    TraversalError,
    ValidationError,
)
from fidesops.core.config import config
from fidesops.graph.config import CollectionAddress
from fidesops.graph.graph import DatasetGraph
from fidesops.graph.traversal import Traversal
from fidesops.models.client import ClientDetail
from fidesops.models.connectionconfig import ConnectionConfig
from fidesops.models.datasetconfig import DatasetConfig
from fidesops.models.policy import Policy, ActionType, PolicyPreWebhook
from fidesops.models.privacy_request import (
    ExecutionLog,
    PrivacyRequest,
    PrivacyRequestStatus,
)
from fidesops.schemas.dataset import DryRunDatasetResponse, CollectionAddressResponse
from fidesops.schemas.external_https import (
    PrivacyRequestResumeFormat,
)
from fidesops.schemas.masking.masking_configuration import MaskingConfiguration
from fidesops.schemas.masking.masking_secrets import MaskingSecretCache
from fidesops.schemas.policy import Rule
from fidesops.schemas.privacy_request import (
    PrivacyRequestCreate,
    PrivacyRequestResponse,
    PrivacyRequestVerboseResponse,
    ExecutionLogDetailResponse,
    BulkPostPrivacyRequests,
    BulkReviewResponse,
    ReviewPrivacyRequestIds,
)
from fidesops.service.masking.strategy.masking_strategy_factory import (
    get_strategy,
)
from fidesops.service.privacy_request.request_runner_service import PrivacyRequestRunner
from fidesops.task.graph_task import collect_queries, EMPTY_REQUEST
from fidesops.task.task_resources import TaskResources
from fidesops.util.cache import FidesopsRedis
from fidesops.util.oauth_util import verify_oauth_client, verify_callback_oauth

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Privacy Requests"], prefix=urls.V1_URL_PREFIX)
EMBEDDED_EXECUTION_LOG_LIMIT = 50


def get_privacy_request_or_error(
    db: Session, privacy_request_id: str
) -> PrivacyRequest:
    """Load the privacy request or throw a 404"""
    logger.info(f"Finding privacy request with id '{privacy_request_id}'")

    privacy_request = PrivacyRequest.get(db, id=privacy_request_id)

    if not privacy_request:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=f"No privacy request found with id '{privacy_request_id}'.",
        )

    return privacy_request


@router.post(
    urls.PRIVACY_REQUESTS,
    status_code=200,
    response_model=BulkPostPrivacyRequests,
)
def create_privacy_request(
    *,
    cache: FidesopsRedis = Depends(deps.get_cache),
    db: Session = Depends(deps.get_db),
    data: conlist(PrivacyRequestCreate, max_items=50) = Body(...),  # type: ignore
) -> BulkPostPrivacyRequests:
    """
    Given a list of privacy request data elements, create corresponding PrivacyRequest objects
    or report failure and execute them within the Fidesops system.

    You cannot update privacy requests after they've been created.
    """
    created = []
    failed = []
    # Optional fields to validate here are those that are both nullable in the DB, and exist
    # on the Pydantic schema

    logger.info(f"Starting creation for {len(data)} privacy requests")

    optional_fields = ["external_id", "started_processing_at", "finished_processing_at"]
    for privacy_request_data in data:
        if not any(privacy_request_data.identity.dict().values()):
            logger.warning(
                "Create failed for privacy request with no identity provided"
            )
            failure = {
                "message": "You must provide at least one identity to process",
                "data": privacy_request_data,
            }
            failed.append(failure)
            continue

        logger.info(f"Finding policy with key '{privacy_request_data.policy_key}'")
        policy = Policy.get_by(
            db=db,
            field="key",
            value=privacy_request_data.policy_key,
        )
        if policy is None:
            logger.warning(
                f"Create failed for privacy request with invalid policy key {privacy_request_data.policy_key}'"
            )

            failure = {
                "message": f"Policy with key {privacy_request_data.policy_key} does not exist",
                "data": privacy_request_data,
            }
            failed.append(failure)
            continue

        kwargs = {
            "requested_at": privacy_request_data.requested_at,
            "policy_id": policy.id,
            "status": "pending",
        }
        for field in optional_fields:
            attr = getattr(privacy_request_data, field)
            if attr is not None:
                kwargs[field] = attr

        try:
            privacy_request = PrivacyRequest.create(db=db, data=kwargs)

            # Store identity in the cache
            logger.info(f"Caching identity for privacy request {privacy_request.id}")
            privacy_request.cache_identity(privacy_request_data.identity)
            privacy_request.cache_encryption(privacy_request_data.encryption_key)

            # Store masking secrets in the cache
            logger.info(
                f"Caching masking secrets for privacy request {privacy_request.id}"
            )
            erasure_rules: List[Rule] = policy.get_rules_for_action(
                action_type=ActionType.erasure
            )
            unique_masking_strategies_by_name: Set[str] = set()
            for rule in erasure_rules:
                strategy_name: str = rule.masking_strategy["strategy"]
                configuration: MaskingConfiguration = rule.masking_strategy[
                    "configuration"
                ]
                if strategy_name in unique_masking_strategies_by_name:
                    continue
                unique_masking_strategies_by_name.add(strategy_name)
                masking_strategy = get_strategy(strategy_name, configuration)
                if masking_strategy.secrets_required():
                    masking_secrets: List[
                        MaskingSecretCache
                    ] = masking_strategy.generate_secrets_for_cache()
                    for masking_secret in masking_secrets:
                        privacy_request.cache_masking_secret(masking_secret)

            if not config.execution.REQUIRE_MANUAL_REQUEST_APPROVAL:
                PrivacyRequestRunner(
                    cache=cache,
                    privacy_request=privacy_request,
                ).submit()

        except common_exceptions.RedisConnectionError as exc:
            logger.error("RedisConnectionError: %s", exc)
            # Thrown when cache.ping() fails on cache connection retrieval
            raise HTTPException(
                status_code=HTTP_424_FAILED_DEPENDENCY,
                detail=exc.args[0],
            )
        except Exception as exc:
            logger.error("Exception: %s", exc)
            failure = {
                "message": "This record could not be added",
                "data": kwargs,
            }
            failed.append(failure)
        else:
            created.append(privacy_request)

    return BulkPostPrivacyRequests(
        succeeded=created,
        failed=failed,
    )


def privacy_request_csv_download(privacy_request_query: Query) -> StreamingResponse:
    """Download privacy requests as CSV for Admin UI"""
    f = io.StringIO()
    csv_file = csv.writer(f)

    csv_file.writerow(
        [
            "Time received",
            "Subject identity",
            "Policy key",
            "Request status",
            "Reviewer",
            "Time approved/denied",
        ]
    )

    for pr in privacy_request_query:
        csv_file.writerow(
            [
                pr.created_at,
                pr.get_cached_identity_data(),
                pr.policy.key if pr.policy else None,
                pr.status.value if pr.status else None,
                pr.reviewed_by,
                pr.reviewed_at,
            ]
        )
    f.seek(0)
    response = StreamingResponse(f, media_type="text/csv")
    response.headers[
        "Content-Disposition"
    ] = f"attachment; filename=privacy_requests_download_{datetime.today().strftime('%Y-%m-%d')}.csv"
    return response


@router.get(
    urls.PRIVACY_REQUESTS,
    dependencies=[Security(verify_oauth_client, scopes=[scopes.PRIVACY_REQUEST_READ])],
    response_model=Page[
        Union[
            PrivacyRequestVerboseResponse,
            PrivacyRequestResponse,
        ]
    ],
)
def get_request_status(
    *,
    db: Session = Depends(deps.get_db),
    params: Params = Depends(),
    id: Optional[str] = None,
    status: Optional[PrivacyRequestStatus] = None,
    created_lt: Optional[Union[date, datetime]] = None,
    created_gt: Optional[Union[date, datetime]] = None,
    started_lt: Optional[Union[date, datetime]] = None,
    started_gt: Optional[Union[date, datetime]] = None,
    completed_lt: Optional[Union[date, datetime]] = None,
    completed_gt: Optional[Union[date, datetime]] = None,
    errored_lt: Optional[Union[date, datetime]] = None,
    errored_gt: Optional[Union[date, datetime]] = None,
    external_id: Optional[str] = None,
    verbose: Optional[bool] = False,
    include_identities: Optional[bool] = False,
    download_csv: Optional[bool] = False,
) -> Union[StreamingResponse, AbstractPage[PrivacyRequest]]:
    """Returns PrivacyRequest information. Supports a variety of optional query params.

    To fetch a single privacy request, use the id query param `?id=`.
    To see individual execution logs, use the verbose query param `?verbose=True`.
    """

    if any([completed_lt, completed_gt]) and any([errored_lt, errored_gt]):
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Cannot specify both succeeded and failed query params.",
        )

    query = db.query(PrivacyRequest)

    # Further restrict all PrivacyRequests by query params
    if id:
        query = query.filter(PrivacyRequest.id.ilike(f"{id}%"))
    if external_id:
        query = query.filter(PrivacyRequest.external_id.ilike(f"{external_id}%"))
    if status:
        query = query.filter(PrivacyRequest.status == status)
    if created_lt:
        query = query.filter(PrivacyRequest.created_at < created_lt)
    if created_gt:
        query = query.filter(PrivacyRequest.created_at > created_gt)
    if started_lt:
        query = query.filter(PrivacyRequest.started_processing_at < started_lt)
    if started_gt:
        query = query.filter(PrivacyRequest.started_processing_at > started_gt)
    if completed_lt:
        query = query.filter(
            PrivacyRequest.status == PrivacyRequestStatus.complete.value,
            PrivacyRequest.finished_processing_at < completed_lt,
        )
    if completed_gt:
        query = query.filter(
            PrivacyRequest.status == PrivacyRequestStatus.complete.value,
            PrivacyRequest.finished_processing_at > completed_gt,
        )
    if errored_lt:
        query = query.filter(
            PrivacyRequest.status == PrivacyRequestStatus.error.value,
            PrivacyRequest.finished_processing_at < errored_lt,
        )
    if errored_gt:
        query = query.filter(
            PrivacyRequest.status == PrivacyRequestStatus.error.value,
            PrivacyRequest.finished_processing_at > errored_gt,
        )

    if download_csv:
        # Returning here if download_csv param was specified
        logger.info("Downloading privacy requests as csv")
        return privacy_request_csv_download(query)

    # Conditionally embed execution log details in the response.
    if verbose:
        logger.info(f"Finding execution log details")
        PrivacyRequest.execution_logs_by_dataset = property(
            execution_logs_by_dataset_name
        )
    else:
        PrivacyRequest.execution_logs_by_dataset = property(lambda self: None)

    query = query.order_by(PrivacyRequest.created_at.desc())

    paginated = paginate(query, params)
    if include_identities:
        # Conditionally include the cached identity data in the response if
        # it is explicitly requested
        for item in paginated.items:
            item.identity = item.get_cached_identity_data()

    logger.info(f"Finding all request statuses with pagination params {params}")
    return paginated


def execution_logs_by_dataset_name(
    self: PrivacyRequest,
) -> DefaultDict[str, List["ExecutionLog"]]:
    """
    Returns a truncated list of ExecutionLogs for each dataset name associated with
    a PrivacyRequest. Added as a conditional property to the PrivacyRequest class at runtime to
    show optionally embedded execution logs.

    An example response might include your execution logs from your mongo db in one group, and execution logs from
    your postgres db in a different group.
    """

    execution_logs: DefaultDict[str, List["ExecutionLog"]] = defaultdict(list)

    for log in self.execution_logs.order_by(
        ExecutionLog.dataset_name, ExecutionLog.updated_at.asc()
    ):
        if len(execution_logs[log.dataset_name]) > EMBEDDED_EXECUTION_LOG_LIMIT - 1:
            continue
        execution_logs[log.dataset_name].append(log)
    return execution_logs


@router.get(
    urls.REQUEST_STATUS_LOGS,
    dependencies=[Security(verify_oauth_client, scopes=[scopes.PRIVACY_REQUEST_READ])],
    response_model=Page[ExecutionLogDetailResponse],
)
def get_request_status_logs(
    privacy_request_id: str,
    *,
    db: Session = Depends(deps.get_db),
    params: Params = Depends(),
) -> AbstractPage[ExecutionLog]:
    """Returns all the execution logs associated with a given privacy request ordered by updated asc."""

    get_privacy_request_or_error(db, privacy_request_id)

    logger.info(
        f"Finding all execution logs for privacy request {privacy_request_id} with params '{params}'"
    )

    return paginate(
        ExecutionLog.query(db=db)
        .filter(ExecutionLog.privacy_request_id == privacy_request_id)
        .order_by(ExecutionLog.updated_at.asc()),
        params,
    )


@router.put(
    REQUEST_PREVIEW,
    status_code=200,
    response_model=List[DryRunDatasetResponse],
    dependencies=[Security(verify_oauth_client, scopes=[PRIVACY_REQUEST_READ])],
)
def get_request_preview_queries(
    *,
    db: Session = Depends(deps.get_db),
    dataset_keys: Optional[List[str]] = Body(None),
) -> List[DryRunDatasetResponse]:
    """Returns dry run queries given a list of dataset ids.  If a dataset references another dataset, both dataset
    keys must be in the request body."""
    dataset_configs: List[DatasetConfig] = []
    if not dataset_keys:
        dataset_configs = DatasetConfig.all(db=db)
        if not dataset_configs:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"No datasets could be found",
            )
    else:
        for dataset_key in dataset_keys:
            dataset_config = DatasetConfig.get_by(
                db=db, field="fides_key", value=dataset_key
            )
            if not dataset_config:
                raise HTTPException(
                    status_code=HTTP_404_NOT_FOUND,
                    detail=f"No dataset with id '{dataset_key}'",
                )
            dataset_configs.append(dataset_config)
    try:
        connection_configs: List[ConnectionConfig] = [
            ConnectionConfig.get(db=db, id=dataset.connection_config_id)
            for dataset in dataset_configs
        ]

        try:
            dataset_graph: DatasetGraph = DatasetGraph(
                *[dataset.get_graph() for dataset in dataset_configs]
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=f"{exc}. Make sure all referenced datasets are included in the request body.",
            )

        identity_seed: Dict[str, str] = {
            k: "something" for k in dataset_graph.identity_keys.values()
        }
        traversal: Traversal = Traversal(dataset_graph, identity_seed)
        queries: Dict[CollectionAddress, str] = collect_queries(
            traversal,
            TaskResources(EMPTY_REQUEST, Policy(), connection_configs),
        )
        return [
            DryRunDatasetResponse(
                collectionAddress=CollectionAddressResponse(
                    dataset=key.dataset, collection=key.collection
                ),
                query=value,
            )
            for key, value in queries.items()
        ]
    except TraversalError as err:
        logger.info(f"Dry run failed: {err}")
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Dry run failed",
        )


@router.post(
    PRIVACY_REQUEST_RESUME, status_code=200, response_model=PrivacyRequestResponse
)
def resume_privacy_request(
    privacy_request_id: str,
    *,
    db: Session = Depends(deps.get_db),
    cache: FidesopsRedis = Depends(deps.get_cache),
    webhook: PolicyPreWebhook = Security(
        verify_callback_oauth, scopes=[scopes.PRIVACY_REQUEST_CALLBACK_RESUME]
    ),
    webhook_callback: PrivacyRequestResumeFormat,
) -> PrivacyRequestResponse:
    """Resume running a privacy request after it was paused by a Pre-Execution webhook"""
    privacy_request = get_privacy_request_or_error(db, privacy_request_id)
    privacy_request.cache_identity(webhook_callback.derived_identity)

    if privacy_request.status != PrivacyRequestStatus.paused:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail=f"Invalid resume request: privacy request '{privacy_request.id}' status = {privacy_request.status.value}.",
        )

    logger.info(
        f"Resuming privacy request '{privacy_request_id}' from webhook '{webhook.key}'"
    )

    privacy_request.status = PrivacyRequestStatus.in_processing
    privacy_request.save(db=db)

    PrivacyRequestRunner(
        cache=cache,
        privacy_request=privacy_request,
    ).submit(from_webhook=webhook)

    return privacy_request


def review_privacy_request(
    db: Session, cache: FidesopsRedis, request_ids: List[str], process_request: Callable
) -> BulkReviewResponse:
    """Helper method shared between the approve and deny privacy request endpoints"""
    succeeded: List[PrivacyRequest] = []
    failed: List[Dict[str, Any]] = []

    for request_id in request_ids:
        privacy_request = PrivacyRequest.get(db, id=request_id)
        if not privacy_request:
            failed.append(
                {
                    "message": f"No privacy request found with id '{request_id}'",
                    "data": {"privacy_request_id": request_id},
                }
            )
            continue

        if privacy_request.status != PrivacyRequestStatus.pending:
            failed.append(
                {
                    "message": f"Cannot transition status",
                    "data": PrivacyRequestResponse.from_orm(privacy_request),
                }
            )
            continue

        try:
            process_request(privacy_request, cache)
        except Exception:
            failure = {
                "message": "Privacy request could not be updated",
                "data": PrivacyRequestResponse.from_orm(privacy_request),
            }
            failed.append(failure)
        else:
            succeeded.append(privacy_request)

    return BulkReviewResponse(
        succeeded=succeeded,
        failed=failed,
    )


@router.patch(
    PRIVACY_REQUEST_APPROVE,
    status_code=200,
    response_model=BulkReviewResponse,
)
def approve_privacy_request(
    *,
    db: Session = Depends(deps.get_db),
    cache: FidesopsRedis = Depends(deps.get_cache),
    client: ClientDetail = Security(
        verify_oauth_client,
        scopes=[PRIVACY_REQUEST_REVIEW],
    ),
    privacy_requests: ReviewPrivacyRequestIds,
) -> BulkReviewResponse:
    """Approve and dispatch a list of privacy requests and/or report failure"""
    user_id = client.user_id

    def _process_request(privacy_request: PrivacyRequest, cache: FidesopsRedis) -> None:
        """Method for how to process requests - approved"""
        privacy_request.status = PrivacyRequestStatus.approved
        privacy_request.reviewed_at = datetime.utcnow()
        privacy_request.reviewed_by = user_id
        privacy_request.save(db=db)

        PrivacyRequestRunner(
            cache=cache,
            privacy_request=privacy_request,
        ).submit()

    return review_privacy_request(
        db, cache, privacy_requests.request_ids, _process_request
    )


@router.patch(
    PRIVACY_REQUEST_DENY,
    status_code=200,
    response_model=BulkReviewResponse,
)
def deny_privacy_request(
    *,
    db: Session = Depends(deps.get_db),
    cache: FidesopsRedis = Depends(deps.get_cache),
    client: ClientDetail = Security(
        verify_oauth_client,
        scopes=[PRIVACY_REQUEST_REVIEW],
    ),
    privacy_requests: ReviewPrivacyRequestIds,
) -> BulkReviewResponse:
    """Deny a list of privacy requests and/or report failure"""
    user_id = client.user_id

    def _process_request(privacy_request: PrivacyRequest, _: FidesopsRedis) -> None:
        """Method for how to process requests - denied"""
        privacy_request.status = PrivacyRequestStatus.denied
        privacy_request.reviewed_at = datetime.utcnow()
        privacy_request.reviewed_by = user_id
        privacy_request.save(db=db)

    return review_privacy_request(
        db, cache, privacy_requests.request_ids, _process_request
    )
