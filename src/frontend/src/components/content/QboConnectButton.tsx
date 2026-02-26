import React from "react";
import { Button, Input, Popover, PopoverSurface, PopoverTrigger } from "@fluentui/react-components";
import { PlugConnected20Regular } from "@fluentui/react-icons";
import { getStoredReviewClientId, setStoredReviewClientId } from "@/services/QboReviewContextService";

interface QboConnectButtonProps {
    clientId?: string;
    onClientIdChange?: (clientId: string) => void;
}

const QboConnectButton: React.FC<QboConnectButtonProps> = ({
    clientId,
    onClientIdChange,
}) => {
    const [draftClientId, setDraftClientId] = React.useState<string>(
        () => String((clientId ?? getStoredReviewClientId()) || "").trim()
    );
    const effectiveClientId = clientId !== undefined ? clientId : draftClientId;

    React.useEffect(() => {
        if (clientId === undefined) {
            return;
        }
        setDraftClientId(clientId);
    }, [clientId]);

    const handleClientIdChange = React.useCallback(
        (nextValue: string) => {
            setDraftClientId(nextValue);
            const normalized = String(nextValue || "").trim();
            setStoredReviewClientId(normalized);
            onClientIdChange?.(normalized);
        },
        [onClientIdChange]
    );

    const clientIdValue = String(effectiveClientId || "");
    const normalizedClientId = clientIdValue.trim();
    const connectHref = normalizedClientId
        ? `/qbo/connect?client_id=${encodeURIComponent(normalizedClientId)}`
        : "#";

    return (
        <Popover withArrow>
            <PopoverTrigger disableButtonEnhancement>
                <Button
                    appearance="outline"
                    icon={<PlugConnected20Regular />}
                    size="small"
                >
                    Connect QBO
                </Button>
            </PopoverTrigger>
            <PopoverSurface style={{ width: 300, display: "grid", gap: 10 }}>
                <div style={{ fontSize: 12, color: "#555" }}>
                    Connect QuickBooks for the client you want to review.
                </div>
                <Input
                    value={clientIdValue}
                    onChange={(_, data) => handleClientIdChange(data.value)}
                    placeholder="Client ID (for example: example_client)"
                />
                <Button
                    as="a"
                    href={connectHref}
                    appearance="primary"
                    disabled={!normalizedClientId}
                    onClick={(event) => {
                        if (!normalizedClientId) event.preventDefault();
                    }}
                    target="_blank"
                    rel="noopener noreferrer"
                >
                    Authenticate in QBO
                </Button>
                <div style={{ fontSize: 11, color: "#666" }}>
                    Opens in a new tab so you can keep chatting here.
                </div>
            </PopoverSurface>
        </Popover>
    );
};

export default QboConnectButton;
