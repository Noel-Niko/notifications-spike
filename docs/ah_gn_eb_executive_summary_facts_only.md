# Transcription Delivery Path Analysis: Facts

**Date**: March 21, 2026
**Scope**: Head-to-head latency and confidence comparison of three transcription delivery paths — Genesys Notifications API (WebSocket), AWS EventBridge (SQS), and Deepgram Direct (POC) — using 6 live test calls with independent ground-truth audio timing.

**Target System**: ~1,200 agents, ~40,000 calls/day, ~6-minute average call duration. Real-time conversation summarization passed to an LLM via MCP server to return agent suggestions during live calls.

---

## Method of Analysis

### Three-Source Cross-System Correlation

A single machine runs three independent transcription capture paths on the same live Genesys call audio simultaneously:

```
Live Genesys Call (agent + customer speaking)
    │
    ├─→ PATH A: Genesys → r2d2 STT → Notifications API (WebSocket) → notifications-spike
    │
    ├─→ PATH B: Genesys → r2d2 STT → EventBridge → SQS → sqs_consumer
    │
    └─→ PATH C: BlackHole audio loopback → Deepgram Nova-3 STT → poc-deepgram
```

**Path C provides ground truth**: Deepgram's `audio_wall_clock_end` tells us the exact wall-clock time each phrase was spoken. Paths A and B record `receivedAt = time.time()` when each transcript event arrives. The difference is the **true end-to-end latency**.

**Matching**: Utterances are correlated across systems using fuzzy text similarity (SequenceMatcher, threshold >= 0.70) within a 15-second temporal window. Each utterance matches at most once per system. 61-62 pairs matched per path from 6 calls covering ~1,300 seconds of audio.

**Formula**:
```
true_latency = receivedAt - deepgram_audio_wall_clock_end
```

Both timestamps are `time.time()` on the same machine — no clock synchronization needed.

---

## Results

### Head-to-Head Latency Comparison

| Source | Median | Mean | p95 | p99 | Min | Max | N |
|--------|-------:|-----:|----:|----:|----:|----:|--:|
| **Deepgram Direct (POC)** | **1,216 ms** | 1,537 ms | 2,947 ms | 3,625 ms | 606 ms | 3,625 ms | 62 |
| **Notifications API (WebSocket)** | **1,369 ms** | 1,744 ms | 3,301 ms | 9,757 ms | 764 ms | 9,757 ms | 61 |
| **EventBridge (SQS)** | **1,570 ms** | 1,936 ms | 3,457 ms | 10,020 ms | 874 ms | 10,020 ms | 62 |
| Notif Self-Reported | 346 ms | 489 ms | 1,194 ms | 2,250 ms | 0 ms | 5,762 ms | 143 |
| EB Self-Reported | 356 ms | 519 ms | 1,240 ms | 3,138 ms | 0 ms | 5,819 ms | 145 |

**Measured differences**:
- EventBridge median is **+201ms** over Notifications (1.15x)
- Notifications median is **+153ms** over Deepgram (1.13x)
- The EB delivery hop (Genesys → SQS → consumer) totals **238ms median** (individual hop medians: 169ms Genesys→SQS, 56ms SQS→consumer poll)

### Self-Reported vs. True Latency

The self-reported numbers (346ms / 356ms median) differ from true latency by a factor of 3.96x (Notifications) and 4.41x (EventBridge). This discrepancy exists because:

1. **Stage 1 is not captured**: Self-reported latency is computed from Genesys's own event metadata (`offsetMs`, `durationMs`, `receivedAt`) using the anchor-event method. This captures Stages 2-4 (STT processing + endpointing + delivery) but does not include Stage 1 — the audio capture transport from caller to Genesys Cloud servers.

2. **Anchor-relative timing zeros out the baseline**: The anchor-event method defines `conversation_start = min(receivedAt - audio_end_offset)` across all events, then measures every event relative to that anchor. The fastest event in each conversation is forced to 0ms. This systematically removes the constant pipeline overhead that every utterance actually experiences.

3. **The gap widens at the tail**: At p95, self-reported shows 1,194ms but true latency is 3,301ms (2.8x). The endpointing batching effect (Stage 3) compounds with the missing baseline.

`summary_latency_confidence.png`
![Summary: Latency and Confidence at a Glance](../analysis_results/cross_system_eb/summary_latency_confidence.png)

---

### Latency Distribution

`distribution_overlay.png`
![Latency Distribution: All Three Sources](../analysis_results/cross_system_eb/distribution_overlay.png)

All three sources show right-skewed distributions with primary peaks around 1,000-1,800ms. Deepgram (purple) clusters tightest with the lowest median. EventBridge (orange) tracks Notifications (blue) with a consistent ~200ms offset. The tail beyond 5,000ms appears simultaneously across delivery paths, correlating with continuous speech segments.

---

### Box Plot Comparison

`boxplot_comparison.png`
![Latency Comparison Across All Sources](../analysis_results/cross_system_eb/boxplot_comparison.png)

The three true end-to-end measurements (Notifications, EventBridge, Deepgram) occupy a similar range with Deepgram having the tightest interquartile spread. Self-reported metrics (green, red) sit 3-4x lower than the corresponding true measurements. Outlier dots beyond 5s correspond to endpointing batching during continuous speech.

---

### Latency Over Time

`timeline_by_source.png`
![Latency Over Time by Delivery Path](../analysis_results/cross_system_eb/timeline_by_source.png)

Scatter plot across all 6 test calls. No systematic drift or degradation observed over time. EventBridge (orange) tracks above Notifications (blue) by a consistent offset. Deepgram (purple) runs below both. Spikes appear simultaneously across delivery paths, correlating with endpointing batching events (Stage 3) rather than delivery path variation (Stage 4).

---

### EventBridge 2-Hop Analysis

`hop_analysis.png`
![EventBridge Hop Analysis](../analysis_results/cross_system_eb/hop_analysis.png)

The EventBridge delivery overhead decomposes into two measurable hops (both with ms-precision timestamps):

| Hop | Median | Mean | p95 |
|-----|-------:|-----:|----:|
| **Hop A**: Genesys → SQS enqueue | 169 ms | 168 ms | 227 ms |
| **Hop B**: SQS → Consumer poll | 56 ms | 70 ms | 142 ms |
| **Total** | 238 ms | 238 ms | 325 ms |

---

### Confidence Scores

`confidence_analysis.png`
![Confidence Score Analysis](../analysis_results/cross_system_eb/confidence_analysis.png)

| Engine | Median (Matched) | Median (All) | N (All) |
|--------|:----------------:|:------------:|:-------:|
| **Deepgram Direct (POC) (Notif-matched)** | 98.3% | 96.9% | 210 |
| **Deepgram Direct (POC) (EB-matched)** | 98.2% | 96.9% | 210 |
| **Genesys r2d2 (Notifications)** | 80.7% | 78.0% | 143 |
| **Genesys r2d2 (EventBridge)** | 80.9% | 78.0% | 145 |

- Deepgram reports **~17 percentage points higher** median confidence than Genesys r2d2 on the same audio
- Genesys confidence drops from 80.7% (matched) to 78.0% (all transcripts) — unmatched utterances tend to have lower confidence
- Notifications and EventBridge carry identical Genesys r2d2 confidence values (same STT engine, different delivery)
- Pearson correlation between Deepgram and Genesys confidence is weak — the two engines assess certainty independently

---

## Production Constraints at Scale

### Latency Budget Components

```
Total time from customer speaks to agent sees suggestion:
  Stage 1-3: Genesys STT + endpointing        ~1,200-1,600 ms (median)
  Stage 4:   Delivery to our application        ~50-200 ms (WebSocket) or ~240 ms (EventBridge)
  Stage 5:   LLM inference via MCP server       ~500-2,000 ms (depends on model/prompt)
  Stage 6:   Render suggestion in agent UI      ~50-100 ms
  ─────────────────────────────────────────────────────────────────
  Total:                                        ~1,800-3,900 ms typical
```

At median, the pipeline completes 1.8-3.9 seconds after the customer finishes speaking. At p95 (3.3-3.5s for Stages 1-4 alone), with LLM inference added, end-to-end latency reaches 4-5.5 seconds.

### Notifications API Topic Limit

The Notifications API has a **hard 1,000 topic limit per WebSocket channel**. The target system requires:

```
  1,200  agent conversation feed topics (static, one per agent)
+   750-1,000  transcription topics (dynamic, at peak)
─────────
= 1,950-2,200  topics needed simultaneously → 2x the limit
```

This requires channel sharding (3-4 WebSocket connections), dynamic topic routing (~80,000 subscribe/unsubscribe API calls/day), 24-hour channel rotation, and a custom recovery mechanism using the analytics API (~8,640 additional API calls/day). During a 6-call test with 2 agents, three bugs were encountered: multi-participant parsing failure, stuck state machine on re-route, and recovery API incompatible with service credentials.

### EventBridge Operational Characteristics

- Zero per-agent subscriptions
- Zero per-conversation subscriptions
- Zero Genesys API calls during steady state
- A single EventBridge rule captures all transcription events org-wide
- SQS scales horizontally with standard AWS autoscaling
- SQS retains messages during consumer downtime (up to 14 days)

Genesys states: *"The WebSocket implementation is designed for responsive UI applications. For server-based integrations, the AWS EventBridge integration is recommended."*

### Confidence Score Characteristics

Genesys r2d2 reports median 78% confidence across all transcripts. In the context of LLM-based suggestion generation:

- Misspelled proper nouns (product names, customer names) produce different knowledge base lookup results
- Misheard intent ("I want to cancel" vs "I want to keep") changes the semantic meaning passed to the LLM
- Utterances below a confidence threshold carry higher probability of transcription errors

### AudioHook Path: Custom STT via Raw Audio Streaming

Genesys AudioHook streams **raw call audio** over WebSocket to an external server, where a custom STT engine (e.g., Deepgram Nova-3) performs transcription. The Deepgram proxy measurements in this analysis approximate what an AudioHook deployment would achieve.

**Measured latency and confidence (POC)**:
- Deepgram Direct (POC): **1,216ms median** (vs. EventBridge 1,570ms, Notifications 1,369ms)
- Deepgram confidence: **98.3% median** (vs. Genesys r2d2 78.0%)

**Infrastructure requirements**:

| Dimension | Genesys AudioHook + Deepgram | EventBridge (SQS) |
|-----------|:--------------------:|:-----------------:|
| Median latency | 1,216 ms | 1,570 ms |
| Median confidence | 98.3% | 78.0% (r2d2) |
| Application code | ~500-1,000 lines | ~80 lines |
| WebSocket connections | ~1,000 concurrent | 0 |
| Inbound bandwidth | ~256 Mbps (audio) | ~5 Mbps (text) |
| Infrastructure | Kubernetes pods + Gloo Gateway + S3 + Secrets Manager | 1 SQS queue |
| Additional licensing | Premium AppFoundry (AudioHook Monitor) | Included |
| STT cost | Deepgram subscription (~$0.0043/min) | $0 (Genesys built-in) |
| Failure recovery | Audio lost if WS drops mid-call | SQS retains 4-14 days |

The detailed AudioHook implementation guide is in `docs/audiohook_research.md`.

### Complexity Comparison (All Three Paths)

| Dimension | EventBridge | Notifications API | Genesys AudioHook + Deepgram |
|-----------|:-----------:|:-----------------:|:--------------------:|
| Application code | ~80 lines (stateless consumer) | ~1,500+ lines (estimated production) | ~500-1,000 lines (AudioHook server + STT) |
| Genesys API calls/day (steady state) | 0 | ~88,640 (subscribe + recovery) | 0 |
| WebSocket connections | 0 | 3-4 concurrent | ~1,000 concurrent (one per call) |
| Inbound bandwidth | ~5 Mbps | ~5 Mbps | ~256 Mbps |
| Failure modes requiring custom code | 1 (consumer crash — SQS retains) | 7+ distinct modes | 2+ (WS drop = lost audio, STT failures) |
| Scaling mechanism | SQS autoscaling (standard AWS) | Channel sharding + rebalancing (custom) | Kubernetes HPA + Gloo Gateway |
| Recovery from downtime | Consumer restarts, drains SQS backlog | Recreate channels, resubscribe all topics, recover missed conversations | No recovery for missed audio; new calls resume automatically |
| Additional cost | $0 | $0 | Premium AppFoundry license + Deepgram STT subscription |

---

## Data Sources

- **Analysis notebook**: `notebooks/cross_system_latency-02-EB-RESULTS.ipynb`
- **Correlation engine**: `scripts/correlate_latency.py`
- **Exported data**: `analysis_results/cross_system_eb/` (CSV, JSON, PNG)
- **Architectural analysis**: `docs/analysis_key_points.md`
- **Prior single-source analysis**: `docs/analysis.md`
- **Testing learnings**: `docs/notifications_testing_learnings.md`
- **AudioHook implementation guide**: `docs/audiohook_research.md`
