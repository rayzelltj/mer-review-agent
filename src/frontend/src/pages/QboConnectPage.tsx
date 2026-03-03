import React, { useEffect, useState } from 'react';
import { Spinner } from '@fluentui/react-components';
import { getApiUrl, getAuthToken, setApiUrl, setEnvData, toBoolean } from '@/api/config';
import { setStoredReviewClientId } from '@/services/QboReviewContextService';
import { redirectToAadLogin } from '@/utils/authSession';

const FETCH_TIMEOUT_MS = 15_000;

const QboConnectPage: React.FC = () => {
  const [message, setMessage] = useState('Preparing QBO authorization...');
  const [isLoading, setIsLoading] = useState(true);

  const resolveApiBaseUrl = async (): Promise<string | null> => {
    let apiUrl = getApiUrl();
    if (!apiUrl) {
      try {
        const response = await fetch('/config');
        if (response.ok) {
          const config = await response.json();
          config.ENABLE_AUTH = toBoolean(config.ENABLE_AUTH);
          setEnvData(config);
          setApiUrl(config.API_URL);
          apiUrl = getApiUrl();
        }
      } catch {
        return null;
      }
    }
    if (!apiUrl) {
      return null;
    }
    return apiUrl.replace(/\/api\/?$/, '');
  };

  useEffect(() => {
    const startOauth = async () => {
      const params = new URLSearchParams(window.location.search || '');
      const clientId = (params.get('client_id') || '').trim();
      if (!clientId) {
        setMessage('Missing client_id. Please retry QBO connect from the app.');
        return;
      }
      setStoredReviewClientId(clientId);

      const baseUrl = await resolveApiBaseUrl();
      if (!baseUrl) {
        setMessage('API URL not configured. Please refresh and try again.');
        return;
      }

      const token = getAuthToken();
      if (!token) {
        redirectToAadLogin();
        return;
      }

      const target = `${baseUrl}/api/qbo/connect/prepare?client_id=${encodeURIComponent(clientId)}`;
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
        const response = await fetch(target, {
          method: 'GET',
          headers: {
            Authorization: `Bearer ${token}`,
          },
          signal: controller.signal,
        });
        clearTimeout(timeoutId);
        if (response.status === 401) {
          redirectToAadLogin();
          return;
        }

        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          const detail = (payload as any)?.detail || 'Unable to start QBO authorization.';
          setMessage(String(detail));
          return;
        }

        const authorizationUrl = String((payload as any)?.authorization_url || '').trim();
        if (!authorizationUrl) {
          setMessage('QBO authorization URL was not returned by backend.');
          return;
        }

        window.location.replace(authorizationUrl);
      } catch (error) {
        const msg = (error as Error).name === 'AbortError'
          ? 'Request timed out. The backend may be starting up — please try again in a moment.'
          : `Unable to start QBO authorization: ${(error as Error).message}`;
        setMessage(msg);
      } finally {
        setIsLoading(false);
      }
    };

    startOauth();
  }, []);

  return (
    <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
      {isLoading && <Spinner size="medium" label={message} />}
      {!isLoading && <p>{message}</p>}
    </div>
  );
};

export default QboConnectPage;
