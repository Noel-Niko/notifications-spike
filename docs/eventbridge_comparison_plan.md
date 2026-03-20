# EventBridge vs Notifications Latency Comparison — Implementation Plan

> **Note**: Copy this plan to `docs/eventbridge_comparison_plan.md` after approval per CLAUDE.md conventions.

## Context

We have an existing analysis measuring Genesys Notifications API (WebSocket) transcription latency using Deepgram as ground truth. The authoritative executive summary is `docs/analysis.md` — a 342-line document containing a 3-column comparison table (Deepgram, Genesys Self-Reported, Genesys End-to-End Ground Truth), pipeline diagrams, methodology, per-movie breakdown, and recommendations.

We now need to add EventBridge (SQS) as a second delivery mechanism and compare it head-to-head against the existing Notifications (WebSocket) path. The user will call Genesys and play the same 6 movie recordings with all three systems capturing in parallel:
- **notifications-spike** — WebSocket Notifications API (`main.py`, saves to `conversation_events/<id>.jsonl`)
- **SQS consumer** — EventBridge → SQS (new script, saves to `EventBridge/conversation_events/<id>.jsonl`)
- **poc-deepgram** — ground truth audio timestamps via BlackHole

### Existing Data & Results (for reference)

| Source | File | Key Numbers |
|--------|------|-------------|
| Notifications ground truth (6 calls) | `analysis_results/cross_system/correlation_summary.json` | 93 matched pairs, median 1712ms, p95 10544ms |
| Genesys self-reported (6 calls) | `docs/analysis.md` line 15 | 130 utterances, median 432ms, mean 626ms |
| Genesys self-reported (147 prod calls) | `analysis_results/latency_summary.json` | 8735 utterances, median 837ms, mean 938ms |
| Deepgram/AudioHook proxy (6 calls) | `docs/analysis.md` line 15 | 225 utterances, median 1248ms, p95 3469ms |

### Self-Reported Latency Method (Unchanged)

The anchor-event method (`latency_analysis-01-RESULTS.ipynb`) is **delivery-path-independent**:
```
conversation_start = min(receivedAt - (offsetMs + durationMs) / 1000)  across all events
latency = receivedAt - (conversation_start + (offsetMs + durationMs) / 1000)
```
The `receivedAt` shifts all events by the same delivery overhead constant, which the anchor cancels out. This produces nearly identical self-reported numbers regardless of whether you compute from Notifications or EventBridge events. For the new 6 calls, reuse this method on the new Notifications data.

### Key Codebase Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI WebSocket client, captures Genesys transcription events, saves JSONL to `conversation_events/` |
| `scripts/correlate_latency.py` | Core correlation library: `load_deepgram_session()`, `load_genesys_conversation()`, `match_utterances()`, `correlate()`, `CorrelationResult`, `GenesysEvent` |
| `tests/test_correlate.py` | Tests for correlation library |
| `notebooks/cross_system_latency-01-RESULTS.ipynb` | Existing Notifications analysis notebook (template for new notebook) |
| `notebooks/latency_analysis-01-RESULTS.ipynb` | Self-reported latency analysis (anchor-event method implementation) |
| `EventBridge/Genesys_EventBridge_Setup_Runbook.md` | EB infrastructure setup, event schema, SQS/CWL/ngrok targets |
| `EventBridge/receiver.py` | Simple HTTP receiver (prints to console, does NOT save files) |
| `docs/analysis.md` | Authoritative executive summary — needs structural updates |
| `docs/manual_test_directions.md` | Test procedure for running all systems simultaneously |

### Notifications JSONL Format (`conversation_events/*.jsonl`)
```json
{
  "conversationId": "bf4c94bf-...",
  "receivedAt": 1773860117.2705212,
  "transcript": {
    "utteranceId": "...", "isFinal": true, "channel": "EXTERNAL",
    "alternatives": [{"confidence": 0.598, "offsetMs": 23460, "durationMs": 1040, "transcript": "..."}],
    "engineProvider": "GENESYS", "engineId": "r2d2"
  }
}
```

### EventBridge Event Format (from SQS, per runbook)
```json
{
  "version": "0", "id": "6efd5506-...",
  "detail-type": "v2.conversations.{id}.transcription",
  "source": "aws.partner/genesys.com/cloud/.../DA-VOICE-SB",
  "time": "2026-03-19T22:04:48Z",
  "detail": {
    "eventBody": {
      "eventTime": "2026-03-19T22:04:48.128Z",
      "conversationId": "97b9dcb3-...",
      "communicationId": "7dd98c4f-...",
      "sessionStartTimeMs": 1773957594383,
      "transcriptionStartTimeMs": 1773957594336,
      "transcripts": [{
        "utteranceId": "5b778cb0-...", "isFinal": true, "channel": "EXTERNAL",
        "alternatives": [{"confidence": 0.658, "offsetMs": 278620, "durationMs": 12480,
          "transcript": "raw text", "decoratedTranscript": "normalized text"}],
        "engineProvider": "GENESYS", "engineId": "r2d2"
      }]
    },
    "metadata": {"CorrelationId": "..."}
  }
}
```

Key structural differences from Notifications:
- `transcripts` is an **array** (vs Notifications' single `transcript` object)
- Wrapped in `detail.eventBody` envelope
- Has additional absolute timestamps: `eventTime`, `sessionStartTimeMs`
- `time` field is the EB envelope timestamp (second-level precision only)

---

## Deliverables

### 1. SQS Consumer Script — `scripts/sqs_consumer.py` (new file)

Polls `genesys-transcription-latency-test` SQS queue, saves events as JSONL per conversation to `EventBridge/conversation_events/<conversation-id>.jsonl`.

**Saved JSONL format** (one line per SQS message):
```json
{
  "conversationId": "97b9dcb3-...",
  "receivedAt": 1773957600.123,
  "sqsSentTimestamp": 1773957599800,
  "ebTime": "2026-03-19T22:04:48Z",
  "genesysEventTime": "2026-03-19T22:04:48.128Z",
  "sessionStartTimeMs": 1773957594383,
  "transcripts": [{ ...full transcript array from eventBody... }],
  "rawEvent": { ...full EB envelope for traceability... }
}
```

**Timing fields for analysis:**

| Field | Source | Precision | Used For |
|-------|--------|-----------|----------|
| `genesysEventTime` | `detail.eventBody.eventTime` | ms | Hop analysis (when Genesys emitted event) |
| `sessionStartTimeMs` | `detail.eventBody.sessionStartTimeMs` | ms | Hop analysis baseline |
| `ebTime` | top-level `time` field | **second only** | Hop analysis (caveat: ~1s rounding) |
| `sqsSentTimestamp` | SQS message attribute `SentTimestamp` | ms | Hop analysis (when SQS enqueued) |
| `receivedAt` | local `time.time()` | ms | Ground truth correlation (local arrival time) |

To get `SentTimestamp`, the `receive_message` call must include `AttributeNames=['SentTimestamp']`.

**Config via env vars** (12-factor):
- `SQS_QUEUE_URL` (required) — `https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test`
- `AWS_PROFILE` (default: `765425735388_admin-role`) — **MUST** use the admin-role profile from account 765425735388. The SSO role in 173078698674 is blocked by Organization SCP `p-kfhxcsd9`. See runbook "Cross-Account Access Notes" section.
- `EB_EVENT_DIR` (default: `EventBridge/conversation_events`)

**Design:**
- Pure functions `parse_sqs_message(body: str, received_at: float, sqs_sent_timestamp: int | None) -> dict` and `save_event(parsed: dict, output_dir: Path) -> Path` — testable without boto3
- `poll_sqs(queue_url: str, profile: str, output_dir: Path) -> None` — AWS interaction, lazy `import boto3`
- Graceful SIGINT/SIGTERM shutdown via `nonlocal` flag (no global variables)
- Long polling: `WaitTimeSeconds=20`
- Delete messages after successful save

**Tests first — `tests/test_sqs_consumer.py`:**

| Test Class | Tests |
|------------|-------|
| `TestParseSqsMessage` | extracts conversationId, receivedAt, sqsSentTimestamp, sessionStartTimeMs, ebTime, genesysEventTime, transcripts, rawEvent |
| `TestSaveEvent` | creates output dir and file, appends to existing file, each line is valid JSON with expected fields |

Use a `SAMPLE_EB_EVENT` fixture based on the confirmed event structure from the runbook (lines 71–137).

### 2. EventBridge Loader — extend `scripts/correlate_latency.py`

Add `load_eventbridge_conversation(path: Path) -> list[GenesysEvent]`:
- Parses EB JSONL format (top-level `transcripts[]` array)
- Handles **multiple transcripts per JSONL line** (one SQS message can carry multiple utterances)
- Filters `isFinal=True` only
- **Deduplicates by `utteranceId`** using a `seen: set[str]` — SQS standard queues guarantee at-least-once delivery; duplicates would inflate match counts
- Returns same `GenesysEvent` dataclass — the entire downstream pipeline (`match_utterances`, `compute_latency`, `correlate`) works unchanged

**`GenesysEvent` dataclass (existing, do NOT modify):**
```python
@dataclass
class GenesysEvent:
    transcript: str
    received_at: float
    channel: str
    utterance_id: str = ""
    offset_ms: int = 0
    duration_ms: int = 0
```
EB-specific fields (`ebTime`, `genesysEventTime`, `sqsSentTimestamp`, `sessionStartTimeMs`) are NOT added to this dataclass. The hop analysis and self-reported computations in the notebook read raw JSONL directly via inline functions. The loader's only job is feeding the correlation pipeline.

Add `correlate_eventbridge(deepgram_path: Path, eventbridge_path: Path, similarity_threshold: float) -> list[CorrelationResult]` — convenience wrapper that calls `load_deepgram_session`, `load_eventbridge_conversation`, `match_utterances`, and `compute_latency`.

**Tests first — add to `tests/test_correlate.py`:**

| Test Class | Tests |
|------------|-------|
| `TestLoadEventBridgeConversation` | loads events, extracts receivedAt/transcript/channel/utteranceId, filters non-final, handles multiple transcripts per line, deduplicates by utteranceId |

Follow the exact fixture pattern of existing `TestLoadGenesysConversation` class in the same file.

### 3. Analysis Notebook — `notebooks/cross_system_latency-02-EB-RESULTS.ipynb`

Follows structure of existing `-01-RESULTS` notebook. All functions inline (DAB exception). No widgets. `NUM_RECENT = 6` default.

| Module | Content |
|--------|---------|
| **1** | Setup & config — same pattern as `-01-RESULTS`, adds `EB_EVENTS_DIR = REPO_ROOT / "EventBridge" / "conversation_events"`, `NUM_RECENT = 6` |
| **2** | Load & auto-match files from all 3 sources (Deepgram, Notifications, EventBridge) by time overlap. Also match Notifications ↔ EventBridge by conversation ID (same UUID in both directories). |
| **2.5** | **Data quality validation** — list conversation IDs captured by each path; flag any conversation present in one path but not the other; compare total event count and `isFinal` count per conversation per path; halt with warning if mismatch is severe |
| **3** | Correlate both paths with Deepgram ground truth → `df_notif` and `df_eb` DataFrames. Tag each with a `source` column. |
| **4** | Summary statistics for each path separately (same format as existing Module 4) |
| **4.5** | **Self-reported latency from same 6 calls** — rerun the anchor-event method from `latency_analysis-01-RESULTS.ipynb` on the NEW Notifications data (inline reimplementation). This produces the self-reported numbers for the comparison table. Uses `calculate_conversation_latency()` logic from that notebook (Module 3, cell 7). |
| **5** | **Head-to-head comparison table** — see detail below |
| **6** | Visualizations — distribution overlay histogram (Notif vs EB, two colors with alpha), side-by-side box plots (all 4 rows), timeline scatter colored by source |
| **7** | **EB 3-hop analysis** — see detail below |
| **8** | Matched pairs detail tables (one per path) |
| **9** | Export to `analysis_results/cross_system_eb/` — CSVs, summary JSON, PNGs, `head_to_head_comparison.json` |

#### Module 5 Detail: Head-to-Head Comparison Table

This is the key deliverable. Four rows:

| Row | What It Measures | Source | Formula |
|-----|------------------|--------|---------|
| **Notifications API (WebSocket)** | True end-to-end via WebSocket (Stages 1–4a) | Deepgram × Notifications correlation | `notif_receivedAt - deepgram_audio_wall_clock_end` |
| **EventBridge (SQS)** | True end-to-end via EB→SQS (Stages 1–4b) | Deepgram × EventBridge correlation | `eb_receivedAt - deepgram_audio_wall_clock_end` |
| **Genesys Self-Reported** | Internal processing (Stages 2–3, anchor-relative) | Anchor-event method on new Notifications data | `receivedAt - (conv_start + (offsetMs+durationMs)/1000)` |
| **Deepgram/Audio Hook** ¹ | Deepgram Nova-3 STT latency | poc-deepgram session data | `server_receipt_time - audio_wall_clock_end` |

¹ *Deepgram processes the same audio independently via BlackHole. This measures a completely separate STT pipeline (Deepgram Nova-3 via WebSocket, 300ms endpointing) and is included as a reference benchmark for fast cloud STT, not a direct comparison to Genesys delivery mechanisms.*

Columns: Median, Mean, p95, p99, Min, Max, N

Plus delta and ratio rows:
```
Delta (EB - Notif):     ???ms     ???ms     ???ms     ...
Ratio (EB / Notif):     ???x      ???x      ???x      ...
```

#### Module 7 Detail: EB 3-Hop Analysis

Uses the 4 delivery timestamps to decompose the EventBridge pipeline into 3 hops:

```
genesysEventTime ──> ebTime ──> sqsSentTimestamp ──> receivedAt
      │                  │              │                   │
      └── Hop 1 ────────┘              │                   │
           Genesys → EB                 │                   │
           (second precision ⚠️)        │                   │
                         └── Hop 2 ────┘                   │
                              EB → SQS enqueue             │
                              (limited by ebTime ⚠️)       │
                                        └── Hop 3 ────────┘
                                             SQS queue → consumer poll
                                             (ms precision ✓)
```

**⚠️ Precision caveat (document prominently):** `ebTime` has only second-level granularity (`"2026-03-19T22:04:48Z"`) while `genesysEventTime` has ms precision (`"2026-03-19T22:04:48.128Z"`). Hop 1 measurements have ~1s rounding error. Hop 2 is also affected. Only Hop 3 (`sqsSentTimestamp` → `receivedAt`) has ms precision on both ends.

Reads raw EB JSONL directly via inline function (NOT via `GenesysEvent` — separate concern).

Visualizations: stacked bar chart (mean per hop), scatter plot (hop1 vs hop3), summary table (median/mean/p95 per hop).

### 4. Update `docs/manual_test_directions.md`

Insert new step between existing notifications-spike startup (step 5) and poc-deepgram startup (step 6):

**Step 5b: Start EventBridge SQS consumer (Terminal 3)**
```bash
cd ~/PycharmProjects/notifications-spike
export SQS_QUEUE_URL="https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test"
export AWS_PROFILE="765425735388_admin-role"
uv run python -m scripts.sqs_consumer
```
Wait for: `Polling SQS queue: ...`

Include notes about:
- Must use `765425735388_admin-role` profile (SCP blocker for SSO role)
- Both systems capture same conversations simultaneously
- If auth fails: `aws sso login --profile 765425735388_admin-role`

Add to "After the Call" section:
- Step 12b: Identify EventBridge output files, cross-check conversation IDs match Notifications
- Step 14b: Reference new EB notebook

Add EB pipeline diagram to "What This Measures" section:
```
EventBridge Delivery Path:
Speaker → [1] Audio Capture → [2] r2d2 STT → [3] Endpointing
  → [4a] EventBridge publish → [4b] EB rule → SQS enqueue → [4c] Consumer polls
```

### 5. Update `docs/analysis.md` (post-data-collection) — 9 Specific Updates

After the 6-call run produces actual numbers, update the executive summary with these 9 structural changes:

#### 5.1. Main comparison table (line 13) — add EventBridge column

Current 3 columns → 4 columns. Relabel existing ground-truth column:

```
| Metric | Deepgram (AudioHook Proxy) | Genesys Self-Reported | Notifications API (WebSocket) | EventBridge (SQS) |
```

Fill with actual numbers from the notebook's Module 5 output.

#### 5.2. Architecture diagram (lines 64–93) — add Path A2

Current diagram has Path A (WebSocket) and Path B (Deepgram). Add Path A2:

```
│  PATH A2 — The EventBridge delivery pipeline (what we're comparing)
├──→ [Genesys Cloud] ──→ EventBridge ──→ SQS Queue ──→ sqs_consumer
│     Same event as        EB rule routes     Standard queue      Local script polls
│     Path A1, but         to SQS target      (at-least-once)     and records
│     published to EB      (Stage 4b-i)       (Stage 4b-ii)       receivedAt
│     (Stage 4b)                                                   (Stage 4b-iii)
```

#### 5.3. Pipeline scope diagram (lines 130–156) — split Stage 4

Show two variants:
```
Stage 4a: WebSocket Delivery (~50–200ms)  → Notifications API column
Stage 4b: EventBridge → SQS → Consumer   → EventBridge column
```

Update ground-truth brackets to show both.

#### 5.4. "What True Latency Captures" table (lines 117–123) — add EB delivery row

Split Stage 4 into 4a and 4b with their respective typical contributions:

```
| Stage 4a. WebSocket Delivery | ... | Low (~50–200 ms) |
| Stage 4b. EB → SQS Delivery | ... | Measured: ???ms   |
```

#### 5.5. "How the two paths connect" table (lines 96–101) — add Path A2 row

```
| Path        | Produces                          | Table Column                        |
|-------------|-----------------------------------|-------------------------------------|
| Path A1     | notif_receivedAt + event metadata  | Notifications API (WebSocket)       |
| Path A2     | eb_receivedAt + event metadata     | EventBridge (SQS)                   |
| Path B      | audio_wall_clock_end + Deepgram timing | Deepgram Nova-3 (AudioHook Proxy)|
| A1 × B      | notif_receivedAt - audio_end      | Notifications ground truth          |
| A2 × B      | eb_receivedAt - audio_end         | EventBridge ground truth            |
```

#### 5.6. Key Takeaways (lines 31–41) — add EB comparison finding

Add new takeaway (likely #5 or #6):

> **N. EventBridge delivery adds/does not add significant overhead vs WebSocket** — median EB latency is ???ms vs ???ms for Notifications (???x ratio). The SQS polling overhead...

Fill with actual comparative finding from notebook.

#### 5.7. New section: "EventBridge Hop Analysis"

Insert after "Why the p95 Is Dramatically Higher" section (after line 195). Content:
- 3-hop breakdown diagram
- Per-hop median/mean/p95 table
- `ebTime` second-precision caveat
- Where time is spent in the EB pipeline
- Whether the dominant cost is EB routing, SQS enqueue, or poll cycle

#### 5.8. Reproduction section (lines 331–342) — add EB commands

```bash
# Start SQS consumer (Terminal 3, alongside notifications-spike and poc-deepgram)
export SQS_QUEUE_URL="https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test"
export AWS_PROFILE="765425735388_admin-role"
uv run python -m scripts.sqs_consumer

# Run the EB comparison notebook
cd notebooks && uv run jupyter notebook cross_system_latency-02-EB-RESULTS.ipynb
```

#### 5.9. Test Corpus table (lines 203–213) — add EB match count column

Each movie row gains a column for EventBridge matched pairs alongside Notifications:

```
| # | Movie | Duration | Notif Matches | EB Matches | Notif Median | EB Median | ...
```

### 6. Dependency & Config

- Add `boto3>=1.35.0` to `pyproject.toml` **main dependencies** (not dev), then `uv lock && uv sync` (must complete before tests)
- Add to `.env` (not committed):
  ```
  SQS_QUEUE_URL=https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test
  AWS_PROFILE=765425735388_admin-role
  ```
- **Do NOT add `EventBridge/conversation_events/` to `.gitignore`** — existing `conversation_events/` is tracked as test evidence; treat both directories consistently

---

## Implementation Order

```
Step 0:  pyproject.toml (add boto3) → uv lock && uv sync
         ↓
Step 1:  [parallel] tests/test_sqs_consumer.py  |  tests/test_correlate.py (add EB tests)
         ↓
Step 2:  [parallel] scripts/sqs_consumer.py     |  scripts/correlate_latency.py (add EB loader)
         ↓
Step 3:  uv run pytest tests/test_sqs_consumer.py tests/test_correlate.py -v
         ↓
Step 4:  [parallel] docs/manual_test_directions.md  |  notebooks/cross_system_latency-02-EB-RESULTS.ipynb
         ↓
Step 5:  .env updates
         ↓
         === USER: Purge SQS, start all 3 systems, play 6 recordings ===
         ↓
Step 6:  Run notebook with real data, finalize
         ↓
Step 7:  Update docs/analysis.md with actual numbers (9 structural updates)
```

## Verification

1. `uv lock && uv sync` — boto3 installed successfully
2. `uv run pytest tests/test_sqs_consumer.py tests/test_correlate.py -v` — all new tests pass, existing tests still pass
3. **Smoke test** — purge SQS queue, start all 3 systems, make 1 short test call:
   - `EventBridge/conversation_events/<id>.jsonl` created with valid JSONL
   - JSONL contains `sqsSentTimestamp`, `sessionStartTimeMs`, `genesysEventTime`
   - Same conversation ID appears in both `conversation_events/<id>.jsonl` and `EventBridge/conversation_events/<id>.jsonl`
   - Module 2.5 data quality cell confirms both paths captured the same conversation
4. Run notebook with smoke test data — all cells execute, comparison table renders (even if N=1)
5. **Full 6-call run** — play all 6 recordings, finalize notebook
6. Update `docs/analysis.md` with final numbers — all 9 sections updated

## Critical Files

| File | Action | Details |
|------|--------|---------|
| `pyproject.toml` | Edit | Add `boto3>=1.35.0` to main dependencies |
| `scripts/sqs_consumer.py` | **Create** | SQS polling consumer with `parse_sqs_message()`, `save_event()`, `poll_sqs()` |
| `tests/test_sqs_consumer.py` | **Create** | `TestParseSqsMessage`, `TestSaveEvent` |
| `scripts/correlate_latency.py` | Edit | Add `load_eventbridge_conversation()` (with dedup), `correlate_eventbridge()` |
| `tests/test_correlate.py` | Edit | Add `TestLoadEventBridgeConversation` class |
| `notebooks/cross_system_latency-02-EB-RESULTS.ipynb` | **Create** | 9-module analysis notebook |
| `docs/manual_test_directions.md` | Edit | Add Terminal 3 SQS consumer step, EB pipeline diagram |
| `docs/analysis.md` | Edit | 9 structural updates (post-data-collection) |
| `.env` | Edit | Add `SQS_QUEUE_URL`, `AWS_PROFILE` |
