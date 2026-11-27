# Durable project context

This directory is CatsChannel's checked-in recall and audit layer. It does not
replace code, Git history, GitHub, tests, or original documents. It connects those
sources to small records that can be searched and turned into a current brief.

## The four layers

| Layer | Artifact | Contract |
| --- | --- | --- |
| Original evidence | `sources.jsonl`, `evidence/`, Git/GitHub and repository documents | Preserve or point to what actually happened. |
| Structured records | `records.jsonl` and `taxonomy.yaml` | Keep facts, decisions, tasks, blockers, and proposals distinguishable. |
| Current project brief | generated `overview.md` and `decisions/` | Explain the situation from records without a second hand-maintained narrative. |
| Context selection | `tools/project_context.py select` | Retrieve, deduplicate, rerank, compress, and budget relevant records. |

`source`, `status`, `freshness`, `last_verified_at`, and `verified_against` are
required on every record. A proposal is not a decision; implemented work on an
open PR is scoped explicitly and is not described as merged into `main`.

The taxonomy file uses JSON syntax, which is valid YAML. This lets the offline
tooling parse it with Python's standard library instead of adding a runtime
dependency.

## Read context

Read the generated overview for a quick situation report:

```bash
sed -n '1,240p' project-context/overview.md
```

Select focused context for a question:

```bash
uv run --frozen python tools/project_context.py select \
  "What is blocking the Telegram downloader?"

uv run --frozen python tools/project_context.py select \
  "Why do Windows and WSL use separate virtual environments?" \
  --kind decision --include-details --max-chars 5000
```

Selection starts with keywords and explicit tags. It removes superseded and
duplicate statements, adds a freshness/status relevance bonus, and emits the most
useful records within the requested record and character budgets. Compact output
always preserves audit fields. Semantic retrieval is intentionally a proposal,
not implemented behavior.

`--max-chars` bounds the complete selected-context stdout in both text and JSON,
including headers, formatting and the final newline, using Python Unicode
character counts rather than bytes or tokens. The minimum is 300. Text displays
at most `min(512, max_chars // 4)` query characters (including any ellipsis);
retrieval still uses the full query. JSON remains an array. Optional details are
dropped before whole records; audit/provenance fields are never sliced. If no
record fits, text returns a bounded explanation and JSON returns `[]` plus a
newline. Empty-result and oversized-query output obey the same bound.

## Record a material change

1. Preserve or catalog the evidence in `sources.jsonl`. Prefer immutable commit
   IDs, GitHub URLs, or repository paths.
2. Append or supersede a record in `records.jsonl`; do not rewrite history just to
   make the current state look cleaner.
   Supersession must form an acyclic directed graph. Validation rejects self-links,
   two-record cycles and longer cycles before selection or generation can hide records.
3. Use `current` only for recently reverified external/current-state claims.
   Current entries expire after the taxonomy window. Use `stable` for durable
   contracts and `historical` for past events.
4. Never store tokens, API hashes, phone numbers, cookie contents, session data,
   proxy credentials, or raw third-party exception messages.
5. Validate and regenerate:

```bash
uv run --frozen python tools/project_context.py validate
uv run --frozen python tools/project_context.py generate
uv run --frozen python tools/project_context.py generate --check
```

`overview.md` and files under `decisions/` are generated. Edit their source record,
not the rendered Markdown.

## Current-status rule

For explicit historical replay, use:

```bash
uv run --frozen python tools/project_context.py --as-of 2026-11-26 validate
uv run --frozen python tools/context_inventory.py --ref 1d066c1e30b91798f642c2b28666ed72f5e56bdf --as-of 2026-11-26
```

The default validation clock remains today. A successful as-of replay is not
current acceptance; dates before captured evidence still reject future entries.
The inventory reads immutable Git objects without checking out or executing them.

Local text sources may pin `content_sha256`: SHA-256 of UTF-8 text after universal
newline normalization (CRLF/CR become LF). Validation rejects changed receipts.
When a cataloged source comes from a maintained document, pin a dedicated
snapshot and record its original path and revision.
The [ACT-P2 document snapshots](evidence/act-p2-doc-snapshots-2026-11-27/README.md)
use this layout so historical receipts survive ordinary documentation edits.
This checks byte-content provenance after that normalization, not claim truth,
remote freshness or external service availability. It is not a binary-media hash.
A current record depending on a stale/unknown source is rejected; historical
sources can support an explicitly dated historical event without pretending to
have re-observed it. Source and verification references remain mandatory.

The [November 26 reconciliation](evidence/act-p2-inventory-2026-11-26.json)
preserves the baseline's 166 expired entries, their individual dispositions and
original claims. The November 18 ledger remains its own dated evidence, not a new
verification date. Original historical receipts are retained unchanged.

Memory helps locate evidence and explains why a choice was made. It is insufficient
proof for questions such as “is this fixed?” or “are we ready?”. For those, select
the relevant records and then check the current branch, code, tests, commit, issue,
or pull-request state. If reality differs, update the source catalog and supersede
or refresh the record before regenerating the brief.

The context CLI delegates validation, rendering and selection to separate modules;
existing file and module entry points remain compatible. For bounded repeated
checks, process ownership, local reports and sanitized log auditing, see
[`docs/OFFLINE_CHECKS.md`](../docs/OFFLINE_CHECKS.md).
