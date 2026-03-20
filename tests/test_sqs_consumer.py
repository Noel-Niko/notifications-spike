"""Tests for SQS consumer — parse and save EventBridge events."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.sqs_consumer import parse_sqs_message, save_event


# ---------------------------------------------------------------------------
# Fixtures: realistic EventBridge event from SQS
# ---------------------------------------------------------------------------

SAMPLE_EB_EVENT: dict = {
    "version": "0",
    "id": "6efd5506-abcd-1234-efgh-567890abcdef",
    "detail-type": "v2.conversations.97b9dcb3-1111-2222-3333-444455556666.transcription",
    "source": "aws.partner/genesys.com/cloud/o-abc123/DA-VOICE-SB",
    "time": "2026-03-19T22:04:48Z",
    "detail": {
        "eventBody": {
            "eventTime": "2026-03-19T22:04:48.128Z",
            "conversationId": "97b9dcb3-1111-2222-3333-444455556666",
            "communicationId": "7dd98c4f-aaaa-bbbb-cccc-ddddeeee0001",
            "sessionStartTimeMs": 1773957594383,
            "transcriptionStartTimeMs": 1773957594336,
            "transcripts": [
                {
                    "utteranceId": "5b778cb0-0001-0001-0001-000000000001",
                    "isFinal": True,
                    "channel": "EXTERNAL",
                    "alternatives": [
                        {
                            "confidence": 0.658,
                            "offsetMs": 278620,
                            "durationMs": 12480,
                            "transcript": "thank you for calling grainger",
                            "decoratedTranscript": "Thank you for calling Grainger.",
                        }
                    ],
                    "engineProvider": "GENESYS",
                    "engineId": "r2d2",
                }
            ],
        },
        "metadata": {"CorrelationId": "abc-123-correlation"},
    },
}

RECEIVED_AT = 1773957600.123
SQS_SENT_TIMESTAMP = 1773957599800


# ---------------------------------------------------------------------------
# Tests: parse_sqs_message
# ---------------------------------------------------------------------------


class TestParseSqsMessage:
    def test_extracts_conversation_id(self):
        parsed = parse_sqs_message(
            json.dumps(SAMPLE_EB_EVENT), RECEIVED_AT, SQS_SENT_TIMESTAMP
        )
        assert parsed["conversationId"] == "97b9dcb3-1111-2222-3333-444455556666"

    def test_extracts_received_at(self):
        parsed = parse_sqs_message(
            json.dumps(SAMPLE_EB_EVENT), RECEIVED_AT, SQS_SENT_TIMESTAMP
        )
        assert parsed["receivedAt"] == pytest.approx(RECEIVED_AT)

    def test_extracts_sqs_sent_timestamp(self):
        parsed = parse_sqs_message(
            json.dumps(SAMPLE_EB_EVENT), RECEIVED_AT, SQS_SENT_TIMESTAMP
        )
        assert parsed["sqsSentTimestamp"] == SQS_SENT_TIMESTAMP

    def test_extracts_session_start_time_ms(self):
        parsed = parse_sqs_message(
            json.dumps(SAMPLE_EB_EVENT), RECEIVED_AT, SQS_SENT_TIMESTAMP
        )
        assert parsed["sessionStartTimeMs"] == 1773957594383

    def test_extracts_eb_time(self):
        parsed = parse_sqs_message(
            json.dumps(SAMPLE_EB_EVENT), RECEIVED_AT, SQS_SENT_TIMESTAMP
        )
        assert parsed["ebTime"] == "2026-03-19T22:04:48Z"

    def test_extracts_genesys_event_time(self):
        parsed = parse_sqs_message(
            json.dumps(SAMPLE_EB_EVENT), RECEIVED_AT, SQS_SENT_TIMESTAMP
        )
        assert parsed["genesysEventTime"] == "2026-03-19T22:04:48.128Z"

    def test_extracts_transcripts(self):
        parsed = parse_sqs_message(
            json.dumps(SAMPLE_EB_EVENT), RECEIVED_AT, SQS_SENT_TIMESTAMP
        )
        assert isinstance(parsed["transcripts"], list)
        assert len(parsed["transcripts"]) == 1
        assert parsed["transcripts"][0]["utteranceId"] == "5b778cb0-0001-0001-0001-000000000001"
        assert parsed["transcripts"][0]["alternatives"][0]["transcript"] == "thank you for calling grainger"

    def test_includes_raw_event(self):
        parsed = parse_sqs_message(
            json.dumps(SAMPLE_EB_EVENT), RECEIVED_AT, SQS_SENT_TIMESTAMP
        )
        assert parsed["rawEvent"] == SAMPLE_EB_EVENT

    def test_handles_none_sqs_sent_timestamp(self):
        parsed = parse_sqs_message(
            json.dumps(SAMPLE_EB_EVENT), RECEIVED_AT, None
        )
        assert parsed["sqsSentTimestamp"] is None


# ---------------------------------------------------------------------------
# Tests: save_event
# ---------------------------------------------------------------------------


class TestSaveEvent:
    def test_creates_output_dir_and_file(self, tmp_path: Path):
        output_dir = tmp_path / "eb_events"
        parsed = parse_sqs_message(
            json.dumps(SAMPLE_EB_EVENT), RECEIVED_AT, SQS_SENT_TIMESTAMP
        )
        result_path = save_event(parsed, output_dir)

        assert output_dir.exists()
        assert result_path.exists()
        assert result_path.name == "97b9dcb3-1111-2222-3333-444455556666.jsonl"

    def test_appends_to_existing_file(self, tmp_path: Path):
        output_dir = tmp_path / "eb_events"
        parsed = parse_sqs_message(
            json.dumps(SAMPLE_EB_EVENT), RECEIVED_AT, SQS_SENT_TIMESTAMP
        )

        # Save twice
        save_event(parsed, output_dir)
        save_event(parsed, output_dir)

        result_path = output_dir / "97b9dcb3-1111-2222-3333-444455556666.jsonl"
        lines = result_path.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_each_line_is_valid_json(self, tmp_path: Path):
        output_dir = tmp_path / "eb_events"
        parsed = parse_sqs_message(
            json.dumps(SAMPLE_EB_EVENT), RECEIVED_AT, SQS_SENT_TIMESTAMP
        )
        save_event(parsed, output_dir)

        result_path = output_dir / "97b9dcb3-1111-2222-3333-444455556666.jsonl"
        for line in result_path.read_text().strip().splitlines():
            data = json.loads(line)
            assert "conversationId" in data
            assert "receivedAt" in data
            assert "transcripts" in data
            assert "sqsSentTimestamp" in data
            assert "ebTime" in data
            assert "genesysEventTime" in data
            assert "sessionStartTimeMs" in data
            assert "rawEvent" in data
