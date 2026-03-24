# Key Points for EventBridge vs Notifications vs Deepgram Analysis

Key arguments, findings, and evidence to incorporate into the final `docs/analysis.md` update after the 6-call comparison run completes. Numbers marked `???` will be filled from actual notebook output.

---

## Summary

EventBridge is the recommended production path ([Recommendation Framework](#8-recommendation-framework)).

| Constraint | Notifications API | EventBridge |
|------------|:-----------------:|:-----------:|
| Topic limit | 1,200 agents need ~2,000 topics (2x the 1,000 limit) | No topic management |
| Failure modes | 7+ distinct modes requiring custom code | 1 (consumer crash -- SQS retains) |
| Application code | ~1,500+ lines (estimated production) | ~80 lines (stateless consumer) |
| Genesys API calls/day | ~88,640 | 0 |
| Latency overhead | Baseline | +201ms median |

Genesys recommends EventBridge for server-side integrations ([Section 1](#1-genesys-themselves-recommend-eventbridge-for-server-side-integrations)).

---

## 1. Genesys Themselves Recommend EventBridge for Server-Side Integrations

The very first paragraph of the Notifications API documentation states:

> "The WebSocket implementation is designed for **responsive UI applications**. For **server-based integrations**, the **AWS EventBridge integration is recommended**." [^1]

Our system is a server-based integration — a backend service monitoring 1,200 agents. We are using the Notifications API contrary to Genesys's own guidance. EventBridge is the vendor-recommended path for this use case.

---

## 2. The 1,000 Topic Limit Is a Hard Architectural Constraint

From the **Usage limitations** section:

> "Each WebSocket connection is limited to 1,000 topics. If you subscribe to more than 1,000 topics, then the notification service returns a **400 error code**." [^2]

### What Is a Topic

A topic is a subscription to a specific event stream for a specific resource instance [^3]. Format: `v2.{resource_type}.{resource_id}.{event_type}`. Each unique topic path counts as 1 toward the 1,000 limit [^2].

Topics are subscribed per channel using `POST /api/v2/notifications/channels/{channelId}/subscriptions` (additive) or `PUT` (destructive replacement) [^3]. The subscription step (step 4 of the Notifications API workflow) requires replacing `{id}` parameters with actual resource IDs — e.g., `v2.users.{id}.presence` becomes `v2.users.00000000-0000-0000-0000-000000000000.presence` [^3].

Examples relevant to our use case:
- `v2.users.{agent_id}.conversations` — one agent's conversation lifecycle events
- `v2.conversations.{conv_id}.transcription` — one conversation's transcription events

### Topic Combining Does Not Help Our Use Case

The documentation describes a "Combine related topics" feature [^4]:

> "Each WebSocket connection is limited to 1,000 topics. For more information, see the Usage limitations section. To remain under the limit, you can combine multiple topics that have the same prefix...The format is similar to a URI query string: `...{prefix}?{suffix1}&{suffix2}&{suffix3}...`" [^4]

The documented example combines three event types for **the same user** [^4]:

```
// Separate: 3 topics
v2.users.00000000-...-000000000000.presence
v2.users.00000000-...-000000000000.routingStatus
v2.users.00000000-...-000000000000.station

// Combined: 1 topic
v2.users.00000000-...-000000000000?presence&routingStatus&station
```

Additional constraints on combined topics: "A combined topic can contain up to 200 characters" and "A combined topic generates separate notifications for each topic under the original, expanded topic name" [^4].

**Why this doesn't help us**: Combining merges multiple **suffixes for the same resource ID**. Our subscriptions are 1,200 **different resources** (agent IDs) each with 1 event type, plus N **different resources** (conversation IDs) each with 1 event type. There is nothing to combine — each topic already has only one suffix for its unique resource. Combining is designed for scenarios like monitoring one user's presence + routing + station (same user, 3 event types). We are monitoring 1,200 different users, each with 1 event type.

### Additional Channel Constraints

From the Usage limitations section [^2]:
- "You can create up to **20 channels** per user and application. When the channel limit is reached, then the new channel replaces the oldest channel that does not have an active connection." [^2]
- "**Channels remain active for 24 hours.** To maintain a channel for longer than 24 hours, resubscribe to topics." [^2]
- "Each channel can only be used by **one WebSocket at a time**. If you connect a second WebSocket with the same channel ID, the first WebSocket disconnects." [^2]

---

## 3. Capacity Math — 1,200 Agents, 40,000 Calls/Day

### Topic Budget

Our system requires two categories of topics:

| Category | Pattern | Count | Lifecycle |
|----------|---------|-------|-----------|
| Agent conversation feeds | `v2.users.{agent_id}.conversations` | 1,200 (one per agent) | Static — subscribed at startup |
| Conversation transcription | `v2.conversations.{conv_id}.transcription` | 1 per active call | Dynamic — subscribe on connect, unsubscribe on end |

**Static agent topics alone (1,200) already exceed the 1,000 limit** [^2].

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

This is **~2× the 1,000 limit** [^2] on a single channel.

### Multi-Channel Workaround

With the 20-channel-per-app limit [^2], we could shard across 3+ channels:

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
- A single EventBridge rule captures **all** transcription events org-wide [^5]
- SQS scales horizontally with standard AWS autoscaling

---

## 4. Notifications API Has Inherent Reliability Problems at Scale

Issues #6, #7, and #8 from `docs/notifications_testing_learnings.md` [^6] demonstrate that the reactive subscription model is fragile:

### 4a. Missed calls on re-route (Issue #6) [^6]

When a call fails on the first agent attempt and Genesys re-routes, the conversation lifecycle event carries stale participant data. The notification system must correctly parse multiple agent participants to find the active one — a bug here silently drops the conversation.

**EventBridge is immune**: it delivers transcription events directly, with no dependency on conversation lifecycle state tracking.

### 4b. Stuck state machine (Issue #7) [^6]

When an agent misses a call and re-readies, the notification system can get stuck in a `connected=False ended=True` loop. The conversation is actively transcribed (EventBridge proves this) but the notification system never recovers because its state machine has no re-activation path.

**EventBridge is immune**: it has no state machine. Every transcription event is delivered to SQS regardless of conversation lifecycle.

### 4c. Recovery mechanism doesn't work with service credentials (Issue #8) [^6]

`GET /api/v2/conversations` returns conversations for the *authenticated user*. With `client_credentials` OAuth (the standard pattern for server-side integrations), there is no user context. The API returns empty results, making the startup recovery mechanism non-functional.

**EventBridge is immune**: no recovery mechanism is needed because delivery doesn't depend on per-conversation subscription state.

### 4d. Recovery requires analytics API workaround at scale (Issue #8 fix) [^6]

The standard Genesys conversation lookup (`GET /api/v2/conversations`) is a **user-context endpoint** — it returns conversations for the authenticated user. With `client_credentials` OAuth (the only viable auth pattern for a server-side integration monitoring 1,200 agents), the endpoint returns nothing.

The fix replaces it with `POST /api/v2/analytics/conversations/details/query`, a platform analytics endpoint that works with service credentials. However, this introduces new scaling concerns for 1,200 agents:

**Query complexity at scale:**
- The analytics query must include **1,200 user ID predicates** in the `segmentFilters` OR clause — one per monitored agent
- Genesys may impose limits on query predicate count or request body size that are not documented for this volume
- The query scans a 24-hour window of conversation history to find active conversations, which grows with org call volume

**Ongoing API load:**
- The recovery function must run at startup **AND** periodically to catch stuck conversations (issue #7), not just once
- At a 10-second poll interval: **8,640 analytics API calls/day** from the recovery mechanism alone
- Each call returns up to 100 conversations that must be parsed and compared against current subscriptions
- This is in addition to the ~80,000 subscribe/unsubscribe API calls/day for conversation topic management (section 9b)

**Cascading dependency:**
- If the analytics API is slow, rate-limited, or temporarily unavailable, stuck conversations accumulate until the next successful poll
- The notification system now depends on **two** Genesys APIs during steady state (WebSocket for events + analytics for recovery) instead of one
- A single EventBridge rule + SQS queue has no equivalent dependency

**Why changing credentials doesn't help:**
- `authorization_code` grant requires interactive user login (not automatable)
- Returns conversations for ONE user — useless for 1,200 agents
- Requires stateful refresh token management, violating 12-factor principles
- `client_credentials` is Genesys's own recommendation for server integrations [^1]

**EventBridge is immune**: no recovery mechanism is needed because delivery doesn't depend on per-conversation subscription state. There is no conversation to "recover" — SQS receives all transcription events regardless of application state.

### Summary: Notification Architecture Failure Modes

| Failure Mode | Notifications API | EventBridge |
|-------------|:-:|:-:|
| Agent re-route / retry [^6] | Must parse multi-participant events correctly | Unaffected |
| Missed call → re-ready [^6] | State machine can get stuck | Unaffected |
| Startup race condition [^6] | Must recover missed conversations | Unaffected |
| Service credential recovery [^6] | Requires analytics API workaround (1,200 predicates) | N/A |
| Recovery polling at scale [^6] | ~8,640 analytics API calls/day | N/A |
| Subscription limit exceeded [^2] | 400 error, events silently dropped | No per-topic subscription |
| WebSocket disconnect [^7] | Must resubscribe all topics | SQS retains messages during consumer downtime [^8] |
| Channel expiry (24hr) [^2] | Must recreate channel and resubscribe | N/A |

Every one of these failure modes requires custom code in the notification system. EventBridge eliminates the entire category.

---

## 5. Latency Comparison Results (fill from notebook)

### Head-to-Head Table

| Metric | Notifications API (WebSocket) | EventBridge (SQS) | Genesys Self-Reported | Deepgram Direct (POC) |
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

2. **EventBridge eliminates an entire class of operational failure modes** — no topic limit management [^2], no channel sharding, no state machine bugs [^6], no subscription lifecycle, no WebSocket reconnection logic [^7].

3. **EventBridge scales linearly** — SQS consumers scale horizontally with standard AWS patterns. No Genesys-side limits on event delivery.

4. **Genesys recommends it** for server-side integrations [^1].

5. **SQS provides durability** — messages survive consumer downtime with retention up to 14 days [^8]. WebSocket events are fire-and-forget; if the consumer is disconnected, events are lost [^7].

6. **Simpler codebase** — the SQS consumer (`scripts/sqs_consumer.py`) is ~80 lines with 2 pure functions. The notification system (`main.py`) is ~570 lines with OAuth, channel management, topic subscription lifecycle, state tracking, recovery logic, and multiple bug-prone edge cases.

---

## 8. Recommendation Framework

### If EB latency ≈ Notifications latency (delta < 500ms):

**Strong recommend EventBridge.** No meaningful latency trade-off, massive architectural simplification, vendor-recommended path [^1], eliminates all notification reliability bugs [^6].

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

- Single EB rule → SQS → consumer fleet (ECS/Lambda) [^5]
- Standard SQS autoscaling based on queue depth
- Dead letter queue for failed messages
- CloudWatch monitoring on queue age / consumer lag
- No Genesys API interaction during steady state (only initial EB integration setup) [^5]

### Notifications Path (what we'd need to build)

Using the Notifications API at 1,200 agents and 40,000 calls/day requires a substantial custom infrastructure layer on top of the WebSocket API. The following components would all need to be designed, built, tested, and operationally maintained.

#### 9a. Channel Shard Manager

The 1,000 topic limit [^2] means a single channel cannot hold all 1,200 agent topics, let alone the dynamic transcription topics. We need **minimum 3 channels** (4 recommended for headroom):

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
- Create channels via `POST /api/v2/notifications/channels` [^3] (limit: 20 per user/app [^2])
- Maintain a mapping: `agent_id → channel_id` and `conversation_id → channel_id`
- Enforce the invariant: no channel exceeds 1,000 topics [^2]

#### 9b. Dynamic Transcription Topic Routing

When a call starts for agent-X:
1. Look up which channel agent-X is assigned to
2. Subscribe `v2.conversations.{conv_id}.transcription` on **that specific channel**
3. When the call ends, unsubscribe the transcription topic from that channel

This creates a constant stream of subscribe/unsubscribe API calls during business hours:
- 40,000 calls/day = ~40,000 subscribes + ~40,000 unsubscribes = ~80,000 API calls/day
- At peak: ~83 calls starting per minute × 2 operations = ~166 subscription API calls/minute
- Each subscribe/unsubscribe uses `PUT /api/v2/notifications/channels/{id}/subscriptions` (replaces the **entire** topic list) or `POST` (adds incrementally) [^3]

The PUT variant is destructive — "This resource replaces an existing list of subscriptions with the list of topics in the request body" [^3]. Under concurrent load, two workers trying to update the same channel simultaneously could overwrite each other's changes. This requires either:
- A single-writer pattern per channel (serialized updates)
- Use of POST (additive) + DELETE for removals, with careful locking
- Accepting occasional race conditions and relying on periodic reconciliation

#### 9c. Channel Rebalancing

If call volume is unevenly distributed across agent shards:
- Channel 1 might hit 950 topics while Channel 3 sits at 500
- Topics cannot be moved between channels — you must unsubscribe from one and subscribe on another
- During the move, events for that agent/conversation may be missed
- Rebalancing under load risks hitting the 1,000 limit [^2] on the receiving channel

A rebalancing strategy must handle:
- Detection: monitor topic counts per channel, trigger rebalance at threshold (e.g., 900)
- Planning: select which agents to move, verify destination channel has capacity
- Execution: unsubscribe agent + all their active conversation topics from source channel, subscribe on destination, update the routing map
- Atomicity: there is no atomic move — events are lost during the migration window

#### 9d. Multi-WebSocket Connection Management

Each channel requires its own WebSocket connection [^2]. With 3–4 channels:

- 3–4 concurrent WebSocket connections, each needing:
  - Independent heartbeat monitoring — the docs provide a manual health check mechanism: send `{"message": "ping"}` and expect a `pong` response; "If you do not receive this response from Genesys Cloud, then close the WebSocket connection and reconnect to the notification channel" [^7]
  - Reconnection logic with exponential backoff
  - Full topic resubscription on reconnect (all agent topics + active conversation topics for that shard)
  - Handling of `v2.system.socket_closing` maintenance notifications — "WebSocket clients have up to one minute to connect a new WebSocket and disconnect the old WebSocket. If the old WebSocket is still connected when maintenance begins, the WebSocket server will close the WebSocket." [^7]
- Message routing: incoming events from all WebSockets must be merged into a unified processing pipeline
- Connection health dashboard: which channels are connected, topic counts, message rates

#### 9e. 24-Hour Channel Rotation

From the docs: "Channels remain active for 24 hours. To maintain a channel for longer than 24 hours, resubscribe to topics." [^2]

For a 24/7 production system:
- Each channel must be refreshed before the 24-hour expiry
- Refresh means: create new channel → subscribe all topics → connect new WebSocket → verify events flowing → disconnect old WebSocket → delete old channel
- This must happen without dropping events — requires overlapping old/new channels during cutover
- With 3–4 channels, rotation must be staggered (not all at once)
- If rotation fails (API error, network issue), the channel dies and all events for that shard are lost until recovery

#### 9f. Conversation Lifecycle State Machine (bugs discovered and partially fixed)

The `main.py` state machine has 3 known bugs discovered during a 6-call test with 2 agents [^6]. At 1,200 agents and 40,000 calls/day, these edge cases will occur regularly — every missed call, every re-route, every agent re-ready creates a potential stuck conversation.

1. **Issue #6 — Multi-participant parsing** [^6]: `_conversation_times()` must iterate ALL agent participants and prefer the active one. **Status: Fixed.** Production hardening added with debug logging that dumps all agent participant data (userId, connectedTime, endTime, state) and warns when no active agent is found.

2. **Issue #7 — Stuck state on re-route** [^6]: When an agent misses a call and re-readies, the state machine gets stuck in `connected=False ended=True`. **Status: Diagnosed, partially mitigated.** Debug logging added to capture exact Genesys participant data during stuck state. The analytics-based recovery (issue #8 fix) can catch these if run periodically, but the root cause in the WebSocket event-driven path remains — the event payload from Genesys may not include the re-routed participant's `connectedTime` immediately, leaving a gap where the conversation is unsubscribed.

3. **Issue #8 — Recovery API incompatible with `client_credentials`** [^6]: `GET /api/v2/conversations` returns empty with service credentials. **Status: Fixed.** Replaced with `POST /api/v2/analytics/conversations/details/query` which works with `client_credentials` auth. Confirmed: the analytics endpoint returned 31 conversations and correctly identified the 1 active conversation during live testing. The fix introduces new scaling concerns at 1,200 agents (see section 4d).

#### 9f-i. Analytics Recovery API — What We Learned

During spike testing, the analytics-based recovery was validated:
- `POST /api/v2/analytics/conversations/details/query` works with `client_credentials` OAuth
- Query with `segmentFilters` for 2 agent user IDs (OR predicate) + purpose=agent filter returned 31 conversations from a 24-hour window
- `extract_active_from_analytics()` correctly identified the 1 active conversation by finding an agent participant with an `interact` segment and no `segmentEnd`
- Conversation `7cf1beb6-0e9d-43ea-a2fa-fd5e97a80f86` was successfully recovered and subscribed for transcription

**Production considerations for this approach at 1,200 agents:**
- The OR predicate in `segmentFilters` must include 1,200 user ID predicates — Genesys predicate count limits unknown
- If predicate limits exist, the query must be batched (e.g., 200 agents per query = 6 queries per poll)
- The 24-hour window may return thousands of conversations at scale (40,000 calls/day), all of which must be parsed
- Periodic polling (e.g., every 10s for stuck-state recovery) adds ~8,640 API calls/day

#### 9g. Monitoring and Alerting

Custom monitoring required (none of this exists in standard AWS/Genesys tooling):

| Metric | Alert Threshold | Action |
|--------|----------------|--------|
| Topic count per channel [^2] | > 900 (of 1,000) | Trigger rebalance or reject new subscriptions |
| WebSocket connection state per channel [^7] | Disconnected > 30s | Reconnect + resubscribe |
| Channel age [^2] | > 23 hours | Trigger rotation |
| Conversations in EventBridge but not Notifications [^6] | Any mismatch | Investigate stuck state |
| Subscribe/unsubscribe API error rate [^3] | > 1% | Throttling or Genesys outage |
| Message rate per WebSocket | Drops to 0 during business hours | Connection dead or topics lost |
| Active conversations vs topic count delta | Growing gap | State machine bug [^6], topics leaking |

#### 9h. Estimated Complexity Comparison

| Dimension | EventBridge Path | Notifications Path |
|-----------|:---:|:---:|
| AWS resources | 1 EB rule, 1 SQS queue, 1 DLQ | 0 (all Genesys-side) |
| Application code | ~80 lines (stateless consumer) | ~1,500+ lines (estimated production-ready) |
| Genesys API calls at steady state | 0 [^5] | ~80,000/day (subscribe/unsubscribe) [^3] + ~8,640/day (analytics recovery polls) |
| WebSocket connections | 0 | 3–4 concurrent [^2] |
| State to manage | None (SQS is the state) | Channel→agent map, conversation→channel map, topic counts, connection health, channel expiry timers |
| Failure modes requiring custom handling | Consumer crash (SQS retains messages [^8]) | 7+ distinct failure modes (see section 4) [^6] |
| Scaling mechanism | SQS consumer autoscaling (standard AWS) | Channel sharding + rebalancing (custom) [^2] |
| Vendor recommendation | "Recommended for server-based integrations" [^1] | "Designed for responsive UI applications" [^1] |
| Recovery from downtime | Consumer restarts, drains backlog from SQS [^8] | Must recreate channels [^2], resubscribe all topics [^3], recover missed conversations [^6] |

---

## References

[^1]: Genesys Cloud Developer Center — Notifications Overview.
https://developer.genesys.cloud/notificationsalerts/notifications/
Section: "Overview" (first paragraph). Exact quote: *"The WebSocket implementation is designed for responsive UI applications. For server-based integrations, the AWS Event Bridge integration is recommended."*

[^2]: Genesys Cloud Developer Center — Notifications Usage Limitations.
https://developer.genesys.cloud/notificationsalerts/notifications/
Section: "Usage limitations". Exact quotes: *"Each WebSocket connection is limited to 1,000 topics. If you subscribe to more than 1,000 topics, then the notification service returns a 400 error code."* · *"You can create up to 20 channels per user and application."* · *"Channels remain active for 24 hours. To maintain a channel for longer than 24 hours, resubscribe to topics."* · *"Each channel can only be used by one WebSocket at a time."*

[^3]: Genesys Cloud Developer Center — Using the Notification Service.
https://developer.genesys.cloud/notificationsalerts/notifications/
Section: "Using the Notification Service" (steps 1–5), "Subscribe to topics", "Show current subscriptions", "Replace a list of subscriptions", "Subscribe and unsubscribe over WebSockets". Covers channel creation (`POST /api/v2/notifications/channels`), topic subscription (`POST` additive, `PUT` destructive replacement, WebSocket-based subscribe/unsubscribe), and topic format (`v2.{resource_type}.{id}.{event_type}`). Exact quote on PUT: *"This resource replaces an existing list of subscriptions with the list of topics in the request body."*

[^4]: Genesys Cloud Developer Center — Combine Related Topics.
https://developer.genesys.cloud/notificationsalerts/notifications/
Section: "Combine related topics". Exact quotes: *"Each WebSocket connection is limited to 1,000 topics...To remain under the limit, you can combine multiple topics that have the same prefix...The format is similar to a URI query string."* · *"A combined topic can contain up to 200 characters."* · *"A combined topic generates separate notifications for each topic under the original, expanded topic name."*

[^5]: Genesys Cloud Resource Center — About the Amazon EventBridge Integration.
https://help.genesys.cloud/articles/about-the-amazon-eventbridge-integration/
Describes EventBridge as delivering Genesys Cloud events to AWS as JSON via a partner event bus. Once the integration is configured, events flow automatically with no per-topic subscription management on the Genesys side. See also: `EventBridge/Genesys_EventBridge_Setup_Runbook.md` for our specific infrastructure configuration.

[^6]: Notifications Testing Learnings — Issues discovered during this comparison test.
`docs/notifications_testing_learnings.md` (local file in this repository).
Issues #6 (multi-participant parsing bug), #7 (stuck state machine on re-route), and #8 (`GET /api/v2/conversations` returns empty with `client_credentials` auth). Each issue includes symptom, root cause, terminal log evidence, and fix status.

[^7]: Genesys Cloud Developer Center — WebSocket Health Check and Closing Notifications.
https://developer.genesys.cloud/notificationsalerts/notifications/
Sections: "WebSocket manual health check", "WebSocket closing notifications". Exact quotes: *"If you do not receive this response from Genesys Cloud, then close the WebSocket connection and reconnect to the notification channel."* · *"WebSocket clients have up to one minute to connect a new WebSocket and disconnect the old WebSocket. If the old WebSocket is still connected when maintenance begins, the WebSocket server will close the WebSocket."*

[^8]: AWS Documentation — Amazon SQS Message Retention & Standard Queue Delivery.
https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/quotas-messages.html — *"By default, a message is retained for 4 days. The minimum is 60 seconds (1 minute). The maximum is 1,209,600 seconds (14 days)."*
https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html — *"Standard queues ensure at-least-once message delivery, but due to the highly distributed architecture, more than one copy of a message might be delivered, and messages may occasionally arrive out of order."*
