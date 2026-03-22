# Result Executive Summary of Experimental Data on Genesys Latency using Notifications (WebSocket)
* Download Executive Summary @ https://github.com/Noel-Niko/notifications-spike/blob/master/docs/exec_summary_final.docx
* Read Analysis @ https://github.com/Noel-Niko/notifications-spike/blob/master/docs/analysis.md
* Review Notebook @ https://github.com/Noel-Niko/notifications-spike/blob/master/notebooks/cross_system_latency.ipynb



-----


# Genesys Cloud Transcript Recorder

Real-time conversation transcript recorder for Genesys Cloud contact center.

## What This Application Does

This application:

1. **Monitors specific agents** (configured in `agents.txt`)
2. **Detects when they start conversations** with customers
3. **Subscribes to live transcriptions** of those conversations
4. **Saves transcript events** to JSONL files (one per conversation)

## How It Integrates with Genesys

**Architecture Flow:**
```
Genesys Cloud → OAuth Authentication → WebSocket Connection → FastAPI App → Local JSONL Files
```

**Integration Steps:**
1. **OAuth Authentication**: Uses client credentials to get an access token from Genesys
2. **Notification Channel**: Creates a WebSocket channel for real-time events
3. **Agent Subscription**: Subscribes to conversation events for agents listed in `agents.txt`
4. **Dynamic Transcription**: When an agent connects to a call, automatically subscribes to that conversation's transcription feed
5. **Data Persistence**: Writes transcript events to `conversation_events/{conversation_id}.jsonl`

## Configuration

### `.env` File

Create a `.env` file in the project root:

```bash
# Genesys Cloud API configuration
REGION_API_BASE=https://api.mypurecloud.com        # Your region's API URL
REGION_LOGIN_BASE=https://login.mypurecloud.com    # Your region's login URL
CLIENT_ID=your-client-id-here                       # OAuth client ID
CLIENT_SECRET=your-client-secret-here               # OAuth client secret

# Optional settings
AGENT_EMAILS_FILE=agents.txt                        # Path to file with agent emails
MAX_CONVERSATIONS=10                                # Max concurrent conversations to track
CONVERSATION_EVENT_DIR=conversation_events          # Where to save transcript files
```

**Common Genesys Region URLs:**
- US East: `https://api.mypurecloud.com` / `https://login.mypurecloud.com`
- US West: `https://api.usw2.pure.cloud` / `https://login.usw2.pure.cloud`
- EU: `https://api.mypurecloud.ie` / `https://login.mypurecloud.ie`

### `agents.txt` File

List agent email addresses to monitor (one per line):

```
kevin.brehm@grainger.com
noel.nosse@grainger.com
```

## How to Run

**Option 1: Using uvicorn (Recommended)**
```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

**Option 2: Direct Python execution**
```bash
uv run python main.py
```

**Option 3: With hot reload for development**
```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## What to Expect When Running

### On Startup

```
[timestamp] INFO Channel created id={channel_id}
[timestamp] INFO Resolved agent email kevin.brehm@grainger.com to id {user_id}
[timestamp] INFO Resolved agent email noel.nosse@grainger.com to id {user_id}
[timestamp] INFO Subscribed to agent kevin.brehm@grainger.com via topic v2.users.{user_id}.conversations
[timestamp] INFO Subscribed to agent noel.nosse@grainger.com via topic v2.users.{user_id}.conversations
[timestamp] INFO WebSocket connected (agents=2, max_concurrent_conversations=10)
```

### When an Agent Starts a Call

```
[timestamp] INFO Conversation {conv_id} agent state: connected=True ended=False
[timestamp] INFO Subscribed to transcripts for conversation {conv_id} (active=1/10)
```

### During the Call

Transcript events are silently written to `conversation_events/{conversation_id}.jsonl`

### When Call Ends

```
[timestamp] INFO Conversation {conv_id} agent state: connected=True ended=True
[timestamp] INFO Stopped tracking conversation {conv_id} (active=0/10)
```

## API Endpoints

### Health Check

Check application status:

```bash
curl http://localhost:8000/health
```

**Response:**
```json
{
  "ok": true,
  "active_conversations": 2
}
```

**Note:** The root path (`/`) is not defined and will return 404. This is expected - the application is a background service that monitors conversations via WebSocket.

## Output Files

### Location

Transcripts are saved in the `conversation_events/` directory.

### Format

Each conversation gets its own JSONL file:

```
conversation_events/
├── 02ecc434-d65b-491e-9555-59aa3949d046.jsonl
├── 032a8212-b286-47c7-9db0-543cb59cc91b.jsonl
└── ...
```

### Content Example

```json
{"conversationId": "abc-123", "receivedAt": 1710590000.123, "transcript": {"channel": "EXTERNAL", "isFinal": true, "alternatives": [{"transcript": "Hello, how can I help you?", "offsetMs": 1000, "durationMs": 2500}]}}
{"conversationId": "abc-123", "receivedAt": 1710590003.456, "transcript": {"channel": "INTERNAL", "isFinal": false, "alternatives": [{"transcript": "I need help with my order", "offsetMs": 3500, "durationMs": 3000}]}}
```

**Fields:**
- `conversationId`: Unique Genesys conversation ID
- `receivedAt`: Unix timestamp when event was received
- `transcript.channel`: `EXTERNAL` (customer) or `INTERNAL` (agent)
- `transcript.isFinal`: Whether this is the final transcription for this utterance
- `transcript.alternatives[].transcript`: The transcribed text
- `transcript.alternatives[].offsetMs`: Timing offset in milliseconds
- `transcript.alternatives[].durationMs`: Duration in milliseconds

## Cross-System Latency Measurement

Measure true end-to-end latency from spoken audio to transcription delivery by correlating this app's data with **poc-deepgram** (a separate repository at `../poc-deepgram`), which provides ground-truth wall-clock timestamps for when speech actually occurred.

> **Full setup and test directions**: See [`docs/setup-and-run-directions/manual_test_directions.md`](docs/setup-and-run-directions/manual_test_directions.md) for complete step-by-step instructions including BlackHole audio routing setup, 3-terminal startup sequence (Notifications + EventBridge SQS consumer + poc-deepgram), Genesys audio device configuration, and troubleshooting.

### Quick Overview

The test setup requires **3 terminals** running simultaneously plus a browser:

| Terminal | Command | Purpose |
|----------|---------|---------|
| 1 | `uv run uvicorn main:app --host 0.0.0.0 --port 8765` | Notifications API (WebSocket) capture |
| 2 | `SQS_QUEUE_URL=... uv run python -m scripts.sqs_consumer` | EventBridge (SQS) capture |
| 3 | `cd ../poc-deepgram && uv run uvicorn poc_deepgram.app:create_app --factory --host 0.0.0.0 --port 8766` | Ground-truth audio timing |
| Browser | `http://localhost:8766` | poc-deepgram UI (select BlackHole 2ch, click Start) |

> **poc-deepgram is a separate repo** — it must be cloned alongside this repo at `../poc-deepgram`. It captures call audio via BlackHole virtual audio routing and sends it to Deepgram for independent transcription with wall-clock timestamps. This provides the ground-truth reference for latency measurement.

### After a Call

Run the correlation tool:

```bash
uv run python -m scripts.correlate_latency \
  --deepgram ../poc-deepgram/results/<session-file>.json \
  --genesys conversation_events/<conversation-id>.jsonl
```

For interactive analysis with visualizations:

```bash
# Notifications latency analysis
uv run jupyter notebook notebooks/cross_system_latency-01-RESULTS.ipynb

# EventBridge vs Notifications comparison
uv run jupyter notebook notebooks/cross_system_latency-02-EB-RESULTS.ipynb
```

### Running Tests

```bash
uv run pytest tests/ -v
```

## Documentation

| Document | Description |
|----------|-------------|
| [`docs/setup-and-run-directions/manual_test_directions.md`](docs/setup-and-run-directions/manual_test_directions.md) | **Start here** — full setup and test execution guide (BlackHole, 3-terminal startup, Genesys audio config, troubleshooting) |
| [`docs/analysis.md`](docs/analysis.md) | Executive summary of latency findings |
| [`docs/analysis_key_points.md`](docs/analysis_key_points.md) | Detailed EventBridge vs Notifications comparison with scaling analysis for 1,200 agents |
| [`docs/notifications_testing_learnings.md`](docs/notifications_testing_learnings.md) | Issues discovered during testing (8 issues with root causes, fixes, and lessons) |
| [`docs/notifications_production_implementation_guide.md`](docs/notifications_production_implementation_guide.md) | What a production Notifications API implementation would require (channel sharding, state machine, recovery, monitoring) |
| [`EventBridge/Genesys_EventBridge_Setup_Runbook.md`](EventBridge/Genesys_EventBridge_Setup_Runbook.md) | EventBridge infrastructure setup (EB rules, SQS targets, CloudWatch) |

## Key Limitations

1. **Max Concurrent Conversations**: Set to 10 by default - if more than 10 agents are on calls simultaneously, additional conversations will be ignored until slots free up
2. **Agent Must Be Connected**: Only captures conversations where the monitored agent is actively connected (not queued calls)
3. **Real-time Only**: No historical conversation retrieval - starts monitoring from when the app launches

## Use Cases

- **Quality Assurance**: Record agent-customer interactions for review
- **Training**: Collect conversation samples for agent training
- **Analytics**: Build datasets for conversation analysis
- **Compliance**: Archive conversations with full transcripts

## Troubleshooting

### Missing Environment Variables

```
Missing required env vars: REGION_API_BASE, REGION_LOGIN_BASE, CLIENT_ID, CLIENT_SECRET
```

**Solution:** Create a `.env` file with the required Genesys credentials (see Configuration section above).

### Virtual Environment Warning

```
warning: `VIRTUAL_ENV=/path/to/wrong/.venv` does not match the project environment path `.venv`
```

**Solution:** This is harmless - `uv run` will use the correct virtual environment. To silence it, run `deactivate` before using `uv run`.

### 404 Not Found on Root Path

The root path (`http://localhost:8000/`) is not defined. Use the `/health` endpoint instead:

```bash
curl http://localhost:8000/health
```

## Dependencies

- FastAPI: Web framework
- uvicorn: ASGI server
- httpx: Async HTTP client
- websockets: WebSocket client
- python-dotenv: Environment variable management
- pydantic: Data validation

Install via:
```bash
uv sync
```

## EventBridge Notes

For EventBridge setup and AWS context, see [`EventBridge/Genesys_EventBridge_Setup_Runbook.md`](EventBridge/Genesys_EventBridge_Setup_Runbook.md).

```bash
# AWS/Kubernetes context for EventBridge sandbox
# Assume: MLOpsNonProd/cscdigitalassistan
kubectx cscdigitalassistan/devbchue2
kubens cscdigitalassistant
```
