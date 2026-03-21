# Add Confidence Score Collection & Comparison (TDD)

## Context

The latency analysis notebook (`notebooks/cross_system_latency-02-EB-RESULTS.ipynb`) compares Deepgram, Notifications, and EventBridge per-utterance latency. Confidence scores exist in all three raw data sources but are currently discarded during loading. This plan adds confidence score collection and comparison using the same per-utterance + aggregated pattern as latency, using TDD.

**Confidence fields in raw data** (all 0.0–1.0 range):
- Deepgram: `transcripts[].confidence` — verified in real data (e.g., `0.777`)
- Notifications: `transcript.alternatives[0].confidence`
- EventBridge: `transcripts[].alternatives[0].confidence`

**Currently**: None of the three dataclasses (`DeepgramEvent`, `GenesysEvent`, `CorrelationResult`) have confidence fields. The loading functions, `compute_latency`, `export_csv`, and `print_summary` all ignore confidence. The test fixtures already include confidence values in their raw JSON but no tests assert on them.

**Self-reported latency for EventBridge**: EB events contain `receivedAt`, `offsetMs`, and `durationMs` — the same three fields used by the anchor-event method in cell-13. Currently self-reported is only computed for Notifications. This plan adds EB self-reported as a 5th row in the head-to-head table.

---

## Review Feedback Incorporated

- **Issue 1 (export_csv test coverage)**: Agreed. Added Step 1g — one test asserting CSV header includes confidence columns.
- **Issue 2 (Pearson r dependency)**: Agreed. Use `pandas.Series.corr()` (already imported), not scipy. Made explicit in Step 3c.
- **Issue 3 (Real Deepgram confidence field)**: Verified. Real file has `transcripts[].confidence` as top-level float (e.g., `0.777`). Path `t.get("confidence", 0.0)` is correct.
- **Issue 4 (Cell renumbering)**: Agreed. Post-insertion steps now reference cells by content/function name, not index.
- **Issue 5 (EB self-reported latency)**: EB data has `receivedAt`, `offsetMs`, `durationMs` — same fields as Notifications. Added Step 3e for EB self-reported.

---

## Files to Modify

| File | Change |
|------|--------|
| `tests/test_correlate.py` | Add 11 new test methods (TDD red phase first) |
| `scripts/correlate_latency.py` | Add confidence to 3 dataclasses, 3 loaders, `compute_latency`, `export_csv`, `print_summary` |
| `notebooks/cross_system_latency-02-EB-RESULTS.ipynb` | Update `results_to_df` + `print_matched_pairs`, add EB self-reported, add Module 10 cells, update export cell |

---

## Progress

### Step 1 — TDD Red Phase: Write Failing Tests

All in `tests/test_correlate.py`. Fixture confidence values already in raw JSON: DG=[0.95, 0.97], Genesys/EB=[0.96, 0.98].

#### 1a. `TestLoadDeepgramSession` — 2 tests
- [x] `test_extracts_confidence`: assert `events[0].confidence == 0.95`, `events[1].confidence == 0.97`
- [x] `test_missing_confidence_defaults_to_zero`: delete confidence from first transcript in fixture, assert `events[0].confidence == 0.0`

#### 1b. `TestLoadGenesysConversation` — 2 tests
- [x] `test_extracts_confidence`: assert `events[0].confidence == 0.96`, `events[1].confidence == 0.98`
- [x] `test_missing_confidence_defaults_to_zero`: delete confidence from first alt, assert `events[0].confidence == 0.0`

#### 1c. `TestLoadEventBridgeConversation` — 2 tests
- [x] `test_extracts_confidence`: assert `events[0].confidence == 0.96`, `events[1].confidence == 0.98`
- [x] `test_missing_confidence_defaults_to_zero`: delete confidence from first alt, assert `events[0].confidence == 0.0`

#### 1d. `TestComputeLatency` — 2 tests
- [x] `test_passes_through_confidence`: construct DG(confidence=0.95) + GN(confidence=0.96), assert `result.deepgram_confidence == 0.95` and `result.genesys_confidence == 0.96`
- [x] `test_confidence_defaults_when_not_provided`: construct without confidence, assert both default to 0.0

#### 1e. `TestCorrelate` — 1 test
- [x] `test_end_to_end_propagates_confidence`: run `correlate()`, assert confidence values propagate

#### 1f. `TestCorrelateEventBridge` — 1 test
- [x] `test_end_to_end_propagates_confidence`: run `correlate_eventbridge()`, assert confidence values propagate

#### 1g. `TestExportCsv` — 1 new test class + test (addresses review issue 1)
- [x] `test_csv_includes_confidence_columns`: run `export_csv()` with results containing confidence values, read back CSV, assert header contains `"deepgram_confidence"` and `"genesys_confidence"`, and data values match

**Result**: 28 passed + 11 failed ✓ → then all 39 passed after Step 2 ✓

---

### Step 2 — TDD Green Phase: Implement in `scripts/correlate_latency.py`

- [x] 2a. Add `confidence: float = 0.0` to `DeepgramEvent` (line 41)
- [x] 2b. Add `confidence: float = 0.0` to `GenesysEvent` (after line 51)
- [x] 2c. Add `deepgram_confidence: float = 0.0` and `genesys_confidence: float = 0.0` to `CorrelationResult` (after line 63)
- [x] 2d. Update `load_deepgram_session` — add `confidence=t.get("confidence", 0.0)` (line 83–89)
- [x] 2e. Update `load_genesys_conversation` — add `confidence=alt.get("confidence", 0.0)` (line 107–116)
- [x] 2f. Update `load_eventbridge_conversation` — add `confidence=alt.get("confidence", 0.0)` (line 146–155)
- [x] 2g. Update `compute_latency` — add `deepgram_confidence=dg.confidence, genesys_confidence=gn.confidence` (line 233–242)
- [x] 2h. Update `export_csv` — add `"deepgram_confidence"` and `"genesys_confidence"` to header row and `round(r.deepgram_confidence, 3)` / `round(r.genesys_confidence, 3)` to data rows (lines 347–367)
- [x] 2i. Update `print_summary` — add `DG Conf` and `GN Conf` columns to per-pair detail table header and rows (lines 332–338)

All defaults use `= 0.0` for backward compatibility (matches existing `similarity: float = 0.0` pattern).

**Result**: All 98 tests pass (39 correlate + 59 other) ✓

---

### Step 3 — Notebook Changes

References by content/function name since new cell insertion shifts cell indices.

- [x] 3a. `results_to_df` function (in correlation cell): Add `deepgram_confidence` and `genesys_confidence` to row dict
- [x] 3b. `print_matched_pairs` function (matched-pairs cell): Add `DG Conf` and `GN Conf` columns (7-char each)
- [x] 3c. New cells after matched-pairs detail — Module 10: Confidence Score Analysis
  - [x] New markdown cell: section header explaining DG vs Genesys/r2d2 confidence comparison
  - [x] New code cell: `print_confidence_summary` (per-path stats + paired comparison — mean diff, which engine higher)
  - [x] New code cell: Head-to-head confidence table (reuse `compute_stats`, display as ×100 percentages)
  - [x] New code cell: Charts — use `pandas.Series.corr()` for Pearson r (no scipy needed):
    - Scatter: Deepgram vs Genesys confidence with y=x identity line and r value
    - Histogram: Overlaid confidence distributions (Deepgram vs Genesys)
    - Scatter: Confidence vs latency (do lower-confidence utterances have higher latency?)
- [x] 3d. Export cell (now cell-30, shifted after insertion): Add `"confidence"` key to `comparison` dict with per-source/per-engine stats + `eb_self_reported` key
- [x] 3e. Self-reported cell (cell-13): Add EB self-reported latency
  - [x] Iterate EB files (both `triple_matched` and `eb_only_matched`)
  - [x] For each EB event, iterate `transcripts[]` array (vs Notifications' singular `transcript`)
  - [x] Extract `receivedAt`, `offsetMs`, `durationMs` per isFinal alternative
  - [x] Applied `calculate_eb_conversation_latency` — separate function for EB format
  - [x] Add "EB Self-Reported" row to head-to-head table in cell-15, alongside existing "Notif Self-Reported"

---

## Verification

- [x] 1. `pytest tests/test_correlate.py -v` — all 39 tests pass (28 old + 11 new)
- [x] 2. `pytest tests/ -v` — full suite passes (98/98)
- [x] 3. Re-run notebook end-to-end — all 31 cells execute without error
- [x] 4. Confidence columns appear in `df_notif` (99 rows) and `df_eb` (101 rows)
- [x] 5. Confidence summary prints non-zero values: DG mean=93.9%, GN mean=77.6% (Notif); DG mean=93.9%, GN mean=77.5% (EB)
- [x] 6. Head-to-head confidence table shows actual percentages for all 4 rows
- [x] 7. Confidence scatter, histogram, and confidence-vs-latency charts render (confidence_analysis.png exported)
- [x] 8. Exported JSON has `confidence` key with per-source stats; CSV has `deepgram_confidence`/`genesys_confidence` columns
- [x] 9. EB self-reported row appears in head-to-head table: median=356ms, n=145
- [ ] 9. EB self-reported row appears in head-to-head latency table with real numbers