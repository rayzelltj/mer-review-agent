from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Type

from pydantic import BaseModel

from .context import RuleContext
from .models import RuleResult


class Rule(ABC):
    rule_id: str
    rule_title: str
    best_practices_reference: str
    sources: List[str]
    config_model: Type[BaseModel]

    def __init__(self):
        if not getattr(self, "rule_id", None):
            raise ValueError("Rule must define rule_id")

    @abstractmethod
    def evaluate(self, ctx: RuleContext) -> RuleResult:  # pragma: no cover
        raise NotImplementedError

