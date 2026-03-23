# Genesys Notifications API — Production Implementation Guide

Full implementation requirements for using the Genesys Notifications API (WebSocket) to capture real-time transcription events at scale (1,200 agents, 40,000 calls/day). This guide documents what we learned during the notifications-spike project and what a production implementation would need.

> **Recommendation**: Use EventBridge instead. See `docs/analysis_key_points.md` for the full comparison. This guide exists to document the Notifications path if EventBridge is not chosen.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Notification Service                          │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Channel 1   │  │  Channel 2   │  │  Channel 3   │  (+1     │
│  │  WS conn     │  │  WS conn     │  │  WS conn     │  spare)  │
│  │  agents 1-400│  │  agents      │  │  agents      │          │
│  │  + their     │  │  401-800     │  │  801-1200    │          │
│  │  conv topics │  │  + convs     │  │  + convs     │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                 │                    │
│         └─────────────────┼─────────────────┘                   │
│                           ▼                                     │
│              ┌────────────────────────┐                         │
│              │  Unified Event Router  │                         │
│              └───────────┬────────────┘                         │
│                          ▼                                      │
│              ┌────────────────────────┐                         │
│              │  Transcript Writer     │◄── JSONL / DB / Stream  │
│              └────────────────────────┘                         │
│                                                                 │
│  Background Tasks:                                              │
│  ┌──────────────────┐ ┌─────────────────┐ ┌─────────────────┐  │
│  │ Channel Rotation  │ │ Analytics       │ │ Shard           │  │
│  │ (every 23h)       │ │ Recovery Poll   │ │ Rebalancer      │  │
│  └──────────────────┘ │ (every 10s)     │ └─────────────────┘  │
│                       └─────────────────┘                       │
│                                                                 │
│  State Store (Redis / DB):                                      │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ agent→channel map │ conv→channel map │ topic counts      │   │
│  │ channel expiry    │ active convs     │ connection health  │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. OAuth Authentication

**Grant type**: `client_credentials` (server-to-server, no interactive login)

```python
# POST {REGION_LOGIN_BASE}/oauth/token
# Content-Type: application/x-www-form-urlencoded
# Auth: Basic(CLIENT_ID, CLIENT_SECRET)
# Body: grant_type=client_credentials
```

**Required OAuth scopes** (configure in Genesys Admin > OAuth):
- `conversations` — conversation lifecycle events
- `notifications` — channel creation, topic subscription
- `users` — user ID resolution from email
- `analytics` — conversation details query (for recovery)

**Token management**:
- Tokens expire (typically 24 hours) — implement refresh before expiry
- Store token in memory, not on disk (12-factor)
- All API calls use `Authorization: Bearer {token}` header

**Important**: `client_credentials` has no user context. `GET /api/v2/conversations` returns empty results. Use `POST /api/v2/analytics/conversations/details/query` for conversation recovery (see section 8).

---

## 3. Channel Shard Manager

### Why sharding is required

Each WebSocket channel is limited to **1,000 concurrent topic subscriptions**. Our system needs:
- 1,200 static agent topics (`v2.users.{agent_id}.conversations`)
- Up to 1,000 dynamic conversation topics at peak (`v2.conversations.{conv_id}.transcription`)
- Total: ~2,200 topics — requires minimum 3 channels

### Implementation

```python
# Data structures (store in Redis or equivalent for multi-process)
agent_to_channel: Dict[str, str]       # agent_user_id → channel_id
conv_to_channel: Dict[str, str]        # conversation_id → channel_id
channel_topic_counts: Dict[str, int]   # channel_id → current topic count
channel_created_at: Dict[str, float]   # channel_id → creation timestamp
```

**Startup sequence**:
1. Create 3-4 channels via `POST /api/v2/notifications/channels`
2. Assign agents to channels (round-robin or hash-based)
3. Subscribe agent topics to assigned channels
4. Connect WebSocket per channel
5. Run analytics recovery to catch in-progress conversations

**Agent assignment**: Use consistent hashing (e.g., `hash(agent_id) % num_channels`) so the assignment is deterministic and survives restarts without state.

---

## 4. Topic Subscription Management

### Subscribe to agent conversation feeds (static, at startup)

```python
# For each agent assigned to a channel:
topic = f"v2.users.{agent_user_id}.conversations"
# POST /api/v2/notifications/channels/{channel_id}/subscriptions
# Body: [{"id": topic}]  (additive — adds to existing subscriptions)
```

### Subscribe to conversation transcription (dynamic, on call start)

When a `v2.users.{agent_id}.conversations` event arrives with an active agent participant:

```python
topic = f"v2.conversations.{conv_id}.transcription"
channel_id = agent_to_channel[agent_user_id]
# Subscribe on the SAME channel as the agent
# Track: conv_to_channel[conv_id] = channel_id
# Increment: channel_topic_counts[channel_id] += 1
```

### Unsubscribe on call end

When `_conversation_times()` returns `(start, end)` with both set:

```python
channel_id = conv_to_channel.pop(conv_id)
# Remove topic from channel subscriptions
# Decrement: channel_topic_counts[channel_id] -= 1
```

### Concurrency safety

`PUT /api/v2/notifications/channels/{id}/subscriptions` replaces the **entire** topic list. Under concurrent load:
- Use a per-channel asyncio lock or Redis-based lock
- Serialize all subscribe/unsubscribe operations per channel
- Alternatively, use WebSocket-based subscribe/unsubscribe (sends `{"message": "subscribe", "topics": [...]}` over the WS connection) which may be safer for incremental updates

---

## 5. WebSocket Connection Management

### Connection per channel

```python
async def channel_ws_loop(channel_id: str, connect_uri: str):
    while True:
        try:
            async with websockets.connect(connect_uri, ping_interval=20, ping_timeout=20) as ws:
                async for raw in ws:
                    msg = json.loads(raw)
                    topic = msg.get("topicName")
                    if topic == "channel.metadata":
                        continue
                    if topic == "v2.system.socket_closing":
                        # Genesys maintenance — reconnect within 60 seconds
                        log.warning("Channel %s: socket_closing received, reconnecting", channel_id)
                        break
                    await route_event(channel_id, msg)
        except Exception as e:
            log.warning("Channel %s WS error: %s; reconnecting in 3s", channel_id, e)
            await asyncio.sleep(3)
```

### Health check

Periodically send `{"message": "ping"}` and expect a pong response. If no response, close and reconnect.

### Reconnection

On reconnect, all topics must be resubscribed. The channel retains its topic list, but the WebSocket connection does not. After reconnecting:
1. Re-fetch current topic list from state store
2. Call `PUT /api/v2/notifications/channels/{id}/subscriptions` with full topic list
3. Run analytics recovery to catch conversations missed during disconnect

---

## 6. 24-Hour Channel Rotation

Channels expire after 24 hours. Production rotation:

```
T+0h:  Create channels A, B, C
T+23h: Create new channel A' → subscribe same topics as A
        → connect WS to A' → verify events flowing
        → disconnect WS from A → delete A
T+23h15m: Rotate B → B'
T+23h30m: Rotate C → C'
```

**Stagger rotations** to avoid rotating all channels simultaneously.

**Overlap period**: Run both old and new channel WebSockets for 30-60 seconds. Deduplicate events by conversation ID + timestamp. This prevents event loss during cutover.

---

## 7. Conversation Lifecycle State Machine

### Participant parsing (`_conversation_times`)

The function must iterate **all** agent participants and prefer the active one (connectedTime set, endTime null). Bugs discovered during testing:

- **Issue #6**: First implementation used `break` on first agent participant, missing re-routed agents. Fix: iterate all, prefer active.
- **Issue #7**: When an agent misses a call and re-readies, the WebSocket event may not include the new participant's `connectedTime` immediately, leaving the system stuck in `connected=False ended=True`.

### Production implementation

```python
def _conversation_times(event_body):
    # Iterate ALL agent participants
    # Prefer: active (connectedTime set, endTime null)
    # Fallback: most recent connectedTime
    # Log WARNING when agents exist but none are active (stuck state)
    # Log DEBUG with full participant dump for diagnosis
```

### Known limitation

The state machine is inherently reactive — it only acts on events it receives. If the WebSocket event payload from Genesys doesn't reflect the new active participant immediately after a re-route, the system has no way to know the conversation is active. The analytics recovery poll (section 8) is the safety net for this gap.

---

## 8. Analytics-Based Recovery

### Why it's needed

1. **Startup recovery**: Conversations active before the service started
2. **Stuck state recovery**: Conversations missed due to re-routing (issue #7)
3. **Reconnection recovery**: Conversations missed during WebSocket disconnect

### API endpoint

```python
# POST /api/v2/analytics/conversations/details/query
# Works with client_credentials auth (unlike GET /api/v2/conversations)
```

### Query construction

```python
def build_analytics_query(agent_user_ids: Set[str]) -> dict:
    now = datetime.now(timezone.utc)
    interval_start = now - timedelta(hours=24)
    return {
        "interval": f"{interval_start.isoformat()}Z/{now.isoformat()}Z",
        "order": "desc",
        "orderBy": "conversationStart",
        "paging": {"pageSize": 100, "pageNumber": 1},
        "segmentFilters": [
            {
                "type": "or",
                "predicates": [
                    {"type": "dimension", "dimension": "userId",
                     "operator": "matches", "value": uid}
                    for uid in agent_user_ids
                ],
            },
            {
                "type": "and",
                "predicates": [
                    {"type": "dimension", "dimension": "purpose",
                     "operator": "matches", "value": "agent"}
                ],
            },
        ],
    }
```

### Response parsing

The analytics response uses a different structure from the conversations API:
- `conversationId` (not `id`)
- `conversationEnd` — if set, conversation is over
- `participants[].sessions[].segments[]` — each segment has `segmentType` and optional `segmentEnd`
- Active conversation = agent participant with `segmentType` in (`interact`, `connected`) and no `segmentEnd`

### Scaling at 1,200 agents

- The OR predicate must include 1,200 user IDs — test for Genesys predicate limits
- If limits exist, batch queries (e.g., 200 agents per query, 6 queries per poll)
- The 24-hour window may return thousands of conversations at scale
- Poll interval trade-off: shorter = faster recovery but more API load
  - Recommended: 10 seconds for production, yielding ~8,640 API calls/day

---

## 9. Monitoring and Alerting

### Required metrics

| Metric | Alert Threshold | Action |
|--------|----------------|--------|
| Topic count per channel | > 900 (of 1,000) | Trigger rebalance or reject new subscriptions |
| WebSocket state per channel | Disconnected > 30s | Reconnect + resubscribe |
| Channel age | > 23 hours | Trigger rotation |
| Analytics recovery: conversations found vs subscribed | Mismatch | Investigate stuck state |
| Subscribe/unsubscribe API error rate | > 1% | Throttling or Genesys outage |
| Message rate per WebSocket | Drops to 0 during business hours | Dead connection or lost topics |
| Active conversations vs topic count | Growing gap | Topic leak (subscribe without unsubscribe) |
| Analytics API response time | > 5s | Query too large, batch agents |
| Token expiry | < 1 hour remaining | Refresh token |

### Logging requirements

- **INFO**: Conversation activation/deactivation, recovery results, channel rotation
- **WARNING**: No active agent found for conversation (stuck state), API errors, WebSocket reconnection
- **DEBUG**: Full participant dumps, analytics query bodies, raw API responses

---

## 10. Estimated Implementation Effort

| Component | Description | Complexity |
|-----------|-------------|:---:|
| OAuth + token refresh | Token management with auto-refresh | Low |
| Channel shard manager | Create channels, assign agents, track topic counts | Medium |
| Dynamic topic routing | Subscribe/unsubscribe transcription topics per call | Medium |
| Multi-WebSocket management | 3-4 concurrent WS with independent reconnection | High |
| 24-hour channel rotation | Staggered rotation with overlap dedup | High |
| Conversation state machine | Parse participants, handle re-routes, debug logging | Medium |
| Analytics recovery | Periodic poll, parse response, re-subscribe | Medium |
| Channel rebalancing | Monitor imbalance, migrate agents between channels | High |
| Monitoring/alerting | Custom metrics for all above components | Medium |
| **Total** | | **~1,500-2,000 lines of application code** |

### Comparison: EventBridge path

| Component | Description | Complexity |
|-----------|-------------|:---:|
| SQS consumer | Poll queue, parse events, write to storage | Low |
| Dead letter queue | Standard AWS DLQ configuration | Low |
| CloudWatch alarms | Queue depth, consumer lag | Low |
| **Total** | | **~80-100 lines of application code** |

---

## 11. Testing Checklist

Before going to production, these scenarios must be tested at scale:

- [ ] 1,200 agents subscribed across 3-4 channels without exceeding 1,000 topics
- [ ] Dynamic transcription topic subscribe/unsubscribe under peak load (166 API calls/minute)
- [ ] Agent misses call → re-readies → answers re-routed call → transcription captured
- [ ] WebSocket disconnect → reconnection → topics resubscribed → no event loss
- [ ] Channel rotation after 23 hours with no event loss during cutover
- [ ] Analytics recovery correctly identifies active conversations at startup
- [ ] Analytics recovery correctly identifies stuck conversations during operation
- [ ] Channel rebalancing when one shard is disproportionately loaded
- [ ] `PUT` subscription under concurrent load (race condition testing)
- [ ] Token expiry during active calls → refresh → no disruption
- [ ] Genesys API rate limiting → graceful backoff → recovery
- [ ] Full 8-hour business day simulation with realistic call patterns

---

## 12. References

- Genesys Notifications API: https://developer.genesys.cloud/notificationsalerts/notifications/
- Genesys EventBridge Integration: https://help.genesys.cloud/articles/about-the-amazon-eventbridge-integration/
- Spike codebase: `main.py` (WebSocket notification system), `scripts/sqs_consumer.py` (EventBridge consumer)
- Testing learnings: `docs/notifications_testing_learnings.md`
- Architecture comparison: `docs/analysis_key_points.md`
