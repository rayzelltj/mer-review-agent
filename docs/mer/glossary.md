# Glossary — MER Review Agent

> **Status:** Living document

---

| Term | Definition |
|---|---|
| **MER** | Month-End Report — a periodic financial review package that summarizes the accounting health of a company at the close of each month. Includes balance sheet review, reconciliations, and evidence checks. |
| **MACAE** | Multi-Agent Custom Automation Engine — the platform on which the MER Review Agent is built. Provides orchestration, multi-agent execution, WebSocket streaming, and team configuration management. |
| **QBO** | QuickBooks Online — cloud-based accounting software by Intuit. The primary data source for the MER Review Agent (balance sheets, P&L, aging reports, accounts). |
| **Balance Sheet** | A financial statement showing a company's assets, liabilities, and equity at a specific point in time. The primary subject of MVP1 review. |
| **P&L / Profit & Loss** | Income statement showing revenue and expenses over a period. Planned for MVP3 rules. |
| **Reconciliation** | The process of comparing two sets of records (e.g., bank statement vs. general ledger) to verify they agree. A core review activity. |
| **Variance** | The difference between two values being compared (e.g., book balance vs. statement balance). Used to determine if accounts are materially reconciled. |
| **Evidence** | Supporting documentation that substantiates a balance or transaction (bank statements, loan schedules, petty cash receipts, etc.). |
| **Evidence Bundle** | A collection of evidence items associated with a review run, organized by evidence type. Represented as `EvidenceBundle` in the rules engine. |
| **Rule** | A deterministic check that evaluates a specific aspect of the balance sheet review. Each rule has an ID, inputs, and produces a `RuleResult`. |
| **Rule Status** | The outcome of a rule evaluation: `PASS`, `FAIL`, `WARN`, `NEEDS_REVIEW`, or `NOT_APPLICABLE`. |
| **Severity** | A firm-policy derivative of rule status: `HIGH` (FAIL/NEEDS_REVIEW), `MEDIUM` (WARN), `LOW` (PASS), `NONE` (NOT_APPLICABLE). |
| **HITL** | Human-In-The-Loop — a design pattern where the system pauses for human input before proceeding. Used for plan approval and missing evidence requests. |
| **MCP** | Model Context Protocol — an open protocol for AI tool invocation. The MCP server exposes domain-specific tools (finance, HR, etc.) that agents can call. |
| **FastMCP** | A Python SDK for building MCP servers. Used by the MACAE MCP server. |
| **Agent** | A specialized AI component with a specific role (e.g., ConnectorAgent, RulesAgent). Each agent has a system prompt and can invoke MCP tools. |
| **Team** | A configured set of agents that work together on a specific domain task. Defined in JSON team config files under `data/agent_teams/`. |
| **Orchestrator** | The backend component that manages the execution of a plan — creating, sequencing, and streaming agent execution. |
| **Plan** | A generated list of steps to accomplish a user's task. Plans require human approval before execution. |
| **Realm ID** | QBO's company identifier. Each QuickBooks company has a unique realm ID used in API calls. |
| **Snapshot** | A stored copy of raw QBO data at a point in time. Used for auditability and reproducibility. |
| **Artifact** | A processed or intermediate result stored in Blob Storage during a review run. |
| **Adapter** | A pure function that transforms raw external data (QBO JSON, CSV, etc.) into canonical Pydantic models consumed by the rules engine. |
| **Connector** | A module that handles authentication and data retrieval from external systems (QBO, Google Drive). |
| **Subledger** | A detailed subsidiary ledger (e.g., AP aging detail, AR aging detail) that should reconcile to the corresponding general ledger balance. |
| **Aging Report** | A report that categorizes outstanding receivables or payables by the length of time they have been outstanding (current, 30 days, 60 days, 90+ days). |
| **Clearing Account** | A temporary holding account used during transaction processing. Should typically be zero at period-end. |
| **Intercompany** | Transactions or balances between related companies. Must reconcile across entities. |
| **Working Paper** | A spreadsheet or document that provides supporting calculations for a balance sheet line item. |
| **Prepaid Schedule** | A working paper tracking prepaid expenses and their amortization. |
| **EasyAuth** | Azure App Service Authentication — a built-in feature that adds identity verification to web apps without code changes. |
| **MSAL** | Microsoft Authentication Library — used for token acquisition in the frontend. |
| **Managed Identity** | Azure identity assigned to a resource for accessing other Azure services without storing credentials. |
| **RAG** | Retrieval-Augmented Generation — a pattern where AI responses are grounded in retrieved documents. Used by other MACAE teams (Retail, RFP, Contract Compliance). |
| **Bicep** | Azure's domain-specific language for deploying Azure resources. Used for infrastructure-as-code in this project. |
| **azd** | Azure Developer CLI — a tool for deploying Azure applications. Used as the primary deployment method. |
| **ACR** | Azure Container Registry — stores Docker images for the Backend and MCP containers. |
| **Container Apps** | Azure Container Apps — serverless container hosting. Runs the Backend and MCP server. |
| **App Service** | Azure App Service — PaaS web hosting. Runs the Frontend. |
| **Cosmos DB** | Azure Cosmos DB — NoSQL database. Stores plans, sessions, QBO tokens, and review runs. |
| **Key Vault** | Azure Key Vault — secrets management. Stores API keys and sensitive configuration. |
| **WebSocket** | A persistent bidirectional communication protocol. Used for real-time streaming of agent messages and plan updates. |
| **Slot Swap** | An Azure deployment technique where a staging slot is promoted to production by swapping traffic routing. Enables zero-downtime deployments. |
| **OAuth2** | An authorization framework. Used for QBO integration (authorization code flow with PKCE). |
| **Bearer Token** | An HTTP authorization header containing a JWT or opaque token that identifies the caller. |
| **TTL** | Time-to-Live — a duration after which data expires or is cleaned up. Used for orchestration run state. |
| **OTLP** | OpenTelemetry Protocol — used for exporting traces and metrics to Azure Monitor. |
