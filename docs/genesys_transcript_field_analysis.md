# Genesys Cloud Transcript Field Analysis

## Overview

This document analyzes the timing fields in Genesys Cloud transcript notifications to identify which measurements relate to transcription latency (time from audio generation to text receipt).

## Data Structure from `calls/*.jsonl`

Each line in the JSONL files contains:

```json
{
  "conversationId": "string",
  "receivedAt": float,
  "transcript": { ... }
}
```

## Field Definitions and Sources

### Application-Generated Fields

#### `conversationId`
- **Source**: Your application (main.py:394)
- **Definition**: Unique identifier for the Genesys conversation
- **Format**: UUID string
- **Example**: `"0af03210-7b32-4264-a02c-2297df54f25d"`

#### `receivedAt`
- **Source**: Your application (main.py:395)
- **Definition**: Unix timestamp (seconds since epoch) when your application received the WebSocket message from Genesys
- **Format**: Float with microsecond precision
- **Example**: `1760549647.076801`
- **Code**: `time.time()`
- **Purpose**: Allows calculation of end-to-end latency from audio to receipt

### Genesys-Provided Fields

All fields within `transcript` object come from Genesys Cloud.

#### `transcript.utteranceId`
- **Source**: Genesys Cloud
- **Definition**: Unique identifier for this specific utterance in the conversation
- **Format**: UUID string
- **Example**: `"4344c524-f791-469b-88ac-a92725d9f8cc"`

#### `transcript.isFinal`
- **Source**: Genesys Cloud
- **Definition**: Boolean indicating whether this is the final transcription for this utterance
- **Values**: `true` | `false`
- **Note**: Genesys may send intermediate (non-final) transcriptions as speech is processed, then send a final corrected version

#### `transcript.channel`
- **Source**: Genesys Cloud
- **Definition**: Audio channel indicator
- **Values**:
  - `"INTERNAL"` - Agent audio
  - `"EXTERNAL"` - Customer/caller audio
- **Example**: `"INTERNAL"`

#### `transcript.alternatives[].confidence`
- **Source**: Genesys Cloud speech recognition engine
- **Definition**: Confidence score for the transcription accuracy
- **Format**: Float between 0.0 and 1.0
- **Example**: `0.9761875`
- **Calculation**: Average of word-level confidence scores

#### `transcript.alternatives[].offsetMs` ⏱️
- **Source**: Genesys Cloud speech recognition engine
- **Definition**: **Time offset in milliseconds from the START OF THE CONVERSATION to the beginning of this utterance**
- **Format**: Integer (milliseconds)
- **Example**: `63459` (means this utterance began 63.459 seconds after conversation started)
- **Reference Point**: Start of the conversation (when audio stream began)
- **Documentation**: Genesys Cloud API - Transcription Alternatives

**Key Insight**: This is NOT when the transcription was generated - it's when the AUDIO was spoken.

#### `transcript.alternatives[].durationMs` ⏱️
- **Source**: Genesys Cloud speech recognition engine
- **Definition**: **Duration in milliseconds of the spoken utterance**
- **Format**: Integer (milliseconds)
- **Example**: `3722` (3.722 seconds of speech)
- **Purpose**: Indicates how long the person spoke
- **Documentation**: Genesys Cloud API - Transcription Alternatives

**Key Insight**: This is the duration of the AUDIO, not the processing time.

#### `transcript.alternatives[].transcript`
- **Source**: Genesys Cloud speech recognition engine
- **Definition**: The transcribed text
- **Format**: Lowercase string
- **Example**: `"thank you for contacting grainger my name is austin and who am i speaking with today"`

#### `transcript.alternatives[].words[]` (Array)
Word-level breakdown with timing for each word:

##### `words[].confidence`
- **Definition**: Confidence score for this specific word
- **Format**: Float between 0.0 and 1.0
- **Example**: `1.0`, `0.681`

##### `words[].offsetMs` ⏱️
- **Definition**: **Time offset in milliseconds from conversation start to when this word was spoken**
- **Format**: Integer (milliseconds)
- **Example**: `63459` (first word), `67102` (last word "today")
- **Reference Point**: Start of conversation

##### `words[].durationMs` ⏱️
- **Definition**: **Duration in milliseconds of this word being spoken**
- **Format**: Integer (milliseconds)
- **Example**: `40` (40ms), `475` (475ms for "contacting")

##### `words[].word`
- **Definition**: The transcribed word text
- **Format**: Lowercase string
- **Example**: `"thank"`, `"you"`

#### `transcript.alternatives[].decoratedTranscript`
- **Source**: Genesys Cloud
- **Definition**: Enhanced transcript with capitalization and formatting
- **Format**: String with proper capitalization
- **Example**: `"thank you for contacting grainger my name is austin and who am i speaking with today"`

#### `transcript.alternatives[].decoratedWords[]`
- **Source**: Genesys Cloud
- **Definition**: Same as `words[]` but corresponds to `decoratedTranscript`
- **Note**: May have different word boundaries (e.g., "II" instead of "i i")

#### `transcript.engineProvider`
- **Source**: Genesys Cloud
- **Definition**: Speech recognition engine provider
- **Example**: `"GENESYS"`

#### `transcript.engineId`
- **Source**: Genesys Cloud
- **Definition**: Specific engine version/ID
- **Example**: `"r2d2"`

#### `transcript.dialect`
- **Source**: Genesys Cloud
- **Definition**: Language and region code
- **Format**: BCP 47 language tag
- **Example**: `"en-US"`

## Calculating Transcription Latency

### End-to-End Latency (Audio Spoken → Text Received)

To calculate the latency from when audio was spoken to when the transcription was received:

```python
# For an utterance
audio_start_time_ms = transcript["alternatives"][0]["offsetMs"]
audio_end_time_ms = audio_start_time_ms + transcript["alternatives"][0]["durationMs"]
received_timestamp = receivedAt  # Unix timestamp in seconds

# Convert conversation start time (approximate from first event)
# This requires tracking the first receivedAt and first offsetMs
conversation_start_time = first_receivedAt - (first_offsetMs / 1000.0)

# When the audio actually finished being spoken
audio_finish_time = conversation_start_time + (audio_end_time_ms / 1000.0)

# Transcription latency
transcription_latency = received_timestamp - audio_finish_time
```

### Example Calculation

From first transcript in sample file:
- `offsetMs`: 63459 (audio started at 63.459s into conversation)
- `durationMs`: 3722 (audio lasted 3.722 seconds)
- `receivedAt`: 1760549647.076801 (Unix timestamp)

**Audio Timeline**:
- Audio start: 63.459s into conversation
- Audio end: 67.181s into conversation (63.459 + 3.722)

**Transcription Latency Calculation**:
- Requires knowing conversation start time
- Can be estimated from first event with `offsetMs` ≈ 0

### Real-World Latency Observations

Looking at your sample data:

**Event 1**:
- offsetMs: 63459 (63.5 seconds)
- durationMs: 3722 (3.7 seconds)
- receivedAt: 1760549647.076801

**Event 2** (next event):
- offsetMs: 68197 (68.2 seconds)
- durationMs: 349 (0.35 seconds)
- receivedAt: 1760549647.764318

Time between events: 0.687 seconds
Audio gap: 68.197 - 67.181 = 1.016 seconds

This suggests transcription was received while the next utterance was already being spoken, indicating **sub-second latency** after utterance completion.

## Fields Useful for Latency Analysis

### For Measuring Transcription Latency:

1. **`receivedAt`** (your app) - When text arrived
2. **`offsetMs`** (Genesys) - When audio started
3. **`durationMs`** (Genesys) - How long audio lasted

### Formula:
```
Transcription Latency = receivedAt - (conversation_start_time + (offsetMs + durationMs) / 1000)
```

Where:
- `conversation_start_time` = First receivedAt - (first offsetMs / 1000)

### Not Useful for Latency:
- `confidence` - Quality metric, not timing
- `utteranceId` - Identifier only
- `channel` - Audio source, not timing
- `engineProvider`/`engineId` - Engine info, not timing

## Additional Timing Considerations

### WebSocket Network Latency
The `receivedAt` timestamp includes:
1. Speech recognition processing time
2. Genesys server → your application network latency
3. WebSocket transmission time

Typical network latency is 10-100ms depending on geography.

### Processing Stages Timeline

```
[Audio Spoken] → [Genesys Captures Audio] → [Speech-to-Text Processing] → [WebSocket Transmission] → [Your App Receives]
     ↑                                                                                                    ↑
  offsetMs                                                                                           receivedAt
  (relative to                                                                                      (absolute time)
   conversation start)
```

## Genesys Cloud Documentation References

Based on the standard Genesys Cloud Notifications API:

- **Notification Topic**: `v2.conversations.{conversationId}.transcription`
- **API Documentation**: https://developer.genesys.cloud/notificationsalerts/notifications/available-topics#v2-conversations--id--transcription
- **Conversation API**: https://developer.genesys.cloud/api/rest/v2/conversations/
- **Speech Recognition**: Uses Genesys "r2d2" engine for en-US dialect ()
    - https://developer.genesys.cloud/analyticsdatamanagement/speechtextanalytics/transcription-notifications
    - https://developer.genesys.cloud/analyticsdatamanagement/speechtextanalytics/transcript-url

## Summary Table

| Field | Source | Represents | Useful for Latency? |
|-------|--------|------------|---------------------|
| `conversationId` | App | Conversation identifier | No |
| `receivedAt` | App | When app received text | ✅ Yes (end point) |
| `utteranceId` | Genesys | Utterance identifier | No |
| `isFinal` | Genesys | Final vs intermediate | No |
| `channel` | Genesys | Agent vs customer audio | No |
| `confidence` | Genesys | Transcription accuracy | No |
| `offsetMs` | Genesys | Audio start time | ✅ Yes (start point) |
| `durationMs` | Genesys | Audio duration | ✅ Yes (audio end) |
| `transcript` | Genesys | Transcribed text | No |
| `words[].offsetMs` | Genesys | Word-level timing | ✅ Yes (fine-grained) |
| `words[].durationMs` | Genesys | Word duration | ✅ Yes (fine-grained) |
| `engineProvider` | Genesys | Engine identifier | No |

## Recommendations for Latency Monitoring

To properly track transcription latency:

1. **Track conversation start time**: Store the first `receivedAt` and `offsetMs` to establish a baseline
2. **Calculate audio end time**: `offsetMs + durationMs` = when speaker finished talking
3. **Measure receipt latency**: `receivedAt - audio_end_time` = processing + transmission latency
4. **Monitor per channel**: Separate latency metrics for INTERNAL vs EXTERNAL
5. **Consider isFinal flag**: Final transcriptions may have higher latency than intermediate ones

## Example Python Analysis Function

```python
def calculate_transcription_latency(conversation_events):
    """Calculate transcription latency for a conversation."""

    # Find conversation start time from first event
    first_event = min(conversation_events, key=lambda e: e["transcript"]["alternatives"][0]["offsetMs"])
    first_offset_ms = first_event["transcript"]["alternatives"][0]["offsetMs"]
    first_received_at = first_event["receivedAt"]

    # Conversation start time (absolute)
    conversation_start_time = first_received_at - (first_offset_ms / 1000.0)

    latencies = []
    for event in conversation_events:
        alt = event["transcript"]["alternatives"][0]
        offset_ms = alt["offsetMs"]
        duration_ms = alt["durationMs"]
        received_at = event["receivedAt"]

        # When audio finished being spoken (absolute time)
        audio_end_time = conversation_start_time + ((offset_ms + duration_ms) / 1000.0)

        # Transcription latency
        latency = received_at - audio_end_time

        latencies.append({
            "utteranceId": event["transcript"]["utteranceId"],
            "channel": event["transcript"]["channel"],
            "latency_seconds": latency,
            "audio_duration_seconds": duration_ms / 1000.0,
            "transcript_text": alt["transcript"]
        })

    return latencies
```

---

## Implementation Plan

For the complete implementation plan to build a latency analysis notebook based on this field analysis, see:

📋 **[Latency Analysis Notebook - Implementation Plan](./latency_analysis_notebook_plan.md)**

The implementation plan includes:
- 7 modules with detailed tasks and checkboxes
- Progress tracking capabilities
- Testing strategy and success criteria
- Expected deliverables and timeline
