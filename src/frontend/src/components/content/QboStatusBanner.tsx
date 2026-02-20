/**
 * QboStatusBanner
 *
 * Displays a Fluent UI MessageBar when QBO is not connected (or has an
 * expired token) for the given clientId.  Auto-dismisses when:
 *   - The OAuth callback window sends a `qbo_connected` postMessage
 *   - The user dismisses it manually
 *
 * The banner is hidden entirely while loading or when connected.
 */

import React from 'react';
import {
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  MessageBarActions,
  Button,
  Link,
} from '@fluentui/react-components';
import { useQboStatus } from '@/hooks/useQboStatus';

interface QboStatusBannerProps {
  /** The accounting client to check. */
  clientId?: string;
}

const QboStatusBanner: React.FC<QboStatusBannerProps> = ({ clientId }) => {
  const normalizedClientId = (clientId || '').trim();
  const { status, refresh } = useQboStatus({ clientId: normalizedClientId });
  const [dismissed, setDismissed] = React.useState(false);

  // When the user completes OAuth in a popup/new-tab the callback page fires a
  // postMessage; re-check status so the banner auto-disappears.
  React.useEffect(() => {
    const handleMessage = (event: MessageEvent) => {
      if (
        event.origin === window.location.origin &&
        event.data?.type === 'qbo_connected'
      ) {
        setDismissed(false); // un-dismiss so banner refreshes then hides
        refresh();
      }
    };
    window.addEventListener('message', handleMessage);
    return () => window.removeEventListener('message', handleMessage);
  }, [refresh]);

  // Hide when loading, connected, or manually dismissed
  if (
    !normalizedClientId ||
    dismissed ||
    status.state === 'loading' ||
    status.state === 'connected'
  ) {
    return null;
  }

  const isExpired =
    status.state === 'error'
      ? false
      : (status as { reason?: string }).reason === 'token_expired';

  const connectHref = `/qbo/connect?client_id=${encodeURIComponent(normalizedClientId)}`;

  const title = isExpired ? 'QuickBooks session expired' : 'QuickBooks not connected';
  const body = isExpired
    ? `Your QuickBooks authorization for "${normalizedClientId}" has expired. Reconnect to run reviews.`
    : `QuickBooks is not connected for "${normalizedClientId}". Connect to enable balance sheet reviews.`;
  const ctaLabel = isExpired ? 'Reconnect' : 'Connect QuickBooks';

  return (
    <MessageBar
      intent="warning"
      style={{ marginBottom: 8 }}
    >
      <MessageBarBody>
        <MessageBarTitle>{title}</MessageBarTitle>
        {' '}{body}
      </MessageBarBody>
      <MessageBarActions
        containerAction={
          <Button
            appearance="transparent"
            size="small"
            onClick={() => setDismissed(true)}
            aria-label="Dismiss"
          >
            ✕
          </Button>
        }
      >
        <Link
          href={connectHref}
          target="_blank"
          rel="noopener noreferrer"
        >
          {ctaLabel}
        </Link>
      </MessageBarActions>
    </MessageBar>
  );
};

export default QboStatusBanner;
