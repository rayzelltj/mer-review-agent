import {
  Body1Strong,
  Button,
  Caption1,
  Input,
  Title2
} from "@fluentui/react-components";

import React, { useRef, useEffect, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";

import "./../../styles/Chat.css";
import "../../styles/prism-material-oceanic.css";
import "./../../styles/HomeInput.css";

import { HomeInputProps, iconMap, QuickTask } from "../../models/homeInput";
import { TaskService } from "../../services/TaskService";
import { NewTaskService } from "../../services/NewTaskService";
import { apiClient, apiService } from "@/api";
import { APIClientError } from "@/api/apiClient";
import {
  getStoredReviewClientId,
  getStoredReviewPeriodEnd,
  setStoredReviewClientId,
  setStoredReviewPeriodEnd,
} from "@/services/QboReviewContextService";
import { buildMerReviewPrompt } from "@/utils/merReviewPrompt";
import { useQboStatus } from "@/hooks/useQboStatus";

import ChatInput from "@/coral/modules/ChatInput";
import InlineToaster, { useInlineToaster } from "../toast/InlineToaster";
import PromptCard from "@/coral/components/PromptCard";
import { Send } from "@/coral/imports/bundleicons";
import { Clipboard20Regular } from "@fluentui/react-icons";

// Icon mapping function to convert string icons to FluentUI icons
const getIconFromString = (
  iconString: string | React.ReactNode
): React.ReactNode => {
  // If it's already a React node, return it
  if (typeof iconString !== "string") {
    return iconString;
  }

  return iconMap[iconString] || iconMap["default"] || <Clipboard20Regular />;
};

const truncateDescription = (
  description: string,
  maxLength: number = 180
): string => {
  if (!description) return "";

  if (description.length <= maxLength) {
    return description;
  }

  const truncated = description.substring(0, maxLength);
  const lastSpaceIndex = truncated.lastIndexOf(" ");

  const cutPoint = lastSpaceIndex > maxLength - 20 ? lastSpaceIndex : maxLength;

  return description.substring(0, cutPoint) + "...";
};

// Extended QuickTask interface to store both truncated and full descriptions
interface ExtendedQuickTask extends QuickTask {
  fullDescription: string; // Store the full, untruncated description
}

const HomeInput: React.FC<HomeInputProps> = ({
  selectedTeam,
  qboClientId,
  onQboClientIdChange,
}) => {
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [input, setInput] = useState<string>("");
  const [activeRunPlanId, setActiveRunPlanId] = useState<string | null>(null);
  const [activeRunMessage, setActiveRunMessage] = useState<string>("");
  const [reviewClientId, setReviewClientId] = useState<string>(
    () => String(qboClientId || getStoredReviewClientId() || "").trim()
  );
  const [reviewPeriodEnd, setReviewPeriodEnd] = useState<string>(
    () => getStoredReviewPeriodEnd()
  );

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const navigate = useNavigate();
  const location = useLocation(); // ✅ location.state used to control focus
  const { showToast, dismissToast } = useInlineToaster();

  // Check if the selected team is the Contract Compliance Review Team
  const isLegalTeam = selectedTeam?.name
    ?.toLowerCase()
    .includes("contract compliance");
  const isBalanceSheetTeam = selectedTeam?.name
    ?.toLowerCase()
    .includes("balance sheet review");

  // QBO connection status — only polled when the balance sheet team is active.
  // Used to hard-disable the submit button so users can't accidentally queue a
  // review without QBO credentials (soft gate in handleSubmit remains as backup).
  const { status: qboStatus } = useQboStatus({
    clientId: isBalanceSheetTeam ? (reviewClientId || "") : "",
  });
  // Disable the submit button when we know QBO is disconnected (not just loading).
  // loading / error states leave the button enabled; verifyQboConnection() handles those.
  const isQboDisconnected =
    isBalanceSheetTeam &&
    !!reviewClientId?.trim() &&
    qboStatus.state === "disconnected";

  useEffect(() => {
    const normalized = String(qboClientId || "").trim();
    if (!normalized) {
      return;
    }
    setReviewClientId(normalized);
  }, [qboClientId]);

  const updateReviewClientId = (value: string) => {
    setReviewClientId(value);
    const normalized = String(value || "").trim();
    setStoredReviewClientId(normalized);
    onQboClientIdChange?.(normalized);
  };

  const updateReviewPeriodEnd = (value: string) => {
    const normalized = String(value || "").trim();
    setReviewPeriodEnd(normalized);
    setStoredReviewPeriodEnd(normalized);
  };

  useEffect(() => {
    if (location.state?.focusInput) {
      textareaRef.current?.focus();
    }
  }, [location]);

  const resetTextarea = () => {
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.focus();
    }
  };

  useEffect(() => {
    const cleanup = NewTaskService.addResetListener(resetTextarea);
    return cleanup;
  }, []);

  useEffect(() => {
    const loadRunStatus = async () => {
      try {
        const status = await apiService.getRunStatus();
        if (status?.active && status.plan_id) {
          setActiveRunPlanId(status.plan_id);
          setActiveRunMessage(
            `Run in progress (run_id: ${status.run_id || "unknown"}). Open the active stream.`
          );
          return;
        }
        setActiveRunPlanId(null);
        setActiveRunMessage("");
      } catch {
        // Keep current state on transient status check errors.
      }
    };
    loadRunStatus();
  }, [selectedTeam?.team_id]);

  const handleOpenActiveStream = async () => {
    if (!activeRunPlanId) {
      return;
    }
    try {
      await apiService.getPlanStatus(activeRunPlanId);
      navigate(`/plan/${activeRunPlanId}`);
      return;
    } catch {
      try {
        const status = await apiService.getRunStatus();
        if (status?.active && status.plan_id) {
          setActiveRunPlanId(status.plan_id);
          setActiveRunMessage(
            `Run in progress (run_id: ${status.run_id || "unknown"}). Open the active stream.`
          );
          navigate(`/plan/${status.plan_id}`);
          return;
        }
      } catch {
        // Fall through to reset local stale UI state.
      }
      setActiveRunPlanId(null);
      setActiveRunMessage("");
      showToast(
        "The previous active run was stale and has been cleared. You can submit a new prompt.",
        "info"
      );
    }
  };

  const submitPlan = async (prompt: string) => {
    const trimmedPrompt = String(prompt || "").trim();
    if (!trimmedPrompt) {
      return;
    }

    setSubmitting(true);
    let id = showToast("Creating a plan", "progress");

    try {
      const status = await apiService.getRunStatus();
      if (status?.active && status.plan_id) {
        dismissToast(id);
        setActiveRunPlanId(status.plan_id);
        setActiveRunMessage(
          `Run in progress (run_id: ${status.run_id || "unknown"}). Open the active stream.`
        );
        showToast("Run already in progress. Opening active stream.", "progress");
        navigate(`/plan/${status.plan_id}`);
        return;
      }

      const response = await TaskService.createPlan(
        trimmedPrompt,
        selectedTeam?.team_id
      );
      console.log("Plan created:", response);
      setInput("");

      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
      }

      if (response.plan_id && response.plan_id !== null) {
        showToast("Plan created!", "success");
        dismissToast(id);
        navigate(`/plan/${response.plan_id}`);
      } else {
        showToast("Failed to create plan", "error");
        dismissToast(id);
      }
    } catch (error: any) {
      console.log("Error creating plan:", error);
      let errorMessage = "Unable to create plan. Please try again.";
      if (error instanceof APIClientError && error.status === 409) {
        const detail = error.data?.detail || error.data || {};
        const planId = detail?.plan_id || null;
        const runId = detail?.run_id || "unknown";
        if (planId) {
          setActiveRunPlanId(planId);
          setActiveRunMessage(
            `Run in progress (run_id: ${runId}). Open the active stream.`
          );
          dismissToast(id);
          showToast("Run already in progress. Opening active stream.", "progress");
          navigate(`/plan/${planId}`);
          return;
        }
        errorMessage = detail?.message || "Run already in progress.";
      } else if (error?.message) {
        errorMessage = String(error.message);
      }
      dismissToast(id);
      showToast(errorMessage, "error");
    } finally {
      setInput("");
      setSubmitting(false);
    }
  };

  const verifyQboConnection = async (clientId: string): Promise<boolean> => {
    try {
      const payload = await apiClient.get("/qbo/status", {
        params: { client_id: clientId },
      });
      if (payload?.connected) {
        return true;
      }
      showToast(
        `QuickBooks is not connected for "${clientId}". Connect QBO before starting the review.`,
        "warning"
      );
      return false;
    } catch (error: any) {
      const message = error instanceof Error ? error.message : "Unable to verify QBO connection.";
      showToast(message, "error");
      return false;
    }
  };

  const handleSubmit = async () => {
    if (activeRunPlanId) {
      await handleOpenActiveStream();
      return;
    }

    if (isBalanceSheetTeam) {
      const normalizedClientId = String(reviewClientId || "").trim();
      const normalizedPeriodEnd = String(reviewPeriodEnd || "").trim();
      if (!normalizedClientId) {
        showToast("Enter a client ID before starting a MER review.", "error");
        return;
      }
      if (!/^\d{4}-\d{2}-\d{2}$/.test(normalizedPeriodEnd)) {
        showToast("Choose a valid period end date (YYYY-MM-DD).", "error");
        return;
      }

      setStoredReviewClientId(normalizedClientId);
      setStoredReviewPeriodEnd(normalizedPeriodEnd);
      onQboClientIdChange?.(normalizedClientId);

      const connected = await verifyQboConnection(normalizedClientId);
      if (!connected) {
        return;
      }

      const prompt = buildMerReviewPrompt(
        normalizedClientId,
        normalizedPeriodEnd,
        input
      );
      await submitPlan(prompt);
      return;
    }

    if (input.trim()) {
      await submitPlan(input.trim());
    }
  };

  const handleQuickTaskClick = (task: ExtendedQuickTask) => {
    setInput(task.fullDescription);
    if (textareaRef.current) {
      textareaRef.current.focus();
    }
  };

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [input]);

  // Convert team starting_tasks to ExtendedQuickTask format
  const tasksToDisplay: ExtendedQuickTask[] =
    selectedTeam && selectedTeam.starting_tasks
      ? selectedTeam.starting_tasks.map((task, index) => {
          // Handle both string tasks and StartingTask objects
          if (typeof task === "string") {
            const fullDescription = isBalanceSheetTeam
              ? "Run the standard balance sheet review."
              : task;
            return {
              id: `team-task-${index}`,
              title: task,
              description: truncateDescription(fullDescription),
              fullDescription,
              icon: getIconFromString("📋"),
            };
          } else {
            // Handle StartingTask objects
            const startingTask = task as any; // Type assertion for now
            const rawTaskDescription =
              startingTask.prompt || startingTask.name || "Task description";
            const normalizedTaskText = String(
              `${startingTask.name || ""} ${startingTask.prompt || ""}`
            ).toLowerCase();
            const isStandardBalanceSheetTask =
              isBalanceSheetTeam &&
              normalizedTaskText.includes("balance sheet review");
            const taskDescription = isStandardBalanceSheetTask
              ? "Run the standard balance sheet review."
              : rawTaskDescription;
            return {
              id: startingTask.id || `team-task-${index}`,
              title: startingTask.name || startingTask.prompt || "Task",
              description: truncateDescription(taskDescription),
              fullDescription: taskDescription, // Store the full description
              icon: getIconFromString(startingTask.logo || "📋"),
            };
          }
        })
      : [];

  return (
    <div className="home-input-container">
      <div className="home-input-content">
        <div className="home-input-center-content">
          <div className="home-input-title-wrapper">
            <Title2>How can I help?</Title2>
          </div>

          {/* Legal Disclaimer for Contract Compliance Review Team */}
          {isLegalTeam && (
            <div
              style={{
                color: "var(--colorNeutralForeground3)",
                marginTop: "8px",
                paddingBottom: "8px",
                textAlign: "center",
              }}
            >
              <Caption1>
                <strong>Disclaimer:</strong> This tool is not intended to give
                legal advice; it is intended solely for the purpose of assessing
                contract compliance against internal guidance and policy frameworks.
              </Caption1>
            </div>
          )}

          {/* Show RAI error if present */}
          {/* {raiError && (
                        <RAIErrorCard
                            error={raiError}
                            onRetry={() => {
                                setRAIError(null);
                                if (textareaRef.current) {
                                    textareaRef.current.focus();
                                }
                            }}
                            onDismiss={() => setRAIError(null)}
                        />
                    )} */}

          {isBalanceSheetTeam && (
            <div
              style={{
                marginBottom: "12px",
                width: "100%",
                maxWidth: "820px",
                border: "1px solid var(--colorNeutralStroke2)",
                borderRadius: "8px",
                padding: "10px",
                background: "var(--colorNeutralBackground1)",
              }}
            >
              <div
                style={{
                  display: "grid",
                  gap: "8px",
                  gridTemplateColumns: "1.5fr 1fr auto",
                  alignItems: "center",
                }}
              >
                <Input
                  value={reviewClientId}
                  placeholder="Client ID (required)"
                  onChange={(_, data) => updateReviewClientId(data.value)}
                  disabled={submitting || !!activeRunPlanId}
                />
                <Input
                  type="date"
                  value={reviewPeriodEnd}
                  onChange={(_, data) => updateReviewPeriodEnd(data.value)}
                  disabled={submitting || !!activeRunPlanId}
                />
                <Button
                  appearance="secondary"
                  onClick={handleSubmit}
                  disabled={submitting || !!activeRunPlanId || isQboDisconnected}
                  title={isQboDisconnected ? "Connect QuickBooks before starting a review" : undefined}
                >
                  Run MER Review
                </Button>
              </div>
              <Caption1>
                Client + period are persisted and reused for each balance sheet review run.
              </Caption1>
            </div>
          )}

          <ChatInput
            ref={textareaRef} // forwarding
            value={input}
            placeholder={
              isBalanceSheetTeam
                ? "Optional reviewer notes (for example: focus on cash and AP anomalies)."
                : "Tell us what needs planning, building, or connecting—we'll handle the rest."
            }
            onChange={setInput}
            onEnter={handleSubmit}
            disabledChat={submitting || !!activeRunPlanId || isQboDisconnected}
          >
            <Button
              appearance="subtle"
              className="home-input-send-button"
              onClick={handleSubmit}
              disabled={submitting || !!activeRunPlanId || isQboDisconnected}
              icon={<Send />}
            />
          </ChatInput>

          {activeRunPlanId && (
            <div
              style={{
                marginTop: "10px",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "12px",
              }}
            >
              <Caption1>{activeRunMessage || "Run in progress."}</Caption1>
              <Button
                appearance="secondary"
                size="small"
                onClick={handleOpenActiveStream}
              >
                Open Active Stream
              </Button>
            </div>
          )}

          <InlineToaster />

          <div className="home-input-quick-tasks-section">
            {tasksToDisplay.length > 0 && (
              <>
                <div className="home-input-quick-tasks-header">
                  <Body1Strong>Quick tasks</Body1Strong>
                </div>

                <div className="home-input-quick-tasks">
                  <div>
                    {tasksToDisplay.map((task) => (
                      <PromptCard
                        key={task.id}
                        title={task.title}
                        icon={task.icon}
                        description={task.description}
                        onClick={() => handleQuickTaskClick(task)}
                        disabled={submitting || !!activeRunPlanId}
                      />
                    ))}
                  </div>
                </div>
              </>
            )}
            {tasksToDisplay.length === 0 && selectedTeam && (
              <div
                style={{
                  textAlign: "center",
                  padding: "32px 16px",
                  color: "#666",
                }}
              >
                <Caption1>No starting tasks available for this team</Caption1>
              </div>
            )}
            {!selectedTeam && (
              <div
                style={{
                  textAlign: "center",
                  padding: "32px 16px",
                  color: "#666",
                }}
              >
                <Caption1>Select a team to see available tasks</Caption1>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default HomeInput;
