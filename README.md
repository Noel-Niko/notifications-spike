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

Measure true end-to-end latency from spoken audio to transcription delivery by correlating this app's data with [poc-deepgram](../poc-deepgram), which provides ground-truth wall-clock timestamps for when speech actually occurred.

### One-Time Setup: Audio Routing

Install [BlackHole](https://existential.audio/blackhole/) to route Genesys call audio into poc-deepgram:

```bash
brew install blackhole-2ch
```

Then in **Audio MIDI Setup** (macOS):
1. Create a **Multi-Output Device** combining your speakers + BlackHole 2ch
2. Set system output to the Multi-Output Device

This lets you hear the call audio while simultaneously routing it to poc-deepgram.

### During a Call

Run both applications simultaneously:

```bash
# Terminal 1: Start this app (Genesys transcript capture)
uv run uvicorn main:app --host 0.0.0.0 --port 8765

# Terminal 2: Start poc-deepgram (ground-truth audio timing)
cd ../poc-deepgram
uv run uvicorn poc_deepgram.app:create_app --factory --host 0.0.0.0 --port 8766
```

Then:
1. Open `http://localhost:8766` in a browser
2. Select **BlackHole 2ch** as the microphone input
3. Click **Start**
4. Take the Genesys call — both systems capture data in parallel
5. When the call ends, click **Stop** in poc-deepgram

### After the Call

Run the correlation tool to compute true latency:

```bash
uv run python -m scripts.correlate_latency \
  --deepgram ../poc-deepgram/results/<session-file>.json \
  --genesys conversation_events/<conversation-id>.jsonl
```

This fuzzy-matches utterances between the two systems by text similarity and computes:

```
true_latency = genesys_receivedAt - deepgram_audio_wall_clock_end
```

Output includes summary statistics (mean, median, p95, p99), per-channel breakdown, and CSV export to `analysis_results/cross_system/`.

For interactive analysis, use the Jupyter notebook:

```bash
cd notebooks
uv run jupyter notebook cross_system_latency.ipynb
```

### How It Works

| System | Role | Key Timestamp |
|--------|------|---------------|
| **poc-deepgram** | Captures call audio, provides wall-clock time of speech | `audio_wall_clock_end` (when words were spoken) |
| **notifications-spike** | Receives Genesys transcription events | `receivedAt` (when text arrived) |

Both apps run on the same machine and use `time.time()`, so clocks are synchronized. The correlation tool matches utterances by fuzzy text similarity (threshold: 0.55) with temporal proximity as a tiebreaker.

### Running Tests

```bash
uv run pytest tests/ -v
```

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

EVENT BRIDGE NOTES
assume MLOpsNonProd/cscdigitalassistan   
kubectx cscdigitalassistan/devbchue2
kubens cscdigitalassistant


