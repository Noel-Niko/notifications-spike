# Fix: EB Comparison Notebook (02) — Implementation Tracker

## Context

The blocking issue (missing `audio_wall_clock_end` in Deepgram files) was fixed by the user. The remaining issues in `notebooks/cross_system_latency-02-EB-RESULTS.ipynb` are:

1. **6th call silently dropped** — 6 DG + 6 EB files but only 5 Notifications files. Matching logic requires Notifications match → 6th EB conversation (`82719a9e`) lost.
2. **Missing `export_csv` import** in cell-2.
3. **No diagnostics** when correlation returns 0 matches.
4. **No false-match filtering** — negative-latency matches aren't excluded.
5. **Hop 1 all negative** — `ebTime` second-precision truncation. Switch to 2-hop.
6. **Stacked bar chart broken** — negative Hop 1 segment.

## Review Feedback Incorporated

- **Omission 1**: EB-only pairs kept in separate `eb_only_matched` list (not mixed into `triple_matched`) to avoid crashing cells 7, 13, 26.
- **Omission 2**: Added data-file existence verification step.
- **Omission 3**: Added `audio_wall_clock_end` sanity check to cell-9 diagnostics.

## File to Modify

`notebooks/cross_system_latency-02-EB-RESULTS.ipynb` — 7 cells (2, 5, 9, 20, 21, 22, 26)

---

## Progress

### Cell-2: Add `export_csv` import
- [x] Add `export_csv` to import block from `scripts.correlate_latency`

### Cell-5: Add `eb_only_matched` for EB-only pairs
- [x] After `triple_matched`, match DG↔EB by time overlap
- [x] EB files not already in a triple → `eb_only_matched` as `(dg_path, eb_path)`
- [x] Print note explaining the 6th call (agent never connected, EB captured org-wide)

### Cell-9: Diagnostics + false-match filter + EB-only loop
- [x] Data file existence verification (DG, Notif, EB counts)
- [x] Check first DG transcript for `audio_wall_clock_end` presence
- [x] After 0-match correlations, load DG/Genesys events separately, print counts
- [x] Add EB-only loop over `eb_only_matched` extending `eb_results`
- [x] Filter `true_latency_ms < 0` from both DataFrames, print count excluded

### Cell-20: Update markdown — 2-hop description
- [x] Replace 3-hop diagram with 2-hop (Hop A: Genesys→SQS, Hop B: SQS→Consumer)
- [x] Explain `ebTime` exclusion (second-precision truncation artifact)

### Cell-21: Replace 3-hop with 2-hop computation
- [x] Replace hop1/hop2/hop3 with hopA/hopB
- [x] `hopA_ms = (sqs_sent_s - genesys_event_time) * 1000`
- [x] `hopB_ms = (received_at - sqs_sent_s) * 1000`
- [x] Remove `eb_time` variable, keep `parse_iso_to_epoch` for `genesysEventTime`
- [x] Include `eb_only_matched` EB paths in hop data loop

### Cell-22: Fix stacked bar chart
- [x] Replace 3-segment with 2-segment (Hop A + Hop B)
- [x] Rename scatter from "Hop 3" to "Hop B: SQS → Consumer"

### Cell-26: Clean up export
- [x] Remove inline `from scripts.correlate_latency import export_csv`
- [x] Update hop keys to `hopA_genesys_to_sqs` / `hopB_sqs_to_consumer`
- [x] Add `eb_only_pairs` to exported comparison JSON

---

## Verification

1. Confirm data files exist (5 Notif, 6 EB, 6 DG)
2. Spot-check Deepgram file for `audio_wall_clock_end`
3. Re-run notebook end-to-end
4. Cell-9 produces non-zero matched pairs
5. Head-to-head table shows numbers for all 4 rows
6. Hop analysis shows positive values
7. Charts render correctly
8. 6th EB call appears via `eb_only_matched`
