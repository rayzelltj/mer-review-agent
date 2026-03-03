import React, { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Spinner, Text, Button } from "@fluentui/react-components";
import { DismissRegular } from "@fluentui/react-icons";
import { PlanDataService } from "../services/PlanDataService";
import { TaskService } from "../services/TaskService";
import { ProcessedPlanData, WebsocketMessageType, MPlanData, AgentMessageData, AgentMessageType, ParsedUserClarification, AgentType, PlanStatus, TeamConfig } from "../models";
import PlanChat from "../components/content/PlanChat";
import PlanPanelRight from "../components/content/PlanPanelRight";
import PlanPanelLeft from "../components/content/PlanPanelLeft";
import CoralShellColumn from "../coral/components/Layout/CoralShellColumn";
import CoralShellRow from "../coral/components/Layout/CoralShellRow";
import Content from "../coral/components/Content/Content";
import ContentToolbar from "../coral/components/Content/ContentToolbar";
import {
    useInlineToaster,
} from "../components/toast/InlineToaster";
import Octo from "../coral/imports/Octopus.png";
import LoadingMessage, { loadingMessages } from "../coral/components/LoadingMessage";
import webSocketService from "../services/WebSocketService";
import { APIService } from "../api/apiService";
import { StreamMessage, StreamingPlanUpdate } from "../models";
import { usePlanCancellationAlert } from "../hooks/usePlanCancellationAlert";
import PlanCancellationDialog from "../components/common/PlanCancellationDialog";
import QboConnectButton from "../components/content/QboConnectButton";
import { getStoredReviewClientId, setStoredReviewClientId } from "@/services/QboReviewContextService";
import { isAuthSessionError, redirectToAadLogin } from "@/utils/authSession";
import "../styles/PlanPage.css"

// Create API service instance
const apiService = new APIService();

/**
 * Page component for displaying a specific plan
 * Accessible via the route /plan/{plan_id}
 */
const PlanPage: React.FC = () => {
    const { planId } = useParams<{ planId: string }>();
    const navigate = useNavigate();
    const { showToast, dismissToast } = useInlineToaster();
    const messagesContainerRef = useRef<HTMLDivElement>(null);
    /** Tracks stable message keys already added to agentMessages — prevents duplicates on WS reconnect / double-send. */
    const seenMessageIds = useRef<Set<string>>(new Set());
    const [input, setInput] = useState<string>("");
    const [planData, setPlanData] = useState<ProcessedPlanData | any>(null);
    const [loading, setLoading] = useState<boolean>(true);
    const [submittingChatDisableInput, setSubmittingChatDisableInput] = useState<boolean>(true);
    const [errorLoading, setErrorLoading] = useState<boolean>(false);
    const [clarificationMessage, setClarificationMessage] = useState<ParsedUserClarification | null>(null);
    const [processingApproval, setProcessingApproval] = useState<boolean>(false);
    const [planApprovalRequest, setPlanApprovalRequest] = useState<MPlanData | null>(null);
    const [reloadLeftList, setReloadLeftList] = useState<boolean>(true);
    const [waitingForPlan, setWaitingForPlan] = useState<boolean>(true);
    const [showProcessingPlanSpinner, setShowProcessingPlanSpinner] = useState<boolean>(false);
    const [showApprovalButtons, setShowApprovalButtons] = useState<boolean>(true);
    const [continueWithWebsocketFlow, setContinueWithWebsocketFlow] = useState<boolean>(false);
    const [selectedTeam, setSelectedTeam] = useState<TeamConfig | null>(null);
    // WebSocket connection state
    const [wsConnected, setWsConnected] = useState<boolean>(false);
    const [pollingFallbackActive, setPollingFallbackActive] = useState<boolean>(false);
    const [streamingMessages, setStreamingMessages] = useState<StreamingPlanUpdate[]>([]);
    const [streamingMessageBuffer, setStreamingMessageBuffer] = useState<string>("");
    const [showBufferingText, setShowBufferingText] = useState<boolean>(false);
    const [agentMessages, setAgentMessages] = useState<AgentMessageData[]>([]);
    const [selectedQboClientId, setSelectedQboClientId] = useState<string>(() => getStoredReviewClientId());
    // activePlanId: the plan whose WebSocket channel is currently open.
    // Decoupled from the URL planId so follow-up submissions can reconnect the
    // WebSocket to a new plan without navigating away (no page remount).
    const [activePlanId, setActivePlanId] = useState<string | undefined>(planId);
    /** Activity log of tool calls — rendered as a collapsible "what's happening" indicator. */
    const [toolActivityLog, setToolActivityLog] = useState<{ label: string; timestamp: number }[]>([]);
    const formatErrorMessage = useCallback((content: string): string => {
        // Split content by newlines and add proper indentation
        const lines = content.split('\n');
        const formattedLines = lines.map((line, index) => {
            if (index === 0) {
                return `⚠️ ${line}`;
            } else if (line.trim() === '') {
                return ''; // Preserve blank lines
            } else {
                return `&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;${line}`;
            }
        });
        return formattedLines.join('\n');
    }, []);

    const extractClarificationFromMessages = useCallback((messages: AgentMessageData[]): ParsedUserClarification | null => {
        if (!messages || messages.length === 0) {
            return null;
        }
        for (let index = messages.length - 1; index >= 0; index -= 1) {
            const raw = messages[index]?.raw_data;
            if (!raw) {
                continue;
            }

            let candidate: any = raw;
            if (typeof candidate === "string") {
                const trimmed = candidate.trim();
                if (!trimmed) {
                    continue;
                }
                try {
                    candidate = JSON.parse(trimmed);
                } catch {
                    candidate = trimmed;
                }
            }

            const parsed = PlanDataService.parseUserClarificationRequest(candidate);
            if (parsed) {
                return parsed;
            }

            if (candidate && typeof candidate === "object") {
                const requestId = String((candidate as any).request_id || "").trim();
                const question = String((candidate as any).question || "").trim();
                if (requestId && question) {
                    return {
                        type: WebsocketMessageType.USER_CLARIFICATION_REQUEST,
                        request_id: requestId,
                        question,
                    };
                }
            }
        }
        return null;
    }, []);

    // Plan cancellation dialog state
    const [showCancellationDialog, setShowCancellationDialog] = useState<boolean>(false);
    const [pendingNavigation, setPendingNavigation] = useState<(() => void) | null>(null);
    const [cancellingPlan, setCancellingPlan] = useState<boolean>(false);

    const [loadingMessage, setLoadingMessage] = useState<string>(loadingMessages[0]);

    // Plan cancellation alert hook
    const { isPlanActive } = usePlanCancellationAlert({
        planData,
        onNavigate: pendingNavigation || (() => { })
    });

    // Handle navigation with plan cancellation check
    const handleNavigationWithAlert = useCallback((navigationFn: () => void) => {
        if (!isPlanActive()) {
            // Plan is not active, proceed with navigation
            navigationFn();
            return;
        }

        // Plan is active, show confirmation dialog
        setPendingNavigation(() => navigationFn);
        setShowCancellationDialog(true);
    }, [isPlanActive]);

    // Handle confirmation dialog response
    const handleConfirmCancellation = useCallback(async () => {
        setCancellingPlan(true);

        try {
            await apiService.cancelRun(planData?.plan?.id);

            // Execute the pending navigation
            if (pendingNavigation) {
                pendingNavigation();
            }
            webSocketService.disconnect();
        } catch (error) {
            console.error('❌ Failed to cancel plan:', error);
            showToast('Failed to cancel the plan properly, but navigation will continue.', 'error');
            // Still proceed with navigation even if cancellation failed
            if (pendingNavigation) {
                pendingNavigation();
            }
        } finally {
            setCancellingPlan(false);
            setShowCancellationDialog(false);
            setPendingNavigation(null);
        }
    }, [planData, pendingNavigation, showToast]);

    const handleCancelDialog = useCallback(() => {
        setShowCancellationDialog(false);
        setPendingNavigation(null);
    }, []);



    const processAgentMessage = useCallback((agentMessageData: AgentMessageData, planData: ProcessedPlanData, is_final: boolean = false, streaming_message: string = '') => {

        // Persist / forward to backend (fire-and-forget with logging)
        const agentMessageResponse = PlanDataService.createAgentMessageResponse(agentMessageData, planData, is_final, streaming_message);
        console.log('📤 Persisting agent message:', agentMessageResponse);
        const sendPromise = apiService.sendAgentMessage(agentMessageResponse)
            .then(saved => {
                console.log('[agent_message][persisted]', {
                    agent: agentMessageData.agent,
                    type: agentMessageData.agent_type,
                    ts: agentMessageData.timestamp
                });

                // If this is a final message, refresh the task list after successful persistence
                if (is_final) {
                    // Single refresh with a delay to ensure backend processing is complete
                    setTimeout(() => {
                        setReloadLeftList(true);
                    }, 1000);
                }
            })
            .catch(err => {
                console.warn('[agent_message][persist-failed]', err);
                // Even if persistence fails, still refresh the task list for final messages
                // The local plan data has been updated, so the UI should reflect that
                if (is_final) {
                    setTimeout(() => {
                        setReloadLeftList(true);
                    }, 1000);
                }
            });

        return sendPromise;

    }, [setReloadLeftList]);

    const resetPlanVariables = useCallback(() => {
        setInput("");
        setPlanData(null);
        setLoading(true);
        setSubmittingChatDisableInput(true);
        setErrorLoading(false);
        setClarificationMessage(null);
        setProcessingApproval(false);
        setPlanApprovalRequest(null);
        setReloadLeftList(true);
        setWaitingForPlan(true);
        setShowProcessingPlanSpinner(false);
        setShowApprovalButtons(true);
        setContinueWithWebsocketFlow(false);
        setWsConnected(false);
        setPollingFallbackActive(false);
        setStreamingMessages([]);
        setStreamingMessageBuffer("");
        setShowBufferingText(false);
        setAgentMessages([]);
        setToolActivityLog([]);
    }, [
        setInput,
        setPlanData,
        setLoading,
        setSubmittingChatDisableInput,
        setErrorLoading,
        setClarificationMessage,
        setProcessingApproval,
        setPlanApprovalRequest,
        setReloadLeftList,
        setWaitingForPlan,
        setShowProcessingPlanSpinner,
        setShowApprovalButtons,
        setContinueWithWebsocketFlow,
        setWsConnected,
        setPollingFallbackActive,
        setStreamingMessages,
        setStreamingMessageBuffer,
        setShowBufferingText,
        setAgentMessages
    ]);

    // Auto-scroll helper
    const scrollToBottom = useCallback(() => {
        setTimeout(() => {
            if (messagesContainerRef.current) {
                //messagesContainerRef.current.scrollTop = messagesContainerRef.current.scrollHeight;
                messagesContainerRef.current?.scrollTo({
                    top: messagesContainerRef.current.scrollHeight,
                    behavior: "smooth",
                });
            }
        }, 100);
    }, []);


    //WebsocketMessageType.PLAN_APPROVAL_REQUEST
    useEffect(() => {
        const unsubscribe = webSocketService.on(WebsocketMessageType.PLAN_APPROVAL_REQUEST, (approvalRequest: any) => {
            console.log('📋 Plan received:', approvalRequest);

            let mPlanData: MPlanData | null = null;

            // Handle the different message structures
            if (approvalRequest.parsedData) {
                // Direct parsedData property
                mPlanData = approvalRequest.parsedData;
            } else if (approvalRequest.data && typeof approvalRequest.data === 'object') {
                // Data property with nested object
                if (approvalRequest.data.parsedData) {
                    mPlanData = approvalRequest.data.parsedData;
                } else {
                    // Try to parse the data object directly
                    mPlanData = approvalRequest.data;
                }
            } else if (approvalRequest.rawData) {
                // Parse the raw data string
                mPlanData = PlanDataService.parsePlanApprovalRequest(approvalRequest.rawData);
            } else {
                // Try to parse the entire object
                mPlanData = PlanDataService.parsePlanApprovalRequest(approvalRequest);
            }

            if (mPlanData) {
                console.log('✅ Parsed plan data:', mPlanData);
                setPlanApprovalRequest(mPlanData);
                setWaitingForPlan(false);
                setShowProcessingPlanSpinner(false);
                scrollToBottom();
            } else {
                console.error('❌ Failed to parse plan data', approvalRequest);
            }
        });

        return () => unsubscribe();
    }, [scrollToBottom]);

    //(WebsocketMessageType.AGENT_MESSAGE_STREAMING
    useEffect(() => {
        const unsubscribe = webSocketService.on(WebsocketMessageType.AGENT_MESSAGE_STREAMING, (streamingMessage: any) => {
            
            //console.log('📋 Streaming Message', streamingMessage);
            // if is final true clear buffer and add final message to agent messages
            const line = PlanDataService.simplifyHumanClarification(streamingMessage.data.content);
            setShowBufferingText(true);
            setStreamingMessageBuffer(prev => prev + line);
            // Dismiss the "Processing..." spinner as soon as streaming content arrives
            setWaitingForPlan(false);
            //scrollToBottom();

        });

        return () => unsubscribe();
    }, [scrollToBottom]);

    //WebsocketMessageType.USER_CLARIFICATION_REQUEST
    useEffect(() => {
        const unsubscribe = webSocketService.on(WebsocketMessageType.USER_CLARIFICATION_REQUEST, (clarificationMessage: any) => {
            console.log('📋 Clarification Message', clarificationMessage);
            console.log('📋 Current plan data User clarification', planData);
            if (!clarificationMessage) {
                console.warn('⚠️ clarification message missing data:', clarificationMessage);
                return;
            }
            const agentMessageData = {
                agent: "Assistant" as AgentType,
                agent_type: AgentMessageType.AI_AGENT,
                timestamp: clarificationMessage.timestamp || Date.now(),
                steps: [],   // intentionally always empty
                next_steps: [],  // intentionally always empty
                content: clarificationMessage.data.question || '',
                raw_data: clarificationMessage.data || '',
            } as AgentMessageData;
            console.log('✅ Parsed clarification message:', agentMessageData);
            setClarificationMessage(clarificationMessage.data as ParsedUserClarification | null);
            setAgentMessages(prev => [...prev, agentMessageData]);
            setShowBufferingText(false);
            setShowProcessingPlanSpinner(false);
            setSubmittingChatDisableInput(false);
            scrollToBottom();
            // Persist the agent message
            processAgentMessage(agentMessageData, planData);

        });

        return () => unsubscribe();
    }, [scrollToBottom, planData, processAgentMessage]);
    //WebsocketMessageType.AGENT_TOOL_MESSAGE — track tool activity for the activity indicator
    useEffect(() => {
        const unsubscribe = webSocketService.on(WebsocketMessageType.AGENT_TOOL_MESSAGE, (toolMessage: any) => {
            console.log('📋 Tool Message', toolMessage);
            const labels: string[] = toolMessage?.data?.friendly_labels || [];
            if (labels.length > 0) {
                setToolActivityLog(prev => [
                    ...prev,
                    ...labels.map(label => ({ label, timestamp: Date.now() })),
                ]);
            }
        });

        return () => unsubscribe();
    }, []);


    //WebsocketMessageType.FINAL_RESULT_MESSAGE
    useEffect(() => {
        const unsubscribe = webSocketService.on(WebsocketMessageType.FINAL_RESULT_MESSAGE, (finalMessage: any) => {
            console.log('📋 Final Result Message', finalMessage);
            if (!finalMessage) {

                console.warn('⚠️ Final result message missing data:', finalMessage);
                return;
            }
            const agentMessageData = {
                agent: "Assistant" as AgentType,
                agent_type: AgentMessageType.AI_AGENT,
                timestamp: Date.now(),
                steps: [],   // intentionally always empty
                next_steps: [],  // intentionally always empty
                content: finalMessage.data?.content || '',
                raw_data: finalMessage,
            } as AgentMessageData;


            console.log('✅ Parsed final result message:', agentMessageData);
            const finalStatus = finalMessage?.data?.status as PlanStatus | undefined;
            if (
                finalStatus === PlanStatus.COMPLETED ||
                finalStatus === PlanStatus.FAILED ||
                finalStatus === PlanStatus.CANCELED
            ) {

                setShowBufferingText(true);
                setShowProcessingPlanSpinner(false);
                setWaitingForPlan(false);
                setSubmittingChatDisableInput(false);
                setAgentMessages(prev => [...prev, agentMessageData]);
                setSelectedTeam(planData?.team || null);
                scrollToBottom();
                // Persist the agent message
                const is_final = true;
                if (planData?.plan) {
                    planData.plan.overall_status = finalStatus || PlanStatus.COMPLETED;
                    setPlanData({ ...planData });
                }

                // Wait for the agent message to be processed and persisted
                // The processAgentMessage function will handle refreshing the task list
                webSocketService.disconnect();
                processAgentMessage(agentMessageData, planData, is_final, streamingMessageBuffer);

            }


        });

        return () => unsubscribe();
    }, [scrollToBottom, planData, processAgentMessage, streamingMessageBuffer, setSelectedTeam]);

    // WebsocketMessageType.ERROR_MESSAGE
    useEffect(() => {
        const unsubscribe = webSocketService.on(WebsocketMessageType.ERROR_MESSAGE, (errorMessage: any) => {
            console.log('❌ Received ERROR_MESSAGE:', errorMessage);
            console.log('❌ Error message data:', errorMessage?.data);
            
            // Try multiple ways to extract the error message
            let errorContent = "An unexpected error occurred. Please try again later.";
            
            // Check for double-nested data structure
            if (errorMessage?.data?.data?.content) {
                const content = errorMessage.data.data.content.trim();
                if (content.length > 0) {
                    errorContent = content;
                }
            } else if (errorMessage?.data?.content) {
                const content = errorMessage.data.content.trim();
                if (content.length > 0) {
                    errorContent = content;
                }
            } else if (errorMessage?.content) {
                const content = errorMessage.content.trim();
                if (content.length > 0) {
                    errorContent = content;
                }
            } else if (typeof errorMessage === 'string') {
                const content = errorMessage.trim();
                if (content.length > 0) {
                    errorContent = content;
                }
            }

            console.log('❌ Final error content to display:', errorContent);

            const errorAgentMessage: AgentMessageData = {
                agent: 'system',
                agent_type: AgentMessageType.SYSTEM_AGENT,
                timestamp: Date.now(),
                steps: [],
                next_steps: [],
                content: formatErrorMessage(errorContent),
                raw_data: errorMessage || '',
            };

            setAgentMessages(prev => [...prev, errorAgentMessage]);
            setShowProcessingPlanSpinner(false);
            setShowBufferingText(false);
            setWaitingForPlan(false);
            setSubmittingChatDisableInput(false);
            scrollToBottom();
            showToast(errorContent, "error");
        });

        return () => unsubscribe();
    }, [scrollToBottom, showToast, formatErrorMessage]);

    // WebsocketMessageType.TIMEOUT_NOTIFICATION
    useEffect(() => {
        const unsubscribe = webSocketService.on(WebsocketMessageType.TIMEOUT_NOTIFICATION, (msg: any) => {
            const text =
                msg?.data?.message ||
                msg?.message ||
                "Timed out waiting for a response. The run was cancelled.";

            const systemMsg: AgentMessageData = {
                agent: 'system',
                agent_type: AgentMessageType.SYSTEM_AGENT,
                timestamp: Date.now(),
                steps: [],
                next_steps: [],
                content: `⏱ ${text}`,
                raw_data: msg || '',
            };
            setAgentMessages(prev => [...prev, systemMsg]);
            scrollToBottom();
            showToast(text, "warning");
        });
        return () => unsubscribe();
    }, [scrollToBottom, showToast]);

    // WebSocket permanent connection loss
    useEffect(() => {
        const unsubscribe = webSocketService.on('error', (errorEvent: any) => {
            const msg = errorEvent?.error || errorEvent?.message || '';
            if (msg === 'Max reconnection attempts reached') {
                showToast(
                    'Connection lost — still checking for results in the background.',
                    'warning'
                );
            }
        });
        return () => unsubscribe();
    }, [showToast]);

    //WebsocketMessageType.AGENT_MESSAGE
    useEffect(() => {
        const unsubscribe = webSocketService.on(WebsocketMessageType.AGENT_MESSAGE, (agentMessage: any) => {
            console.log('📋 Agent Message', agentMessage)
            console.log('📋 Current plan data', planData);
            const agentMessageData = agentMessage.data as AgentMessageData;
            if (agentMessageData) {
                agentMessageData.content = PlanDataService.simplifyHumanClarification(agentMessageData?.content);

                // Dismiss the "Processing..." spinner as soon as agent output arrives
                setWaitingForPlan(false);

                // Dedup: build a stable key and silently drop messages we have already seen
                // (covers WS reconnect storms, double-sends, and duplicate run_id emissions).
                const msgKey = `${agentMessageData.agent}|${agentMessageData.timestamp}|${(agentMessageData.content || '').slice(0, 100)}`;
                if (seenMessageIds.current.has(msgKey)) {
                    console.debug('🔁 Duplicate agent message suppressed:', msgKey);
                    return;
                }
                seenMessageIds.current.add(msgKey);
                // Attach the key as message_id so the render layer can use it as a stable React key.
                agentMessageData.message_id = msgKey;

                setAgentMessages(prev => [...prev, agentMessageData]);
                setShowProcessingPlanSpinner(true);
                scrollToBottom();
                processAgentMessage(agentMessageData, planData);
            }

        });

        return () => unsubscribe();
    }, [scrollToBottom, planData, processAgentMessage]); //onPlanReceived, scrollToBottom

    // Loading message rotation effect
    useEffect(() => {
        let interval: NodeJS.Timeout;
        if (loading) {
            let index = 0;
            interval = setInterval(() => {
                index = (index + 1) % loadingMessages.length;
                setLoadingMessage(loadingMessages[index]);
            }, 3000);
        }
        return () => clearInterval(interval);
    }, [loading]);

    // WebSocket connection with proper error handling and v4 backend compatibility.
    // Uses activePlanId (not planId from URL) so follow-up submissions can reconnect
    // to a new plan channel without triggering a page remount / navigate().
    useEffect(() => {
        if (activePlanId && continueWithWebsocketFlow) {
            console.log('🔌 Connecting WebSocket:', { activePlanId, continueWithWebsocketFlow });

            const connectWebSocket = async () => {
                try {
                    await webSocketService.connect(activePlanId);
                    console.log('✅ WebSocket connected successfully');
                } catch (error) {
                    console.error('❌ WebSocket connection failed:', error);
                    // Continue without WebSocket - the app should still work
                }
            };

            connectWebSocket();

            const handleConnectionChange = (connected: boolean) => {
                setWsConnected(connected);
                setPollingFallbackActive(!connected);
                console.log('🔗 WebSocket connection status:', connected);
            };

            const handleStreamingMessage = (message: StreamMessage) => {
                console.log('📨 Received streaming message:', message);
                if (message.data && message.data.plan_id) {
                    setStreamingMessages(prev => [...prev, message.data]);
                }
            };

            const handlePlanApprovalResponse = (message: StreamMessage) => {
                console.log('✅ Plan approval response received:', message);
            };

            const handlePlanApprovalRequest = (message: StreamMessage) => {
                console.log('📥 Plan approval request received:', message);
                // This is handled by PlanChat component through its own listener
            };

            // Subscribe to all relevant v4 backend events
            const unsubscribeConnection = webSocketService.on('connection_status', (message) => {
                handleConnectionChange(message.data?.connected || false);
            });
            const unsubscribeReconnecting = webSocketService.on('reconnecting', (message) => {
                const reconnecting = Boolean(message.data?.active);
                if (reconnecting) {
                    setPollingFallbackActive(true);
                }
            });

            const unsubscribeStreaming = webSocketService.on(WebsocketMessageType.AGENT_MESSAGE, handleStreamingMessage);
            const unsubscribePlanApproval = webSocketService.on(WebsocketMessageType.PLAN_APPROVAL_RESPONSE, handlePlanApprovalResponse);
            const unsubscribePlanApprovalRequest = webSocketService.on(WebsocketMessageType.PLAN_APPROVAL_REQUEST, handlePlanApprovalRequest);

            return () => {
                console.log('🔌 Cleaning up WebSocket connections');
                unsubscribeConnection();
                unsubscribeReconnecting();
                unsubscribeStreaming();
                unsubscribePlanApproval();
                unsubscribePlanApprovalRequest();
                webSocketService.disconnect();
            };
        }
    }, [activePlanId, continueWithWebsocketFlow]);

    useEffect(() => {
        if (!planId || !continueWithWebsocketFlow || wsConnected || loading) {
            return;
        }

        setPollingFallbackActive(true);
        let cancelled = false;
        let pollCount = 0;
        let intervalId: number | null = null;

        const pollPlanState = async () => {
            if (cancelled) {
                return;
            }
            try {
                pollCount += 1;
                const status = await apiService.getPlanStatus(planId);
                if (cancelled || !status) {
                    return;
                }

                const streamed = status.streaming_message || "";
                if (streamed.trim() !== "") {
                    setStreamingMessageBuffer(streamed);
                    setShowBufferingText(true);
                }

                const planStatus = status.overall_status as PlanStatus;
                const shouldRefreshFullPlan =
                    pollCount % 3 === 0 ||
                    planStatus === PlanStatus.COMPLETED ||
                    planStatus === PlanStatus.FAILED;

                if (shouldRefreshFullPlan) {
                    const refreshed = await PlanDataService.fetchPlanData(planId, false);
                    if (!refreshed || cancelled) {
                        return;
                    }
                    setPlanData(refreshed);
                    if (refreshed.messages) {
                        setAgentMessages(refreshed.messages);
                    }
                    if (refreshed.mplan) {
                        setPlanApprovalRequest(refreshed.mplan);
                        setWaitingForPlan(false);
                    }
                    if (refreshed.streaming_message && refreshed.streaming_message.trim() !== "") {
                        setStreamingMessageBuffer(refreshed.streaming_message);
                        setShowBufferingText(true);
                        setWaitingForPlan(false);
                    }
                    if (
                        refreshed.plan?.overall_status === PlanStatus.COMPLETED ||
                        refreshed.plan?.overall_status === PlanStatus.FAILED ||
                        refreshed.plan?.overall_status === PlanStatus.CANCELED
                    ) {
                        setWaitingForPlan(false);
                    }
                }

                if (
                    planStatus === PlanStatus.COMPLETED ||
                    planStatus === PlanStatus.FAILED ||
                    planStatus === PlanStatus.CANCELED
                ) {
                    setContinueWithWebsocketFlow(false);
                    setShowProcessingPlanSpinner(false);
                    setWaitingForPlan(false);
                    setSubmittingChatDisableInput(false);
                    setPollingFallbackActive(false);
                }
            } catch (error) {
                if (isAuthSessionError(error)) {
                    cancelled = true;
                    if (intervalId !== null) {
                        clearInterval(intervalId);
                    }
                    setPollingFallbackActive(false);
                    redirectToAadLogin();
                    return;
                }
                console.warn("Polling fallback failed:", error);
            }
        };

        intervalId = window.setInterval(pollPlanState, 5000);
        pollPlanState();

        return () => {
            cancelled = true;
            if (intervalId !== null) {
                clearInterval(intervalId);
            }
        };
    }, [planId, continueWithWebsocketFlow, wsConnected, loading]);

    // Create loadPlanData function with useCallback to memoize it
    const loadPlanData = useCallback(
        async (useCache = true): Promise<ProcessedPlanData | null> => {
            if (!planId) return null;
            resetPlanVariables();
            setLoading(true);
            try {

                let planResult: ProcessedPlanData | null = null;
                console.log("Fetching plan with ID:", planId);
                planResult = await PlanDataService.fetchPlanData(planId, useCache);
                console.log("Plan data fetched:", planResult);
                if (planResult?.plan?.overall_status === PlanStatus.IN_PROGRESS) {
                    setShowApprovalButtons(true);

                } else {
                    setShowApprovalButtons(false);
                    setWaitingForPlan(false);
                }
                if (
                    planResult?.plan?.overall_status !== PlanStatus.COMPLETED &&
                    planResult?.plan?.overall_status !== PlanStatus.FAILED
                ) {
                    setContinueWithWebsocketFlow(true);
                }
                if (
                    planResult?.plan?.overall_status === PlanStatus.COMPLETED ||
                    planResult?.plan?.overall_status === PlanStatus.FAILED
                ) {
                    setSubmittingChatDisableInput(false);
                }
                if (planResult?.messages) {
                    setAgentMessages(planResult.messages);
                }
                const restoredClarification = extractClarificationFromMessages(planResult?.messages || []);
                if (restoredClarification) {
                    setClarificationMessage(restoredClarification);
                    setWaitingForPlan(false);
                    setShowProcessingPlanSpinner(false);
                    setSubmittingChatDisableInput(false);
                }
                if (planResult?.mplan) {
                    setPlanApprovalRequest(planResult.mplan);
                    setWaitingForPlan(false);
                }
                if (planResult?.messages && planResult.messages.length > 0) {
                    setWaitingForPlan(false);
                }
                if (planResult?.streaming_message && planResult.streaming_message.trim() !== "") {
                    setStreamingMessageBuffer(planResult.streaming_message);
                    setShowBufferingText(true);
                    setWaitingForPlan(false);
                }
                setPlanData(planResult);
                return planResult;
            } catch (err) {
                console.log("Failed to load plan data:", err);
                setErrorLoading(true);
                setPlanData(null);
                return null;
            } finally {
                setLoading(false);
            }
        },
        [planId, navigate, resetPlanVariables, extractClarificationFromMessages]
    );

    useEffect(() => {
        const refreshAfterQboConnect = async (rawClientId: unknown) => {
            const clientId = String(rawClientId || "").trim();
            if (clientId) {
                setStoredReviewClientId(clientId);
                setSelectedQboClientId(clientId);
            }
            const suffix = clientId ? ` for ${clientId}` : "";
            showToast(`QBO connected${suffix}. Refreshing this plan.`, "success");
            try {
                await loadPlanData(false);
            } catch (error) {
                console.warn("Failed to refresh plan after QBO connection:", error);
            }
        };

        const handleWindowMessage = (event: MessageEvent) => {
            if (event.origin !== window.location.origin) {
                return;
            }
            const payload = event.data as { type?: string; client_id?: string } | null;
            if (!payload || payload.type !== "qbo_connected") {
                return;
            }
            void refreshAfterQboConnect(payload.client_id);
        };

        const handleStorage = (event: StorageEvent) => {
            if (event.key !== "qbo_connect_event" || !event.newValue) {
                return;
            }
            try {
                const payload = JSON.parse(event.newValue) as { type?: string; client_id?: string };
                if (payload.type !== "qbo_connected") {
                    return;
                }
                void refreshAfterQboConnect(payload.client_id);
            } catch {
                // Ignore malformed localStorage events.
            }
        };

        window.addEventListener("message", handleWindowMessage);
        window.addEventListener("storage", handleStorage);
        return () => {
            window.removeEventListener("message", handleWindowMessage);
            window.removeEventListener("storage", handleStorage);
        };
    }, [loadPlanData, showToast]);


    // Handle plan approval
    const handleApprovePlan = useCallback(async () => {
        if (!planApprovalRequest) return;

        setProcessingApproval(true);
        let id = showToast("Submitting Approval", "progress");

        try {
            await apiService.approvePlan({
                m_plan_id: planApprovalRequest.id,
                plan_id: planData?.plan?.id,
                approved: true,
                feedback: 'Plan approved by user'
            });
            
            dismissToast(id);
            setShowProcessingPlanSpinner(true);
            setShowApprovalButtons(false);

        } catch (error) {
            dismissToast(id);
            showToast("Failed to submit approval", "error");
            console.error('❌ Failed to approve plan:', error);
        } finally {
            setProcessingApproval(false);
        }
    }, [planApprovalRequest, planData, setProcessingApproval]);

    // Handle plan rejection  
    const handleRejectPlan = useCallback(async () => {
        if (!planApprovalRequest) return;

        setProcessingApproval(true);
        let id = showToast("Submitting cancellation", "progress");
        try {
            await apiService.approvePlan({
                m_plan_id: planApprovalRequest.id,
                plan_id: planData?.plan?.id,
                approved: false,
                feedback: 'Plan rejected by user'
            });

            dismissToast(id);

            navigate('/');

        } catch (error) {
            dismissToast(id);
            showToast("Failed to submit cancellation", "error");
            console.error('❌ Failed to reject plan:', error);
            navigate('/');
        } finally {
            setProcessingApproval(false);
        }
    }, [planApprovalRequest, planData, navigate, setProcessingApproval]);
    // Handle "Stop run" button — reuses the cancellation dialog
    const handleStopRun = useCallback(() => {
        setPendingNavigation(() => () => navigate('/'));
        setShowCancellationDialog(true);
    }, [navigate]);

    // Chat submission handler - updated for v4 backend compatibility

    const handleOnchatSubmit = useCallback(
        async (chatInput: string) => {
            if (!chatInput.trim()) {
                showToast("Please enter a clarification", "error");
                return;
            }
            setInput("");

            if (!planData?.plan) return;
            const isCompleted =
                planData.plan.overall_status === PlanStatus.COMPLETED ||
                planData.plan.overall_status === PlanStatus.FAILED;
            const hasClarificationRequest =
                Boolean(clarificationMessage?.request_id) && Boolean(planApprovalRequest?.id);

            setSubmittingChatDisableInput(true);
            const progressMessage = hasClarificationRequest
                ? "Submitting clarification"
                : "Starting follow-up analysis";
            let id = showToast(progressMessage, "progress");

            try {
                if (!hasClarificationRequest && isCompleted) {
                    const followUpSessionId = planData.plan.session_id;
                    const followUpTeamId = planData.team?.team_id || planData.plan.team_id;
                    const response = await TaskService.createPlan(
                        chatInput,
                        followUpTeamId,
                        followUpSessionId,
                    );

                    dismissToast(id);

                    // Add the user's message optimistically so the conversation thread
                    // shows it immediately (before the WS reconnects and streams back).
                    const userFollowUpMsg: AgentMessageData = {
                        agent: 'human',
                        agent_type: AgentMessageType.HUMAN_AGENT,
                        timestamp: Date.now(),
                        steps: [],
                        next_steps: [],
                        content: chatInput,
                        raw_data: chatInput,
                    } as AgentMessageData;
                    setAgentMessages(prev => [...prev, userFollowUpMsg]);

                    // Update planData so subsequent handlers use the new plan id.
                    if (planData?.plan) {
                        setPlanData({
                            ...planData,
                            plan: {
                                ...planData.plan,
                                id: response.plan_id,
                                overall_status: PlanStatus.IN_PROGRESS,
                            },
                        });
                    }

                    // Reset per-plan state for the new run without clearing message history.
                    setPlanApprovalRequest(null);
                    setClarificationMessage(null);
                    setStreamingMessageBuffer("");
                    setShowBufferingText(false);
                    setWaitingForPlan(false);
                    setShowProcessingPlanSpinner(true);
                    setSubmittingChatDisableInput(true);

                    // Switch the WebSocket channel to the new plan.
                    // activePlanId change triggers the WS useEffect to disconnect the old
                    // channel and connect to the new one — no page remount needed.
                    setActivePlanId(response.plan_id);
                    setContinueWithWebsocketFlow(true);

                    // Update the browser URL silently so a page refresh lands on the new
                    // plan, but without triggering React Router's re-render / remount.
                    window.history.replaceState(null, '', `/plan/${response.plan_id}`);

                    showToast("Follow-up started — continuing in this conversation", "success");
                    scrollToBottom();
                    return;
                }

                const response = await PlanDataService.submitClarification({
                    request_id: clarificationMessage?.request_id || "",
                    answer: chatInput,
                    plan_id: planData?.plan.id,
                    m_plan_id: planApprovalRequest?.id || ""
                });

                console.log("Clarification submitted successfully:", response);
                setInput("");
                dismissToast(id);
                showToast("Clarification submitted successfully", "success");

                const agentMessageData = {
                    agent: 'human',
                    agent_type: AgentMessageType.HUMAN_AGENT,
                    timestamp: Date.now(),
                    steps: [],
                    next_steps: [],
                    content: chatInput || '',
                    raw_data: chatInput || '',
                } as AgentMessageData;

                setAgentMessages(prev => [...prev, agentMessageData]);
                setSubmittingChatDisableInput(true);
                setShowProcessingPlanSpinner(true);
                scrollToBottom();

            } catch (error: any) {
                setShowProcessingPlanSpinner(false);
                dismissToast(id);
                setSubmittingChatDisableInput(false);
                const failedMessage = hasClarificationRequest
                    ? "Failed to submit clarification"
                    : "Failed to start follow-up prompt";
                showToast(failedMessage, "error");

            } finally {

            }
        },
        [
            clarificationMessage?.request_id,
            dismissToast,
            navigate,
            planApprovalRequest?.id,
            planData,
            scrollToBottom,
            setActivePlanId,
            showToast,
        ]
    );


    // ✅ Handlers for PlanPanelLeft with plan cancellation protection
    const handleNewTaskButton = useCallback(() => {
        handleNavigationWithAlert(() => {
            navigate("/", { state: { focusInput: true } });
        });
    }, [navigate, handleNavigationWithAlert]);


    const resetReload = useCallback(() => {
        setReloadLeftList(false);
    }, []);

    useEffect(() => {
        const initializePlanLoading = async () => {
            if (!planId) {
                resetPlanVariables();
                setErrorLoading(true);
                return;
            }

            try {
                await loadPlanData(false);
            } catch (err) {
                console.error("Failed to initialize plan loading:", err);
            }
        };

        initializePlanLoading();
    }, [planId, loadPlanData, resetPlanVariables, setErrorLoading]);

    // When the user navigates to a different plan via a sidebar link, keep activePlanId
    // in sync with the URL-derived planId so the WebSocket reconnects to the new plan.
    // This does NOT fire on follow-up submissions (those use window.history.replaceState
    // which bypasses React Router and leaves planId unchanged).
    useEffect(() => {
        setActivePlanId(planId);
    }, [planId]);

    useEffect(() => {
        if (planData?.team) {
            setSelectedTeam(planData.team);
        }
    }, [planData, setSelectedTeam]);

    if (errorLoading) {
        return (
            <CoralShellColumn>
                <CoralShellRow>
                    <PlanPanelLeft
                        reloadTasks={reloadLeftList}
                        onNewTaskButton={handleNewTaskButton}
                        restReload={resetReload}
                        onTeamSelect={() => { }}
                        onTeamUpload={async () => { }}
                        isHomePage={false}
                        selectedTeam={selectedTeam}
                        onNavigationWithAlert={handleNavigationWithAlert}
                    />
                    <Content>
                        <div className="plan-error-message">
                            <Text size={500}>
                                {"An error occurred while loading the plan"}
                            </Text>
                        </div>
                    </Content>
                </CoralShellRow>
            </CoralShellColumn>
        );
    }

    return (
        <CoralShellColumn>
            <CoralShellRow>
                {/* ✅ RESTORED: PlanPanelLeft for navigation */}
                <PlanPanelLeft
                    reloadTasks={reloadLeftList}
                    onNewTaskButton={handleNewTaskButton}
                    restReload={resetReload}
                    onTeamSelect={() => { }}
                    onTeamUpload={async () => { }}
                    isHomePage={false}
                    selectedTeam={selectedTeam}
                    onNavigationWithAlert={handleNavigationWithAlert}
                />

                <Content>
                    {loading || !planData ? (
                        <>
                            <div className="plan-loading-spinner">
                                <Spinner size="medium" />
                                <Text>Loading plan data...</Text>
                            </div>
                            <LoadingMessage
                                loadingMessage={loadingMessage}
                                iconSrc={Octo}
                            />
                        </>
                    ) : (
                        <>
                            
                            <ContentToolbar
                                panelTitle="Multi-Agent Planner"
                            >
                                {continueWithWebsocketFlow && (
                                    <Button
                                        appearance="subtle"
                                        size="small"
                                        icon={<DismissRegular />}
                                        onClick={handleStopRun}
                                        disabled={cancellingPlan}
                                    >
                                        Stop run
                                    </Button>
                                )}
                                <QboConnectButton
                                    clientId={selectedQboClientId}
                                    onClientIdChange={setSelectedQboClientId}
                                />
                            </ContentToolbar>

                            {pollingFallbackActive && (
                                <div
                                    style={{
                                        margin: "8px auto 0",
                                        maxWidth: "800px",
                                        width: "100%",
                                        padding: "8px 12px",
                                        background: "#fff4ce",
                                        border: "1px solid #f8d22a",
                                        borderRadius: "6px",
                                        fontSize: "12px",
                                    }}
                                >
                                    WebSocket reconnecting. Showing progress via polling every 5 seconds.
                                </div>
                            )}
                            
                            <PlanChat
                                planData={planData}
                                OnChatSubmit={handleOnchatSubmit}
                                loading={loading}
                                setInput={setInput}
                                submittingChatDisableInput={submittingChatDisableInput}
                                input={input}
                                inputPlaceholder={
                                    clarificationMessage?.request_id
                                        ? "Provide clarification for this plan..."
                                        : planData?.plan?.overall_status === PlanStatus.COMPLETED
                                            ? "Ask a follow-up question about failed rules, evidence, or specific accounts..."
                                            : "Type your message here..."
                                }
                                streamingMessages={streamingMessages}
                                wsConnected={wsConnected}
                                planApprovalRequest={planApprovalRequest}
                                waitingForPlan={waitingForPlan}
                                messagesContainerRef={messagesContainerRef}
                                streamingMessageBuffer={streamingMessageBuffer}
                                showBufferingText={showBufferingText}
                                agentMessages={agentMessages}
                                showProcessingPlanSpinner={showProcessingPlanSpinner}
                                showApprovalButtons={showApprovalButtons}
                                processingApproval={processingApproval}
                                handleApprovePlan={handleApprovePlan}
                                handleRejectPlan={handleRejectPlan}
                                toolActivityLog={toolActivityLog}
                            />
                        </>
                    )}
                </Content>

                <PlanPanelRight
                    planData={planData}
                    loading={loading}
                    planApprovalRequest={planApprovalRequest}
                />
            </CoralShellRow>

            {/* Plan Cancellation Confirmation Dialog */}
            <PlanCancellationDialog
                isOpen={showCancellationDialog}
                onConfirm={handleConfirmCancellation}
                onCancel={handleCancelDialog}
                loading={cancellingPlan}
            />
        </CoralShellColumn>
    );
};

export default PlanPage;
