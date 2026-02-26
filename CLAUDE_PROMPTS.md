# Claude Code — Starter Prompts for MACAE

## 🚀 First-Time Initialization Prompt

Copy and paste this into Claude Code to kick off the first session:

---

```
Read CLAUDE.md thoroughly. Then read these docs in order:
1. docs/architecture/project-spec.md
2. docs/mer/README.md (the full index)
3. docs/mer/system-overview.md
4. docs/mer/architecture.md
5. docs/mer/known-gaps-and-roadmap.md
6. docs/mer/error-handling.md
7. docs/mer/api-reference.md

After reading, confirm you understand the project by answering:
- What are the 3 architecture boundaries and what lives in each?
- What is the MER review pipeline's agent execution sequence?
- What are the 6 known P0/P1 issues in CLAUDE.md?

Then ask me at least 5 counter-questions about:
- Edge cases I may not have considered
- Ambiguities in the current requirements
- Priorities I should clarify before you start coding
- Dependencies between the issues that affect sequencing
```

---

## 🏗️ Phase 1 Prompt: UX Overhaul Planning

After Claude has read the docs, use this to start the structured planning phase:

---

```
We're going to fix the web app UX. Operate as a team of:
- Senior Software Engineer (architecture decisions, code quality)
- UI/UX Engineer (user experience, interaction design)
- QA Engineer (edge cases, test coverage, regression risks)
- Devil's Advocate (challenge every decision, find weaknesses)

The 6 issues to fix, in priority order:
1. Chat follow-ups create separate windows (should stay in same thread)
2. App gets stuck / unresponsive (run lock, stall detection, sticky flags)
3. Chat output shows code-like text (agent names, tool names, raw JSON)
4. QBO auth flow is clunky (token loss, no loading UI, fragile cross-tab)
5. Latency / slow responses (agent cold start, polling, round limits)
6. Limited question flexibility (prescriptive prompts, narrow tool surface)

For EACH issue, I need you to:
1. Trace the full code path (frontend → backend → agents → response)
2. Propose 2-3 solution approaches with tradeoffs
3. Identify edge cases and regression risks
4. Estimate complexity (S/M/L) and files affected
5. Flag any dependencies on other issues

After presenting all 6, propose a sequencing plan that:
- Minimizes rework (do foundational changes first)
- Delivers visible UX improvements early
- Groups related changes to reduce context switching
- Includes test checkpoints between phases

Ask me questions before finalizing the plan. Challenge my assumptions.
```

---

## 🔧 Phase 2 Prompt: Execute a Specific Fix

Once you've agreed on a plan, use this template for each fix:

---

```
Execute fix for: [ISSUE NAME]

Approach: [CHOSEN APPROACH from planning phase]

Workflow:
1. INVESTIGATE: Read all affected files. List every function that needs to change.
2. PLAN: Write out the exact changes, file by file. List new tests needed.
3. ASK: Before writing any code — ask me about edge cases you're unsure about.
4. IMPLEMENT: Make changes one file at a time. Run tests after each file.
5. TEST: Run full backend test suite (cd src/backend && uv run pytest --tb=short -q) and frontend build (cd src/frontend && npm run build).
6. VERIFY: Re-read the changed files. Devil's advocate pass — what could break?
7. DOCUMENT: Update any affected docs in docs/mer/.

Do NOT skip the ASK step. I want to review edge cases before you write code.
```

---

## 🔁 Looping / Iteration Prompt

Use this when you want Claude to self-review and iterate:

---

```
Review the changes you just made. Act as:

1. QA Engineer: 
   - What test cases are missing?
   - What happens if [WebSocket drops / token expires / API returns 500 / user double-clicks / concurrent requests]?
   - Are there race conditions?

2. Devil's Advocate:
   - Argue against this implementation. What's the weakest part?
   - What would a senior engineer criticize in code review?
   - What assumptions did you make that could be wrong?

3. UI/UX Engineer:
   - Walk through the user journey step by step. Where does it feel janky?
   - What loading/error states are missing?
   - Is the copy human-friendly?

Based on your review, propose specific improvements. Ask me before implementing.
```

---

## 📏 Rules Development Prompt

For when you (the owner) are focused on MER review rules:

---

```
I want to work on MER review rules. Read these first:
- docs/rules/STATUS.md
- docs/rules/balance_sheet/ (all 22 rule specs)
- docs/mer/rules-engine.md
- src/backend/common/rules_engine/ (all source files)
- src/backend/adapters/ (all adapter files)

Then help me with: [DESCRIBE WHAT YOU WANT — e.g., "create a new rule BS-INTERCOMPANY-MATCH that verifies intercompany balances net to zero across related entities"]

For each new/modified rule:
1. Write the rule spec (following existing format in docs/rules/balance_sheet/)
2. Identify what adapter data the rule needs
3. Check if the adapter exists or needs to be created
4. Implement the rule with decorator registration
5. Write unit tests with both passing and failing fixtures
6. Update docs/rules/STATUS.md
7. Run the full test suite to verify no regressions
```

---

## 💡 Tips for Getting the Best Results

1. **Always start sessions with:** "Read CLAUDE.md" — this loads all project context
2. **Be specific about which issue** you're working on — don't ask Claude to fix everything at once
3. **Use the loop prompt** after every major change — it catches issues early
4. **Ask Claude to explain tradeoffs** before choosing an approach
5. **Run tests frequently** — have Claude run `uv run pytest` after every file change
6. **Keep changes incremental** — one logical change per session, committed before moving on
7. **Update docs as you go** — docs/mer/ should always reflect current code behavior
