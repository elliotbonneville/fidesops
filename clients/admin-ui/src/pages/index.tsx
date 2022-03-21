import React from 'react';
import type { GetServerSideProps, NextPage } from 'next';
import Head from 'next/head';
import { getSession, useSession } from 'next-auth/react';
import { Session } from 'next-auth';
import { Flex, Heading, Text, Button, Select, Box } from '@fidesui/react';

import Header from '../features/common/Header';

import {
  ArrowDownLineIcon,
  DownloadSolidIcon,
  CloseSolidIcon,
} from '../features/common/Icon';

import RequestTable from '../features/subject-requests/RequestTable';

import { useGetAllSubjectRequestsQuery } from '../features/subject-requests/subject-requests.slice';

const Home: NextPage<{ session: Session | null }> = ({ session }) => {
  const { status } = useSession();
  const { data: requests } = useGetAllSubjectRequestsQuery(null);
  return (
    <div>
      <Head>
        <title>Fides Admin UI</title>
        <meta name="description" content="Generated from FidesUI template" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <Header />

      <main>
        <Flex
          borderBottom="1px"
          borderTop="1px"
          px={9}
          py={1}
          borderColor="gray.100"
        >
          <Button variant="ghost" mr={4} colorScheme="complimentary">
            Subject Requests
          </Button>
          <Button variant="ghost" mr={4}>
            Datastore Connections
          </Button>
          <Button variant="ghost" mr={4}>
            User Management
          </Button>
          <Button variant="ghost" rightIcon={<ArrowDownLineIcon />}>
            More
          </Button>
        </Flex>
        <Box px={9} py={10}>
          <Heading mb={8} fontSize="2xl" fontWeight="semibold">
            Subject Requests
          </Heading>
          <Flex mb={6} justifyContent="space-between">
            <Flex>
              <Select placeholder="Status" width={229} mr={4} />
              <Select placeholder="Reviewer" width={404} />
            </Flex>
            <Flex>
              <Button variant="ghost" rightIcon={<DownloadSolidIcon />}>
                Download
              </Button>
              <Button variant="ghost" rightIcon={<CloseSolidIcon />}>
                Clear all filters
              </Button>
            </Flex>
          </Flex>
          <RequestTable />
          <Flex justifyContent="space-between" mt={6}>
            <Text fontSize="xs" color="gray.600">
              {requests.length} results
            </Text>
            <div>
              <Button disabled mr={2}>
                Previous
              </Button>
              <Button disabled>Next</Button>
            </div>
          </Flex>
        </Box>
      </main>
    </div>
  );
};

export const getServerSideProps: GetServerSideProps = async (context) => {
  const session = await getSession(context);
  return {
    props: {
      session,
    },
  };
};

export default Home;
