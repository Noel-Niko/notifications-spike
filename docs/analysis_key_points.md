# Key Points for EventBridge vs Notifications vs Deepgram Analysis

Key arguments, findings, and evidence to incorporate into the final `docs/analysis.md` update after the 6-call comparison run completes. Numbers marked `???` will be filled from actual notebook output.

---

## 1. Genesys Themselves Recommend EventBridge for Server-Side Integrations

The very first paragraph of the Notifications API documentation states:

> "The WebSocket implementation is designed for **responsive UI applications**. For **server-based integrations**, the **AWS EventBridge integration is recommended**."

Source: https://developer.genesys.cloud/notificationsalerts/notifications/

Our system is a server-based integration — a backend service monitoring 1,200 agents. We are using the Notifications API contrary to Genesys's own guidance. EventBridge is the vendor-recommended path for this use case.

---

## 2. The 1,000 Topic Limit Is a Hard Architectural Constraint

From the **Usage limitations** section of the same page:

> "Each WebSocket connection is limited to 1,000 topics. If you subscribe to more than 1,000 topics, then the notification service returns a **400 error code**."

Source: https://developer.genesys.cloud/notificationsalerts/notifications/ (Usage limitations section)

### What Is a Topic

A topic is a subscription to a specific event stream for a specific resource instance. Format: `v2.{resource_type}.{resource_id}.{event_type}`. Each unique topic path counts as 1 toward the 1,000 limit.

Examples:
- `v2.users.{agent_id}.conversations` — one agent's conversation lifecycle events
- `v2.conversations.{conv_id}.transcription` — one conversation's transcription events

### Topic Combining Does Not Help Our Use Case

The documentation describes a "Combine related topics" feature:

> "To remain under the limit, you can combine multiple topics that have the same prefix...The format is similar to a URI query string: `...{prefix}?{suffix1}&{suffix2}&{suffix3}...`"

This combines multiple **event types for the same resource** — e.g., one user's `presence` + `routingStatus` + `station` becomes 1 topic instead of 3.

Our subscriptions are 1,200 **different resources** (agent IDs) each with 1 event type, plus N **different resources** (conversation IDs) each with 1 event type. There is nothing to combine. Combining is irrelevant to our scale problem.

### Additional Channel Constraints

From the same page:
- 20 channels max per user/app combination
- Channels expire after 24 hours idle
- One WebSocket per channel at a time

Source: https://developer.genesys.cloud/notificationsalerts/notifications/ (Usage limitations section)

---

## 3. Capacity Math — 1,200 Agents, 40,000 Calls/Day

### Topic Budget

Our system requires two categories of topics:

| Category | Pattern | Count | Lifecycle |
|----------|---------|-------|-----------|
| Agent conversation feeds | `v2.users.{agent_id}.conversations` | 1,200 (one per agent) | Static — subscribed at startup |
| Conversation transcription | `v2.conversations.{conv_id}.transcription` | 1 per active call | Dynamic — subscribe on connect, unsubscribe on end |

**Static agent topics alone (1,200) already exceed the 1,000 limit.**

### Concurrent Call Estimate

```
40,000 calls/day × 6 min average duration
────────────────────────────────────────── = 500 concurrent calls (average)
         480 min/business day (8 hrs)

Peak load (1.5–2× average)               = 750–1,000 concurrent calls
```

### Total Topics at Peak

```
  1,200  agent conversation feed topics (static)
+   750–1,000  transcription topics (dynamic, at peak)
─────────
= 1,950–2,200  topics needed simultaneously
```

This is **~2× the 1,000 limit** on a single channel.

### Multi-Channel Workaround

With the 20-channel limit, we could shard across 3+ channels:

```
Channel 1: agents 1–400    + their active conversation topics
Channel 2: agents 401–800  + their active conversation topics
Channel 3: agents 801–1200 + their active conversation topics
```

This introduces:
- Routing logic to assign agents and dynamic conversation topics to the correct channel
- Rebalancing when one channel approaches 1,000 while others have headroom
- 3+ WebSocket connections with independent reconnection/resubscription logic
- Dynamic topic churn — subscribing/unsubscribing as calls start and end
- Operational complexity: monitoring channel health, topic counts, shard distribution

### EventBridge: Zero Topic Management

EventBridge requires:
- Zero per-agent subscriptions
- Zero per-conversation subscriptions
- No 1,000-topic limit concern
- No channel sharding
- A single EventBridge rule captures **all** transcription events org-wide
- SQS scales horizontally with standard AWS autoscaling

---

## 4. Notifications API Has Inherent Reliability Problems at Scale

Issues #6, #7, and #8 from `docs/notifications_testing_learnings.md` demonstrate that the reactive subscription model is fragile:

### 4a. Missed calls on re-route (Issue #6)

When a call fails on the first agent attempt and Genesys re-routes, the conversation lifecycle event carries stale participant data. The notification system must correctly parse multiple agent participants to find the active one — a bug here silently drops the conversation.

**EventBridge is immune**: it delivers transcription events directly, with no dependency on conversation lifecycle state tracking.

### 4b. Stuck state machine (Issue #7)

When an agent misses a call and re-readies, the notification system can get stuck in a `connected=False ended=True` loop. The conversation is actively transcribed (EventBridge proves this) but the notification system never recovers because its state machine has no re-activation path.

**EventBridge is immune**: it has no state machine. Every transcription event is delivered to SQS regardless of conversation lifecycle.

### 4c. Recovery mechanism doesn't work with service credentials (Issue #8)

`GET /api/v2/conversations` returns conversations for the *authenticated user*. With `client_credentials` OAuth (the standard pattern for server-side integrations), there is no user context. The API returns empty results, making the startup recovery mechanism non-functional.

**EventBridge is immune**: no recovery mechanism is needed because delivery doesn't depend on per-conversation subscription state.

### Summary: Notification Architecture Failure Modes

| Failure Mode | Notifications API | EventBridge |
|-------------|:-:|:-:|
| Agent re-route / retry | Must parse multi-participant events correctly | Unaffected |
| Missed call → re-ready | State machine can get stuck | Unaffected |
| Startup race condition | Must recover missed conversations | Unaffected |
| Service credential recovery | `GET /api/v2/conversations` returns nothing | N/A |
| Subscription limit exceeded | 400 error, events silently dropped | No per-topic subscription |
| WebSocket disconnect | Must resubscribe all topics | SQS retains messages during consumer downtime |
| Channel expiry (24hr) | Must recreate channel and resubscribe | N/A |

Every one of these failure modes requires custom code in the notification system. EventBridge eliminates the entire category.

---

## 5. Latency Comparison Results (fill from notebook)

### Head-to-Head Table

| Metric | Notifications API (WebSocket) | EventBridge (SQS) | Genesys Self-Reported | Deepgram Nova-3 |
|--------|---:|---:|---:|---:|
| **Median** | ??? ms | ??? ms | ??? ms | ??? ms |
| **Mean** | ??? ms | ??? ms | ??? ms | ??? ms |
| **p95** | ??? ms | ??? ms | ??? ms | ??? ms |
| **p99** | ??? ms | ??? ms | ??? ms | ??? ms |
| **Min** | ??? ms | ??? ms | ??? ms | ??? ms |
| **Max** | ??? ms | ??? ms | ??? ms | ??? ms |
| **N** | ??? | ??? | ??? | ??? |

### Delta and Ratio

```
Delta (EB - Notif):  median ???ms, mean ???ms, p95 ???ms
Ratio (EB / Notif):  median ???x,  mean ???x,  p95 ???x
```

### Key question to answer

Is EventBridge latency comparable to (or better than) Notifications? If the delta is small relative to the dominant latency sources (STT processing + endpointing = Stages 2–3), then the delivery mechanism (Stage 4) is not the bottleneck and EventBridge is the clear winner on architecture.

---

## 6. EventBridge 3-Hop Analysis (fill from notebook)

The EventBridge pipeline has 3 measurable hops:

```
genesysEventTime ──→ ebTime ──→ sqsSentTimestamp ──→ receivedAt
     Hop 1: Genesys → EB     Hop 2: EB → SQS       Hop 3: SQS → Consumer
```

| Hop | Median | Mean | p95 | Precision Caveat |
|-----|---:|---:|---:|---|
| Hop 1: Genesys → EventBridge | ??? ms | ??? ms | ??? ms | `ebTime` has **second-level only** granularity — ~1s rounding error |
| Hop 2: EventBridge → SQS | ??? ms | ??? ms | ??? ms | Limited by `ebTime` precision |
| Hop 3: SQS → Consumer | ??? ms | ??? ms | ??? ms | ms precision on both ends |
| **Total delivery overhead** | ??? ms | ??? ms | ??? ms | |

Where does time go? If Hop 3 (SQS poll cycle) dominates, it can be reduced by tuning `WaitTimeSeconds` or switching to SQS → Lambda trigger.

---

## 7. The Architectural Argument (Regardless of Latency Numbers)

Even if EventBridge adds measurable latency overhead vs WebSocket:

1. **The delivery hop (Stage 4) is a tiny fraction of total latency.** STT processing (Stage 2: ~500–800ms) and endpointing (Stage 3: 0.3–15s+) dominate. Adding 100–500ms to Stage 4 is noise within the total pipeline.

2. **EventBridge eliminates an entire class of operational failure modes** — no topic limit management, no channel sharding, no state machine bugs, no subscription lifecycle, no WebSocket reconnection logic.

3. **EventBridge scales linearly** — SQS consumers scale horizontally with standard AWS patterns. No Genesys-side limits on event delivery.

4. **Genesys recommends it** for server-side integrations.

5. **SQS provides durability** — messages survive consumer downtime (retention up to 14 days). WebSocket events are fire-and-forget; if the consumer is disconnected, events are lost.

6. **Simpler codebase** — the SQS consumer (`scripts/sqs_consumer.py`) is ~80 lines with 2 pure functions. The notification system (`main.py`) is ~570 lines with OAuth, channel management, topic subscription lifecycle, state tracking, recovery logic, and multiple bug-prone edge cases.

---

## 8. Recommendation Framework

### If EB latency ≈ Notifications latency (delta < 500ms):

**Strong recommend EventBridge.** No meaningful latency trade-off, massive architectural simplification, vendor-recommended path, eliminates all notification reliability bugs.

### If EB latency moderately higher (delta 500ms–2s):

**Still recommend EventBridge.** The delta is within endpointing variance (Stage 3 alone varies by 0.3–15s). For real-time transcription display, the user cannot perceive 500ms–2s additional delivery delay when the total pipeline is already 1.5–2.5s. The operational benefits outweigh the marginal latency cost.

### If EB latency significantly higher (delta > 2s):

**Investigate the hop analysis.** Determine which hop is the bottleneck:
- If Hop 3 (SQS poll) dominates → switch to Lambda trigger or reduce poll interval
- If Hop 1–2 (EB routing) dominates → this is an AWS/Genesys infrastructure issue, engage support
- Consider whether the latency delta matters for the specific use case (real-time display vs async processing vs analytics)

---

## 9. Production Deployment Considerations

### EventBridge Path (recommended)

- Single EB rule → SQS → consumer fleet (ECS/Lambda)
- Standard SQS autoscaling based on queue depth
- Dead letter queue for failed messages
- CloudWatch monitoring on queue age / consumer lag
- No Genesys API interaction during steady state (only initial EB integration setup)

### Notifications Path (what we'd need to build)

Using the Notifications API at 1,200 agents and 40,000 calls/day requires a substantial custom infrastructure layer on top of the WebSocket API. The following components would all need to be designed, built, tested, and operationally maintained.

#### 9a. Channel Shard Manager

The 1,000 topic limit means a single channel cannot hold all 1,200 agent topics, let alone the dynamic transcription topics. We need **minimum 3 channels** (4 recommended for headroom):

```
Channel 1: agents 1–400     (~400 agent topics + up to ~333 transcription topics at peak)
Channel 2: agents 401–800   (~400 agent topics + up to ~333 transcription topics at peak)
Channel 3: agents 801–1200  (~400 agent topics + up to ~333 transcription topics at peak)
──────────────────────────────────────────────────────────────────────────────────────────
Per-channel peak: ~733 topics (under 1,000 with ~27% headroom)
```

The shard manager must:
- Assign each agent to a channel at startup
- Track current topic count per channel in real time
- Create channels via `POST /api/v2/notifications/channels`
- Maintain a mapping: `agent_id → channel_id` and `conversation_id → channel_id`
- Enforce the invariant: no channel exceeds 1,000 topics

#### 9b. Dynamic Transcription Topic Routing

When a call starts for agent-X:
1. Look up which channel agent-X is assigned to
2. Subscribe `v2.conversations.{conv_id}.transcription` on **that specific channel**
3. When the call ends, unsubscribe the transcription topic from that channel

This creates a constant stream of subscribe/unsubscribe API calls during business hours:
- 40,000 calls/day = ~40,000 subscribes + ~40,000 unsubscribes = ~80,000 API calls/day
- At peak: ~83 calls starting per minute × 2 operations = ~166 subscription API calls/minute
- Each subscribe/unsubscribe is a `PUT /api/v2/notifications/channels/{id}/subscriptions` call that replaces the **entire** topic list for that channel (or a `POST` to add incrementally)

The PUT variant is destructive — it replaces all subscriptions. Under concurrent load, two workers trying to update the same channel simultaneously could overwrite each other's changes. This requires either:
- A single-writer pattern per channel (serialized updates)
- Use of POST (additive) + DELETE for removals, with careful locking
- Accepting occasional race conditions and relying on periodic reconciliation

#### 9c. Channel Rebalancing

If call volume is unevenly distributed across agent shards:
- Channel 1 might hit 950 topics while Channel 3 sits at 500
- Topics cannot be moved between channels — you must unsubscribe from one and subscribe on another
- During the move, events for that agent/conversation may be missed
- Rebalancing under load risks hitting the 1,000 limit on the receiving channel

A rebalancing strategy must handle:
- Detection: monitor topic counts per channel, trigger rebalance at threshold (e.g., 900)
- Planning: select which agents to move, verify destination channel has capacity
- Execution: unsubscribe agent + all their active conversation topics from source channel, subscribe on destination, update the routing map
- Atomicity: there is no atomic move — events are lost during the migration window

#### 9d. Multi-WebSocket Connection Management

Each channel requires its own WebSocket connection. With 3–4 channels:

- 3–4 concurrent WebSocket connections, each needing:
  - Independent heartbeat monitoring (`ping`/`pong` per the docs)
  - Reconnection logic with exponential backoff
  - Full topic resubscription on reconnect (all agent topics + active conversation topics for that shard)
  - Handling of `v2.system.socket_closing` maintenance notifications (docs: "WebSocket clients have up to one minute to connect a new WebSocket and disconnect the old WebSocket")
- Message routing: incoming events from all WebSockets must be merged into a unified processing pipeline
- Connection health dashboard: which channels are connected, topic counts, message rates

#### 9e. 24-Hour Channel Rotation

From the docs: "Channels remain active for 24 hours. To maintain a channel for longer than 24 hours, resubscribe to topics."

For a 24/7 production system:
- Each channel must be refreshed before the 24-hour expiry
- Refresh means: create new channel → subscribe all topics → connect new WebSocket → verify events flowing → disconnect old WebSocket → delete old channel
- This must happen without dropping events — requires overlapping old/new channels during cutover
- With 3–4 channels, rotation must be staggered (not all at once)
- If rotation fails (API error, network issue), the channel dies and all events for that shard are lost until recovery

#### 9f. Conversation Lifecycle State Machine (bug fixes required)

The current `main.py` state machine has 3 known bugs that must be fixed for production:

1. **Issue #6 — Multi-participant parsing**: `_conversation_times()` must iterate ALL agent participants and prefer the active one. (Fixed in current code, but needs production hardening with logging.)

2. **Issue #7 — Stuck state on re-route**: When an agent misses a call and re-readies, the state machine gets stuck. The fix requires either:
   - Ensuring `_conversation_times()` correctly identifies the new active participant from the re-routed event payload (depends on what Genesys actually sends — needs production-level diagnosis with debug logging)
   - Adding a periodic reconciliation loop that detects conversations with transcription activity (via EventBridge/SQS or analytics API) but no notification subscription, and force-subscribes them

3. **Issue #8 — Recovery API incompatible with `client_credentials`**: `GET /api/v2/conversations` returns empty results with service credentials. Must replace with `POST /api/v2/analytics/conversations/details/query` or `GET /api/v2/users/{userId}/conversations`, both of which need testing to confirm they work with `client_credentials` auth.

Each of these bugs was discovered during a 6-call test with a single agent. At 1,200 agents and 40,000 calls/day, these edge cases will occur regularly — every missed call, every re-route, every agent re-ready creates a potential stuck conversation.

#### 9g. Monitoring and Alerting

Custom monitoring required (none of this exists in standard AWS/Genesys tooling):

| Metric | Alert Threshold | Action |
|--------|----------------|--------|
| Topic count per channel | > 900 (of 1,000) | Trigger rebalance or reject new subscriptions |
| WebSocket connection state per channel | Disconnected > 30s | Reconnect + resubscribe |
| Channel age | > 23 hours | Trigger rotation |
| Conversations in EventBridge but not Notifications | Any mismatch | Investigate stuck state |
| Subscribe/unsubscribe API error rate | > 1% | Throttling or Genesys outage |
| Message rate per WebSocket | Drops to 0 during business hours | Connection dead or topics lost |
| Active conversations vs topic count delta | Growing gap | State machine bug, topics leaking |

#### 9h. Estimated Complexity Comparison

| Dimension | EventBridge Path | Notifications Path |
|-----------|:---:|:---:|
| AWS resources | 1 EB rule, 1 SQS queue, 1 DLQ | 0 (all Genesys-side) |
| Application code | ~80 lines (stateless consumer) | ~1,500+ lines (estimated production-ready) |
| Genesys API calls at steady state | 0 | ~80,000/day (subscribe/unsubscribe) |
| WebSocket connections | 0 | 3–4 concurrent |
| State to manage | None (SQS is the state) | Channel→agent map, conversation→channel map, topic counts, connection health, channel expiry timers |
| Failure modes requiring custom handling | Consumer crash (SQS retains messages) | 7+ distinct failure modes (see section 4) |
| Scaling mechanism | SQS consumer autoscaling (standard AWS) | Channel sharding + rebalancing (custom) |
| Vendor recommendation | "Recommended for server-based integrations" | "Designed for responsive UI applications" |
| Recovery from downtime | Consumer restarts, drains backlog from SQS | Must recreate channels, resubscribe all topics, recover missed conversations |
