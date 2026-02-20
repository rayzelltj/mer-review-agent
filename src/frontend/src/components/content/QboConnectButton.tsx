import React from "react";
import { Button, Input, Popover, PopoverSurface, PopoverTrigger } from "@fluentui/react-components";
import { PlugConnected20Regular } from "@fluentui/react-icons";

const QboConnectButton: React.FC = () => {
    const [clientId, setClientId] = React.useState("");
    const normalizedClientId = (clientId || "").trim();
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
                    value={clientId}
                    onChange={(_, data) => setClientId(data.value)}
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
