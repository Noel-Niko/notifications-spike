# Cross-System End-to-End Latency Measurement Plan

## Goal

Measure the **true end-to-end latency** from the moment words are spoken on a live Genesys customer service call to the moment the transcribed text arrives at the notifications API (captured by notifications-spike). Use poc-deepgram as an independent ground-truth clock for when audio was actually generated.

## Architecture Overview

```
Live Genesys Call (agent + customer speaking)
    │
    ├──→ [Genesys Cloud] ──→ Speech-to-Text ──→ WebSocket Notification ──→ notifications-spike
    │                                                                        (records receivedAt)
    │
    └──→ [Microphone/System Audio] ──→ poc-deepgram ──→ Deepgram STT ──→ Session JSON
                                        (records wall-clock audio timestamps)
```

**After the call**: A correlation tool matches utterances between the two systems by text similarity and computes:

```
True Latency = genesys_receivedAt - (deepgram_stream_start + audio_end)
```

Where:
- `genesys_receivedAt` = wall-clock time notifications-spike received the transcription event
- `deepgram_stream_start + audio_end` = wall-clock time the words were actually spoken (ground truth from poc-deepgram)

Both apps run on the same machine, so `time.time()` is synchronized.

---

## Phase 1: Audio Routing Setup (No Code Changes)

### Problem
poc-deepgram captures browser microphone audio. During a Genesys call, we need it to capture the **call audio** (both agent and customer speech).

### Options (choose one at call time)

| Option | How | Pros | Cons |
|--------|-----|------|------|
| **A. Open mic** | Place mic near speakers during call | Zero setup | Background noise, echo, lower quality |
| **B. Virtual audio device (Recommended)** | Install BlackHole (free) or Loopback ($). Route system audio → virtual input. Select virtual input as mic in browser. | Clean capture, no ambient noise | One-time setup, may need multi-output device to still hear call |
| **C. Headset mic** | Use headset; mic picks up agent voice, speakers play customer voice | Simple | Only captures agent side clearly |

### Recommended: BlackHole Setup (one-time)
1. `brew install blackhole-2ch`
2. Open **Audio MIDI Setup** → Create **Multi-Output Device** combining your speakers + BlackHole 2ch
3. Set system output to Multi-Output Device (you hear audio AND it routes to BlackHole)
4. In poc-deepgram browser tab, select **BlackHole 2ch** as microphone input
5. Both sides of the call audio now flow into poc-deepgram

---

## Phase 2: Data Enrichment in poc-deepgram

### Current State
poc-deepgram already saves session JSON with:
- `stream_start_time` (lazy-initialized on first audio chunk)
- Per-transcript: `audio_start`, `audio_end` (seconds from stream start), `server_receipt_time`
- Word-level: `start_ms`, `end_ms` per word

### Required Changes
Add explicit **wall-clock audio timestamps** to each transcript event to simplify correlation:

1. **Add `audio_wall_clock_start` and `audio_wall_clock_end`** to each transcript event:
   ```python
   # In deepgram_client.py _handle_message()
   event["audio_wall_clock_start"] = self._stream_start_time + audio_start
   event["audio_wall_clock_end"] = self._stream_start_time + audio_end
   ```

2. **Add `stream_start_time` to session metadata** (already tracked internally, just expose it):
   ```python
   # In app.py save_session_results()
   "stream_start_time": session._stream_start_time
   ```

3. **Add a `session_id` field** (UUID generated at session start) to make correlation explicit:
   ```python
   # In app.py websocket_endpoint()
   session_id = str(uuid.uuid4())
   ```

---

## Phase 3: Session Linking in notifications-spike

### Problem
After a call, we need to know which poc-deepgram session corresponds to which Genesys conversation. Currently there's no link between them.

### Solution: Lightweight Session Manifest

Add a simple JSON manifest file that the user creates (or the correlation tool prompts for) after each call:

```json
{
  "call_date": "2026-03-17",
  "deepgram_session_file": "results/nova-3_2026-03-17T18-36-27Z.json",
  "genesys_conversation_id": "02ecc434-d65b-491e-9555-59aa3949d046",
  "notes": "Test call with Kevin - discussing order #12345"
}
```

**Alternative**: The correlation tool can auto-detect matching sessions by:
1. Finding poc-deepgram sessions and notifications-spike conversations with overlapping time windows
2. Confirming via text similarity of transcripts

This avoids requiring manual manifest creation. The tool would:
- Scan `poc-deepgram/results/*.json` for sessions in the target time range
- Scan `notifications-spike/conversation_events/*.jsonl` for conversations in the same range
- Match by temporal overlap + text similarity

---

## Phase 4: Correlation & Analysis Tool

Build a Python script (or notebook) in **this repo** (`notifications-spike`) that:

### Step 1: Load Data
- Load poc-deepgram session JSON → extract final transcripts with wall-clock audio times
- Load notifications-spike JSONL → extract transcript events with `receivedAt`

### Step 2: Match Utterances
Use a **fuzzy text matching** approach:
1. For each Genesys transcript event, find the poc-deepgram transcript with the highest text similarity (using `difflib.SequenceMatcher` or similar)
2. Filter matches below a similarity threshold (e.g., 0.6)
3. Use temporal proximity as a tiebreaker (events should be within ~30s of each other)
4. Handle that Genesys may split/merge utterances differently than Deepgram

### Step 3: Compute True Latency
For each matched pair:
```python
true_latency = genesys_event["receivedAt"] - deepgram_event["audio_wall_clock_end"]
```

This measures: time from when speech ended → when transcription arrived at notifications-spike.

### Step 4: Analysis & Output
- Summary statistics: median, p50, p75, p95, p99 latency
- Breakdown by channel (INTERNAL vs EXTERNAL)
- Breakdown by utterance length (short vs long)
- Comparison with Genesys's self-reported latency (from existing analysis)
- Visualization: latency distribution, timeline, scatter plots
- Export: CSV of matched pairs with latencies

### Deliverables
- `scripts/correlate_latency.py` — CLI tool that takes a deepgram session file and a conversation JSONL
- `notebooks/cross_system_latency.ipynb` — Interactive analysis notebook
- Output to `analysis_results/cross_system/`

---

## Phase 5: Operational Workflow

### During a Call
1. Start notifications-spike: `uv run uvicorn main:app --host 0.0.0.0 --port 8000`
2. Start poc-deepgram: `uv run uvicorn poc_deepgram.app:create_app --factory --host 0.0.0.0 --port 8001`
3. Open poc-deepgram browser UI at `http://localhost:8001`
4. Set audio input to BlackHole (or mic)
5. Click **Start** in poc-deepgram
6. Take the Genesys call
7. When call ends: click **Stop** in poc-deepgram (saves session JSON)
8. notifications-spike automatically saves conversation JSONL

### After the Call
```bash
# From notifications-spike repo
uv run python scripts/correlate_latency.py \
  --deepgram ../poc-deepgram/results/nova-3_2026-03-17T18-36-27Z.json \
  --genesys conversation_events/02ecc434-d65b-491e-9555-59aa3949d046.jsonl
```

Or use the Jupyter notebook for interactive analysis.

---

## Implementation Steps

- [x] **Step 1**: Add wall-clock timestamps to poc-deepgram transcript events (`audio_wall_clock_start`, `audio_wall_clock_end`)
- [x] **Step 2**: Expose `stream_start_time` in poc-deepgram session metadata
- [x] **Step 3**: Add `session_id` to poc-deepgram sessions
- [x] **Step 4**: Build correlation script (`scripts/correlate_latency.py`) in notifications-spike (19 tests passing)
- [x] **Step 5**: Build analysis notebook (`notebooks/cross_system_latency.ipynb`) in notifications-spike
- [x] **Step 6**: Test with a live call — audio routing verified (Chrome for Genesys, BlackHole for poc-deepgram), transcription confirmed in poc-deepgram UI. Latency correlation pending.
- [x] **Step 7**: Document operational workflow in README
- [x] **Step 8**: Conduct 6 movie monologue test calls (Maleficent, Cyrano de Bergerac, Glengarry Glen Ross, Iron Man, To Kill a Mockingbird, Shawshank Redemption) — 94 matched pairs, 225 Deepgram utterances, 130 Genesys events
- [x] **Step 9**: Build executive summary (`docs/executive_summary.md`) with 3-way comparison table (Deepgram AudioHook proxy / Genesys self-reported / Genesys ground truth), all from same 6 test calls, plus footnote comparing to 147 production calls
- [x] **Step 10**: Notebook Module 6 computes Genesys self-reported latency from the 6 test JSONL files using anchor-event method, enabling apples-to-apples 3-way comparison

---

## Key Assumptions

1. **Same machine**: Both apps run on the same computer, so `time.time()` is synchronized
2. **Audio quality**: The audio poc-deepgram receives is clear enough for Deepgram to transcribe (needed for text matching)
3. **Temporal overlap**: poc-deepgram is started before or at the same time as the Genesys call
4. **Genesys transcription scope**: We're measuring Genesys's full pipeline (audio capture → STT → WebSocket delivery), not just STT processing time

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Deepgram and Genesys produce very different transcriptions | Correlation fails | Use word-level matching, lower similarity threshold, manual review |
| Audio routing adds latency | Skews ground truth | BlackHole adds <1ms; negligible for our measurement |
| poc-deepgram mic captures ambient noise | Poor transcription quality | Use virtual audio device (BlackHole) instead of open mic |
| Genesys splits utterances differently than Deepgram | 1:1 matching breaks | Use sliding window matching, allow many:many matches |
| Clock drift between Deepgram events and Genesys events | Systematic bias | Both use same machine's `time.time()`; no drift possible |
