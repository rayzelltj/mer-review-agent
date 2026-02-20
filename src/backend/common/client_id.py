from __future__ import annotations

import json
from difflib import get_close_matches
from pathlib import Path
from typing import Iterable, Mapping


def _normalize(value: str) -> str:
    return "".join(ch.lower() for ch in value if ch.isalnum())


def _default_alias_path() -> Path:
    base = Path(__file__).resolve()
    parents = list(base.parents)
    candidates = [parents[1] / "config" / "client_aliases.json"] if len(parents) > 1 else []
    if len(parents) > 3:
        candidates.append(parents[3] / "config" / "client_aliases.json")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    if candidates:
        return candidates[0]
    return base / "config" / "client_aliases.json"


def load_client_aliases(path: Path | None = None) -> dict[str, list[str]]:
    if path is None:
        path = _default_alias_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(raw, dict) and "aliases" in raw:
        raw = raw.get("aliases")
    if not isinstance(raw, dict):
        return {}
    aliases: dict[str, list[str]] = {}
    for canonical, values in raw.items():
        canonical_value = str(canonical or "").strip()
        if not canonical_value:
            continue
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, (list, tuple)):
            values = []
        cleaned: list[str] = []
        for value in values:
            item = str(value or "").strip()
            if item:
                cleaned.append(item)
        aliases[canonical_value] = cleaned
    return aliases


def resolve_client_id(
    requested: str,
    candidates: Iterable[str] | None = None,
    aliases: Mapping[str, Iterable[str]] | None = None,
) -> str:
    requested_value = str(requested or "").strip()
    if not requested_value:
        return requested_value
    requested_norm = _normalize(requested_value)

    if aliases:
        for canonical, alias_list in aliases.items():
            values = [canonical, *list(alias_list or [])]
            for value in values:
                if _normalize(str(value or "")) == requested_norm:
                    return str(canonical).strip()

    if candidates:
        candidate_list = [str(value or "").strip() for value in candidates if str(value or "").strip()]
        for value in candidate_list:
            if _normalize(value) == requested_norm:
                return value

        matches: list[str] = []
        for value in candidate_list:
            normalized_value = _normalize(value)
            if not normalized_value:
                continue
            if requested_norm in normalized_value or normalized_value in requested_norm:
                matches.append(value)
        if len(matches) == 1:
            return matches[0]

    return requested_value


def suggest_client_ids(requested: str, candidates: Iterable[str], limit: int = 3) -> list[str]:
    normalized_requested = _normalize(requested or "")
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)

    if not normalized_requested or not unique:
        return []

    exact = [value for value in unique if _normalize(value) == normalized_requested]
    if exact:
        return exact[:limit]

    matches: list[str] = []
    for value in unique:
        normalized_value = _normalize(value)
        if normalized_requested in normalized_value or normalized_value in normalized_requested:
            matches.append(value)
            if len(matches) >= limit:
                return matches

    lowered = [value.lower() for value in unique]
    close = set(get_close_matches(requested.lower(), lowered, n=limit, cutoff=0.6))
    for value in unique:
        if value in matches:
            continue
        if value.lower() in close:
            matches.append(value)
            if len(matches) >= limit:
                break

    return matches
