/**
 * Unit tests for the three guards introduced to fix duplicate-message and
 * internal_agent_message rendering bugs:
 *
 *  1. INTERNAL_AGENT_MESSAGE suppression in WebSocketService
 *  2. Stable-key dedup in the AGENT_MESSAGE handler (PlanPage)
 *  3. Once-per-run_id BalanceSheetReviewPanel guard (StreamingAgentMessage)
 *
 * These tests are intentionally self-contained — they do NOT import React
 * components so they run fast without a full DOM render.
 */

import { describe, it, expect, beforeEach } from 'vitest';

// ---------------------------------------------------------------------------
// 1. Stable message-key computation (mirrors the logic in PlanPage.tsx)
// ---------------------------------------------------------------------------
function stableMsgKey(agent: string, timestamp: number, content: string): string {
    return `${agent}|${timestamp}|${content.slice(0, 100)}`;
}

describe('stableMsgKey', () => {
    it('produces the same key for identical inputs', () => {
        const k1 = stableMsgKey('OrchestratorAgent', 1700000000000, 'Hello world');
        const k2 = stableMsgKey('OrchestratorAgent', 1700000000000, 'Hello world');
        expect(k1).toBe(k2);
    });

    it('differs when the agent changes', () => {
        const k1 = stableMsgKey('AgentA', 1700000000000, 'same content');
        const k2 = stableMsgKey('AgentB', 1700000000000, 'same content');
        expect(k1).not.toBe(k2);
    });

    it('differs when the timestamp changes', () => {
        const k1 = stableMsgKey('AgentA', 1000, 'same content');
        const k2 = stableMsgKey('AgentA', 2000, 'same content');
        expect(k1).not.toBe(k2);
    });

    it('truncates content to 100 chars so near-identical long messages collide on the key prefix', () => {
        const base = 'x'.repeat(200);
        const k1 = stableMsgKey('A', 1, base + 'suffix1');
        const k2 = stableMsgKey('A', 1, base + 'suffix2');
        // Both map to the same 100-char prefix → same key (intentional dedup behaviour).
        expect(k1).toBe(k2);
    });
});

// ---------------------------------------------------------------------------
// 2. Dedup Set guard (mirrors the seenMessageIds ref logic in PlanPage.tsx)
// ---------------------------------------------------------------------------
describe('seenMessageIds Set dedup', () => {
    let seenMessageIds: Set<string>;

    beforeEach(() => {
        seenMessageIds = new Set<string>();
    });

    const tryAdd = (agent: string, timestamp: number, content: string): boolean => {
        const key = stableMsgKey(agent, timestamp, content);
        if (seenMessageIds.has(key)) return false; // duplicate → reject
        seenMessageIds.add(key);
        return true; // new → accept
    };

    it('accepts the first occurrence of a message', () => {
        expect(tryAdd('Agent', 1000, 'Hello')).toBe(true);
    });

    it('rejects an identical second occurrence (reconnect / double-send)', () => {
        tryAdd('Agent', 1000, 'Hello');
        expect(tryAdd('Agent', 1000, 'Hello')).toBe(false);
    });

    it('accepts a different message from the same agent', () => {
        tryAdd('Agent', 1000, 'First message');
        expect(tryAdd('Agent', 2000, 'Second message')).toBe(true);
    });

    it('correctly deduplicates 7 identical run_id emissions', () => {
        const accepted: boolean[] = [];
        for (let i = 0; i < 7; i++) {
            accepted.push(tryAdd('BalanceSheetAgent', 1234567890, 'run_id: "abc123"'));
        }
        expect(accepted.filter(Boolean)).toHaveLength(1);
        expect(accepted.filter(v => !v)).toHaveLength(6);
    });
});

// ---------------------------------------------------------------------------
// 3. shouldRenderMessage — internal_agent_message must be suppressed
// ---------------------------------------------------------------------------
const INTERNAL_AGENT_MESSAGE = 'internal_agent_message';
const AGENT_MESSAGE = 'agent_message';
const AGENT_TOOL_MESSAGE = 'agent_tool_message';
const FINAL_RESULT_MESSAGE = 'final_result_message';
const ERROR_MESSAGE = 'error_message';
const USER_CLARIFICATION_REQUEST = 'user_clarification_request';
const AGENT_MESSAGE_STREAMING = 'agent_message_streaming';

function shouldRenderMessage(type: string): boolean {
    // Sub-agent structured JSON payloads — intentionally NOT rendered.
    if (type === INTERNAL_AGENT_MESSAGE) return false;
    return true;
}

describe('shouldRenderMessage', () => {
    it('returns false for internal_agent_message', () => {
        expect(shouldRenderMessage(INTERNAL_AGENT_MESSAGE)).toBe(false);
    });

    it('returns true for user-facing orchestrator messages', () => {
        expect(shouldRenderMessage(AGENT_MESSAGE)).toBe(true);
        expect(shouldRenderMessage(FINAL_RESULT_MESSAGE)).toBe(true);
        expect(shouldRenderMessage(USER_CLARIFICATION_REQUEST)).toBe(true);
        expect(shouldRenderMessage(ERROR_MESSAGE)).toBe(true);
    });

    it('returns true for tool/progress messages (spinners, status)', () => {
        expect(shouldRenderMessage(AGENT_TOOL_MESSAGE)).toBe(true);
        expect(shouldRenderMessage(AGENT_MESSAGE_STREAMING)).toBe(true);
    });

    it('returns true for any unknown type (safe default — do not hide)', () => {
        expect(shouldRenderMessage('some_future_type')).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// 4. Once-per-run_id BalanceSheetReviewPanel guard
//    (mirrors the seenRunIds Set logic in StreamingAgentMessage.tsx)
// ---------------------------------------------------------------------------
const RUN_ID_PATTERNS = [
    /run_id"?\s*[:=]\s*"?([a-f0-9]{32})/i,
    /run id[:\s]*([a-f0-9]{32})/i,
];

function extractRunId(content: string): string | null {
    if (!content) return null;
    for (const pattern of RUN_ID_PATTERNS) {
        const match = content.match(pattern);
        if (match?.[1]) return match[1];
    }
    return null;
}

function buildRenderDecisions(
    messages: Array<{ content: string; isHuman: boolean }>
): Array<{ shouldRenderPanel: boolean; runId: string | null }> {
    const seenRunIds = new Set<string>();
    return messages.map(({ content, isHuman }) => {
        const runId = isHuman ? null : extractRunId(content);
        const shouldRenderPanel = runId !== null && !seenRunIds.has(runId);
        if (shouldRenderPanel && runId) seenRunIds.add(runId);
        return { shouldRenderPanel, runId };
    });
}

describe('seenRunIds — once-per-run_id BalanceSheet guard', () => {
    const RUN_A = 'a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4';
    const RUN_B = 'deadbeefdeadbeefdeadbeefdeadbeef';

    it('renders the panel exactly once for a single run_id', () => {
        const msgs = [
            { content: `Balance sheet ready. run_id: "${RUN_A}"`, isHuman: false },
        ];
        const [r0] = buildRenderDecisions(msgs);
        expect(r0.shouldRenderPanel).toBe(true);
        expect(r0.runId).toBe(RUN_A);
    });

    it('renders panel only ONCE even when 6 duplicate messages carry the same run_id', () => {
        const msgs = Array.from({ length: 6 }, () => ({
            content: `run_id: "${RUN_A}" - analysis complete`,
            isHuman: false,
        }));
        const decisions = buildRenderDecisions(msgs);
        expect(decisions.filter(d => d.shouldRenderPanel)).toHaveLength(1);
        expect(decisions.filter(d => !d.shouldRenderPanel && d.runId)).toHaveLength(5);
    });

    it('renders once per DISTINCT run_id across interleaved messages', () => {
        const msgs = [
            { content: `run_id: "${RUN_A}"`, isHuman: false },
            { content: `run_id: "${RUN_B}"`, isHuman: false },
            { content: `run_id: "${RUN_A}"`, isHuman: false }, // duplicate A
            { content: `run_id: "${RUN_B}"`, isHuman: false }, // duplicate B
        ];
        const decisions = buildRenderDecisions(msgs);
        expect(decisions.filter(d => d.shouldRenderPanel)).toHaveLength(2);
    });

    it('never renders a panel for human messages even if content has a run_id pattern', () => {
        const msgs = [
            { content: `Please review run_id: "${RUN_A}"`, isHuman: true },
        ];
        const [r0] = buildRenderDecisions(msgs);
        expect(r0.shouldRenderPanel).toBe(false);
        expect(r0.runId).toBeNull();
    });

    it('still renders the text bubble (shouldRenderPanel=false ≠ skip message)', () => {
        const msgs = [
            { content: `run_id: "${RUN_A}"`, isHuman: false },
            { content: `run_id: "${RUN_A}" (follow-up text)`, isHuman: false },
        ];
        const [first, second] = buildRenderDecisions(msgs);
        // Both messages are present (text bubble would be rendered for both).
        expect(first.runId).toBe(RUN_A);
        expect(second.runId).toBe(RUN_A);
        // Panel suppressed on the second occurrence only.
        expect(first.shouldRenderPanel).toBe(true);
        expect(second.shouldRenderPanel).toBe(false);
    });
});
