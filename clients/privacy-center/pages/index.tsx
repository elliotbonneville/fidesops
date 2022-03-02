import React, {
  createContext,
  useState,
  Dispatch,
  SetStateAction,
  useMemo,
} from 'react';
import type { NextPage } from 'next';
import Head from 'next/head';
import { Session } from 'next-auth';
import {
  Flex,
  Heading,
  Text,
  Stack,
  Box,
  Grid,
  Alert,
  AlertIcon,
  AlertDescription,
  CloseButton,
} from '@fidesui/react';
import Image from 'next/image';

import { useRequestModal, RequestModal } from '../components/RequestModal';

import config from '../config/config.json';

import type { AlertState } from '../lib/types/AlertState';

export const alertContext = createContext<{
  alert: AlertState | null;
  setAlert: Dispatch<SetStateAction<AlertState | null>>;
}>({
  alert: null,
  setAlert: () => {},
});

const Home: NextPage<{ session: Session }> = () => {
  const { onClose, onOpen, isOpen, openAction } = useRequestModal();
  const [alert, setAlert] = useState<AlertState | null>(null);
  const alertContextValue = useMemo(() => ({ alert, setAlert }), [alert]);
  return (
    <div>
      <Head>
        <title>FidesUI App</title>
        <meta name="description" content="Generated from FidesUI template" />
        <link rel="icon" href="/favicon.ico" />
      </Head>

      <header>
        <Flex
          bg="gray.100"
          minHeight={14}
          px={1}
          py={1}
          width="100%"
          justifyContent="center"
          alignItems="center"
        >
          {alert ? (
            <Alert
              status={alert.status}
              minHeight={14}
              maxWidth="5xl"
              zIndex={1}
            >
              <AlertIcon />
              <AlertDescription>{alert.description}</AlertDescription>
              <CloseButton
                position="absolute"
                right="8px"
                onClick={() => setAlert(null)}
              />
            </Alert>
          ) : (
            <Image src="/logo.svg" height="56px" width="304px" alt="Logo" />
          )}
        </Flex>
      </header>
      <alertContext.Provider value={alertContextValue}>
        <main>
          <Stack align="center" py={['6', '16']} px={5} spacing={8}>
            <Stack align="center" spacing={3}>
              <Heading
                fontSize={['3xl', '4xl']}
                color="gray.600"
                fontWeight="semibold"
                textAlign="center"
              >
                {config.title}
              </Heading>
              <Text
                fontSize={['small', 'medium']}
                fontWeight="medium"
                maxWidth={624}
                textAlign="center"
                color="gray.600"
              >
                {config.description}
              </Text>
            </Stack>
            <Grid
              templateColumns={[
                'repeat(1, 1fr)',
                'repeat(1, 1fr)',
                'repeat(3, 1fr)',
              ]}
              gap={4}
            >
              {config.actions.map((action) => (
                <Box
                  as="button"
                  key={action.title}
                  bg="white"
                  py={8}
                  px={6}
                  borderRadius={4}
                  boxShadow="base"
                  maxWidth={['100%', '100%', '100%', 304]}
                  transition="box-shadow 50ms"
                  cursor="pointer"
                  userSelect="none"
                  _hover={{
                    boxShadow: 'complimentary-2xl',
                  }}
                  _focus={{
                    outline: 'none',
                    boxShadow: 'complimentary-2xl',
                  }}
                  onClick={() => onOpen(action.policy_key)}
                >
                  <Stack spacing={7}>
                    <Flex width="100%" justifyContent="center">
                      <Image
                        src={action.icon_path}
                        alt={action.description}
                        width={54}
                        height={54}
                      />
                    </Flex>
                    <Stack spacing={1} textAlign="center">
                      <Heading
                        fontSize="large"
                        fontWeight="semibold"
                        lineHeight="28px"
                        color="gray.600"
                      >
                        {action.title}
                      </Heading>
                      <Text fontSize="xs" color="gray.600">
                        {action.description}
                      </Text>
                    </Stack>
                  </Stack>
                </Box>
              ))}
            </Grid>
          </Stack>
          <RequestModal
            isOpen={isOpen}
            onClose={onClose}
            openAction={openAction}
            setAlert={setAlert}
          />
        </main>
      </alertContext.Provider>
    </div>
  );
};

export default Home;
