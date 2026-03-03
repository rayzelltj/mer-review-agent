import React from "react";
import { PlanChatProps, MPlanData } from "../../models/plan";
import InlineToaster from "../toast/InlineToaster";
import { AgentMessageData } from "@/models";
import renderUserPlanMessage from "./streaming/StreamingUserPlanMessage";
import renderPlanResponse from "./streaming/StreamingPlanResponse";
import { renderPlanExecutionMessage, renderThinkingState } from "./streaming/StreamingPlanState";
import ContentNotFound from "../NotFound/ContentNotFound";
import PlanChatBody from "./PlanChatBody";
import renderAgentMessages from "./streaming/StreamingAgentMessage";
import StreamingBufferMessage from "./streaming/StreamingBufferMessage";

interface SimplifiedPlanChatProps extends PlanChatProps {
  onPlanReceived?: (planData: MPlanData) => void;
  initialTask?: string;
  planApprovalRequest: MPlanData | null;
  waitingForPlan: boolean;
  messagesContainerRef: React.RefObject<HTMLDivElement>;
  streamingMessageBuffer: string;
  showBufferingText: boolean;
  agentMessages: AgentMessageData[];
  showProcessingPlanSpinner: boolean;
  showApprovalButtons: boolean;
  handleApprovePlan: () => Promise<void>;
  handleRejectPlan: () => Promise<void>;
  processingApproval: boolean;
  inputPlaceholder?: string;
  toolActivityLog?: { label: string; timestamp: number }[];
}

const PlanChat: React.FC<SimplifiedPlanChatProps> = ({
  planData,
  input,
  setInput,
  submittingChatDisableInput,
  OnChatSubmit,
  onPlanApproval,
  onPlanReceived,
  initialTask,
  planApprovalRequest,
  waitingForPlan,
  messagesContainerRef,
  streamingMessageBuffer,
  showBufferingText,
  agentMessages,
  showProcessingPlanSpinner,
  showApprovalButtons,
  handleApprovePlan,
  handleRejectPlan,
  processingApproval,
  inputPlaceholder,
  toolActivityLog,
}) => {
  // States

  if (!planData)
    return (
      <ContentNotFound subtitle="The requested page could not be found." />
    );
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',

    }}>
      {/* Messages Container */}
      <InlineToaster />
      <div
        ref={messagesContainerRef}
        style={{
          flex: 1,
          overflow: 'auto',
          padding: '32px 0',
          maxWidth: '800px',
          margin: '0 auto',
          width: '100%'
        }}
      >
        {/* User plan message */}
        {renderUserPlanMessage(planApprovalRequest, initialTask, planData)}

        {/* AI thinking state */}
        {renderThinkingState(waitingForPlan)}

        {/* Plan response with all information */}
        {renderPlanResponse(planApprovalRequest, handleApprovePlan, handleRejectPlan, processingApproval, showApprovalButtons)}
        {renderAgentMessages(agentMessages)}

        {showProcessingPlanSpinner && renderPlanExecutionMessage()}

        {/* Activity indicator — shows tool calls the agent is performing */}
        {toolActivityLog && toolActivityLog.length > 0 && showProcessingPlanSpinner && (
          <div style={{
            maxWidth: '800px',
            margin: '0 auto 16px auto',
            padding: '0 24px',
          }}>
            <details open style={{
              backgroundColor: 'var(--colorNeutralBackground2)',
              borderRadius: '8px',
              padding: '8px 12px',
              fontSize: '13px',
              color: 'var(--colorNeutralForeground2)',
            }}>
              <summary style={{ cursor: 'pointer', fontWeight: 600, marginBottom: '4px' }}>
                Working on it... ({toolActivityLog.length} {toolActivityLog.length === 1 ? 'step' : 'steps'})
              </summary>
              <ul style={{ margin: '4px 0 0 0', paddingLeft: '20px', listStyleType: 'none' }}>
                {toolActivityLog.map((entry, idx) => (
                  <li key={idx} style={{ padding: '2px 0', opacity: idx === toolActivityLog.length - 1 ? 1 : 0.6 }}>
                    {idx === toolActivityLog.length - 1 ? '▸ ' : '✓ '}{entry.label}
                  </li>
                ))}
              </ul>
            </details>
          </div>
        )}

        {/* Streaming plan updates */}
        {showBufferingText && (
          <StreamingBufferMessage
            streamingMessageBuffer={streamingMessageBuffer}
            isStreaming={true}
          />
        )}
      </div>

      {/* Chat Input - only show if no plan is waiting for approval */}
      <PlanChatBody
        planData={planData}
        input={input}
        setInput={setInput}
        submittingChatDisableInput={submittingChatDisableInput}
        OnChatSubmit={OnChatSubmit}
        waitingForPlan={waitingForPlan}
        inputPlaceholder={inputPlaceholder}
        loading={false} />

    </div>
  );
};

export default PlanChat;
