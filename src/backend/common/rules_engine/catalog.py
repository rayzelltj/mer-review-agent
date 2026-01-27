from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from .registry import registry

# Ensure built-in rules are imported/registered when generating a catalog.
from . import rules as _builtin_rules  # noqa: F401


class RuleCatalogEntry(BaseModel):
    rule_id: str
    rule_title: str
    best_practices_reference: str = ""
    sources: List[str] = Field(default_factory=list)

    module: str
    class_name: str

    config_model: str
    config_schema: Dict[str, Any]


def build_catalog() -> List[RuleCatalogEntry]:
    entries: List[RuleCatalogEntry] = []
    for rule_id in registry.ids():
        rule_cls = registry.get(rule_id)
        cfg_model = getattr(rule_cls, "config_model", None)
        cfg_schema: Dict[str, Any] = {}
        cfg_model_name = ""
        if cfg_model is not None:
            cfg_model_name = getattr(cfg_model, "__name__", str(cfg_model))
            try:
                cfg_schema = cfg_model.model_json_schema()  # pydantic v2
            except Exception:
                cfg_schema = {}

        entries.append(
            RuleCatalogEntry(
                rule_id=rule_id,
                rule_title=getattr(rule_cls, "rule_title", ""),
                best_practices_reference=getattr(rule_cls, "best_practices_reference", ""),
                sources=list(getattr(rule_cls, "sources", []) or []),
                module=getattr(rule_cls, "__module__", ""),
                class_name=getattr(rule_cls, "__name__", ""),
                config_model=cfg_model_name,
                config_schema=cfg_schema,
            )
        )

    entries.sort(key=lambda e: e.rule_id)
    return entries


def _dump_json(catalog: list[dict[str, Any]]) -> str:
    return json.dumps(catalog, indent=2, sort_keys=True)


def _dump_yaml(catalog: list[dict[str, Any]]) -> str:
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "PyYAML is required for YAML output. Install it in your backend venv (e.g., `uv add pyyaml`)."
        ) from exc

    return yaml.safe_dump(catalog, sort_keys=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate a rules catalog from the registry.")
    parser.add_argument(
        "--format",
        choices=("yaml", "json"),
        default="yaml",
        help="Output format (default: yaml).",
    )
    args = parser.parse_args(argv)

    catalog = [e.model_dump() for e in build_catalog()]
    if args.format == "json":
        print(_dump_json(catalog))
    else:
        print(_dump_yaml(catalog))


if __name__ == "__main__":
    main()
