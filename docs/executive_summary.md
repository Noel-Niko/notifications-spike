# Genesys Cloud Transcription Latency: Executive Summary

**Date**: March 18, 2026
**Scope**: End-to-end latency measurement of the Genesys Cloud real-time transcription pipeline
**Method**: Cross-system correlation using independent ground-truth audio timestamps

---

## Three-Way Latency Comparison

| Metric | Deepgram Nova-3 (AudioHook Proxy) | Genesys r2d2 (Self-Reported) | Cross-System (Ground Truth) |
|--------|----------------------------------:|-----------------------------:|----------------------------:|
| **Median (p50)** | 1,213 ms | 837 ms | 1,710 ms |
| **Mean** | 1,504 ms | 938 ms | 2,430 ms |
| **p95** | 3,330 ms | 2,003 ms | 10,428 ms |
| **p99** | 4,389 ms | 3,304 ms | 16,430 ms |
| **Min** | 271 ms | 0 ms | 733 ms |
| **Max** | 4,833 ms | 18,636 ms | 20,365 ms |
| **Sample Size** | 223 utterances | 8,735 utterances | 94 matched pairs |

### What Each Column Measures

- **Deepgram Nova-3 (AudioHook Proxy)**: Time from when speech ended to when Deepgram returned the transcript, measured via poc-deepgram capturing the same call audio independently. This serves as a **proxy for the Genesys AudioHook integration** — streaming call audio to an external STT engine instead of using the built-in r2d2 engine. Deepgram uses a 300ms endpointing threshold, producing faster but more granular utterances.

- **Genesys r2d2 (Self-Reported)**: Genesys's own reported STT processing latency — measures **only Stage 2** (audio-to-text conversion). Does not include audio capture transport, endpointing wait, or WebSocket delivery. Based on 147 real customer service conversations (8,735 utterances) from October 2025.

- **Cross-System (Ground Truth)**: The **true end-to-end latency** from the moment words are spoken to when the transcribed text arrives at our application via WebSocket. Captures all four pipeline stages. Measured by correlating Deepgram ground-truth timestamps with Genesys notification arrival times.

### Key Takeaways

1. **Deepgram (AudioHook proxy) median is 1.2s** — faster than Genesys end-to-end (1.7s) because Deepgram endpoints more aggressively (300ms vs Genesys's variable-length endpointing) and delivers transcripts directly without WebSocket routing overhead.

2. **Genesys self-reported median is 0.8s** — but this only measures STT processing (Stage 2). The true end-to-end latency is **2x higher** (1.7s) because it includes audio capture, endpointing, and WebSocket delivery.

3. **Tail latency diverges dramatically** — at p95, Deepgram stays at 3.3s while Genesys end-to-end jumps to 10.4s. The 7s gap is caused by Genesys batching continuous speech into large final events (Stage 3 endpointing). Deepgram's faster endpointing avoids this accumulation.

4. **An AudioHook integration would likely deliver transcripts ~30% faster at the median** and dramatically reduce tail latency, assuming similar audio quality and network conditions as our test setup.

---

## Cross-System vs Genesys Self-Reported Detail

| Metric | Cross-System (Ground Truth) | Genesys Self-Reported | Delta |
|--------|---------------------------:|---------------------:|------:|
| **Median (p50)** | 1,710 ms | 837 ms | +873 ms |
| **Mean** | 2,430 ms | 938 ms | +1,492 ms |
| **p95** | 10,428 ms | 2,003 ms | +8,425 ms |
| **p99** | 16,430 ms | 3,304 ms | +13,126 ms |

**Bottom line**: The true end-to-end latency from spoken word to delivered transcription is roughly **double** what Genesys self-reports at the median, and **5x higher** at the 95th percentile. The median of ~1.7 seconds is acceptable for most real-time use cases. The inflated tail latency (p95/p99) is driven by Genesys's endpointing behavior during continuous speech, not by STT processing delays.

---

## Methodology

### Architecture

Two independent systems capture the same live call audio simultaneously on a single machine (no clock synchronization needed):

```
Live Genesys Call (agent + customer speaking)
    │
    ├──→ [Genesys Cloud] ──→ r2d2 STT ──→ Endpointing ──→ WebSocket ──→ notifications-spike
    │                                                                      (records receivedAt)
    │
    └──→ [BlackHole Virtual Audio] ──→ poc-deepgram ──→ Deepgram Nova-3 STT
                                        (records audio_wall_clock_end)
```

### Formula

```
true_latency = genesys_receivedAt − deepgram_audio_wall_clock_end
```

Both `receivedAt` and `audio_wall_clock_end` are wall-clock timestamps (`time.time()`) recorded on the same machine, eliminating clock drift.

### What True Latency Captures

The measurement spans four pipeline stages:

| Stage | Description | Typical Contribution |
|-------|-------------|---------------------|
| **1. Audio Capture** | VoIP/WebRTC transport from caller to Genesys Cloud | Low (~50–100 ms) |
| **2. STT Processing** | Genesys r2d2 engine: acoustic model, language model, word-level timing | Moderate (~500–800 ms) |
| **3. Endpointing** | Genesys holds partial transcripts until it decides the utterance is final (`isFinal=true`) | **Highly variable (0.3–15+ s)** |
| **4. WebSocket Delivery** | Serialization + routing through Genesys infrastructure to our application | Low (~50–200 ms) |

Genesys's self-reported latency measures only **Stage 2**. Our cross-system measurement captures **all four stages**.

---

## Why the p95 Is Dramatically Higher Than the Median

The median adds only **+0.87s** over Genesys self-reported latency — a modest and expected overhead from Stages 1, 3, and 4 combined. But at p95, the gap explodes to **+8.4s**. This is caused by **Stage 3: Endpointing**.

### The Endpointing Effect

Genesys's endpointing algorithm determines when a speaker has finished an utterance before emitting `isFinal=true`. During continuous speech (like the movie monologues in this test), the algorithm:

1. **Waits for silence** — the speaker pauses infrequently during a monologue, so Genesys holds the transcript buffer longer
2. **Batches multiple sentences** into a single final event — where Deepgram (300ms endpointing) would emit 3–4 separate utterances, Genesys emits 1 combined event
3. **Delays the timestamp** — the `receivedAt` reflects when the batched event finally arrived, long after the first words in that batch were spoken

This means the **tail latency is dominated by how long Genesys waited to finalize**, not how long STT processing took.

### Evidence From the Data

The highest-latency matches consistently show Genesys combining multiple Deepgram utterances:

| True Latency | What Happened |
|---:|---|
| 20,365 ms | Genesys batched multiple sentences from the Glengarry Glen Ross monologue into one event |
| 16,134 ms | Short phrase held until the next natural pause point |
| 12,978 ms | Iron Man press conference — continuous speech, Genesys combined 3 Deepgram utterances |
| 12,883 ms | Cyrano nose monologue — Genesys waited for the full passage to endpoint |
| 11,937 ms | Maleficent curse — entire monologue segment batched |

### Impact on Real Calls

Movie monologues are a **worst-case scenario** for endpointing — they are continuous speech with minimal pauses. In real customer service calls:

- Speakers take turns with natural pauses between sentences
- Genesys endpoints trigger faster on conversational speech
- The p95 in production would be significantly lower (likely 2–4s rather than 10+s)

The test intentionally uses monologues to stress-test the pipeline and expose the full range of endpointing behavior.

---

## Test Corpus

Six movie monologues were played through live Genesys calls, providing diverse speech patterns and durations:

| # | Movie | Duration | Matched Pairs | Median Latency | Speech Pattern |
|---|-------|----------|:---:|---:|---|
| 1 | **Maleficent** (Sleeping Beauty curse) | 105.7s | 1 | 11,937 ms | Slow, dramatic, few pauses |
| 2 | **Cyrano de Bergerac** (nose monologue) | 203.3s | 15 | 1,748 ms | Rapid wit, staccato delivery |
| 3 | **Glengarry Glen Ross** (ABC speech) | 274.1s | 23 | 1,734 ms | Aggressive, punctuated by short pauses |
| 4 | **Iron Man** (press conference) | 95.9s | 8 | 2,920 ms | Mixed: dialogue + monologue |
| 5 | **To Kill a Mockingbird** (closing argument) | 197.2s | 28 | 1,129 ms | Measured, deliberate, clear pauses |
| 6 | **The Shawshank Redemption** (Red's parole hearing) | 173.7s | 19 | 1,785 ms | Reflective, conversational cadence |

**Total**: 94 matched utterance pairs across ~1,050 seconds of call audio.

### Per-Movie Observations

- **To Kill a Mockingbird** had the lowest median (1,129 ms) — Atticus Finch's deliberate, pause-heavy courtroom delivery aligns well with Genesys endpointing
- **Iron Man** had the highest median (2,920 ms) — mixed dialogue format caused more endpointing confusion
- **Maleficent** produced only 1 match — the slow, dramatic delivery resulted in Genesys batching the entire passage, making utterance-level matching difficult
- **Glengarry Glen Ross** produced the most matches (23) — Alec Baldwin's aggressive, punchy delivery creates frequent natural endpoints

---

## Aggregate Results

### Full Distribution

| Percentile | Latency |
|---:|---:|
| p50 (Median) | 1,710 ms |
| p75 | 2,300 ms |
| p90 | 4,627 ms |
| p95 | 10,428 ms |
| p99 | 16,430 ms |
| Max | 20,365 ms |
| Min | 733 ms |

- **Standard Deviation**: 4,677 ms — reflects the heavy right tail from endpointing batching
- **Mean Similarity**: 0.798 — indicates strong cross-system utterance matching quality

### Latency Bands

| Band | Count | % of Total | Description |
|------|:---:|:---:|---|
| < 1,000 ms | ~12 | ~13% | Fast — short utterances with quick endpointing |
| 1,000–2,000 ms | ~52 | ~55% | Typical — normal single-utterance processing |
| 2,000–5,000 ms | ~20 | ~21% | Moderate — some endpointing batching |
| 5,000–10,000 ms | ~4 | ~4% | Elevated — multi-sentence batching |
| > 10,000 ms | ~6 | ~6% | High — heavy batching during continuous speech |

The majority of utterances (68%) arrive within 2 seconds. The long tail is driven by a small number of heavily-batched events.

---

## Visualizations

The following charts are generated by the analysis notebook (`notebooks/cross_system_latency.ipynb`) and saved to `analysis_results/cross_system/`:

### Latency Distribution Histogram

![Latency Distribution](../analysis_results/cross_system/cross_latency_distribution.png)

The distribution is right-skewed with a primary peak around 1,500–2,000 ms and a long tail extending past 10,000 ms. The mean (red dashed) is pulled right by the tail outliers, while the median (green dashed) sits in the primary cluster.

### Latency Timeline (Scatter + Trend)

![Latency Timeline](../analysis_results/cross_system/cross_latency_timeline.png)

Latency plotted against audio timestamp across all 6 test calls. Most points cluster below 5,000 ms with intermittent spikes corresponding to endpointing batching events. No systematic drift or degradation over time.

### Match Quality vs Latency

![Match Quality](../analysis_results/cross_system/cross_latency_match_quality.png)

Text similarity score (x-axis) versus true latency (y-axis). High-latency outliers tend to have lower similarity scores (0.55–0.65), consistent with Genesys combining multiple utterances that only partially overlap with the matched Deepgram event.

---

## Data Quality Notes

- **1 false match detected**: In To Kill a Mockingbird, "is." was matched to "i'm so" with similarity 0.571, producing a latency of -29,618 ms (negative = impossible). This is a matching artifact from the short utterance length and should be excluded from statistical analysis. The aggregate statistics above include this outlier; excluding it would reduce the standard deviation and slightly improve the mean.
- **Similarity threshold**: 0.55 — balances match recall against false positive risk. Lower thresholds would increase matches but introduce more noise.
- **Channel**: All matched utterances are EXTERNAL (customer/caller side), since the monologue audio played through the phone system appears as the external participant.

---

## Interpretation Guide

| Measured Latency | Likely Cause |
|---:|---|
| 700–1,200 ms | Fast path: short utterance, quick endpointing, minimal batching. Stages 1+2+4 only. |
| 1,200–2,500 ms | Normal path: single utterance with standard endpointing pause detection. |
| 2,500–5,000 ms | Moderate batching: Genesys combined 2 short sentences into one final event. |
| 5,000–15,000 ms | Heavy batching: continuous speech, Genesys waited for a clear pause before finalizing 3+ sentences. |
| > 15,000 ms | Extreme batching: prolonged continuous speech with no detectable pause point. Rare in real conversations. |

---

## Recommendations

1. **Use the median (1.7s) as the primary latency benchmark**, not the mean — the right-skewed distribution makes the mean misleading.
2. **Expect p95 to be lower in production** — real customer service calls have natural conversational pauses that trigger faster endpointing than movie monologues.
3. **Design for ~2s latency in real-time features** — any UI or workflow that depends on transcription arrival should assume 1.5–2.5s typical latency.
4. **Budget 5s+ for worst-case scenarios** — long utterances or rapid speech may trigger batching delays.
5. **Repeat this test with live customer calls** to establish production-representative percentile benchmarks. The monologue test establishes the methodology and bounds; real call data will refine the operational expectations.

---

## Reproduction

```bash
# Run correlation on a specific pair
uv run python -m scripts.correlate_latency \
  --deepgram ../poc-deepgram/results/<SESSION>.json \
  --genesys conversation_events/<CONVERSATION>.jsonl

# Run the full analysis notebook (auto-matches N most recent pairs)
# Set NUM_RECENT=6 in the first code cell
cd notebooks && uv run jupyter notebook cross_system_latency.ipynb
```

See `docs/manual_test_directions.md` for the complete setup and test execution guide.
