import hashlib
from typing import Optional, List, Dict

from fidesops.core.config import config
from fidesops.schemas.masking.masking_configuration import (
    HashMaskingConfiguration,
    MaskingConfiguration,
)
from fidesops.schemas.masking.masking_secrets import (
    MaskingSecretCache,
    SecretType,
    MaskingSecretMeta,
)
from fidesops.schemas.masking.masking_strategy_description import (
    MaskingStrategyDescription,
    MaskingStrategyConfigurationDescription,
)
from fidesops.service.masking.strategy.format_preservation import FormatPreservation
from fidesops.service.masking.strategy.masking_strategy import MaskingStrategy
from fidesops.util.encryption.secrets_util import SecretsUtil

HASH = "hash"


class HashMaskingStrategy(MaskingStrategy):
    """Masks a value by hashing it"""

    def __init__(
        self,
        configuration: HashMaskingConfiguration,
    ):
        self.algorithm = configuration.algorithm
        if self.algorithm == HashMaskingConfiguration.Algorithm.SHA_256:
            self.algorithm_function = self._hash_sha256
        elif self.algorithm == HashMaskingConfiguration.Algorithm.SHA_512:
            self.algorithm_function = self._hash_sha512
        self.format_preservation = configuration.format_preservation

    def mask(
        self, value: Optional[str], privacy_request_id: Optional[str]
    ) -> Optional[str]:
        """Returns the hashed version of the provided value. Returns None if the provided value
        is None"""
        if value is None:
            return None
        masking_meta: Dict[
            SecretType, MaskingSecretMeta
        ] = self._build_masking_secret_meta()
        salt: str = SecretsUtil.get_or_generate_secret(
            privacy_request_id,
            SecretType.salt,
            masking_meta[SecretType.salt],
        )
        masked: str = self.algorithm_function(value, salt)
        if self.format_preservation is not None:
            formatter = FormatPreservation(self.format_preservation)
            return formatter.format(masked)
        return masked

    def secrets_required(self) -> bool:
        return True

    def generate_secrets_for_cache(self) -> List[MaskingSecretCache]:
        masking_meta: Dict[
            SecretType, MaskingSecretMeta
        ] = self._build_masking_secret_meta()
        return SecretsUtil.build_masking_secrets_for_cache(masking_meta)

    @staticmethod
    def get_configuration_model() -> MaskingConfiguration:
        return HashMaskingConfiguration

    # MR Note - We will need a way to ensure that this does not fall out of date. Given that it
    # includes subjective instructions, this is not straightforward to automate
    @staticmethod
    def get_description() -> MaskingStrategyDescription:
        return MaskingStrategyDescription(
            name=HASH,
            description="Masks the input value by returning a hashed version of the input value",
            configurations=[
                MaskingStrategyConfigurationDescription(
                    key="algorithm",
                    description="Specifies the hashing algorithm to be used. Can be SHA-256 or "
                    "SHA-512. If not provided, default is SHA-256",
                ),
                MaskingStrategyConfigurationDescription(
                    key="format_preservation",
                    description="Option to preserve format in masking, with a provided suffix",
                ),
            ],
        )

    @staticmethod
    def data_type_supported(data_type: Optional[str]) -> bool:
        """Determines whether or not the given data type is supported by this masking strategy"""
        supported_data_types = {"string"}
        return data_type in supported_data_types

    # Helpers

    @staticmethod
    def _hash_sha256(value: str, salt: str) -> str:
        return hashlib.sha256(
            (value + salt).encode(config.security.ENCODING)
        ).hexdigest()

    @staticmethod
    def _hash_sha512(value: str, salt: str) -> str:
        return hashlib.sha512(
            (value + salt).encode(config.security.ENCODING)
        ).hexdigest()

    @staticmethod
    def _build_masking_secret_meta() -> Dict[SecretType, MaskingSecretMeta]:
        return {
            SecretType.salt: MaskingSecretMeta[str](
                masking_strategy=HASH,
                generate_secret_func=SecretsUtil.generate_secret_string,
            )
        }
