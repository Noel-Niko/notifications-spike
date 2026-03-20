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

## Scaling Note: Genesys Notifications API Limits

The Notifications API (WebSocket) has a **1,000 concurrent topic subscription limit** per channel (enterprise tier). Each active conversation requires one subscription (`v2.conversations.{id}.transcription`).

Our target is **1,200 agents**. At peak, this could exceed the 1,000-subscription limit. Options:
- Multiple WebSocket channels (at least 2) with agent sharding
- Wildcard topic subscriptions (if Genesys supports them)
- **EventBridge as primary delivery** — no per-conversation subscription needed. A single EB rule captures all transcription events org-wide. SQS scales horizontally.

If EventBridge latency is comparable to Notifications, EventBridge is the better production architecture at our scale.
