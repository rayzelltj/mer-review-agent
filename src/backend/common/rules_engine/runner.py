from __future__ import annotations

import concurrent.futures
import uuid
from datetime import datetime, timezone
from typing import Iterable, Optional

from .context import RuleContext
from .models import RuleRunReport, RuleStatus
from .registry import registry

_RULES_CONCURRENCY = 8  # rules are pure CPU-bound functions; 8 threads saturates typical core count


class RulesRunner:
    def __init__(self, rules: Optional[Iterable] = None):
        self._rules = list(rules) if rules is not None else registry.create_all()

    def run(self, ctx: RuleContext, *, rule_ids: Optional[set[str]] = None) -> RuleRunReport:
        active_rules = [
            rule for rule in self._rules
            if rule_ids is None or rule.rule_id in rule_ids
        ]

        with concurrent.futures.ThreadPoolExecutor(max_workers=_RULES_CONCURRENCY) as pool:
            futures = [pool.submit(rule.evaluate, ctx) for rule in active_rules]
        results = sorted(
            [f.result() for f in futures],
            key=lambda r: r.rule_id,
        )

        totals: dict[RuleStatus, int] = {}
        for res in results:
            totals[res.status] = totals.get(res.status, 0) + 1

        return RuleRunReport(
            run_id=str(uuid.uuid4()),
            generated_at=datetime.now(timezone.utc),
            period_end=ctx.period_end,
            results=results,
            totals=totals,
        )
