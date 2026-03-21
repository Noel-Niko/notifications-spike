# Notifications Testing Learnings

Issues encountered during EventBridge vs Notifications latency comparison testing (March 2026). Document these to avoid repeating mistakes in future test runs.

---

## 1. MAX_CONCURRENT_CONVERSATIONS defaulted to 1

**Symptom**: Only every other conversation captured by notifications-spike. Alternating miss-hit-miss-hit pattern across 6 sequential calls — 3 of 6 conversations missing.

**Root cause**: `MAX_CONCURRENT_CONVERSATIONS` in `main.py` defaulted to `1` via `os.environ.get("MAX_CONVERSATIONS", "1")`. When a new call started before the previous conversation was fully deactivated, the new one was silently rejected at the capacity check.

**Fix**: Changed default to `10`. For production, consider the Genesys enterprise limit of 1,000 concurrent topic subscriptions per WebSocket channel (see scaling note below).

**Time lost**: Two full 6-call test runs (~30 minutes each).

---

## 2. Startup race condition — first conversation missed

**Symptom**: First conversation captured by EventBridge and Deepgram but NOT by notifications-spike. Subsequent conversations captured by all 3 systems.

**Root cause**: notifications-spike uses a reactive subscription model — it subscribes to `v2.conversations.{id}.transcription` only after receiving a `v2.users.{id}.conversations` event with `connectedTime`. If a call is already in progress (or starts) before the WebSocket subscription is fully established, the initial conversation event is missed and that conversation is never subscribed.

The startup sequence is: get OAuth token → create channel → subscribe agent topics → connect WebSocket. A call that starts during any of these steps is invisible to the system.

**Fix**: Added `recover_active_conversations()` which calls `GET /api/v2/conversations` immediately after the WebSocket connects, finds conversations where a monitored agent is connected but not ended, and subscribes to them. This catches calls that started during the startup window.

**⚠️ Update (see issue #8)**: `recover_active_conversations()` likely never worked. `GET /api/v2/conversations` returns conversations for the *logged-in user*, but with `client_credentials` OAuth there is no user context — the API returns an empty `entities` array. The real reason issue #2 was mitigated is that testers followed the "Prevention" step below.

**Prevention**: Always wait for the `WebSocket connected (agents=N, max_concurrent_conversations=10)` log line before taking the first call. The recovery function is a safety net, not a replacement for proper sequencing.

**Time lost**: One partial test run (had to redo 4 of 6 calls).

---

## 3. SQS consumer not started — all EventBridge data missing

**Symptom**: Notebook showed "No EventBridge hop data available." SQS queue had 152 unprocessed messages.

**Root cause**: The SQS consumer (`scripts/sqs_consumer.py`) was never started during the test calls. EventBridge was correctly delivering to SQS, but nobody was consuming. The messages accumulated in the queue with stale timestamps.

**Why `receivedAt` was unrecoverable**: The consumer records `time.time()` as `receivedAt` when it processes a message. Draining the queue hours/days later produces `receivedAt` values that are useless for latency correlation. `sqsSentTimestamp` (set by SQS at enqueue time) could serve as a proxy but misses the SQS→consumer poll hop.

**Fix**: Created `EventBridge/testing_steps.md` with complete 3-system startup checklist. All 3 terminals must be running before the first call.

**Time lost**: One full 6-call test run (~30 minutes) plus data investigation.

---

## 4. SQS consumer missing AWS region

**Symptom**: `botocore.exceptions.NoRegionError: You must specify a region.`

**Root cause**: `poll_sqs()` created a boto3 Session with `profile_name` but no `region_name`. The `765425735388_admin-role` profile in `~/.aws/credentials` doesn't have a default region.

**Fix**: Added `AWS_REGION` env var (default `us-east-2`) and passed `region_name` to `boto3.Session()`.

---

## 5. SQS consumer crashed on status events

**Symptom**: `KeyError: 'transcripts'` for some SQS messages. Failed messages were re-polled forever (poison message loop).

**Root cause**: Genesys sends both transcript events and status events (e.g., `SESSION_ONGOING`) via EventBridge. Status events have a `status` field instead of `transcripts`. The consumer assumed all events had `transcripts`.

Second bug: failed messages were not deleted from SQS (the `continue` after the exception skipped the `delete_message` call), creating poison messages.

**Fix**: `parse_sqs_message()` returns `None` for events without `transcripts`. The consumer skips saving but still deletes the message from SQS.

---

## 6. `_conversation_times` stops at first agent participant — re-routed calls missed

**Symptom**: Conversation `346de798` captured by EventBridge and Deepgram (Shawshank Redemption recording) but NOT by notifications-spike. Terminal logs showed `connected=False ended=False` then `connected=False ended=True` for that conversation — as if the agent never answered.

**Root cause**: `_conversation_times()` in `main.py` iterates participants and `break`s on the **first** participant with `purpose="agent"`. When a call fails on the first agent attempt (no `connectedTime`, later gets `endTime`) and Genesys re-routes to a second agent participant who IS connected, the function never reaches that second participant. It returns `connectedTime=None` for the first failed agent, so the conversation is never activated for transcription.

```python
# Bug: breaks on first agent participant
for part in participants:
    if isinstance(purpose, str) and purpose.lower() == "agent":
        call_start = part.get("connectedTime")
        call_end = part.get("endTime")
        break  # ← never sees the second, connected agent participant
```

The same pattern affects `extract_active_conversation_ids()` for startup recovery — it also `break`s on the first matching agent.

**Fix needed**: Iterate ALL agent participants for the monitored user and prefer the one with `connectedTime` set and no `endTime`. Fall back to any agent participant with `connectedTime`.

**Prevention**: When answering a Genesys call, if the first attempt fails (e.g., timeout, routing error), be aware the re-routed answer creates a second participant entry. The fix above handles this programmatically. Until the fix is applied, retry the recording if a call has a failed first answer attempt.

**Data action**: Removed `346de798` JSONL from EventBridge and matching Deepgram file (`nova-3_2026-03-20T22-02-43Z.json`). Need to re-record Shawshank Redemption as the 6th call.

**Time lost**: One call out of 6, plus diagnosis time.

---

## 7. Notification system stuck after missed call and agent re-ready

**Symptom**: Conversation `7cf1beb6` captured by EventBridge/SQS but NOT by notifications-spike. SQS consumer logs show active transcription events being saved at 19:56–19:57, but the notification system terminal shows the conversation stuck at `connected=False ended=True` since 19:46 — a ~10-minute gap with no recovery.

```
# Notification system (stuck):
[2026-03-20 19:46:03,876] INFO Conversation 7cf1beb6-... agent state: connected=False ended=True
[2026-03-20 19:48:49,608] INFO Conversation 7cf1beb6-... agent state: connected=False ended=True

# SQS consumer (working):
[2026-03-20 19:56:58,045] INFO Saved event for conversation 7cf1beb6-... to EventBridge/conversation_events/7cf1beb6-....jsonl
[2026-03-20 19:57:02,741] INFO Saved event for conversation 7cf1beb6-... to EventBridge/conversation_events/7cf1beb6-....jsonl
```

**Trigger**: Agent misses the first call attempt (doesn't answer in time), then sets themselves as "ready" again in Genesys. The call re-routes to the same agent, who answers successfully on the second attempt.

**Root cause**: The notification system's state machine cannot recover from a missed-call deactivation mid-session. The sequence is:

1. Call arrives, agent is alerted → Genesys creates participant with `connectedTime=null`
2. Agent doesn't answer in time → Genesys sets `endTime` on that participant (alerting timed out)
3. `_conversation_times()` skips participants with no `connectedTime` (line 459: `if not connected: continue`), but the conversation update event still carries the ended participant data, producing `connected=False ended=True` in the state evaluation at line 550
4. The `elif call_end:` branch fires, but since the conversation was never in `active_conversations` (it was never activated because `connectedTime` was never set), `deactivate_conversation` is a no-op
5. Agent re-readies in Genesys → call re-routes → new agent participant created in alerting state (`connectedTime=null`)
6. Agent answers → new participant gets `connectedTime` set, `endTime=null`
7. **But**: the `v2.users.{agent_id}.conversations` event payload from Genesys may not immediately reflect the new participant's connected state, OR the notification system's event processing has already settled into the `connected=False ended=True` loop from the first participant's data, and never receives a clean `connected=True ended=False` event that would trigger `schedule_conversation`

The SQS/EventBridge system is unaffected because it has **no state machine** — it passively consumes all org-wide transcription events from the SQS queue regardless of conversation lifecycle state.

**Key architectural difference**: The notification system requires an explicit subscribe→receive→unsubscribe cycle per conversation, while EventBridge delivers all events to a single queue with no per-conversation subscription management.

**Why `recover_active_conversations()` doesn't help**: This function (line 405) polls `GET /api/v2/conversations` to find active conversations, but it **only runs once at WebSocket connect** during startup. There is no periodic recovery mechanism during the session. If a conversation enters a stuck state mid-session, there is no way to recover it.

**Fix needed**: The fix must be event-driven (not periodic polling) — 30–60s polling is too slow and would miss the start of re-routed calls. Additionally, periodic polling via `recover_active_conversations()` won't work because `GET /api/v2/conversations` returns nothing with `client_credentials` auth (see issue #8). Options:

1. **Re-activation on state change (recommended)**: When the WebSocket receives a `v2.users.{agent_id}.conversations` event where `_conversation_times` returns `(call_start, None)` — i.e., an active agent participant — call `schedule_conversation` regardless of whether the conversation was previously deactivated. The current code already does this at line 548 (`if call_start and not call_end: schedule_conversation`), so the real fix is in `_conversation_times`: ensure it correctly identifies the new active participant even when previous participants have ended. Debug logging should be added to dump the raw participant list when the function returns `(None, ...)` to diagnose exactly what Genesys sends for the re-routed participant.
2. **Remove the one-directional state assumption**: Allow re-subscription. When a conversation update event arrives and ANY agent participant (not just the first) shows `connectedTime` set with no `endTime`, treat it as active. The current `_conversation_times` logic does prefer active participants (lines 465–466), so the issue may be in what Genesys sends in the event payload, not in the parsing logic.
3. **Fix the API first (issue #8), then add fast periodic polling**: Once `recover_active_conversations()` uses an API that works with `client_credentials` (e.g., `POST /api/v2/analytics/conversations/details/query`), run it every 5–10 seconds as a safety net alongside the event-driven re-activation.

**Prevention**: Until fixed, if you miss a call and re-ready:
- Do NOT rely on restarting the notification system — `recover_active_conversations()` doesn't work (see issue #8)
- Accept that the notification system will miss that conversation and rely on EventBridge/SQS data

**Data action**: Conversation `7cf1beb6` has EventBridge data only. Notification system JSONL is empty/missing for this conversation.

---

## 8. `recover_active_conversations()` returns nothing — wrong API for `client_credentials` auth

**Symptom**: After restarting the notification system during an active conversation (attempting the workaround from issue #7), the recovery log shows `No in-progress conversations to recover` even though an agent is actively connected to a call.

```
[2026-03-20 20:07:22,504] INFO HTTP Request: GET https://api.mypurecloud.com/api/v2/conversations "HTTP/1.1 200 OK"
[2026-03-20 20:07:22,505] INFO No in-progress conversations to recover
```

**Root cause**: `recover_active_conversations()` calls `GET /api/v2/conversations` (line 419), which returns conversations **for the currently authenticated user**. The system authenticates with `client_credentials` OAuth grant (line 170), which has no user context — it's a service-to-service token. The API returns `200 OK` with an empty `entities` array because there's no "logged-in user" to query conversations for.

This means `recover_active_conversations()` has **never actually recovered a conversation**. The issue #2 symptom was mitigated entirely by the "Prevention" step (waiting for WebSocket to connect before taking calls), not by the recovery code.

**Fix applied**: Replaced `GET /api/v2/conversations` with `POST /api/v2/analytics/conversations/details/query` — a platform analytics endpoint that works with `client_credentials` auth because it queries org-wide data rather than "current user" data.

The new implementation:
- `build_analytics_query(agent_user_ids)` constructs the query body with a 24-hour interval and segment filters for all monitored agent user IDs (purpose=agent)
- `query_active_conversations(client, token, agent_user_ids)` executes the POST request with error handling
- `extract_active_from_analytics(conversations, agent_user_ids)` parses the analytics response format (which uses `conversationId`, `participants.sessions.segments` structure) and identifies conversations where a monitored agent has an active `interact` or `connected` segment with no `segmentEnd`
- Comprehensive debug logging dumps the raw analytics response so the response format can be verified on first live test

**Why not change credentials?** Switching from `client_credentials` to `authorization_code` grant was considered and rejected:
- `authorization_code` requires interactive user login (not automatable for a server process)
- Returns conversations for only ONE user — useless for monitoring 1,200 agents
- Requires stateful token refresh management
- Violates 12-factor principles (manual intervention, stateful sessions)
- `client_credentials` is Genesys's recommended auth pattern for server integrations

**Verification needed**: The analytics API response format may differ from what the parser expects. On first live test, check the DEBUG-level logs for the raw response and adjust `extract_active_from_analytics()` if needed. The function logs a warning if the response is empty or the format doesn't match expectations.

**Impact on issue #7**: With this fix applied, `recover_active_conversations()` can now be called periodically (not just at startup) to catch stuck conversations. However, this adds ongoing API load — see section 4d of `docs/analysis_key_points.md` for the 1,200-agent scaling implications.

---

## Scaling Note: Genesys Notifications API Limits

The Notifications API (WebSocket) has a **1,000 concurrent topic subscription limit** per channel (enterprise tier). Each active conversation requires one subscription (`v2.conversations.{id}.transcription`).

Our target is **1,200 agents**. At peak, this could exceed the 1,000-subscription limit. Options:
- Multiple WebSocket channels (at least 2) with agent sharding
- Wildcard topic subscriptions (if Genesys supports them)
- **EventBridge as primary delivery** — no per-conversation subscription needed. A single EB rule captures all transcription events org-wide. SQS scales horizontally.

If EventBridge latency is comparable to Notifications, EventBridge is the better production architecture at our scale.
