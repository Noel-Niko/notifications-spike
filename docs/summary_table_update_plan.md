# Plan: Summary Table Update — transcription_delivery_path_analysis.md

## Goal
Replace the current small summary table (lines 14-19) with a comprehensive executive decision matrix consolidating key facts from across the document.

## Decisions Made
- **A:** Keep the AudioHook caveat paragraph below the table
- **B:** Use inline labels for SLA stage scope (e.g. ">2s rate (Stages 1-4)")
- **C:** Include "Production blockers" as a row in the table

## Proposed Table Structure

**Columns (4 channels):**
1. Genesys AudioHook + Deepgram (est. from official docs)
2. Deepgram Direct (measured)
3. Genesys Notifications WS
4. Genesys EventBridge SQS

**Rows (grouped by category):**

### Latency
| Row | AudioHook+DG (est.) | Deepgram Direct | Notifications WS | EventBridge SQS | Ref |
|-----|---------------------|-----------------|-------------------|-----------------|-----|
| p99 | ~3,500 ms | 3,569 ms | 7,310 ms | 7,470 ms | [1] |
| p95 | ~2,870 ms | 2,945 ms | 3,301 ms | 3,435 ms | [1] |
| p50 | ~1,140 ms | 1,216 ms | 1,369 ms | 1,570 ms | [1] |

### SLA Exceedance (Stages 1-4 only)
| Row | AudioHook+DG (est.) | Deepgram Direct | Notifications WS | EventBridge SQS | Ref |
|-----|---------------------|-----------------|-------------------|-----------------|-----|
| >2s rate (Stages 1-4) | ~27.4% | 27.4% | 18.0% | 19.4% | [1] |
| >2s/day (Stages 1-4) | ~219,200 | ~219,200 | ~144,000 | ~155,200 | [1] |
| >3s rate (Stages 1-4) | ~4.8% | 4.8% | 6.6% | 8.1% | [1] |
| >3s/day (Stages 1-4) | ~38,400 | ~38,400 | ~52,800 | ~64,800 | [1] |
| >5s rate (Stages 1-4) | ~0% | 0.0% | 3.3% | 3.2% | [1] |
| >5s/day (Stages 1-4) | ~0 | 0 | ~26,400 | ~25,600 | [1] |

### Accuracy
| Row | AudioHook+DG (est.) | Deepgram Direct | Notifications WS | EventBridge SQS | Ref |
|-----|---------------------|-----------------|-------------------|-----------------|-----|
| STT Confidence (median) | 98% | 98% | 78% | 78% | [1] |

### Cost
| Row | AudioHook+DG (est.) | Deepgram Direct | Notifications WS | EventBridge SQS | Ref |
|-----|---------------------|-----------------|-------------------|-----------------|-----|
| Monthly cost | ~$68-94K + AudioHook license | N/A (POC only) | $0 | $0 | [14][15] |

### Complexity
| Row | AudioHook+DG (est.) | Deepgram Direct | Notifications WS | EventBridge SQS | Ref |
|-----|---------------------|-----------------|-------------------|-----------------|-----|
| Application code | ~500-1,000 lines | N/A | ~1,500+ lines | ~80 lines | [10][11] |
| Genesys API calls/day | 0 | N/A | ~88,640 | 0 | [10][11] |
| WebSocket connections | ~1,000 (1/call) | N/A | 3-4 | 0 | [10][11][15][17] |
| Failure modes | 2+ | N/A | 7+ | 1 | [10][11] |

### Infrastructure
| Row | AudioHook+DG (est.) | Deepgram Direct | Notifications WS | EventBridge SQS | Ref |
|-----|---------------------|-----------------|-------------------|-----------------|-----|
| Inbound bandwidth | ~256 Mbps | N/A | ~5 Mbps | ~5 Mbps | [16] |

### Resilience
| Row | AudioHook+DG (est.) | Deepgram Direct | Notifications WS | EventBridge SQS | Ref |
|-----|---------------------|-----------------|-------------------|-----------------|-----|
| Recovery from downtime | Limited (20s buffer, 5 retries) | N/A | Recreate channels, resubscribe, recover | SQS retains messages up to 14 days | [12][16] |

### Readiness
| Row | AudioHook+DG (est.) | Deepgram Direct | Notifications WS | EventBridge SQS | Ref |
|-----|---------------------|-----------------|-------------------|-----------------|-----|
| Production blockers | POC + Deepgram contract + AudioHook license | N/A (POC only) | Channel sharding + dynamic topic mgmt + 24h rotation + analytics recovery | None | [7][8][10] |

## Implementation Notes
- All of the above will be a SINGLE markdown table (not separate tables per category) — using a "Category" or blank-row grouping approach
- Keep the AudioHook caveat paragraph after the table (existing text, lines 21)
- Remove the standalone STT Confidence table (lines 27-33) since confidence is now in the main table
- Remove the standalone Complexity Comparison table (lines 189-201) since all data is now in the summary — OR keep it as a detail section. TBD based on approval.
- Keep all downstream detail sections intact (Method, Self-Reported vs True, EB Delivery Overhead, etc.)
- Add [ref] notation to every data point in the table

## Steps
- [ ] Step 1: Draft the combined markdown table
- [ ] Step 2: Replace lines 14-19 with the new table
- [ ] Step 3: Keep caveat paragraph
- [ ] Step 4: Review for accuracy against source data
- [ ] Step 5: User review and approval
