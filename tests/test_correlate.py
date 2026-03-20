"""Tests for cross-system latency correlation logic."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.correlate_latency import (
    CorrelationResult,
    GenesysEvent,
    DeepgramEvent,
    load_deepgram_session,
    load_genesys_conversation,
    load_eventbridge_conversation,
    match_utterances,
    compute_latency,
    correlate,
    correlate_eventbridge,
)


# ---------------------------------------------------------------------------
# Fixtures: realistic test data
# ---------------------------------------------------------------------------

STREAM_START = 1700000000.0  # Arbitrary wall-clock anchor


def _deepgram_session(transcripts: list[dict] | None = None) -> dict:
    """Build a minimal poc-deepgram session JSON structure."""
    if transcripts is None:
        transcripts = [
            {
                "index": 0,
                "type": "final",
                "transcript": "thank you for calling grainger",
                "confidence": 0.95,
                "audio_start": 2.0,
                "audio_end": 4.5,
                "audio_wall_clock_start": STREAM_START + 2.0,
                "audio_wall_clock_end": STREAM_START + 4.5,
                "offset_ms": 2000.0,
                "duration_ms": 2500.0,
                "server_receipt_time": STREAM_START + 4.7,
                "latency_ms": 200.0,
                "word_count": 5,
                "speaker": 0,
                "words": [],
            },
            {
                "index": 1,
                "type": "final",
                "transcript": "how can i help you today",
                "confidence": 0.97,
                "audio_start": 5.0,
                "audio_end": 7.0,
                "audio_wall_clock_start": STREAM_START + 5.0,
                "audio_wall_clock_end": STREAM_START + 7.0,
                "offset_ms": 5000.0,
                "duration_ms": 2000.0,
                "server_receipt_time": STREAM_START + 7.3,
                "latency_ms": 300.0,
                "word_count": 6,
                "speaker": 0,
                "words": [],
            },
        ]
    return {
        "session": {
            "session_id": "test-session-001",
            "model": "nova-3",
            "stream_start_time": STREAM_START,
            "started_at": "2026-03-17T00:00:00+00:00",
            "ended_at": "2026-03-17T00:01:00+00:00",
            "duration_seconds": 60.0,
        },
        "transcripts": transcripts,
        "summary": {"total_finals": len(transcripts)},
    }


def _genesys_events(events: list[dict] | None = None) -> list[dict]:
    """Build minimal notifications-spike JSONL events."""
    if events is None:
        events = [
            {
                "conversationId": "conv-001",
                "receivedAt": STREAM_START + 5.3,
                "transcript": {
                    "utteranceId": "utt-001",
                    "isFinal": True,
                    "channel": "INTERNAL",
                    "alternatives": [
                        {
                            "transcript": "thank you for calling grainger",
                            "confidence": 0.96,
                            "offsetMs": 2000,
                            "durationMs": 2500,
                        }
                    ],
                },
            },
            {
                "conversationId": "conv-001",
                "receivedAt": STREAM_START + 7.8,
                "transcript": {
                    "utteranceId": "utt-002",
                    "isFinal": True,
                    "channel": "INTERNAL",
                    "alternatives": [
                        {
                            "transcript": "how can i help you today",
                            "confidence": 0.98,
                            "offsetMs": 5000,
                            "durationMs": 2000,
                        }
                    ],
                },
            },
        ]
    return events


@pytest.fixture
def deepgram_session_file(tmp_path: Path) -> Path:
    fp = tmp_path / "session.json"
    fp.write_text(json.dumps(_deepgram_session()))
    return fp


@pytest.fixture
def genesys_jsonl_file(tmp_path: Path) -> Path:
    fp = tmp_path / "conversation.jsonl"
    lines = [json.dumps(e) for e in _genesys_events()]
    fp.write_text("\n".join(lines))
    return fp


# ---------------------------------------------------------------------------
# Tests: Data loading
# ---------------------------------------------------------------------------


class TestLoadDeepgramSession:
    def test_loads_transcripts(self, deepgram_session_file: Path):
        events = load_deepgram_session(deepgram_session_file)
        assert len(events) == 2
        assert all(isinstance(e, DeepgramEvent) for e in events)

    def test_extracts_wall_clock_fields(self, deepgram_session_file: Path):
        events = load_deepgram_session(deepgram_session_file)
        assert events[0].audio_wall_clock_end == pytest.approx(STREAM_START + 4.5)
        assert events[1].audio_wall_clock_end == pytest.approx(STREAM_START + 7.0)

    def test_extracts_transcript_text(self, deepgram_session_file: Path):
        events = load_deepgram_session(deepgram_session_file)
        assert events[0].transcript == "thank you for calling grainger"
        assert events[1].transcript == "how can i help you today"

    def test_skips_events_without_wall_clock(self, tmp_path: Path):
        session = _deepgram_session()
        session["transcripts"][0]["audio_wall_clock_end"] = None
        fp = tmp_path / "session.json"
        fp.write_text(json.dumps(session))
        events = load_deepgram_session(fp)
        assert len(events) == 1
        assert events[0].transcript == "how can i help you today"


class TestLoadGenesysConversation:
    def test_loads_events(self, genesys_jsonl_file: Path):
        events = load_genesys_conversation(genesys_jsonl_file)
        assert len(events) == 2
        assert all(isinstance(e, GenesysEvent) for e in events)

    def test_extracts_received_at(self, genesys_jsonl_file: Path):
        events = load_genesys_conversation(genesys_jsonl_file)
        assert events[0].received_at == pytest.approx(STREAM_START + 5.3)

    def test_extracts_transcript_text(self, genesys_jsonl_file: Path):
        events = load_genesys_conversation(genesys_jsonl_file)
        assert events[0].transcript == "thank you for calling grainger"

    def test_extracts_channel(self, genesys_jsonl_file: Path):
        events = load_genesys_conversation(genesys_jsonl_file)
        assert events[0].channel == "INTERNAL"

    def test_filters_final_only(self, tmp_path: Path):
        events = _genesys_events()
        events[0]["transcript"]["isFinal"] = False
        fp = tmp_path / "conversation.jsonl"
        fp.write_text("\n".join(json.dumps(e) for e in events))
        loaded = load_genesys_conversation(fp)
        assert len(loaded) == 1
        assert loaded[0].transcript == "how can i help you today"


# ---------------------------------------------------------------------------
# Tests: Utterance matching
# ---------------------------------------------------------------------------


class TestMatchUtterances:
    def test_exact_text_match(self):
        dg = [
            DeepgramEvent(
                transcript="thank you for calling grainger",
                audio_wall_clock_start=STREAM_START + 2.0,
                audio_wall_clock_end=STREAM_START + 4.5,
            ),
        ]
        gn = [
            GenesysEvent(
                transcript="thank you for calling grainger",
                received_at=STREAM_START + 5.3,
                channel="INTERNAL",
                utterance_id="utt-001",
                offset_ms=2000,
                duration_ms=2500,
            ),
        ]
        matches = match_utterances(dg, gn)
        assert len(matches) == 1
        assert matches[0][0] is dg[0]
        assert matches[0][1] is gn[0]

    def test_fuzzy_text_match(self):
        dg = [
            DeepgramEvent(
                transcript="Thank you for calling Grainger.",
                audio_wall_clock_start=STREAM_START + 2.0,
                audio_wall_clock_end=STREAM_START + 4.5,
            ),
        ]
        gn = [
            GenesysEvent(
                transcript="thank you for calling grainger",
                received_at=STREAM_START + 5.3,
                channel="INTERNAL",
                utterance_id="utt-001",
                offset_ms=2000,
                duration_ms=2500,
            ),
        ]
        matches = match_utterances(dg, gn)
        assert len(matches) == 1

    def test_no_match_below_threshold(self):
        dg = [
            DeepgramEvent(
                transcript="something completely different",
                audio_wall_clock_start=STREAM_START + 2.0,
                audio_wall_clock_end=STREAM_START + 4.5,
            ),
        ]
        gn = [
            GenesysEvent(
                transcript="thank you for calling grainger",
                received_at=STREAM_START + 5.3,
                channel="INTERNAL",
                utterance_id="utt-001",
                offset_ms=2000,
                duration_ms=2500,
            ),
        ]
        matches = match_utterances(dg, gn)
        assert len(matches) == 0

    def test_multiple_matches_best_fit(self):
        dg = [
            DeepgramEvent(
                transcript="thank you for calling grainger",
                audio_wall_clock_start=STREAM_START + 2.0,
                audio_wall_clock_end=STREAM_START + 4.5,
            ),
            DeepgramEvent(
                transcript="how can i help you today",
                audio_wall_clock_start=STREAM_START + 5.0,
                audio_wall_clock_end=STREAM_START + 7.0,
            ),
        ]
        gn = [
            GenesysEvent(
                transcript="thank you for calling grainger",
                received_at=STREAM_START + 5.3,
                channel="INTERNAL",
                utterance_id="utt-001",
                offset_ms=2000,
                duration_ms=2500,
            ),
            GenesysEvent(
                transcript="how can i help you today",
                received_at=STREAM_START + 7.8,
                channel="INTERNAL",
                utterance_id="utt-002",
                offset_ms=5000,
                duration_ms=2000,
            ),
        ]
        matches = match_utterances(dg, gn)
        assert len(matches) == 2
        # Each genesys event matched to the correct deepgram event
        assert matches[0][0].transcript == "thank you for calling grainger"
        assert matches[1][0].transcript == "how can i help you today"

    def test_genesys_event_not_matched_twice(self):
        """Each Genesys event should only match one Deepgram event."""
        dg = [
            DeepgramEvent(
                transcript="hello world",
                audio_wall_clock_start=STREAM_START + 1.0,
                audio_wall_clock_end=STREAM_START + 2.0,
            ),
            DeepgramEvent(
                transcript="hello world again",
                audio_wall_clock_start=STREAM_START + 3.0,
                audio_wall_clock_end=STREAM_START + 4.0,
            ),
        ]
        gn = [
            GenesysEvent(
                transcript="hello world",
                received_at=STREAM_START + 2.5,
                channel="INTERNAL",
                utterance_id="utt-001",
                offset_ms=1000,
                duration_ms=1000,
            ),
        ]
        matches = match_utterances(dg, gn)
        assert len(matches) == 1


# ---------------------------------------------------------------------------
# Tests: Latency computation
# ---------------------------------------------------------------------------


class TestComputeLatency:
    def test_basic_latency(self):
        dg = DeepgramEvent(
            transcript="thank you for calling grainger",
            audio_wall_clock_start=STREAM_START + 2.0,
            audio_wall_clock_end=STREAM_START + 4.5,
        )
        gn = GenesysEvent(
            transcript="thank you for calling grainger",
            received_at=STREAM_START + 5.3,
            channel="INTERNAL",
            utterance_id="utt-001",
            offset_ms=2000,
            duration_ms=2500,
        )
        result = compute_latency(dg, gn)
        assert isinstance(result, CorrelationResult)
        # Latency = received_at - audio_wall_clock_end = 5.3 - 4.5 = 0.8s
        assert result.true_latency_s == pytest.approx(0.8, abs=0.001)

    def test_latency_ms_conversion(self):
        dg = DeepgramEvent(
            transcript="test",
            audio_wall_clock_start=STREAM_START + 1.0,
            audio_wall_clock_end=STREAM_START + 2.0,
        )
        gn = GenesysEvent(
            transcript="test",
            received_at=STREAM_START + 2.5,
            channel="EXTERNAL",
            utterance_id="utt-003",
            offset_ms=1000,
            duration_ms=1000,
        )
        result = compute_latency(dg, gn)
        assert result.true_latency_ms == pytest.approx(500.0, abs=1.0)

    def test_result_includes_metadata(self):
        dg = DeepgramEvent(
            transcript="hello",
            audio_wall_clock_start=STREAM_START + 1.0,
            audio_wall_clock_end=STREAM_START + 2.0,
        )
        gn = GenesysEvent(
            transcript="hello",
            received_at=STREAM_START + 3.0,
            channel="EXTERNAL",
            utterance_id="utt-004",
            offset_ms=1000,
            duration_ms=1000,
        )
        result = compute_latency(dg, gn)
        assert result.channel == "EXTERNAL"
        assert result.deepgram_transcript == "hello"
        assert result.genesys_transcript == "hello"
        assert result.genesys_received_at == STREAM_START + 3.0
        assert result.audio_wall_clock_end == STREAM_START + 2.0


# ---------------------------------------------------------------------------
# Tests: End-to-end correlation
# ---------------------------------------------------------------------------


class TestCorrelate:
    def test_end_to_end(self, deepgram_session_file: Path, genesys_jsonl_file: Path):
        results = correlate(deepgram_session_file, genesys_jsonl_file)
        assert len(results) == 2
        # First utterance: received at +5.3, audio ended at +4.5 → latency 0.8s
        assert results[0].true_latency_s == pytest.approx(0.8, abs=0.001)
        # Second utterance: received at +7.8, audio ended at +7.0 → latency 0.8s
        assert results[1].true_latency_s == pytest.approx(0.8, abs=0.001)

    def test_returns_empty_for_no_matches(self, tmp_path: Path):
        dg_session = _deepgram_session()
        gn_events = _genesys_events()
        # Completely different transcripts
        gn_events[0]["transcript"]["alternatives"][0]["transcript"] = "abcdef xyz"
        gn_events[1]["transcript"]["alternatives"][0]["transcript"] = "ghijkl mnop"

        dg_file = tmp_path / "session.json"
        dg_file.write_text(json.dumps(dg_session))
        gn_file = tmp_path / "conversation.jsonl"
        gn_file.write_text("\n".join(json.dumps(e) for e in gn_events))

        results = correlate(dg_file, gn_file)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Fixtures: EventBridge JSONL (SQS consumer output format)
# ---------------------------------------------------------------------------


def _eventbridge_events(events: list[dict] | None = None) -> list[dict]:
    """Build minimal SQS consumer output JSONL events."""
    if events is None:
        events = [
            {
                "conversationId": "conv-001",
                "receivedAt": STREAM_START + 5.5,
                "sqsSentTimestamp": int((STREAM_START + 5.2) * 1000),
                "ebTime": "2026-03-17T00:00:05Z",
                "genesysEventTime": "2026-03-17T00:00:04.800Z",
                "sessionStartTimeMs": int(STREAM_START * 1000),
                "transcripts": [
                    {
                        "utteranceId": "utt-eb-001",
                        "isFinal": True,
                        "channel": "INTERNAL",
                        "alternatives": [
                            {
                                "transcript": "thank you for calling grainger",
                                "confidence": 0.96,
                                "offsetMs": 2000,
                                "durationMs": 2500,
                            }
                        ],
                    }
                ],
                "rawEvent": {},
            },
            {
                "conversationId": "conv-001",
                "receivedAt": STREAM_START + 8.0,
                "sqsSentTimestamp": int((STREAM_START + 7.7) * 1000),
                "ebTime": "2026-03-17T00:00:07Z",
                "genesysEventTime": "2026-03-17T00:00:07.500Z",
                "sessionStartTimeMs": int(STREAM_START * 1000),
                "transcripts": [
                    {
                        "utteranceId": "utt-eb-002",
                        "isFinal": True,
                        "channel": "INTERNAL",
                        "alternatives": [
                            {
                                "transcript": "how can i help you today",
                                "confidence": 0.98,
                                "offsetMs": 5000,
                                "durationMs": 2000,
                            }
                        ],
                    }
                ],
                "rawEvent": {},
            },
        ]
    return events


@pytest.fixture
def eventbridge_jsonl_file(tmp_path: Path) -> Path:
    fp = tmp_path / "eb_conversation.jsonl"
    lines = [json.dumps(e) for e in _eventbridge_events()]
    fp.write_text("\n".join(lines))
    return fp


# ---------------------------------------------------------------------------
# Tests: EventBridge loading
# ---------------------------------------------------------------------------


class TestLoadEventBridgeConversation:
    def test_loads_events(self, eventbridge_jsonl_file: Path):
        events = load_eventbridge_conversation(eventbridge_jsonl_file)
        assert len(events) == 2
        assert all(isinstance(e, GenesysEvent) for e in events)

    def test_extracts_received_at(self, eventbridge_jsonl_file: Path):
        events = load_eventbridge_conversation(eventbridge_jsonl_file)
        assert events[0].received_at == pytest.approx(STREAM_START + 5.5)
        assert events[1].received_at == pytest.approx(STREAM_START + 8.0)

    def test_extracts_transcript_text(self, eventbridge_jsonl_file: Path):
        events = load_eventbridge_conversation(eventbridge_jsonl_file)
        assert events[0].transcript == "thank you for calling grainger"
        assert events[1].transcript == "how can i help you today"

    def test_extracts_channel(self, eventbridge_jsonl_file: Path):
        events = load_eventbridge_conversation(eventbridge_jsonl_file)
        assert events[0].channel == "INTERNAL"

    def test_extracts_utterance_id(self, eventbridge_jsonl_file: Path):
        events = load_eventbridge_conversation(eventbridge_jsonl_file)
        assert events[0].utterance_id == "utt-eb-001"
        assert events[1].utterance_id == "utt-eb-002"

    def test_filters_final_only(self, tmp_path: Path):
        events = _eventbridge_events()
        events[0]["transcripts"][0]["isFinal"] = False
        fp = tmp_path / "eb.jsonl"
        fp.write_text("\n".join(json.dumps(e) for e in events))
        loaded = load_eventbridge_conversation(fp)
        assert len(loaded) == 1
        assert loaded[0].transcript == "how can i help you today"

    def test_handles_multiple_transcripts_per_line(self, tmp_path: Path):
        """One SQS message can carry multiple utterances in transcripts[]."""
        event = {
            "conversationId": "conv-001",
            "receivedAt": STREAM_START + 6.0,
            "sqsSentTimestamp": int((STREAM_START + 5.8) * 1000),
            "ebTime": "2026-03-17T00:00:05Z",
            "genesysEventTime": "2026-03-17T00:00:05.500Z",
            "sessionStartTimeMs": int(STREAM_START * 1000),
            "transcripts": [
                {
                    "utteranceId": "utt-multi-001",
                    "isFinal": True,
                    "channel": "EXTERNAL",
                    "alternatives": [
                        {"transcript": "first utterance", "confidence": 0.9,
                         "offsetMs": 1000, "durationMs": 1000}
                    ],
                },
                {
                    "utteranceId": "utt-multi-002",
                    "isFinal": True,
                    "channel": "INTERNAL",
                    "alternatives": [
                        {"transcript": "second utterance", "confidence": 0.95,
                         "offsetMs": 2000, "durationMs": 1500}
                    ],
                },
            ],
            "rawEvent": {},
        }
        fp = tmp_path / "eb_multi.jsonl"
        fp.write_text(json.dumps(event))
        loaded = load_eventbridge_conversation(fp)
        assert len(loaded) == 2
        assert loaded[0].transcript == "first utterance"
        assert loaded[1].transcript == "second utterance"

    def test_deduplicates_by_utterance_id(self, tmp_path: Path):
        """SQS at-least-once delivery can produce duplicate messages."""
        events = _eventbridge_events()
        # Duplicate the first event (same utteranceId)
        all_events = events + [events[0]]
        fp = tmp_path / "eb_dup.jsonl"
        fp.write_text("\n".join(json.dumps(e) for e in all_events))
        loaded = load_eventbridge_conversation(fp)
        assert len(loaded) == 2
        utterance_ids = [e.utterance_id for e in loaded]
        assert len(set(utterance_ids)) == 2


class TestCorrelateEventBridge:
    def test_end_to_end(
        self, deepgram_session_file: Path, eventbridge_jsonl_file: Path
    ):
        results = correlate_eventbridge(
            deepgram_session_file, eventbridge_jsonl_file
        )
        assert len(results) == 2
        # First: received at +5.5, audio ended at +4.5 → 1.0s
        assert results[0].true_latency_s == pytest.approx(1.0, abs=0.001)
        # Second: received at +8.0, audio ended at +7.0 → 1.0s
        assert results[1].true_latency_s == pytest.approx(1.0, abs=0.001)
