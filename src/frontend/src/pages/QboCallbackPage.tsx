import React, { useEffect, useState } from 'react';
import { getApiUrl, getAuthToken, setApiUrl, setEnvData, toBoolean } from '@/api/config';

const QboCallbackPage: React.FC = () => {
  const [message, setMessage] = useState('Completing QBO connection...');

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
    const redirect = async () => {
      const baseUrl = await resolveApiBaseUrl();
      if (!baseUrl) {
        setMessage('API URL not configured. Please refresh and try again.');
        return;
      }
      const query = window.location.search || '';
      if (!query) {
        setMessage('Missing OAuth parameters. Please retry the QBO connection.');
        return;
      }

      const token = getAuthToken();
      if (!token) {
        const postLoginRedirect = `${window.location.pathname}${window.location.search || ''}`;
        const loginUrl = `/.auth/login/aad?post_login_redirect_uri=${encodeURIComponent(postLoginRedirect || '/')}`;
        window.location.assign(loginUrl);
        return;
      }

      const target = `${baseUrl}/qbo/callback${query}`;
      try {
        const response = await fetch(target, {
          method: 'GET',
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          const detail = (payload as any)?.detail || 'Unable to complete QBO callback.';
          setMessage(String(detail));
          return;
        }

        const resolvedClientId = String((payload as any)?.client_id || '').trim();
        const connectedEvent = {
          type: 'qbo_connected',
          client_id: resolvedClientId || null,
          timestamp: Date.now(),
        };
        try {
          localStorage.setItem('qbo_connect_event', JSON.stringify(connectedEvent));
        } catch {
          // Ignore storage failures (private mode/quota).
        }
        try {
          if (window.opener && window.opener !== window) {
            window.opener.postMessage(connectedEvent, window.location.origin);
          }
        } catch {
          // Ignore cross-window messaging failures.
        }

        if (window.opener && window.opener !== window) {
          setMessage('QBO connection completed. You can return to the previous tab.');
          window.setTimeout(() => {
            window.close();
          }, 700);
          return;
        }

        setMessage('QBO connection completed. Redirecting...');
        const suffix = resolvedClientId ? `?qbo_connected=1&client_id=${encodeURIComponent(resolvedClientId)}` : '?qbo_connected=1';
        window.location.replace(`/${suffix}`);
      } catch (error) {
        setMessage(`Unable to complete QBO callback: ${(error as Error).message}`);
      }
    };

    redirect();
  }, []);

  return <div style={{ padding: '24px' }}>{message}</div>;
};

export default QboCallbackPage;
