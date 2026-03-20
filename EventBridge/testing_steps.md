# EventBridge vs Notifications — Complete Test Run Steps

All commands to run a clean latency comparison test with all 3 systems capturing in parallel.

For BlackHole audio routing setup (one-time), see `docs/manual_test_directions.md`.
For EventBridge infrastructure details, see `Genesys_EventBridge_Setup_Runbook.md`.

---

## Prerequisites

- AWS SSO login active for the sandbox account:
  ```bash
  aws sso login --profile 765425735388_admin-role
  ```
  > **Must use `765425735388_admin-role`** — the SSO role in account 173078698674 is blocked by Organization SCP `p-kfhxcsd9`.

- Dependencies installed:
  ```bash
  cd ~/PycharmProjects/notifications-spike
  uv sync
  ```

- `.env` file configured with Genesys credentials (`CLIENT_ID`, `CLIENT_SECRET`, etc.)

- BlackHole Multi-Output Device set as macOS system output (see `docs/manual_test_directions.md`)
SEE README.ME IN 
---

## 1. Clean Up Previous Data

### Purge the SQS queue

```bash
aws sqs purge-queue \
  --queue-url https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test \
  --region us-east-2 \
  --profile 765425735388_admin-role
```

> Purge takes up to 60 seconds. Verify with:

```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test \
  --attribute-names ApproximateNumberOfMessages \
  --region us-east-2 \
  --profile 765425735388_admin-role
```

Expected: `"ApproximateNumberOfMessages": "0"`

### Delete previous result files (optional)

```bash
rm -f EventBridge/conversation_events/*.jsonl
rm -f conversation_events/*.jsonl
rm -f ~/PycharmProjects/poc-deepgram/results/nova-3_*.json
```

---
## 2. Start All 3 Systems
All 3 must be running **before** you take the first call.

### Terminal 1 — notifications-spike (Genesys WebSocket)

```bash
cd ~/PycharmProjects/notifications-spike
uv run uvicorn main:app --host 0.0.0.0 --port 8765
```

Wait for:
```
WebSocket connected (agents=N, max_concurrent_conversations=10)
```

### Terminal 2 — SQS consumer (EventBridge)

```bash
cd ~/PycharmProjects/notifications-spike
SQS_QUEUE_URL="https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test" \
AWS_PROFILE="765425735388_admin-role" \
AWS_REGION="us-east-2" \
uv run python -m scripts.sqs_consumer
```

Wait for:
```
[...] INFO Polling SQS queue: https://sqs.us-east-2.amazonaws.com/765425735388/...
[...] INFO Saving events to: EventBridge/conversation_events
```

### Terminal 3 — poc-deepgram (ground truth audio)

```bash
cd ~/PycharmProjects/poc-deepgram
uv run uvicorn poc_deepgram.app:create_app --factory --host 0.0.0.0 --port 8766
```

Then open **http://localhost:8766** in a browser, select **BlackHole 2ch** as audio input, and click **Start**.

---

## 3. Run the Test Calls

1. Open **Chrome** and navigate to `apps.mypurecloud.com`
2. Answer each Genesys call — play the recording, wait for it to finish, end the call
3. All 3 systems capture in parallel automatically:
   - **notifications-spike** → `conversation_events/<id>.jsonl`
   - **SQS consumer** → `EventBridge/conversation_events/<id>.jsonl`
   - **poc-deepgram** → `~/PycharmProjects/poc-deepgram/results/<session>.json`
4. In poc-deepgram browser UI, click **Stop** after each call, then **Start** before the next

> **Tip**: 2+ minutes of active conversation per call gives enough utterances for meaningful statistics.

---

## 4. Verify All Data Was Captured

After the calls, check each system captured the same conversations:

```bash
# Notifications files
ls -lt conversation_events/*.jsonl | head -8

# EventBridge files
ls -lt EventBridge/conversation_events/*.jsonl | head -8

# Deepgram sessions
ls -lt ~/PycharmProjects/poc-deepgram/results/nova-3_*.json | head -8
```

Cross-check conversation IDs match between Notifications and EventBridge:

```bash
diff <(ls conversation_events/*.jsonl | xargs -I{} basename {} | sort) \
     <(ls EventBridge/conversation_events/*.jsonl | xargs -I{} basename {} | sort)
```

If a conversation is missing from one path, check that terminal's logs for errors.

---

## 5. Run the Analysis Notebook

```bash
cd ~/PycharmProjects/notifications-spike/notebooks
uv run jupyter notebook cross_system_latency-02-EB-RESULTS.ipynb
```

Run all cells. The notebook auto-matches files from all 3 sources by conversation ID and time overlap.

---

## SQS Consumer Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SQS_QUEUE_URL` | *(required)* | Full SQS queue URL |
| `AWS_PROFILE` | `765425735388_admin-role` | AWS credentials profile |
| `AWS_REGION` | `us-east-2` | AWS region for SQS client |
| `EB_EVENT_DIR` | `EventBridge/conversation_events` | Output directory for JSONL files |

### Output Format

Each JSONL line contains:

```json
{
  "conversationId": "97b9dcb3-...",
  "receivedAt": 1773957600.123,
  "sqsSentTimestamp": 1773957599800,
  "ebTime": "2026-03-19T22:04:48Z",
  "genesysEventTime": "2026-03-19T22:04:48.128Z",
  "sessionStartTimeMs": 1773957594383,
  "transcripts": [{ ... }],
  "rawEvent": { ... }
}
```

### Peek at SQS Without Consuming (debugging)

```bash
aws sqs receive-message \
  --queue-url https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test \
  --max-number-of-messages 1 \
  --visibility-timeout 0 \
  --attribute-names SentTimestamp \
  --region us-east-2 \
  --profile 765425735388_admin-role \
  | jq '.Messages[0].Body | fromjson'
```

Check queue depth:

```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
  --region us-east-2 \
  --profile 765425735388_admin-role
```

---

## Troubleshooting

### `NoRegionError: You must specify a region`

Set `AWS_REGION=us-east-2` in the environment. The `765425735388_admin-role` profile may not have a default region configured in `~/.aws/config`.

### `NoCredentialError` or `ExpiredToken`

Re-authenticate:
```bash
aws sso login --profile 765425735388_admin-role
```

### Consumer runs but no messages arrive

- Confirm EventBridge rule is active in the AWS console (account `765425735388`, region `us-east-2`)
- Confirm a Genesys call is in progress with transcription enabled
- Check CloudWatch Logs: `/aws/events/genesys/eventbridge/transcription-test`

### Conversation missing from one path

- **Missing from Notifications**: Check notifications-spike terminal — confirm `Subscribed to transcripts for conversation` appears. Verify the agent is in `agents.txt`.
- **Missing from EventBridge**: Check SQS consumer terminal for errors. Verify SQS queue depth is changing during calls.
- **Missing from Deepgram**: Verify BlackHole 2ch is selected in the browser dropdown and the status shows Connected (green).

### `KeyError` in parse_sqs_message

Status-only events (no `transcripts` key) are automatically skipped. If you see other unexpected formats, peek at the raw message with the debug command above.
