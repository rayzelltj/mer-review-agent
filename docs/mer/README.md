# MER Review Agent — Documentation Index

> **Last updated:** 2026-03-02
> **Maintainer:** Engineering team
> **Status:** Living documentation — update as the codebase evolves

---

## Who This Is For

| Audience | Start Here |
|---|---|
| **New engineer onboarding** | [System Overview](system-overview.md) → [Architecture](architecture.md) → [Local Development](local-development.md) |
| **Reviewer / auditor** | [System Overview](system-overview.md) → [Rules Engine](rules-engine.md) → [Data Flow](data-flow.md) |
| **Engineering manager** | [System Overview](system-overview.md) → [Known Gaps & Roadmap](known-gaps-and-roadmap.md) → [Security & Privacy](security-privacy.md) |
| **DevOps / SRE** | [Deployment & Operations](deployment-operations.md) → [Operational Runbook](runbook.md) → [Security & Privacy](security-privacy.md) |
| **QA / tester** | [Testing & Validation](testing-validation.md) → [Rules Engine](rules-engine.md) |

---

## Documentation Map

| # | Document | Description |
|---|---|---|
| 1 | [System Overview](system-overview.md) | What the MER Review Agent does and does not do; high-level workflow; design goals |
| 2 | [Architecture](architecture.md) | Components, agent roles, orchestration flow, boundaries, Mermaid diagrams |
| 3 | [Data Flow](data-flow.md) | Inputs, processing pipeline, outputs, evidence traceability |
| 4 | [Rules Engine](rules-engine.md) | Rule model, severity/status contracts, implemented rules, how to add new rules |
| 5 | [QBO Integration](integrations/qbo.md) | QuickBooks Online API usage, auth flow, endpoints, failure modes |
| 6 | [Google Drive & Sheets](integrations/google-drive-sheets.md) | Drive connector, OAuth2 auth, read/write responsibilities |
| 7 | [Security & Privacy](security-privacy.md) | Sensitive data, access controls, secret management, PII, risks |
| 8 | [Local Development](local-development.md) | Prerequisites, setup, env vars, run/test commands |
| 9 | [Deployment & Operations](deployment-operations.md) | Azure deployment, environments, config/secrets, monitoring |
| 10 | [Testing & Validation](testing-validation.md) | Test strategy, coverage, gaps, fixture-based testing |
| 11 | [Known Gaps & Roadmap](known-gaps-and-roadmap.md) | Limitations, tech debt, documentation TODOs, priority next steps |
| 12 | [Glossary](glossary.md) | Key terms: MER, QBO, reconciliation, variance, etc. |
| 13 | [API Reference](api-reference.md) | All REST endpoints with request/response schemas, status codes, and usage notes |
| 14 | [Error Handling](error-handling.md) | Error codes, retry strategies, exception hierarchy, user-facing messages |
| 15 | [Operational Runbook](runbook.md) | Troubleshooting decision trees, operational procedures, emergency playbooks |
| 16 | [Agent Team Evolution Proposal](agent-team-evolution-proposal.md) | Initial v2 proposal (SUPERSEDED — see docs 17-18 below) |
| 17 | [Architecture Decision Record](architecture-decision-record.md) | 10 ADRs governing v2 agent evolution: merged agents, constrained planning, evidence ledger, correction memory, context budgeting, escalation model |
| 18 | [V2 Implementation Spec](v2-implementation-spec.md) | Approved implementation blueprint: 5 phases, 3 agents, 8 new MCP tools, full system prompts, cost projections, risk register, testing strategy |

---

## Source-of-Truth Conventions

Every claim in these docs is tagged with a confidence level:

| Tag | Meaning |
|---|---|
| ✅ **Verified in code** | Confirmed by reading source files (path cited) |
| 🔍 **Inferred from code/config** | Derived from code patterns, configs, or naming — not explicitly documented elsewhere |
| ⚠️ **Needs verification** | Uncertain or based on incomplete evidence — requires manual confirmation |

When existing architecture docs (under `docs/architecture/`) conflict with code behavior, **code is treated as the current truth** unless the code is clearly deprecated.

---

## Upstream References

These existing docs are the authoritative project specs and should be consulted alongside this set:

| Document | Path | Role |
|---|---|---|
| MACAE Project Spec | [docs/architecture/project-spec.md](../architecture/project-spec.md) | Platform-wide product & technical spec |
| MER Review Agent Spec | [docs/architecture/mer-review-agent-spec.md](../architecture/mer-review-agent-spec.md) | MER-specific product intent & MVP roadmap |
| Repo-Derived Architecture | [docs/architecture/architecture.md](../architecture/architecture.md) | Full system architecture from code evidence |
| Security Controls | [docs/architecture/controls.md](../architecture/controls.md) | Trust boundaries, identities, secrets, gaps |
| Rules Engine Status | [docs/rules/STATUS.md](../rules/STATUS.md) | Implementation checklist for rules & adapters |
| MVP1 Smoke Checklist | [docs/architecture/mer-mvp1-smoke-checklist.md](../architecture/mer-mvp1-smoke-checklist.md) | Manual smoke test runbook |
| Mermaid Diagrams | [docs/architecture/diagrams/](../architecture/diagrams/) | C4, deployment, data flow, auth sequence diagrams |
| Balance Sheet Rule Docs | [docs/rules/balance_sheet/](../rules/balance_sheet/) | Per-rule specification (22 files) |

---

## How to Maintain These Docs

1. **Update after every significant code change** — if you change a rule, adapter, connector, or API endpoint, update the relevant doc.
2. **Use the confidence tags** — when adding new content, tag it appropriately.
3. **Prefer code references over prose** — cite file paths and function names so docs stay verifiable.
4. **Keep docs incremental** — small, frequent updates are better than large rewrites.
5. **Run the smoke checklist** — after any MER pipeline change, verify against [MVP1 Smoke Checklist](../architecture/mer-mvp1-smoke-checklist.md).
