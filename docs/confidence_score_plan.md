# Add Confidence Score Collection & Comparison (TDD)

## Context

The latency analysis notebook (`notebooks/cross_system_latency-02-EB-RESULTS.ipynb`) compares Deepgram, Notifications, and EventBridge per-utterance latency. Confidence scores exist in all three raw data sources but are currently discarded during loading. This plan adds confidence score collection and comparison using the same per-utterance + aggregated pattern as latency, using TDD.

**Confidence fields in raw data** (all 0.0–1.0 range):
- Deepgram: `transcripts[].confidence`
- Notifications: `transcript.alternatives[0].confidence`
- EventBridge: `transcripts[].alternatives[0].confidence`

**Currently**: None of the three dataclasses (`DeepgramEvent`, `GenesysEvent`, `CorrelationResult`) have confidence fields. The loading functions, `compute_latency`, `export_csv`, and `print_summary` all ignore confidence. The test fixtures already include confidence values in their raw JSON but no tests assert on them.

---

## Files to Modify

| File | Change |
|------|--------|
| `tests/test_correlate.py` | Add 10 new test methods (TDD red phase first) |
| `scripts/correlate_latency.py` | Add confidence to 3 dataclasses, 3 loaders, `compute_latency`, `export_csv`, `print_summary` |
| `notebooks/cross_system_latency-02-EB-RESULTS.ipynb` | Update cell-9 + cell-24, add new Module 10 cells, update cell-26 export |

---

## Progress

### Step 1 — TDD Red Phase: Write Failing Tests

All in `tests/test_correlate.py`. Fixture confidence values already in raw JSON: DG=[0.95, 0.97], Genesys/EB=[0.96, 0.98].

#### 1a. `TestLoadDeepgramSession` — 2 tests
- [ ] `test_extracts_confidence`: assert `events[0].confidence == 0.95`, `events[1].confidence == 0.97`
- [ ] `test_missing_confidence_defaults_to_zero`: delete confidence from first transcript in fixture, assert `events[0].confidence == 0.0`

#### 1b. `TestLoadGenesysConversation` — 2 tests
- [ ] `test_extracts_confidence`: assert `events[0].confidence == 0.96`, `events[1].confidence == 0.98`
- [ ] `test_missing_confidence_defaults_to_zero`: delete confidence from first alt, assert `events[0].confidence == 0.0`

#### 1c. `TestLoadEventBridgeConversation` — 2 tests
- [ ] `test_extracts_confidence`: assert `events[0].confidence == 0.96`, `events[1].confidence == 0.98`
- [ ] `test_missing_confidence_defaults_to_zero`: delete confidence from first alt, assert `events[0].confidence == 0.0`

#### 1d. `TestComputeLatency` — 2 tests
- [ ] `test_passes_through_confidence`: construct DG(confidence=0.95) + GN(confidence=0.96), assert `result.deepgram_confidence == 0.95` and `result.genesys_confidence == 0.96`
- [ ] `test_confidence_defaults_when_not_provided`: construct without confidence, assert both default to 0.0

#### 1e. `TestCorrelate` — 1 test
- [ ] `test_end_to_end_propagates_confidence`: run `correlate()`, assert confidence values propagate

#### 1f. `TestCorrelateEventBridge` — 1 test
- [ ] `test_end_to_end_propagates_confidence`: run `correlate_eventbridge()`, assert confidence values propagate

**Expected**: 28 existing pass + 10 new fail.

---

### Step 2 — TDD Green Phase: Implement in `scripts/correlate_latency.py`

- [ ] 2a. Add `confidence: float = 0.0` to `DeepgramEvent` (line 41)
- [ ] 2b. Add `confidence: float = 0.0` to `GenesysEvent` (after line 51)
- [ ] 2c. Add `deepgram_confidence: float = 0.0` and `genesys_confidence: float = 0.0` to `CorrelationResult` (after line 63)
- [ ] 2d. Update `load_deepgram_session` — add `confidence=t.get("confidence", 0.0)` (line 83–89)
- [ ] 2e. Update `load_genesys_conversation` — add `confidence=alt.get("confidence", 0.0)` (line 107–116)
- [ ] 2f. Update `load_eventbridge_conversation` — add `confidence=alt.get("confidence", 0.0)` (line 146–155)
- [ ] 2g. Update `compute_latency` — add `deepgram_confidence=dg.confidence, genesys_confidence=gn.confidence` (line 233–242)
- [ ] 2h. Update `export_csv` — add confidence columns to header and data rows (lines 347–367)
- [ ] 2i. Update `print_summary` — add confidence columns to per-pair detail table (lines 332–338)

All defaults use `= 0.0` for backward compatibility (matches existing `similarity: float = 0.0` pattern).

**Expected**: All 38 tests pass.

---

### Step 3 — Notebook Changes

- [ ] 3a. Cell-9: Add `deepgram_confidence` and `genesys_confidence` to `results_to_df` row dict
- [ ] 3b. Cell-24: Add `DG Conf` and `GN Conf` columns to `print_matched_pairs`
- [ ] 3c. New cells after cell-24 — Module 10: Confidence Score Analysis
  - [ ] New markdown cell: section header
  - [ ] New code cell: `print_confidence_summary` (per-path stats + paired comparison)
  - [ ] New code cell: Head-to-head confidence table (reuse `compute_stats`, display as %)
  - [ ] New code cell: Charts (DG vs GN scatter, distribution histograms, confidence vs latency)
- [ ] 3d. Cell-26: Add `"confidence"` key to export JSON with per-source/per-engine stats

---

## Verification

- [ ] 1. `pytest tests/test_correlate.py -v` — all 38 tests pass (28 old + 10 new)
- [ ] 2. `pytest tests/ -v` — full suite passes
- [ ] 3. Re-run notebook end-to-end
- [ ] 4. Confidence columns appear in `df_notif` and `df_eb` DataFrames
- [ ] 5. Confidence summary prints non-zero values for all paths
- [ ] 6. Head-to-head confidence table shows actual percentages
- [ ] 7. Confidence scatter and histogram charts render
- [ ] 8. Exported JSON includes confidence stats