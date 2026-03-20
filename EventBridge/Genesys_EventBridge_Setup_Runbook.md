# Genesys Cloud EventBridge Setup Runbook

## Consuming `v2.conversations.{id}.transcription` Events

---

## Environment Details

| Item | Value |
|------|-------|
| AWS Account (EventBridge, SQS, CloudWatch) | `765425735388` — `cscda-sandbox` |
| AWS Account (CLI / SSO role) | `173078698674` — `cscdigitalassistan` |
| SSO Role ARN | `arn:aws:sts::173078698674:assumed-role/AWSReservedSSO_173078698674-cscdigitalassistan_6e3a3c6c123a8e57/xnxn040` |
| Admin CLI Profile | `765425735388_admin-role` (in `~/.aws/credentials`) |
| Region | `us-east-2` |
| Genesys Partner Event Bus | `aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB` |
| Event Bus ARN | `arn:aws:events:us-east-2:765425735388:event-bus/aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB` |
| Notification Topic | `v2.conversations.{id}.transcription` |
| SQS Queue URL | `https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test` |
| SQS Queue ARN | `arn:aws:sqs:us-east-2:765425735388:genesys-transcription-latency-test` |
| CW Log Group | `/aws/events/genesys/eventbridge/transcription-test` |

---

## Cross-Account Access Notes

Two AWS accounts are involved. The SSO role in 173078698674 is blocked by an Organization SCP from accessing resources in 765425735388 cross-account:

```
SCP: arn:aws:organizations::052343574110:policy/o-y3vn941x7j/service_control_policy/p-kfhxcsd9
```

**Workaround:** Use the admin-role credentials from 765425735388 directly. These were obtained via AWS IAM Identity Center ("Get credentials for admin-role") and stored as profile `765425735388_admin-role` in `~/.aws/credentials`.

All CLI commands in this runbook use `--profile 765425735388_admin-role` to run directly against cscda-sandbox.

---

## Prerequisites

Before setting up EventBridge rules, confirm:

- Genesys Cloud voice transcription is **enabled** (Admin → Speech and Text Analytics → Speech and Text Configuration)
- **Low Latency Transcription** is enabled in the same settings for ~3–5 second latency
- The topic `v2.conversations.{id}.transcription` is added to your EventBridge integration's **Topic Filtering** in Genesys Cloud Admin → Integrations → Amazon EventBridge Source → Configuration
- The partner event source is **Active** (not Pending) in the AWS EventBridge console
- The partner event source has been **associated with an event bus**

---

## Event Pattern (Used for All Rules)

All three targets use the same event pattern:

```json
{
  "source": [{"prefix": "aws.partner/genesys.com"}],
  "detail-type": ["v2.conversations.{id}.transcription"]
}
```

> **Note:** When creating rules via the console, EventBridge may auto-populate the source as the full bus name (e.g., `"source": ["aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB"]`). Either format works.

---

## Confirmed Event Structure (Captured from SQS)

This is the actual event schema captured from the live integration on 2026-03-19:

```json
{
  "version": "0",
  "id": "6efd5506-3fd6-09a1-5599-09ae48bd6dd8",
  "detail-type": "v2.conversations.{id}.transcription",
  "source": "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB",
  "account": "765425735388",
  "time": "2026-03-19T22:04:48Z",
  "region": "us-east-2",
  "resources": [],
  "detail": {
    "topicName": "v2.conversations.97b9dcb3-c182-4d1f-8123-76a4b5cf1f5a.transcription",
    "version": "2",
    "eventBody": {
      "eventTime": "2026-03-19T22:04:48.128Z",
      "organizationId": "cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721",
      "conversationId": "97b9dcb3-c182-4d1f-8123-76a4b5cf1f5a",
      "communicationId": "7dd98c4f-61ab-33a2-9bc3-18eefd1a0824",
      "sessionStartTimeMs": 1773957594383,
      "transcriptionStartTimeMs": 1773957594336,
      "transcripts": [
        {
          "utteranceId": "5b778cb0-3745-4243-b703-688f8b6597a0",
          "isFinal": true,
          "channel": "EXTERNAL",
          "alternatives": [
            {
              "confidence": 0.6584736842105261,
              "offsetMs": 278620,
              "durationMs": 12480,
              "transcript": "and the more's our neighbors see we had ten cissians were like more than every blood julies but well",
              "words": [
                {
                  "confidence": 0.917,
                  "offsetMs": 278620,
                  "durationMs": 80,
                  "word": "and"
                }
              ],
              "decoratedTranscript": "and the more's our neighbors see we had 10 cissians were like more than every blood julies but well",
              "decoratedWords": [
                {
                  "confidence": 0.92,
                  "offsetMs": 278620,
                  "durationMs": 80,
                  "word": "and"
                }
              ]
            }
          ],
          "engineProvider": "GENESYS",
          "engineId": "r2d2",
          "dialect": "en-US",
          "agentAssistEnabled": false,
          "voiceTranscriptionEnabled": true
        }
      ],
      "status": {
        "offsetMs": 278620,
        "status": "SESSION_ONGOING"
      }
    },
    "metadata": {
      "CorrelationId": "d1ab36e9-af51-4b3c-ab96-98d7349e75b4"
    },
    "timestamp": "2026-03-19T22:04:48.128Z"
  }
}
```

> **Note:** The `words` and `decoratedWords` arrays are truncated above. Each contains one entry per word with `confidence`, `offsetMs`, `durationMs`, and `word` fields.

### Key Fields Reference

| Field Path | Example Value | Description |
|------------|---------------|-------------|
| `time` | `2026-03-19T22:04:48Z` | When EventBridge received the event |
| `detail.eventBody.eventTime` | `2026-03-19T22:04:48.128Z` | Genesys event timestamp (ms precision) |
| `detail.eventBody.conversationId` | UUID | Genesys conversation ID |
| `detail.eventBody.communicationId` | UUID | Specific communication leg within the conversation |
| `detail.eventBody.sessionStartTimeMs` | `1773957594383` | Epoch ms — session start (use for latency calculations) |
| `detail.eventBody.transcriptionStartTimeMs` | `1773957594336` | Epoch ms — when transcription started |
| `detail.eventBody.transcripts[].utteranceId` | UUID | Unique per utterance — use for deduplication |
| `detail.eventBody.transcripts[].isFinal` | `true` / `false` | **Filter for final utterances only (`true`)** |
| `detail.eventBody.transcripts[].channel` | `EXTERNAL` / `INTERNAL` | `EXTERNAL` = customer, `INTERNAL` = agent/IVR |
| `detail.eventBody.transcripts[].dialect` | `en-US` | Language/dialect code |
| `detail.eventBody.transcripts[].engineProvider` | `GENESYS` | Transcription engine provider |
| `detail.eventBody.transcripts[].engineId` | `r2d2` | Genesys native transcription engine |
| `detail.eventBody.transcripts[].agentAssistEnabled` | `false` | Whether Agent Assist is active |
| `detail.eventBody.transcripts[].voiceTranscriptionEnabled` | `true` | Whether voice transcription is active |
| `detail.eventBody.transcripts[].alternatives[].confidence` | `0.658` | Overall utterance confidence (0.0–1.0) |
| `detail.eventBody.transcripts[].alternatives[].transcript` | raw text | Raw transcribed text ("ten" as word) |
| `detail.eventBody.transcripts[].alternatives[].decoratedTranscript` | normalized text | Normalized text ("10" as digit) — **use this for LLM input** |
| `detail.eventBody.transcripts[].alternatives[].offsetMs` | `278620` | Offset from start of communication (ms) |
| `detail.eventBody.transcripts[].alternatives[].durationMs` | `12480` | Duration of the utterance (ms) |
| `detail.eventBody.transcripts[].alternatives[].words[]` | array | Per-word confidence, timing, and text |
| `detail.eventBody.transcripts[].alternatives[].decoratedWords[]` | array | Per-word normalized version (digits, etc.) |
| `detail.eventBody.status.status` | `SESSION_ONGOING` / `SESSION_ENDED` | Session lifecycle state |
| `detail.eventBody.status.offsetMs` | `278620` | Offset at which this status was reported |
| `detail.metadata.CorrelationId` | UUID | Correlation ID for tracing |

### Filtering for Final Utterances

For LLM summary pipelines, filter on:
- `isFinal == true` — only completed utterances (not partials being refined)
- Use `decoratedTranscript` over `transcript` — numbers are normalized to digits
- `status.status == "SESSION_ENDED"` indicates the call has finished (useful for triggering end-of-call processing)

---

## Target 1: CloudWatch Logs (Quick Visual Validation)

Use this to see raw event JSON and validate the pipeline is working.

### Console Steps (765425735388 — admin)

**Create the log group:**

1. Go to **CloudWatch** → **Log groups** → **Create log group**
2. Log group name: `/aws/events/genesys/eventbridge/transcription-test`
3. Retention: 1 day (temporary test)
4. Click **Create**

**Create the EventBridge rule:**

1. Go to **Amazon EventBridge** → **Rules** → **Create rule**
2. Name: `genesys-transcription-to-cwl`
3. Event bus: select `aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB`
4. Click **Next**
5. Event source: **Other**
6. Creation method: **Custom pattern (JSON editor)**
7. Paste the event pattern
8. Click **Next**
9. Target type: **AWS service**
10. Select a target: **CloudWatch log group**
11. Log Group: select `/aws/events/genesys/eventbridge/transcription-test`
12. Click **Next** → skip Tags → **Next** → Review → **Create rule**

> The console automatically creates a resource policy allowing EventBridge to write to the log group. If events don't arrive, add it manually (see CLI steps).

### CLI Steps (use `--profile 765425735388_admin-role`)

```bash
# Create log group
aws logs create-log-group \
  --log-group-name /aws/events/genesys/eventbridge/transcription-test \
  --region us-east-2 \
  --profile 765425735388_admin-role

# Add resource policy (so EventBridge can write to it)
aws logs put-resource-policy \
  --policy-name eventbridge-to-cwl-transcription \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"Service": "events.amazonaws.com"},
      "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:us-east-2:765425735388:log-group:/aws/events/genesys/eventbridge/transcription-test:*"
    }]
  }' \
  --region us-east-2 \
  --profile 765425735388_admin-role

# Create the rule
aws events put-rule \
  --name genesys-transcription-to-cwl \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --event-pattern '{
    "source": [{"prefix": "aws.partner/genesys.com"}],
    "detail-type": ["v2.conversations.{id}.transcription"]
  }' \
  --state ENABLED \
  --region us-east-2 \
  --profile 765425735388_admin-role

# Set the target
aws events put-targets \
  --rule genesys-transcription-to-cwl \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --targets '[{
    "Id": "cwl-target",
    "Arn": "arn:aws:logs:us-east-2:765425735388:log-group:/aws/events/genesys/eventbridge/transcription-test"
  }]' \
  --region us-east-2 \
  --profile 765425735388_admin-role
```

### How to View Events

**Console (765425735388 — admin):**

1. Go to **CloudWatch** → **Log groups** → click the log group
2. Use **Live Tail** to watch events in real time

**Terminal:**

```bash
aws logs tail /aws/events/genesys/eventbridge/transcription-test \
  --follow --format short \
  --region us-east-2 \
  --profile 765425735388_admin-role
```

---

## Target 2: SQS Queue (Local Script Polling)

Use this for programmatic consumption of events from a local machine.

### Console Steps (765425735388 — admin)

**Create the queue:**

1. Go to **Amazon SQS** → **Create queue**
2. Type: **Standard**
3. Name: `genesys-transcription-latency-test`
4. Configuration:
   - Receive message wait time: **20 seconds**
   - Message retention period: **1 hour**
5. Click **Create queue**
6. Copy the **Queue URL** and **Queue ARN**

**Set the access policy:**

1. On the queue detail page → **Access policy** tab → **Edit**
2. Switch to the JSON editor and paste:

```json
{
  "Version": "2012-10-17",
  "Id": "__default_policy_ID",
  "Statement": [
    {
      "Sid": "__owner_statement",
      "Effect": "Allow",
      "Principal": {
        "AWS": "765425735388"
      },
      "Action": "SQS:*",
      "Resource": "arn:aws:sqs:us-east-2:765425735388:genesys-transcription-latency-test"
    },
    {
      "Sid": "eventbridge_delivery",
      "Effect": "Allow",
      "Principal": {
        "Service": "events.amazonaws.com"
      },
      "Action": "sqs:SendMessage",
      "Resource": "arn:aws:sqs:us-east-2:765425735388:genesys-transcription-latency-test"
    },
    {
      "Sid": "__receiver_statement",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:sts::173078698674:assumed-role/AWSReservedSSO_173078698674-cscdigitalassistan_6e3a3c6c123a8e57/xnxn040"
      },
      "Action": [
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility",
        "sqs:GetQueueAttributes"
      ],
      "Resource": "arn:aws:sqs:us-east-2:765425735388:genesys-transcription-latency-test"
    }
  ]
}
```

3. Click **Save**

> **Note:** The `__receiver_statement` for the SSO role is blocked by the Organization SCP. Use `--profile 765425735388_admin-role` instead for CLI access.

**Create the EventBridge rule:**

1. Go to **EventBridge** → **Rules** → **Create rule**
2. Name: `genesys-transcription-to-sqs`
3. Event bus: select the Genesys partner bus
4. Click **Next**
5. Event source: **Other** → Custom pattern (JSON editor) → paste event pattern
6. Click **Next**
7. Target type: **AWS service**
8. Select a target: **SQS queue**
9. Queue: select `genesys-transcription-latency-test`
10. **Execution role:** not required for SQS — skip past this
11. Click **Next** → Tags → **Next** → Review → **Create rule**

### CLI Steps (use `--profile 765425735388_admin-role`)

```bash
# Create the queue
aws sqs create-queue \
  --queue-name genesys-transcription-latency-test \
  --attributes '{
    "ReceiveMessageWaitTimeSeconds": "20",
    "MessageRetentionPeriod": "3600"
  }' \
  --region us-east-2 \
  --profile 765425735388_admin-role

# Create the rule
aws events put-rule \
  --name genesys-transcription-to-sqs \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --event-pattern '{
    "source": [{"prefix": "aws.partner/genesys.com"}],
    "detail-type": ["v2.conversations.{id}.transcription"]
  }' \
  --state ENABLED \
  --region us-east-2 \
  --profile 765425735388_admin-role

# Add the SQS target
aws events put-targets \
  --rule genesys-transcription-to-sqs \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --targets '[{
    "Id": "sqs-target",
    "Arn": "arn:aws:sqs:us-east-2:765425735388:genesys-transcription-latency-test"
  }]' \
  --region us-east-2 \
  --profile 765425735388_admin-role
```

### How to Consume Events

**Console (765425735388 — admin):**

1. Go to **SQS** → click the queue → **Send and receive messages** → **Poll for messages**
2. Click any message to see the full JSON body

**Terminal — single message (pretty-printed):**

```bash
aws sqs receive-message \
  --queue-url https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test \
  --max-number-of-messages 1 \
  --wait-time-seconds 20 \
  --region us-east-2 \
  --profile 765425735388_admin-role \
  | jq '.Messages[0].Body | fromjson'
```

**Terminal — batch of messages (raw):**

```bash
aws sqs receive-message \
  --queue-url https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test \
  --max-number-of-messages 10 \
  --wait-time-seconds 20 \
  --region us-east-2 \
  --profile 765425735388_admin-role
```

**Terminal — continuous polling loop (compact output, final utterances only):**

```bash
while true; do
  aws sqs receive-message \
    --queue-url https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test \
    --max-number-of-messages 10 \
    --wait-time-seconds 20 \
    --region us-east-2 \
    --profile 765425735388_admin-role \
    | jq -c '.Messages[]?.Body | fromjson | .detail.eventBody | {
        conversationId,
        utteranceId: .transcripts[0].utteranceId,
        isFinal: .transcripts[0].isFinal,
        channel: .transcripts[0].channel,
        text: .transcripts[0].alternatives[0].decoratedTranscript,
        confidence: .transcripts[0].alternatives[0].confidence,
        offsetMs: .transcripts[0].alternatives[0].offsetMs,
        durationMs: .transcripts[0].alternatives[0].durationMs,
        sessionStatus: .status.status
      }'
done
```

**Terminal — purge all messages from queue (start fresh):**

```bash
aws sqs purge-queue \
  --queue-url https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test \
  --region us-east-2 \
  --profile 765425735388_admin-role
```

**Terminal — check queue depth:**

```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
  --region us-east-2 \
  --profile 765425735388_admin-role
```

**Terminal — delete a single message after processing:**

```bash
aws sqs delete-message \
  --queue-url https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test \
  --receipt-handle "YOUR_RECEIPT_HANDLE" \
  --region us-east-2 \
  --profile 765425735388_admin-role
```

### Python SQS Consumer (Local)

For integration with a local LLM, use this script to poll SQS and process final utterances:

```python
import boto3
import json
from datetime import datetime, timezone

session = boto3.Session(profile_name='765425735388_admin-role', region_name='us-east-2')
sqs = session.client('sqs')
queue_url = 'https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test'

print("Polling for transcription events...")
while True:
    resp = sqs.receive_message(
        QueueUrl=queue_url,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=20
    )
    for msg in resp.get('Messages', []):
        received_at = datetime.now(timezone.utc)
        body = json.loads(msg['Body'])

        eb_time = body.get('time', '')
        detail = body.get('detail', {})
        event_body = detail.get('eventBody', {})
        conversation_id = event_body.get('conversationId', 'unknown')
        communication_id = event_body.get('communicationId', 'unknown')
        session_status = event_body.get('status', {}).get('status', 'unknown')
        transcripts = event_body.get('transcripts', [])

        for t in transcripts:
            utterance_id = t.get('utteranceId', 'unknown')
            is_final = t.get('isFinal', False)
            channel = t.get('channel', '?')
            dialect = t.get('dialect', '?')

            for alt in t.get('alternatives', []):
                text = alt.get('decoratedTranscript', alt.get('transcript', ''))
                confidence = alt.get('confidence', 0)
                offset_ms = alt.get('offsetMs', 0)
                duration_ms = alt.get('durationMs', 0)

                print(f"\n[RECEIVED {received_at.isoformat()}]")
                print(f"  EB time:      {eb_time}")
                print(f"  Conv:         {conversation_id}")
                print(f"  Comm:         {communication_id}")
                print(f"  Utterance:    {utterance_id}")
                print(f"  isFinal:      {is_final}")
                print(f"  Channel:      {channel}")
                print(f"  Dialect:      {dialect}")
                print(f"  Text:         \"{text}\"")
                print(f"  Confidence:   {confidence}")
                print(f"  Offset:       {offset_ms}ms")
                print(f"  Duration:     {duration_ms}ms")
                print(f"  Session:      {session_status}")

                # === INTEGRATION POINT ===
                # Filter for final utterances and send to your local LLM:
                # if is_final:
                #     send_to_llm(conversation_id, channel, text, confidence)

        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg['ReceiptHandle'])
```

---

## Target 3: API Destination + ngrok (Direct Push to Local Machine)

This bypasses the cross-account SCP issue entirely. EventBridge pushes events as HTTP POSTs through ngrok directly to your local machine. No SQS, no Lambda, no cross-account access needed.

### Local Machine Setup

**Install ngrok:**

```bash
# Mac
brew install ngrok

# Configure auth token (free account at https://ngrok.com)
ngrok config add-authtoken YOUR_NGROK_AUTH_TOKEN
```

**Create `receiver.py`:**

```python
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
import json

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        received_at = datetime.now(timezone.utc)

        try:
            event = json.loads(body)
            eb_time = event.get('time', '')
            detail = event.get('detail', {})
            event_body = detail.get('eventBody', {})
            conversation_id = event_body.get('conversationId', 'unknown')
            communication_id = event_body.get('communicationId', 'unknown')
            session_status = event_body.get('status', {}).get('status', 'unknown')
            transcripts = event_body.get('transcripts', [])

            for t in transcripts:
                utterance_id = t.get('utteranceId', 'unknown')
                is_final = t.get('isFinal', False)
                channel = t.get('channel', '?')
                dialect = t.get('dialect', '?')

                for alt in t.get('alternatives', []):
                    text = alt.get('decoratedTranscript', alt.get('transcript', ''))
                    confidence = alt.get('confidence', 0)
                    offset_ms = alt.get('offsetMs', 0)
                    duration_ms = alt.get('durationMs', 0)

                    print(f"\n[RECEIVED {received_at.isoformat()}]")
                    print(f"  EB time:      {eb_time}")
                    print(f"  Conv:         {conversation_id}")
                    print(f"  Comm:         {communication_id}")
                    print(f"  Utterance:    {utterance_id}")
                    print(f"  isFinal:      {is_final}")
                    print(f"  Channel:      {channel}")
                    print(f"  Dialect:      {dialect}")
                    print(f"  Text:         \"{text}\"")
                    print(f"  Confidence:   {confidence}")
                    print(f"  Offset:       {offset_ms}ms")
                    print(f"  Duration:     {duration_ms}ms")
                    print(f"  Session:      {session_status}")

                    # === INTEGRATION POINT ===
                    # if is_final:
                    #     send_to_llm(conversation_id, channel, text, confidence)

        except Exception as e:
            print(f"\n[RAW EVENT {received_at.isoformat()}]")
            print(body.decode('utf-8', errors='replace'))

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

    def log_message(self, format, *args):
        pass

print("Listening on port 8080...")
HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
```

**Start both (two terminal windows):**

Terminal 1:
```bash
python receiver.py
```

Terminal 2:
```bash
ngrok http 8080
```

Copy the **Forwarding** URL from ngrok (e.g., `https://willful-reynalda-stoutly.ngrok-free.dev`).

> **Tip:** For a stable URL that survives restarts, use: `ngrok http 8080 --url=your-chosen-name.ngrok-free.app`

### Console Steps (765425735388 — admin)

**Create the API Destination:**

1. Go to **EventBridge** → **API destinations** (left menu under Integration) → **Create API destination**
2. Name: `ngrok-local-receiver`
3. API destination endpoint: paste your ngrok HTTPS URL
4. HTTP method: **POST**
5. Connection type: **Create a new connection**
6. Connection name: `ngrok-connection`
7. Authorization type: **API Key**
8. API key name: `x-api-key`
9. Value: `test123`
10. Click **Create**

**Create the EventBridge rule:**

1. Go to **EventBridge** → **Rules** → **Create rule**
2. Name: `genesys-transcription-to-local`
3. Event bus: select the Genesys partner bus
4. Click **Next**
5. Event source: **Other** → Custom pattern (JSON editor) → paste event pattern
6. Click **Next**
7. Target type: **EventBridge API destination**
8. API destination: select `ngrok-local-receiver`
9. Execution role: **Create a new role for this specific resource**
10. Click **Next** → Tags → **Next** → Review → **Create rule**

### CLI Steps (use `--profile 765425735388_admin-role`)

```bash
# Create the connection
aws events create-connection \
  --name ngrok-connection \
  --authorization-type API_KEY \
  --auth-parameters '{"ApiKeyAuthParameters": {"ApiKeyName": "x-api-key", "ApiKeyValue": "test123"}}' \
  --region us-east-2 \
  --profile 765425735388_admin-role

# Create the API destination (replace YOUR_NGROK_URL)
aws events create-api-destination \
  --name ngrok-local-receiver \
  --connection-arn "arn:aws:events:us-east-2:765425735388:connection/ngrok-connection" \
  --invocation-endpoint "YOUR_NGROK_URL" \
  --http-method POST \
  --region us-east-2 \
  --profile 765425735388_admin-role

# Create the rule
aws events put-rule \
  --name genesys-transcription-to-local \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --event-pattern '{
    "source": [{"prefix": "aws.partner/genesys.com"}],
    "detail-type": ["v2.conversations.{id}.transcription"]
  }' \
  --state ENABLED \
  --region us-east-2 \
  --profile 765425735388_admin-role

# Add the API destination target (replace the API destination ARN and RoleArn)
aws events put-targets \
  --rule genesys-transcription-to-local \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --targets '[{
    "Id": "api-target",
    "Arn": "arn:aws:events:us-east-2:765425735388:api-destination/ngrok-local-receiver",
    "RoleArn": "arn:aws:iam::765425735388:role/Amazon_EventBridge_Invoke_Api_Destination"
  }]' \
  --region us-east-2 \
  --profile 765425735388_admin-role
```

> **Note:** The `RoleArn` for the API destination target is auto-created when using the console. If using CLI, you may need to create it manually or use the ARN of the role the console created.

**Update API Destination endpoint (when ngrok URL changes):**

```bash
aws events update-api-destination \
  --name ngrok-local-receiver \
  --invocation-endpoint "YOUR_NEW_NGROK_URL" \
  --region us-east-2 \
  --profile 765425735388_admin-role
```

### Verified Output

```
[RECEIVED 2026-03-19T21:59:01.842644+00:00]
  EB time:      2026-03-19T21:59:01Z
  Conv:         974ed10b-6764-4e45-8657-334e8f95ebad
  Utterance:    ...
  isFinal:      True
  Channel:      EXTERNAL
  Text:         "same thing isn't really real"
  Confidence:   0.9251999999999999
  Session:      SESSION_ONGOING
```

Latency from EventBridge to local machine: **under 1 second**.

### Important Notes

- Every time ngrok restarts, the URL changes. Update the API Destination endpoint or use a stable ngrok domain.
- Delete the rule and API Destination when testing is complete so EventBridge isn't pushing to a dead endpoint.

---

## Cleanup

When testing is complete, remove all temporary resources.

### Console (765425735388 — admin)

**EventBridge Rules** (delete targets first via the rule detail page, then delete the rule):

- `genesys-transcription-to-cwl`
- `genesys-transcription-to-sqs`
- `genesys-transcription-to-local`

**EventBridge API Destination & Connection:**

- `ngrok-local-receiver`
- `ngrok-connection`

**SQS Queue:**

- `genesys-transcription-latency-test`

**CloudWatch Log Group:**

- `/aws/events/genesys/eventbridge/transcription-test`

### CLI (use `--profile 765425735388_admin-role`)

```bash
# --- CloudWatch rule ---
aws events remove-targets --rule genesys-transcription-to-cwl \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --ids cwl-target \
  --region us-east-2 \
  --profile 765425735388_admin-role

aws events delete-rule --name genesys-transcription-to-cwl \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --region us-east-2 \
  --profile 765425735388_admin-role

# --- SQS rule ---
aws events remove-targets --rule genesys-transcription-to-sqs \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --ids sqs-target \
  --region us-east-2 \
  --profile 765425735388_admin-role

aws events delete-rule --name genesys-transcription-to-sqs \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --region us-east-2 \
  --profile 765425735388_admin-role

# --- API Destination rule ---
aws events remove-targets --rule genesys-transcription-to-local \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --ids api-target \
  --region us-east-2 \
  --profile 765425735388_admin-role

aws events delete-rule --name genesys-transcription-to-local \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --region us-east-2 \
  --profile 765425735388_admin-role

# --- API Destination & Connection ---
aws events delete-api-destination \
  --name ngrok-local-receiver \
  --region us-east-2 \
  --profile 765425735388_admin-role

aws events delete-connection \
  --name ngrok-connection \
  --region us-east-2 \
  --profile 765425735388_admin-role

# --- SQS queue ---
aws sqs delete-queue \
  --queue-url https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test \
  --region us-east-2 \
  --profile 765425735388_admin-role

# --- CloudWatch log group ---
aws logs delete-log-group \
  --log-group-name /aws/events/genesys/eventbridge/transcription-test \
  --region us-east-2 \
  --profile 765425735388_admin-role
```

---

## Request to MLOps Team

Hello Team,

I'm running a latency spike comparing the Genesys Cloud EventBridge integration against the WebSocket Notifications API for consuming real-time voice transcription events (`v2.conversations.{id}.transcription`).

The EventBridge integration is fully working in account **765425735388** (`cscda-sandbox`). I've confirmed events are flowing into both CloudWatch Logs and an SQS queue (`genesys-transcription-latency-test`). However, my SSO role in **173078698674** is blocked by an Organization SCP when trying to access resources in 765425735388 cross-account.

**The blocker:**

```
An error occurred (AccessDenied) when calling the ReceiveMessage operation:
User: arn:aws:sts::173078698674:assumed-role/AWSReservedSSO_173078698674-cscdigitalassistan_6e3a3c6c123a8e57/xnxn040
is not authorized to perform: sqs:receivemessage on resource:
arn:aws:sqs:us-east-2:765425735388:genesys-transcription-latency-test
with an explicit deny in a service control policy:
arn:aws:organizations::052343574110:policy/o-y3vn941x7j/service_control_policy/p-kfhxcsd9
```

The same SCP also blocks `logs:CreateLogGroup` and `logs:FilterLogEvents` cross-account.

The SQS resource-based policy already grants my role the necessary actions. The deny is from the SCP, not a missing permission.

**Current workaround:** I obtained admin-role credentials directly from 765425735388 via IAM Identity Center and use them as an AWS CLI profile (`765425735388_admin-role`). This works but the credentials are temporary.

**What I need (either option works):**

1. An SCP exception allowing my SSO role in 173078698674 to perform `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:ChangeMessageVisibility`, `sqs:GetQueueAttributes`, `logs:FilterLogEvents`, and `logs:CreateLogGroup` cross-account on resources in 765425735388 — or —
2. A persistent CLI-capable role in 765425735388 that I can assume from 173078698674

This is for a temporary latency test — happy to have the access scoped and time-limited.

Thanks!
