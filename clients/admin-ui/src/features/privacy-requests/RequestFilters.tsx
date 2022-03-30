import React from 'react';
import { useDispatch, useSelector } from 'react-redux';
import {
  Flex,
  Text,
  Button,
  Select,
  Input,
  InputGroup,
  InputLeftElement,
  InputLeftAddon,
  Stack,
} from '@fidesui/react';

import PIIToggle from './PIIToggle';
import {
  DownloadSolidIcon,
  CloseSolidIcon,
  SearchLineIcon,
} from '../common/Icon';
import { statusPropMap } from './RequestBadge';

import { PrivacyRequestStatus } from './types';
import {
  setRequestStatus,
  setRequestId,
  setRequestFrom,
  setRequestTo,
  clearAllFilters,
  selectPrivacyRequestFilters,
  requestCSVDownload,
} from './privacy-requests.slice';
import { selectUserToken } from '../user/user.slice';

const useRequestFilters = () => {
  const filters = useSelector(selectPrivacyRequestFilters);
  const token = useSelector(selectUserToken);
  const dispatch = useDispatch();
  const handleSearchChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    dispatch(setRequestId(event.target.value));
  };
  const handleStatusChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    dispatch(setRequestStatus(event.target.value as PrivacyRequestStatus));
  };
  const handleFromChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    dispatch(setRequestFrom(event?.target.value));
  };
  const handleToChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    dispatch(setRequestTo(event?.target.value));
  };
  const handleClearAllFilters = () => {
    dispatch(clearAllFilters());
  };
  const handleDownloadClick = () => {
    requestCSVDownload({ ...filters, token });
  };

  return {
    handleSearchChange,
    handleStatusChange,
    handleFromChange,
    handleToChange,
    handleClearAllFilters,
    handleDownloadClick,
    ...filters,
  };
};

const StatusOption: React.FC<{ status: PrivacyRequestStatus }> = ({
  status,
}) => <option value={status}>{statusPropMap[status].label}</option>;

const RequestFilters: React.FC = () => {
  const {
    status,
    handleSearchChange,
    handleStatusChange,
    handleFromChange,
    handleToChange,
    handleClearAllFilters,
    handleDownloadClick,
    id,
    from,
    to,
  } = useRequestFilters();
  return (
    <Stack direction="row" spacing={4} mb={6}>
      <Select
        placeholder="Status"
        size="sm"
        minWidth="144px"
        value={status || ''}
        onChange={handleStatusChange}
      >
        <StatusOption status="approved" />
        <StatusOption status="complete" />
        <StatusOption status="denied" />
        <StatusOption status="error" />
        <StatusOption status="in_processing" />
        <StatusOption status="paused" />
        <StatusOption status="pending" />
      </Select>
      <InputGroup size="sm">
        <InputLeftElement pointerEvents="none">
          <SearchLineIcon color="gray.300" w="17px" h="17px" />
        </InputLeftElement>
        <Input
          type="text"
          minWidth={200}
          placeholder="Search"
          size="sm"
          value={id}
          name="search"
          onChange={handleSearchChange}
        />
      </InputGroup>
      <InputGroup size="sm">
        <InputLeftAddon>From</InputLeftAddon>
        <Input
          type="date"
          name="From"
          value={from}
          onChange={handleFromChange}
        />
      </InputGroup>
      <InputGroup size="sm">
        <InputLeftAddon>To</InputLeftAddon>
        <Input type="date" name="To" value={to} onChange={handleToChange} />
      </InputGroup>
      <Flex flexShrink={0} alignItems="center">
        <Text fontSize="xs" mr={2} size="sm">
          Reveal PII
        </Text>
        <PIIToggle />
      </Flex>
      <Button
        variant="ghost"
        flexShrink={0}
        rightIcon={<DownloadSolidIcon />}
        size="sm"
        onClick={handleDownloadClick}
      >
        Download
      </Button>
      <Button
        variant="ghost"
        flexShrink={0}
        rightIcon={<CloseSolidIcon />}
        size="sm"
        onClick={handleClearAllFilters}
      >
        Clear all filters
      </Button>
    </Stack>
  );
};

export default RequestFilters;
