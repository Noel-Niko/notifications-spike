# Genesys Cloud EventBridge Setup Runbook

## Consuming `v2.conversations.{id}.transcription` Events

---

## Environment Details

| Item | Value |
|------|-------|
| AWS Account (EventBridge, SQS, CloudWatch) | `765425735388` — `cscda-sandbox` |
| AWS Account (CLI / SSO role) | `173078698674` — `cscdigitalassistan` |
| SSO Role ARN | `arn:aws:sts::173078698674:assumed-role/AWSReservedSSO_173078698674-cscdigitalassistan_6e3a3c6c123a8e57/xnxn040` |
| Region | `us-east-2` |
| Genesys Partner Event Bus | `aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB` |
| Event Bus ARN | `arn:aws:events:us-east-2:765425735388:event-bus/aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB` |
| Notification Topic | `v2.conversations.{id}.transcription` |

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

> **Note:** When creating rules via the console, EventBridge may auto-populate the source as the full bus name. Either format works.

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
7. Paste the event pattern above
8. Click **Next**
9. Target type: **AWS service**
10. Select a target: **CloudWatch log group**
11. Log Group: select `/aws/events/genesys/eventbridge/transcription-test`
12. Click **Next** → skip Tags → **Next** → Review → **Create rule**

**Add the resource policy** (so EventBridge can write to the log group):

> This is typically created automatically when you select a CloudWatch log group as a target in the console. If events are not arriving, add it manually via the CLI (requires permissions):

```bash
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
  }'
```

### CLI Steps

```bash
# Create log group
aws logs create-log-group \
  --log-group-name /aws/events/genesys/eventbridge/transcription-test \
  --region us-east-2

# Create the rule
aws events put-rule \
  --name genesys-transcription-to-cwl \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --event-pattern '{
    "source": [{"prefix": "aws.partner/genesys.com"}],
    "detail-type": ["v2.conversations.{id}.transcription"]
  }' \
  --state ENABLED \
  --region us-east-2

# Set the target
aws events put-targets \
  --rule genesys-transcription-to-cwl \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --targets '[{
    "Id": "cwl-target",
    "Arn": "arn:aws:logs:us-east-2:765425735388:log-group:/aws/events/genesys/eventbridge/transcription-test"
  }]' \
  --region us-east-2
```

### How to View Events

**Console (works with admin access in 765425735388):**

1. Go to **CloudWatch** → **Log groups** → click the log group
2. Use **Live Tail** to watch events in real time

**Terminal (requires `logs:FilterLogEvents` permission):**

```bash
aws logs tail /aws/events/genesys/eventbridge/transcription-test --follow --format short --region us-east-2
```

> **Known blocker:** The SSO role in 173078698674 is denied by SCP. Use the console Live Tail instead.

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

### CLI Steps

```bash
# Create the queue
aws sqs create-queue \
  --queue-name genesys-transcription-latency-test \
  --attributes '{
    "ReceiveMessageWaitTimeSeconds": "20",
    "MessageRetentionPeriod": "3600"
  }' \
  --region us-east-2

# Create the rule
aws events put-rule \
  --name genesys-transcription-to-sqs \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --event-pattern '{
    "source": [{"prefix": "aws.partner/genesys.com"}],
    "detail-type": ["v2.conversations.{id}.transcription"]
  }' \
  --state ENABLED \
  --region us-east-2

# Add the SQS target
aws events put-targets \
  --rule genesys-transcription-to-sqs \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --targets '[{
    "Id": "sqs-target",
    "Arn": "arn:aws:sqs:us-east-2:765425735388:genesys-transcription-latency-test"
  }]' \
  --region us-east-2
```

### How to Consume Events

**Console (765425735388 — admin):**

1. Go to **SQS** → click the queue → **Send and receive messages** → **Poll for messages**

**Terminal (requires cross-account SQS access):**

```bash
aws sqs receive-message \
  --queue-url https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test \
  --max-number-of-messages 10 \
  --wait-time-seconds 20 \
  --region us-east-2
```

> **Known blocker:** Cross-account SQS access from 173078698674 is denied by an Organization SCP (`arn:aws:organizations::052343574110:policy/o-y3vn941x7j/service_control_policy/p-kfhxcsd9`). The resource-based policy on the queue is correct, but the SCP explicitly denies the call. See the MLOps team request at the end of this document.

---

## Target 3: API Destination + ngrok (Direct Push to Local Machine)

This bypasses the cross-account SCP issue entirely. EventBridge pushes events as HTTP POSTs through ngrok directly to your local machine. No SQS, no Lambda.

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
            transcripts = event_body.get('transcripts', [])

            for t in transcripts:
                channel = t.get('channel', '?')
                for alt in t.get('alternatives', []):
                    text = alt.get('transcript', '')
                    confidence = alt.get('confidence', 0)
                    print(f"\n[RECEIVED {received_at.isoformat()}]")
                    print(f"  EB time:    {eb_time}")
                    print(f"  Conv:       {conversation_id}")
                    print(f"  Channel:    {channel}")
                    print(f"  Text:       \"{text}\"")
                    print(f"  Confidence: {confidence}")
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
3. API destination endpoint: paste your ngrok HTTPS URL (e.g., `https://willful-reynalda-stoutly.ngrok-free.dev`)
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

### Verified Output

```
[RECEIVED 2026-03-19T21:59:01.842644+00:00]
  EB time:    2026-03-19T21:59:01Z
  Conv:       974ed10b-6764-4e45-8657-334e8f95ebad
  Channel:    EXTERNAL
  Text:       "same thing isn't really real"
  Confidence: 0.9251999999999999
```

Latency from EventBridge to local machine: **under 1 second**.

### Important Notes

- Every time ngrok restarts, the URL changes. Update the API Destination endpoint in the console, or use a stable ngrok domain.
- Delete the rule and API Destination when testing is complete so EventBridge isn't pushing to a dead endpoint.

---

## Sample Event Structure

The transcription events arrive in the following format:

```json
{
  "version": "0",
  "id": "abc123-...",
  "source": "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB",
  "detail-type": "v2.conversations.{id}.transcription",
  "account": "765425735388",
  "region": "us-east-2",
  "time": "2026-03-19T21:59:01Z",
  "resources": [],
  "detail": {
    "topicName": "v2.conversations.<conversation-id>.transcription",
    "version": "2",
    "eventBody": {
      "conversationId": "974ed10b-6764-4e45-8657-334e8f95ebad",
      "communicationId": "x1y2z3-...",
      "transcripts": [
        {
          "channel": "EXTERNAL",
          "dialect": "en-US",
          "alternatives": [
            {
              "confidence": 0.925,
              "offsetMs": 1200,
              "durationMs": 3500,
              "transcript": "same thing isn't really real"
            }
          ]
        }
      ]
    },
    "metadata": {
      "CorrelationId": "..."
    }
  }
}
```

Key fields:

| Field | Description |
|-------|-------------|
| `detail.eventBody.conversationId` | Genesys conversation ID |
| `detail.eventBody.communicationId` | Specific communication leg |
| `detail.eventBody.transcripts[].channel` | `EXTERNAL` (customer) or `INTERNAL` (agent) |
| `detail.eventBody.transcripts[].alternatives[].transcript` | The transcribed text |
| `detail.eventBody.transcripts[].alternatives[].confidence` | Confidence score (0.0–1.0) |
| `detail.eventBody.transcripts[].alternatives[].offsetMs` | Offset from start of communication |
| `time` | When EventBridge received the event |

---

## Cleanup

When testing is complete, remove all temporary resources in the **765425735388 console**:

**EventBridge Rules** (delete targets first, then rules):

- `genesys-transcription-to-cwl`
- `genesys-transcription-to-sqs`
- `genesys-transcription-to-local`

**EventBridge API Destination:**

- `ngrok-local-receiver` (and connection `ngrok-connection`)

**SQS Queue:**

- `genesys-transcription-latency-test`

**CloudWatch Log Group:**

- `/aws/events/genesys/eventbridge/transcription-test`

CLI equivalents (if permissions allow):

```bash
# CloudWatch rule
aws events remove-targets --rule genesys-transcription-to-cwl \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --ids cwl-target --region us-east-2
aws events delete-rule --name genesys-transcription-to-cwl \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --region us-east-2

# SQS rule
aws events remove-targets --rule genesys-transcription-to-sqs \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --ids sqs-target --region us-east-2
aws events delete-rule --name genesys-transcription-to-sqs \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --region us-east-2

# API Destination rule
aws events remove-targets --rule genesys-transcription-to-local \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --ids api-target --region us-east-2
aws events delete-rule --name genesys-transcription-to-local \
  --event-bus-name "aws.partner/genesys.com/cloud/cf6cb7d5-d0ea-45b5-b0cf-73ad5f5b8721/DA-VOICE-SB" \
  --region us-east-2

# SQS queue
aws sqs delete-queue \
  --queue-url https://sqs.us-east-2.amazonaws.com/765425735388/genesys-transcription-latency-test \
  --region us-east-2

# CloudWatch log group
aws logs delete-log-group \
  --log-group-name /aws/events/genesys/eventbridge/transcription-test \
  --region us-east-2
```

---

## Request to MLOps Team

Hello Team,

I'm running a latency spike comparing the Genesys Cloud EventBridge integration against the WebSocket Notifications API for consuming real-time voice transcription events (`v2.conversations.{id}.transcription`).

The EventBridge integration is fully working in account **765425735388** (`cscda-sandbox`). I've confirmed events are flowing into both CloudWatch Logs and an SQS queue (`genesys-transcription-latency-test`). However, I need to poll that SQS queue from my local machine to run the latency comparison, and my SSO role in **173078698674** is blocked by an Organization Service Control Policy.

**The blocker:**

```
An error occurred (AccessDenied) when calling the ReceiveMessage operation:
User: arn:aws:sts::173078698674:assumed-role/AWSReservedSSO_173078698674-cscdigitalassistan_6e3a3c6c123a8e57/xnxn040
is not authorized to perform: sqs:receivemessage on resource:
arn:aws:sqs:us-east-2:765425735388:genesys-transcription-latency-test
with an explicit deny in a service control policy:
arn:aws:organizations::052343574110:policy/o-y3vn941x7j/service_control_policy/p-kfhxcsd9
```

The SQS resource-based policy already grants my role `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:ChangeMessageVisibility`, and `sqs:GetQueueAttributes`. The deny is coming from the SCP, not a missing permission.

**What I need (either option works):**

1. An SCP exception allowing my SSO role in 173078698674 to perform `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:ChangeMessageVisibility`, and `sqs:GetQueueAttributes` on `arn:aws:sqs:us-east-2:765425735388:genesys-transcription-latency-test` — or —
2. CLI permissions in 765425735388 directly (including `sqs:ReceiveMessage` and `logs:FilterLogEvents`)

This is for a temporary latency test — happy to have the access scoped and time-limited.

Thanks!
