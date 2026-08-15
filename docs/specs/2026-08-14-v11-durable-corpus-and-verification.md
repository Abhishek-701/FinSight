# v11 — Durable corpus, verifiable citations, filing diffs

Status: approved design, not yet implemented
Date: 2026-08-14
Predecessor: v10 (first-impression replay, richer charts, Features page)

## Why this update

FinSight's thesis is that citations are the product. Two things currently undercut it.

The corpus is ephemeral. A company a user adds is deleted when the dynamic universe hits
`UNIVERSE_MAX_DYNAMIC` (12) and is wiped entirely on redeploy, because `data/dynamic/` lives on
Render's ephemeral disk. Only six companies ship pre-indexed, so a visitor's own company is
usually absent, and re-adding it costs a full EDGAR round trip, re-parse, and re-embed.

Citations are shown but not checkable. `SourceInspector` renders the chunk text, form, period,
and chunk ID, but there is no path from a cited figure to the actual SEC document it came from.
The chunk knows its accession number; it does not know the filing's URL.

This update makes the corpus durable and cumulative, makes every cited number independently
verifiable against sec.gov, and adds year-over-year filing diffs — a capability that becomes
available once more than one annual filing per company is reachable.

Audience: a public portfolio project with low traffic, used by the author for real research.
Free-tier hosting stays. Cost control is a safety concern, not a scaling one.

## Constraints that shaped the design

- **512MB RAM in the deploy image.** This is the binding constraint. It is why the reranker is
  off in production, why `INGEST_MAX_CONCURRENT` is 1, and why `UNIVERSE_MAX_DYNAMIC` is 12.
  Nothing in this update raises the number of companies resident in memory at once.
- **Embedding is nearly free.** ~630 chunks per company at ~800 tokens is ~500K tokens, about
  one cent at `text-embedding-3-small` pricing. Vectors for all six seeds are ~23MB; Chroma's
  on-disk index is 89MB. The cheap artifact is worth persisting; the expensive one is worth
  treating as disposable.
- **Offline tests.** The `unittest` suite and CI run with no `DATABASE_URL` and no LLM calls.
  Every new layer must be exercisable in that mode.
- **Supabase free tier (500MB).** At ~5MB per company (3.9MB of vectors plus ~1.3MB of text),
  this holds well over 50 companies.

## Scope

In scope:

1. Postgres/sqlite-backed corpus of record, with Chroma demoted to a rebuildable cache
2. Per-company rehydration replacing re-ingest on cache miss
3. Pre-warming the production corpus with ~20 well-known companies
4. Provenance (`cik`, `source_url`) on every chunk and XBRL fact
5. Source inspector: open on EDGAR, expand to surrounding context, highlight the cited figure
6. `filing_diff` tool: year-over-year textual diff of Item 1A / Item 7
7. Polish: coverage page, honest loading states, empty states, responsive pass, design tokens

Explicitly out of scope, with reasons:

- **Numeric multi-year trends** (revenue trajectory, margin direction). Deliberately dropped.
- **Alerts, email digests, earnings calendar, transcripts.** Alerts need an awake process this
  service does not have; transcripts have no reliable free source. Deferred to a later update.
- **Frontend test framework and eval-in-CI.** A conscious omission, not an oversight.
- **pgvector as the retrieval engine.** Rejected: it forces Postgres into local development and
  the offline test suite for no gain, because the vectors are the cheap part.
- **Committing more companies to git as seeds.** Rejected: ~15MB of Chroma index per company
  bloats the repo and image, and pre-warming a durable store costs about a cent per company.

## Section 1 — Durability: Postgres as the corpus of record

### Architecture

Today Chroma (`data/chroma/`) plus `data/chunks.json`, `data/facts.json`, and `data/dynamic/*`
are the only copies of the corpus. After this change, the SQL store is the corpus of record and
Chroma is a local cache that can be rebuilt from it at any time.

Three new tables, created through the existing `storage.connect()` abstraction in
`app/storage.py` so they work on both sqlite and Postgres:

- `corpus_filings` — one row per (ticker, form): `cik`, `accession`, `filing_date`,
  `primary_doc`, `source_url`, `company`, `ingested_at`
- `corpus_chunks` — `chunk_id` (PK), `ticker`, `form`, `accession`, `item`, `section_title`,
  `kind`, `text`, `embedding`
- `corpus_facts` — the XBRL fact rows, plus `accession` and `cik` for provenance
- `corpus_diffs` — cached diff results (section 3), keyed by (ticker, section, prior accession,
  current accession)

`embedding` serializes as JSON text on sqlite and as a float array on Postgres. The dialect
difference is confined to the corpus store module, matching how `sqlite_columns()` and
`insert_ignore()` already confine their differences to one call site each.

### Rehydration replaces re-ingest

`evict_ticker` in `app/universe.py` currently deletes a company's registry entry, chunk and fact
files, and Chroma vectors. It keeps doing exactly that — but it becomes cache eviction rather
than data loss, because the rows survive in SQL.

On a question about a ticker present in `corpus_filings` but absent from the live Chroma
collection, the app rehydrates that one company: read its chunk rows, call `coll.add` with the
stored embeddings, write the chunk/fact JSON files, invalidate the `retrieve` and `facts`
caches, and re-register it in the dynamic registry. No EDGAR request, no OpenAI request — a few
seconds instead of ~60.

The hook sits where the company router already resolves tickers and calls `touch_ticker`
(`app/router.py`), before retrieval runs. Rehydration is **synchronous** — it blocks that
request rather than answering from an incomplete corpus — and emits a `rehydrating` progress
event on the SSE stream so the wait is visible. This is a distinct state from `needs_ingest`:
the company is known and paid for, it is merely cold.

`UNIVERSE_MAX_DYNAMIC` stays at 12. It now describes the in-memory working set, not the size of
the corpus.

### Write path

`ingest_ticker` in `ingest/pipeline.py` gains a SQL write. It goes **last**, after the Chroma
add and the file writes, preserving the existing ordering rule: nothing may observe a ticker as
ingested before its data is queryable. A SQL write failure therefore leaves a working
in-memory ingest that simply is not durable, which is today's behaviour and an acceptable
degradation.

### Pre-warming

A script (`ingest/prewarm.py`) ingests a fixed list of tickers against a running instance so the
production corpus starts broad. The list is the six seeds plus: MSFT, GOOGL, AMZN, META, TSLA,
AVGO, LLY, UNH, V, XOM, COST, HD, PG, BAC — chosen as large, liquid, domestic 10-K filers, since
foreign filers (20-F) and funds have no 10-K and would fail ingest. Twenty companies in total,
for a one-time cost of roughly twenty cents. Because the store is cumulative, every company any
visitor adds thereafter persists for the next visitor.

### Failure modes

- SQL unreachable at boot: the corpus degrades to disk-only (current behaviour). The app must
  not fail to start. `/health` reports which corpus backend is live.
- Rehydration fails or returns nothing: fall back to the existing full EDGAR ingest path.
- Rehydration in flight: the existing single-slot concurrency guard applies, so a rehydration
  and an ingest cannot run simultaneously.

## Section 2 — Verification: a cited number checkable in two clicks

### Provenance

`chunk_filing` in `ingest/chunk.py` already emits `accession`, `filing_date`, `item`,
`section_title`, `form`, and `kind`. It gains `cik` and `source_url`, both available from the
`meta` dict it is already passed (and from `data/manifest.json` for the seed batch).

This requires no re-embedding. `retrieve()` builds results from the `by_id` map loaded out of
`chunks.json`; Chroma is queried only for the ticker filter and the similarity score. Chunk text
and chunk IDs are unchanged, so re-running `ingest/chunk.py` for the seeds is sufficient and the
Chroma collection is untouched.

`extract_facts_from_html` in `ingest/xbrl.py` currently receives ticker, filing date, and form.
It gains accession and CIK so facts carry the same provenance as chunks.

### Inspector affordances

**Open on SEC EDGAR.** A link to the exact primary document, built as
`https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_nodash}/{primary_doc}` — the same
construction as `download.doc_url`. A text fragment (`#:~:text=`) makes Chrome, Edge, and Safari
scroll to and highlight the passage; it is built from the first 8 to 12 whole words of the chunk
after whitespace normalization, percent-encoded, and omitted entirely for `table` chunks, whose
serialized form does not appear verbatim in the filing HTML. Best-effort by design: parsing
normalizes whitespace, so the fragment sometimes fails to match, and Firefox ignores fragments
entirely. In both cases the user lands on the correct document, which is the guarantee that
matters.

**Expand to surrounding context.** Chunk IDs are sequential within a filing (`AAPL-0007`,
`AAPL-10Q-0003`), so the preceding and following chunks are a dictionary lookup away. Expanding
the excerpt in place answers the "is this quote cherry-picked" objection.

**Highlight the cited figure.** Given a figure from the answer, match it inside the chunk text
across the common presentations of the same value (`94,036`, `$94.0 billion`, `94.0`) and
highlight it. Clicking a number in an answer opens the inspector scrolled to that highlight.

**XBRL facts.** Show the tagged concept, unit, and period beside the value, with a secondary
link to SEC's `companyconcept` API as the authoritative machine-readable source.

## Section 3 — Year-over-year filing diffs

A diff is a text operation on two parsed documents. It needs no embeddings, no Chroma, and no
slot in the 12-company working set.

### Flow

1. `latest_form` in `ingest/download.py` walks the submissions feed for the first exact form
   match. Generalize it to return the *nth* match, giving access to the prior 10-K.
2. Download that filing, subject to the existing `INGEST_MAX_RAW_MB` (30MB) cap.
3. `parse_filing` tags every block with its Item number and section title. Select Item 1A or
   Item 7 blocks from both filings.
4. Diff at paragraph granularity with `difflib`. `SequenceMatcher` over the two paragraph lists
   yields raw insertions and deletions; an inserted and a deleted paragraph within the same
   replace block are then paired as "rewritten" when their `SequenceMatcher.ratio()` is at least
   0.60, and reported as an independent addition and removal below that. Rewritten pairs where
   the ratio is above 0.98 are dropped as formatting noise.
5. Synthesize at temp 0 over **only** the added and removed passages, citing them.

### Citations

Diff passages become pseudo-chunks with IDs of the form `AAPL-DIFF-0003`, following the existing
`-CALC-` convention for computed ratios. They carry both accessions and both filing dates, so
section 2's EDGAR link works on either side of the comparison, and they flow through the existing
citation, inspector, and eval machinery without a parallel code path.

### Concurrency and caching

Parsing a second full filing has a memory profile similar to the parse step of an ingest, so the
diff tool shares the existing single-slot concurrency limit. A diff is deterministic for a given
(ticker, section, prior accession, current accession), so results cache in the SQL store and
repeat views are instant.

### Routing and refusal

Regex-first, no router model: "what changed", "new risks", "since last year" and similar
phrasings combined with a section word map straight to the tool.

Typed failure reasons, following the `IngestError.reason` pattern: `no_prior_filing`,
`section_not_found`, `filing_too_large`. Section extraction genuinely fails on some issuers —
financial filers structure Item 1A differently from Apple — and the correct response is a
specific refusal, not a whole-document diff that produces noise.

## Section 4 — Polish

- **Coverage page** ("what FinSight knows"): every loaded company, its filings, filing dates,
  and freshness, built on the existing `/api/corpus/status` endpoint.
- **Honest loading states** for the three distinct waits, which currently all look identical:
  ~3s rehydration, ~60s EDGAR ingest, ~30s free-tier cold start.
- **Empty states** for portfolio, watchlist, screener, and first-load chat, each teaching the
  next action.
- **Responsive pass** so chat and insight work on a phone. Seven views plus a left sidebar plus
  a right watchlist panel is currently desktop-only, and portfolio links get opened on phones.
- **Design tokens** for spacing, type scale, focus rings, and keyboard/a11y consistency, applied
  centrally rather than per component.

## Error handling summary

| Failure | Behaviour |
|---|---|
| SQL unreachable | Corpus degrades to disk-only; app starts; `/health` reports backend |
| Rehydration fails | Fall back to full EDGAR ingest (today's path) |
| Corpus SQL write fails during ingest | Ingest still succeeds in memory; not durable |
| EDGAR text fragment does not match | User lands at the top of the correct document |
| No prior filing on file | `no_prior_filing` refusal |
| Item 1A/7 not isolatable | `section_not_found` refusal, no whole-document fallback |
| SSE stream drops mid-answer | Visible recoverable state with retry |

## Testing

Offline `unittest`, matching the existing suite's style:

- Corpus store round-trip on sqlite: write chunks with embeddings, read them back, confirm
  fidelity including the embedding serialization.
- Rehydration: given rows in the store and an empty Chroma collection, the company becomes
  retrievable without any network call.
- Eviction then rehydration: a company evicted past the working-set limit is still recoverable
  from the store.
- Provenance: every chunk carries a `source_url`, and the constructed URL matches EDGAR's
  archive format for a known accession.
- Diff classification against two small fixture filings, asserting deterministic added/removed
  sets, plus the `section_not_found` refusal on a fixture whose Item 1A cannot be isolated.

Eval additions:

- Diff cases where a specific added risk phrase must appear in the citations.
- A refusal case for a filer whose Item 1A cannot be isolated.

## Sequencing

1. **Provenance and inspector** — self-contained, immediately visible, no schema work.
2. **Corpus store and rehydration** — the largest piece.
3. **Filing diffs** — depends on nothing above it.
4. **Polish** — last, once the surfaces it applies to exist.

Each step is independently shippable and independently valuable, so this can land as four
commits rather than one. Step 2 is the only one with schema and failure-mode risk; if it slips,
steps 1, 3, and 4 still ship.

## Success criteria

- A company added on the deployed instance is still answerable after a redeploy, without an
  EDGAR round trip.
- A company evicted past the working-set limit becomes answerable again in seconds, not ~60.
- Every filing-sourced figure in an answer reaches its source document on sec.gov in two clicks,
  with the surrounding context viewable in-app.
- "What changed in Apple's risk factors since last year" returns a cited summary of actual added
  and removed passages, and refuses specifically when the section cannot be isolated.
- The full offline `unittest` suite passes with no `DATABASE_URL` and no API keys.
- Peak memory in the deploy image does not increase.
