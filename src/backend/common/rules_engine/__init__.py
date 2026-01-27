"""Source-agnostic rules engine for MER checks.

This package intentionally contains only domain logic:
- Rule inputs are report snapshots + evidence + client config.
- No QBO, Google Drive, or network calls live here.
"""

from .context import RuleContext
from .models import (
    BalanceSheetSnapshot,
    ProfitAndLossSnapshot,
    EvidenceBundle,
    EvidenceItem,
    ReconciliationSnapshot,
    RuleResult,
    RuleRunReport,
)
from .runner import RulesRunner

# Import built-in rules so they self-register with the global registry.
from . import rules as _builtin_rules  # noqa: F401
