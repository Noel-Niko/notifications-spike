# Plan: Session-Level Transcription Accuracy Analysis

## Goal
Create a notebook that measures Word Error Rate (WER) for each transcription channel (Deepgram Nova-3, Notifications/r2d2, EventBridge/r2d2) against YouTube subtitle ground truth, compares WER to confidence scores, and produces summary statistics and a mismatch document.

**Engine vs Delivery Path distinction:**
- **Deepgram Nova-3** vs **r2d2 (Genesys)**: ASR engine comparison (different models)
- **Notifications (WebSocket)** vs **EventBridge (SQS)**: Delivery path comparison (same r2d2 engine)

## Answers from User
1. **Mapping**: Match movies to sessions by text content (no mapping file)
2. **Maleficent**: Skip (no SRT available); last task = create a ground truth doc
3. **Metric**: Standard WER via `jiwer`
4. **Notif vs EB**: Handle as separate channels — detect dropped utterances, verify text identity
5. **Alignment**: Session-level only — concatenate all text per session, compute WER per channel. No per-utterance time alignment needed.
6. **Ground truth quality**: Treat SRT files as perfect ground truth. User will rerun analysis after manual SRT verification.

## Movie → Session Mapping (preliminary, by transcript content)
| Movie | SRT File | Deepgram Session | Conversation ID | SRT Type |
|-------|----------|-----------------|-----------------|----------|
| Maleficent | *(missing)* | nova-3_2026-03-21T00-40-56Z.json | a9708b9e-39fb-4de9-8060-d8bdda444a5d | SKIP |
| Cyrano | Cyrano.en.auto.srt | nova-3_2026-03-21T00-53-40Z.json | b986f068-1f3f-4bb2-8519-505e7516af2a | auto |
| Glengarry | Glengarry.en.auto.srt | nova-3_2026-03-21T00-59-23Z.json | 9fb83242-e353-4020-a105-07cc714d362e | auto |
| Mockingbird | Mockingbird.en.manual.srt | nova-3_2026-03-21T01-04-49Z.json | ecb7785a-f230-44ef-8cc8-ee1007a04578 | manual |
| Shawshank | Shawshank.en.auto.srt | nova-3_2026-03-21T01-08-57Z.json | 62ea6595-667f-4215-a252-12e13204ced0 | auto |
| Iron Man | IronMan.en.auto.srt | nova-3_2026-03-21T01-14-22Z.json | ccb202d4-e2a9-4e9d-8c02-183f5bd418ab | auto |

Mapping will be confirmed programmatically in the notebook by comparing concatenated text.

## Dependencies
- **Add `jiwer`** to pyproject.toml (standard WER library: computes WER, MER, WIL, insertions/deletions/substitutions)
- **Deepgram session files**: Located at `../poc-deepgram/results/` relative to repo root (same path used by notebook-03)

## Notebook Structure (10 cells)

### Cell 1: Setup & Configuration
- Imports: `jiwer`, `pandas`, `numpy`, `pathlib`, `json`, `matplotlib`, `seaborn`
- Import from `scripts.correlate_latency`: `load_deepgram_session`, `load_genesys_conversation`, `load_eventbridge_conversation`, `_normalize`
- Directory paths (same as notebook-03):
  - `DEEPGRAM_RESULTS_DIR = (REPO_ROOT / ".." / "poc-deepgram" / "results").resolve()`
  - `NOTIF_EVENTS_DIR = REPO_ROOT / "conversation_events"`
  - `EB_EVENTS_DIR = REPO_ROOT / "EventBridge" / "conversation_events"`
  - `SUBS_DIR = REPO_ROOT / "subs"`
  - `OUTPUT_DIR = REPO_ROOT / "analysis_results" / "transcription_accuracy"`
- Load SRT parser (inline function — SRT format is simple; must handle multi-line text within subtitle blocks)

### Cell 2: Parse SRT Files
- Parse each `.srt` file into list of `{index, start_time, end_time, text}`
  - Handle multi-line text within a single subtitle block (e.g., Mockingbird has multi-line entries)
- Concatenate all text per movie into a single ground truth string
- Display summary: movie name, SRT type (auto/manual), word count, segment count

### Cell 3: Load All Channel Data
- Import `load_deepgram_session()`, `load_genesys_conversation()`, `load_eventbridge_conversation()` from `scripts.correlate_latency`
- **Copy file matching logic from notebook-03** (this logic is inline in the notebook, NOT in correlate_latency.py):
  - `get_dg_time_range()` — reads session.started_at/ended_at from Deepgram JSON
  - `get_jsonl_time_range()` — reads min/max receivedAt from JSONL
  - Triple matching: Deepgram ↔ Notifications by time overlap, Notifications ↔ EventBridge by conversation ID
- For each session: extract all final utterance texts per channel

### Cell 4: Map Sessions to Movies
- For each Deepgram session, concatenate all transcript text
- Compute text similarity (SequenceMatcher) between session text and each SRT ground truth
- Use `_normalize()` from `correlate_latency` for consistent normalization
- Assign best match; display mapping table with similarity scores
- Flag Maleficent session (no SRT) and exclude

### Cell 5: Session-Level WER (Primary Analysis)
- For each mapped session x each channel (Deepgram, Notifications, EventBridge):
  - Concatenate all utterance text (using `_normalize()` from correlate_latency for consistency)
  - Concatenate all SRT text (same normalization)
  - Compute WER using `jiwer.wer()` and `jiwer.process_words()` for detailed breakdown
  - Record: WER, insertions, deletions, substitutions, total reference words
- Summary table: WER per channel per movie, plus overall weighted average
- Note: Deepgram vs r2d2 = engine comparison; Notif vs EB = delivery path comparison

### Cell 6: Dropped Utterance Detection (Notifications vs EventBridge)
- **Scope: Notif vs EB only** (both use r2d2 engine, so utterance segmentation is comparable)
- Deepgram uses Nova-3 which segments audio differently — not comparable at utterance level
- For each session, match Notif ↔ EB utterances by text similarity (SequenceMatcher >= 0.70)
- Identify utterances present in one but missing from the other
- Record: session, missing utterance text, which delivery path dropped it

### Cell 7: Notifications vs EventBridge Text Identity
- For each session, match Notifications ↔ EventBridge utterances (same r2d2 engine, should be identical)
- Compare matched pairs: are transcripts identical?
- Record any differences (text, similarity score, which fields differ)

### Cell 8: WER vs Confidence Correlation
- Scatter plot: WER (x) vs confidence score (y) for each channel
  - Deepgram channel uses Deepgram confidence
  - Notif/EB channels use r2d2 confidence
- Compute Pearson/Spearman correlation between WER and confidence
- Identify quadrants: high-confidence-high-WER (false confidence), low-confidence-low-WER (appropriate uncertainty)
- Summary statistics per quadrant

### Cell 9: Descriptive Statistics + Mismatch Document
- Per-channel: mean WER, median WER, std, min, max
- Per-movie: same breakdown
- Confidence statistics split by WER buckets (0-10%, 10-20%, 20%+)
- Box plots: WER distribution by channel
- Write `analysis_results/transcription_accuracy/mismatches.md`:
  - For each channel, show session-level reference vs hypothesis text where WER > 0
  - Include WER score, word count, insertions/deletions/substitutions
  - Grouped by channel, sorted by WER descending

### Cell 10: Export Results
- CSV with session-level WER data (all channels)
- JSON summary (same format as notebook-03's p99_comparison.json)
- Mismatch markdown document
- All outputs to `analysis_results/transcription_accuracy/`

## Final Task: Maleficent Ground Truth Document
- After the notebook is complete, create a ground truth transcript for the Maleficent clip
- Based on ALL Deepgram transcripts from the Maleficent session (not just matched ones — notebook-03 showed only 4 matched utterances, but the full session has more) + manual correction by listening
- Save as `subs/Maleficent.en.manual.srt` or equivalent

## Steps
- [x] Step 0: Plan review — 6 issues + 5 omissions identified and corrected
- [x] Step 1: Add `jiwer` to pyproject.toml and install (jiwer 4.0.0 + rapidfuzz 3.14.3)
- [x] Step 2: Write the notebook (cells 1-10 + Cell 5b) → `notebooks/transcription_accuracy-04-WER-ANALYSIS.ipynb`
  - Added Cell 5b: deeper WER analysis (error breakdown, word-level alignment, per-category analysis)
  - Added Cell 9b: WER pipeline comparison diagram (flow chart: Audio → engines → delivery paths)
  - Fixed Cell 4: switched from text similarity to known conversation ID mapping + keyword anchor verification
    - 5 distinctive anchor words per movie, verified against Deepgram transcript: 5/5 VERIFIED
    - Manual spot-check confirmed Cyrano session (b986f068) is the nose monologue — SequenceMatcher was wrong
  - Added scipy dependency for Pearson/Spearman correlation
  - Enhanced Cell 9 mismatch doc with word-level alignment tables
  - Notebook executes successfully → `transcription_accuracy-04-WER-ANALYSIS-executed.ipynb`
  - 8 output files in `analysis_results/transcription_accuracy/`
- [x] Step 3: Notebook executed and results reviewed
- [ ] Step 4: Create Maleficent ground truth document

## Review Changes Log
**2026-03-26 — Review by Claude:**
- Removed Cell 8 (Per-Utterance WER with time alignment) per user direction — session-level WER only
- Consolidated Cells 10-12 into Cells 9-10 (reduced from 12 to 10 cells)
- Added Conversation IDs to mapping table for traceability
- Specified full Deepgram session file names (not abbreviated)
- Added Engine vs Delivery Path framing (Deepgram=Nova-3 vs r2d2=engine comparison; Notif vs EB=delivery path)
- Scoped Cell 6 (Dropped Utterances) to Notif vs EB only (different ASR engines segment differently)
- Added note to reuse `_normalize()` from `correlate_latency` for consistent normalization
- Added note that file matching logic must be copied from notebook-03 (it's inline, not in correlate_latency.py)
- Changed output directory to `analysis_results/transcription_accuracy/` (consistent with existing pattern)
- Added multi-line SRT text handling note
- Added `poc-deepgram` path dependency
- Updated Maleficent ground truth task to use ALL session transcripts, not just matched ones
- Noted SRT files treated as perfect ground truth; user will rerun after manual verification