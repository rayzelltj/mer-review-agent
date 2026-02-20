/**
 * useQboStatus
 *
 * Checks whether QBO is connected for a given client_id by calling
 * GET /api/qbo/status (fast, Cosmos-only).
 *
 * Auto-refreshes when:
 *   - the component mounts
 *   - a `qbo_connected` postMessage arrives from the OAuth callback window
 *   - the `qbo_connect_event` localStorage key changes in another tab
 *
 * The hook intentionally does NOT call /api/qbo/validate (the live Intuit
 * probe) on every page load — that would add a QBO API round-trip to every
 * mount.  Use `revalidate()` explicitly when you want the live check.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { getApiUrl, getAuthToken } from '@/api/config.tsx';

export type QboStatusState =
  | { state: 'loading' }
  | { state: 'connected'; clientId: string; realmId?: string }
  | { state: 'disconnected'; reason?: string; clientId?: string }
  | { state: 'error'; message: string };

interface UseQboStatusOptions {
  /** The accounting client to check. */
  clientId: string;
  /**
   * When true, runs the live Intuit probe (/api/qbo/validate) instead of the
   * cheap status check.  Use sparingly – it costs one QBO API call.
   */
  liveProbe?: boolean;
}

export function useQboStatus(options: UseQboStatusOptions) {
  const { clientId, liveProbe = false } = options;
  const [status, setStatus] = useState<QboStatusState>({ state: 'loading' });
  const inFlightRef = useRef(false);

  const check = useCallback(async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;

    try {
      if (!clientId?.trim()) {
        setStatus({ state: 'disconnected', reason: 'missing_client_id' });
        return;
      }
      const baseApiUrl = getApiUrl();
      if (!baseApiUrl) {
        setStatus({ state: 'error', message: 'API URL not configured' });
        return;
      }
      // Strip trailing /api if present so we can build the path cleanly.
      const base = baseApiUrl.replace(/\/api\/?$/, '');
      const endpoint = liveProbe ? 'validate' : 'status';
      const url = `${base}/api/qbo/${endpoint}?client_id=${encodeURIComponent(clientId)}`;

      const token = getAuthToken();
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(url, { headers });
      if (!res.ok) {
        // 401 = not logged in yet; don't show error banner
        if (res.status === 401) {
          setStatus({ state: 'loading' });
          return;
        }
        setStatus({ state: 'error', message: `QBO status check failed (${res.status})` });
        return;
      }
      const data = await res.json();

      if (data?.connected) {
        setStatus({
          state: 'connected',
          clientId: String(data.client_id || clientId),
          realmId: data.realm_id,
        });
      } else {
        setStatus({
          state: 'disconnected',
          reason: data?.reason,
          clientId: String(data?.client_id || clientId),
        });
      }
    } catch (err) {
      setStatus({ state: 'error', message: String((err as Error).message) });
    } finally {
      inFlightRef.current = false;
    }
  }, [clientId, liveProbe]);

  // Initial check on mount
  useEffect(() => {
    check();
  }, [check]);

  // Re-check when a qbo_connected postMessage arrives (from QboCallbackPage)
  useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (
        event.origin === window.location.origin &&
        event.data?.type === 'qbo_connected'
      ) {
        check();
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [check]);

  // Re-check when localStorage is updated by another tab's callback page
  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key === 'qbo_connect_event' && event.newValue) {
        check();
      }
    };
    window.addEventListener('storage', handleStorage);
    return () => window.removeEventListener('storage', handleStorage);
  }, [check]);

  return { status, refresh: check };
}
