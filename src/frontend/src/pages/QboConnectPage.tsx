import React, { useEffect, useState } from 'react';
import { getApiUrl, getAuthToken, setApiUrl, setEnvData, toBoolean } from '@/api/config';

const QboConnectPage: React.FC = () => {
  const [message, setMessage] = useState('Preparing QBO authorization...');

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

      const baseUrl = await resolveApiBaseUrl();
      if (!baseUrl) {
        setMessage('API URL not configured. Please refresh and try again.');
        return;
      }

      const token = getAuthToken();
      if (!token) {
        const postLoginRedirect = `${window.location.pathname}${window.location.search || ''}`;
        const loginUrl = `/.auth/login/aad?post_login_redirect_uri=${encodeURIComponent(postLoginRedirect || '/')}`;
        window.location.assign(loginUrl);
        return;
      }

      const target = `${baseUrl}/api/qbo/connect/prepare?client_id=${encodeURIComponent(clientId)}`;
      try {
        const response = await fetch(target, {
          method: 'GET',
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });

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
        setMessage(`Unable to start QBO authorization: ${(error as Error).message}`);
      }
    };

    startOauth();
  }, []);

  return <div style={{ padding: '24px' }}>{message}</div>;
};

export default QboConnectPage;
