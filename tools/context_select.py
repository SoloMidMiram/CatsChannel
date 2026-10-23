"""Bounded keyword/tag retrieval with source-preserving rendering."""

from __future__ import annotations

import json
import re
from typing import Any

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(value: object) -> set[str]:
    return set(_TOKEN.findall(str(value).lower()))


def select_records(
    records: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    query: str,
    *,
    kinds: set[str] | None = None,
    areas: set[str] | None = None,
    max_records: int = 8,
) -> list[tuple[int, dict[str, Any]]]:
    """Keyword/tag retrieval with deduplication and deterministic reranking."""
    query_tokens = _tokens(query)
    if not query_tokens:
        return []
    source_by_id = {source["id"]: source for source in sources}
    superseded = {
        record["supersedes"] for record in records if isinstance(record.get("supersedes"), str)
    }
    ranked: list[tuple[int, dict[str, Any]]] = []
    for record in records:
        if record["id"] in superseded or record["status"] == "superseded":
            continue
        if kinds and record["kind"] not in kinds:
            continue
        if areas and record["area"] not in areas:
            continue
        tag_tokens = set(record["tags"])
        categorical_tokens = _tokens(
            f"{record['kind']} {record['area']} {record['status']} {record.get('scope', '')}"
        )
        statement_tokens = _tokens(record["statement"])
        detail_tokens = _tokens(record.get("details", ""))
        source_tokens = _tokens(source_by_id[record["source"]]["title"])
        score = 0
        score += 10 * len(query_tokens & tag_tokens)
        score += 6 * len(query_tokens & categorical_tokens)
        score += 4 * len(query_tokens & statement_tokens)
        score += 2 * len(query_tokens & detail_tokens)
        score += len(query_tokens & source_tokens)
        if query.lower().strip() in record["statement"].lower():
            score += 12
        if score == 0:
            continue
        score += {"current": 3, "stable": 2, "historical": 0, "stale": -3}.get(
            record["freshness"], -1
        )
        if record["status"] in {
            "open",
            "pending",
            "in_progress",
            "blocked",
            "proposed",
        } and query_tokens & {"block", "blocking", "next", "pending", "unresolved"}:
            score += 5
        ranked.append((score, record))
    ranked.sort(
        key=lambda item: (
            -item[0],
            -item[1].get("brief", {}).get("priority", 0),
            item[1]["id"],
        )
    )
    deduplicated: list[tuple[int, dict[str, Any]]] = []
    seen_statements: set[str] = set()
    for item in ranked:
        normalized_statement = " ".join(item[1]["statement"].lower().split())
        if normalized_statement in seen_statements:
            continue
        deduplicated.append(item)
        seen_statements.add(normalized_statement)
    return deduplicated[:max_records]


def render_selection(
    query: str,
    selected: list[tuple[int, dict[str, Any]]],
    sources: list[dict[str, Any]],
    *,
    include_details: bool,
    max_chars: int,
) -> str:
    if max_chars < 300:
        raise ValueError("max_chars must be at least 300")
    source_by_id = {source["id"]: source for source in sources}
    query_limit = min(512, max_chars // 4)
    displayed_query = query if len(query) <= query_limit else query[: query_limit - 1] + "…"
    header = f"# Selected project context\n\nQuery: {displayed_query}\n"
    if not selected:
        return f"{header}\nNo matching records.\n"
    chunks: list[str] = []
    length = len(header) + 1
    for score, record in selected:
        source = source_by_id[record["source"]]
        lines = [
            f"## {record['id']} ({record['kind']} / {record['area']}; score {score})",
            "",
            f"- Statement: {record['statement']}",
            f"- Status: {record['status']}",
            f"- Freshness: {record['freshness']} (verified {record['last_verified_at']})",
            f"- Source: {record['source']} — {source['title']} — {source['locator']}",
            f"- Verified against: {', '.join(record['verified_against'])}",
        ]
        if record.get("scope"):
            lines.append(f"- Scope: {record['scope']}")
        base = "\n".join(lines) + "\n"
        detailed = base
        if include_details and record.get("details"):
            detailed += f"- Details: {record['details']}\n"
        chunk = detailed if length + len(detailed) <= max_chars else base
        if length + len(chunk) > max_chars:
            continue
        chunks.append(chunk)
        length += len(chunk) + 1
    if not chunks:
        return f"{header}\nNo record fits the requested context budget.\n"
    return f"{header}\n" + "\n".join(chunks)


def render_json_selection(
    selected: list[tuple[int, dict[str, Any]]],
    *,
    include_details: bool,
    max_chars: int,
) -> str:
    """Budget the final serialized array, retaining complete provenance fields."""
    if max_chars < 300:
        raise ValueError("max_chars must be at least 300")

    def serialize(payload: list[dict]) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"

    payload: list[dict] = []
    for score, record in selected:
        compact = {
            key: record[key]
            for key in (
                "id",
                "kind",
                "area",
                "statement",
                "status",
                "source",
                "freshness",
                "last_verified_at",
                "verified_against",
            )
        }
        compact["score"] = score
        detailed = compact.copy()
        if include_details and record.get("details"):
            detailed["details"] = record["details"]
        if len(serialize([*payload, detailed])) <= max_chars:
            payload.append(detailed)
        elif len(serialize([*payload, compact])) <= max_chars:
            payload.append(compact)
    return serialize(payload)
