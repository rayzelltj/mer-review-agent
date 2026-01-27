from __future__ import annotations

from typing import Dict, Iterable, Type

from .rule import Rule


class RuleRegistry:
    def __init__(self):
        self._rules: Dict[str, Type[Rule]] = {}

    def register(self, rule_cls: Type[Rule]) -> None:
        rule_id = getattr(rule_cls, "rule_id", None)
        if not rule_id:
            raise ValueError("Rule class missing rule_id")
        if rule_id in self._rules:
            raise ValueError(f"Duplicate rule_id registered: {rule_id}")
        self._rules[rule_id] = rule_cls

    def create_all(self) -> list[Rule]:
        return [cls() for cls in self._rules.values()]

    def get(self, rule_id: str) -> Type[Rule]:
        return self._rules[rule_id]

    def ids(self) -> Iterable[str]:
        return self._rules.keys()


registry = RuleRegistry()


def register_rule(rule_cls: Type[Rule]) -> Type[Rule]:
    registry.register(rule_cls)
    return rule_cls

