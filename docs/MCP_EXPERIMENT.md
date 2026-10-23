# MCP Phase 2R protocol

Phase 2R was a bounded feasibility and validity-repair exercise. It did not test
production activation and does not justify making MCP mandatory for ordinary work.
The compact evidence summary is in `docs/evidence/mcp-phase2r-2026-10-23.md`.

## Conditions

The experiment used a fixed read-only source snapshot, one model/reasoning setting,
frozen baseline documentation and independently prepared answer oracles. Conditions
were:

- A: shell and source inspection only;
- B: A plus read-only Serena semantic tools;
- C: A plus guarded Context7 public documentation tools.

"Natural" prompts did not name an MCP server or require tool use. "Mandatory"
prompts explicitly required the relevant tools and were analyzed separately. An
"encouraged" condition was not run. One replicate per cell supports feasibility,
not performance or causal benefit.

R1 asked for source-symbol and caller tracing. R2 asked for version-sensitive
aiogram and SQLAlchemy guidance. Natural A/B and A/C pairs used byte-identical task
prompts. Live evidence returned only to a treatment cell made that cell ineligible
for an evidence-matched causal quality comparison.

## Transport and privacy gates

Before comparison, one stdio connection had to complete `initialize`, `tools/list`,
a first retrieval, an eight-second idle, and a second retrieval. Transport success,
tool success, tool selection, answer quality, and process exit were recorded as
separate concepts.

Context7 accepted only `resolve-library-id` and `query-docs`, only for aiogram and
SQLAlchemy base IDs, with short generic public questions. It had no source mount
and no credential environment. Audit output retained fixed classifications and a
request digest, never raw arguments or returned documentation.

Serena used a read-only source mount, disabled network and memories, and exposed
only `find_declaration`, `find_implementations`, `find_referencing_symbols`,
`find_symbol`, and `get_symbols_overview`. Its reference coordinates in the tested
setup were zero-based; citations must normalize them to one-based source lines and
then verify the referenced text.

## Validity repairs

Two harness defects were reproduced independently of answer quality:

1. `--die-with-parent` bound server lifetime to the thread that spawned the
   bubblewrap launcher. Exiting that thread killed an otherwise healthy server with
   SIGKILL. Removing that option preserved the same connection; explicit
   supervision now owns termination and reaping.
2. The guard wrote policy errors without a terminating newline. Clients waiting for
   framed JSON-RPC lines reported timeouts. Newline-terminated rejection restored
   prompt errors and allowed a later valid request on the same connection.

The base-ID allowlist was deliberately retained. A version-qualified library ID is
therefore a local policy rejection, not evidence that the upstream service lacks
that version. Exact-version retrieval remains unestablished.

## Result interpretation

All six registered cells completed, but every natural MCP condition made zero MCP
calls. Mandatory use demonstrated four successful Serena calls and four successful
of six attempted Context7 calls; the two apparent Context7 timeouts were the
unframed local policy errors above. These observations establish visibility and
bounded operational feasibility only.

Do not infer an MCP latency, quality, or adoption benefit from elapsed-time or
single-reviewer scores. The natural comparisons had no actual tool treatment, the
mandatory conditions changed the prompt, the Context7 mandatory condition gained
unequal live evidence, and answer scoring was not independently blinded. The
decision is **REVISE**.
