"""Tests for active conversation recovery and conversation time extraction."""

from __future__ import annotations

import json
import logging

import pytest

from main import extract_active_conversation_ids, _conversation_times


# ---------------------------------------------------------------------------
# Fixtures: Genesys GET /api/v2/conversations response shapes
# ---------------------------------------------------------------------------

AGENT_USER_IDS = {"agent-111", "agent-222"}


def _make_participant(
    user_id: str,
    purpose: str = "agent",
    connected_time: str | None = "2026-03-20T18:00:00Z",
    end_time: str | None = None,
    state: str | None = None,
) -> dict:
    p = {"userId": user_id, "purpose": purpose}
    if connected_time is not None:
        p["connectedTime"] = connected_time
    if end_time is not None:
        p["endTime"] = end_time
    if state is not None:
        p["state"] = state
    return p


def _make_conversation(conv_id: str, participants: list[dict]) -> dict:
    return {"id": conv_id, "participants": participants}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExtractActiveConversationIds:
    def test_returns_active_conversation(self):
        conversations = [
            _make_conversation("conv-1", [
                _make_participant("agent-111", connected_time="2026-03-20T18:00:00Z"),
                _make_participant("customer-999", purpose="customer"),
            ]),
        ]
        result = extract_active_conversation_ids(conversations, AGENT_USER_IDS)
        assert result == {"conv-1"}

    def test_ignores_ended_conversation(self):
        conversations = [
            _make_conversation("conv-1", [
                _make_participant(
                    "agent-111",
                    connected_time="2026-03-20T18:00:00Z",
                    end_time="2026-03-20T18:05:00Z",
                ),
            ]),
        ]
        result = extract_active_conversation_ids(conversations, AGENT_USER_IDS)
        assert result == set()

    def test_ignores_conversation_without_connected_time(self):
        conversations = [
            _make_conversation("conv-1", [
                _make_participant("agent-111", connected_time=None),
            ]),
        ]
        result = extract_active_conversation_ids(conversations, AGENT_USER_IDS)
        assert result == set()

    def test_ignores_conversation_for_unknown_agent(self):
        conversations = [
            _make_conversation("conv-1", [
                _make_participant("agent-999", connected_time="2026-03-20T18:00:00Z"),
            ]),
        ]
        result = extract_active_conversation_ids(conversations, AGENT_USER_IDS)
        assert result == set()

    def test_multiple_conversations_mixed(self):
        conversations = [
            # Active — agent-111 connected, no endTime
            _make_conversation("conv-active", [
                _make_participant("agent-111", connected_time="2026-03-20T18:00:00Z"),
            ]),
            # Ended — agent-222 has endTime
            _make_conversation("conv-ended", [
                _make_participant(
                    "agent-222",
                    connected_time="2026-03-20T17:00:00Z",
                    end_time="2026-03-20T17:30:00Z",
                ),
            ]),
            # Active — agent-222 connected, no endTime
            _make_conversation("conv-active-2", [
                _make_participant("agent-222", connected_time="2026-03-20T18:10:00Z"),
            ]),
            # Not our agent
            _make_conversation("conv-other", [
                _make_participant("agent-999", connected_time="2026-03-20T18:00:00Z"),
            ]),
        ]
        result = extract_active_conversation_ids(conversations, AGENT_USER_IDS)
        assert result == {"conv-active", "conv-active-2"}

    def test_empty_conversations_list(self):
        result = extract_active_conversation_ids([], AGENT_USER_IDS)
        assert result == set()

    def test_empty_agent_ids(self):
        conversations = [
            _make_conversation("conv-1", [
                _make_participant("agent-111", connected_time="2026-03-20T18:00:00Z"),
            ]),
        ]
        result = extract_active_conversation_ids(conversations, set())
        assert result == set()

    def test_non_agent_purpose_ignored(self):
        """Only participants with purpose 'agent' should trigger activation."""
        conversations = [
            _make_conversation("conv-1", [
                _make_participant("agent-111", purpose="customer", connected_time="2026-03-20T18:00:00Z"),
            ]),
        ]
        result = extract_active_conversation_ids(conversations, AGENT_USER_IDS)
        assert result == set()

    def test_already_tracked_still_returned(self):
        """The function is pure — it doesn't check active_conversations state."""
        conversations = [
            _make_conversation("conv-1", [
                _make_participant("agent-111", connected_time="2026-03-20T18:00:00Z"),
            ]),
        ]
        result = extract_active_conversation_ids(conversations, AGENT_USER_IDS)
        assert "conv-1" in result


# ---------------------------------------------------------------------------
# Tests for _conversation_times
# ---------------------------------------------------------------------------


class TestConversationTimes:
    def test_single_active_agent(self):
        event_body = {
            "participants": [
                _make_participant("agent-111", connected_time="2026-03-20T18:00:00Z"),
            ],
        }
        start, end = _conversation_times(event_body)
        assert start == "2026-03-20T18:00:00Z"
        assert end is None

    def test_single_ended_agent(self):
        event_body = {
            "participants": [
                _make_participant(
                    "agent-111",
                    connected_time="2026-03-20T18:00:00Z",
                    end_time="2026-03-20T18:05:00Z",
                ),
            ],
        }
        start, end = _conversation_times(event_body)
        assert start == "2026-03-20T18:00:00Z"
        assert end == "2026-03-20T18:05:00Z"

    def test_no_participants(self):
        start, end = _conversation_times({})
        assert start is None
        assert end is None

    def test_no_agent_participants(self):
        event_body = {
            "participants": [
                _make_participant("cust-1", purpose="customer", connected_time="2026-03-20T18:00:00Z"),
            ],
        }
        start, end = _conversation_times(event_body)
        assert start is None
        assert end is None

    def test_agent_without_connected_time(self):
        event_body = {
            "participants": [
                _make_participant("agent-111", connected_time=None),
            ],
        }
        start, end = _conversation_times(event_body)
        assert start is None
        assert end is None

    def test_rerouted_call_first_agent_failed_second_connected(self):
        """When first agent attempt fails and call is re-routed, prefer the connected agent."""
        event_body = {
            "participants": [
                # First agent attempt — never connected, then ended
                _make_participant("agent-111", connected_time=None, end_time="2026-03-20T18:01:00Z"),
                # Second agent attempt — connected and active
                _make_participant("agent-111", connected_time="2026-03-20T18:01:05Z"),
            ],
        }
        start, end = _conversation_times(event_body)
        assert start == "2026-03-20T18:01:05Z"
        assert end is None

    def test_rerouted_call_first_ended_second_active(self):
        """When first agent ended and second is active, prefer the active agent."""
        event_body = {
            "participants": [
                # First agent — connected then ended
                _make_participant(
                    "agent-111",
                    connected_time="2026-03-20T17:50:00Z",
                    end_time="2026-03-20T17:55:00Z",
                ),
                # Second agent — connected, still active
                _make_participant("agent-222", connected_time="2026-03-20T17:55:05Z"),
            ],
        }
        start, end = _conversation_times(event_body)
        assert start == "2026-03-20T17:55:05Z"
        assert end is None

    def test_all_agents_ended_returns_last(self):
        """When all agents have ended, return the last one that was connected."""
        event_body = {
            "participants": [
                _make_participant(
                    "agent-111",
                    connected_time="2026-03-20T17:50:00Z",
                    end_time="2026-03-20T17:55:00Z",
                ),
                _make_participant(
                    "agent-222",
                    connected_time="2026-03-20T17:55:05Z",
                    end_time="2026-03-20T18:00:00Z",
                ),
            ],
        }
        start, end = _conversation_times(event_body)
        # Should return the last connected agent (most recent connectedTime)
        assert start == "2026-03-20T17:55:05Z"
        assert end == "2026-03-20T18:00:00Z"

    def test_mixed_purposes_only_considers_agents(self):
        """Customer participants should be ignored even if they have connectedTime."""
        event_body = {
            "participants": [
                _make_participant("cust-1", purpose="customer", connected_time="2026-03-20T17:59:00Z"),
                _make_participant("agent-111", connected_time=None, end_time="2026-03-20T18:01:00Z"),
                _make_participant("agent-222", connected_time="2026-03-20T18:01:05Z"),
            ],
        }
        start, end = _conversation_times(event_body)
        assert start == "2026-03-20T18:01:05Z"
        assert end is None


# ---------------------------------------------------------------------------
# Tests for _conversation_times debug/warning logging (issue #7/#8 diagnostics)
# ---------------------------------------------------------------------------


class TestConversationTimesLogging:
    """Verify diagnostic logging added for issue #7 stuck-state debugging."""

    def test_warns_when_all_agents_ended(self, caplog):
        """When agents exist but all have endTime, emit a WARNING with participant dump."""
        event_body = {
            "id": "conv-stuck",
            "participants": [
                _make_participant(
                    "agent-111",
                    connected_time="2026-03-20T18:00:00Z",
                    end_time="2026-03-20T18:05:00Z",
                    state="disconnected",
                ),
            ],
        }
        with caplog.at_level(logging.WARNING, logger="transcript-recorder"):
            start, end = _conversation_times(event_body)

        assert start == "2026-03-20T18:00:00Z"
        assert end == "2026-03-20T18:05:00Z"

        warning_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_msgs) == 1
        assert "conv-stuck" in warning_msgs[0].message
        assert "no active agent found" in warning_msgs[0].message
        assert "agent-111" in warning_msgs[0].message

    def test_no_warning_when_active_agent_exists(self, caplog):
        """When an active agent is found, no warning should be emitted."""
        event_body = {
            "id": "conv-ok",
            "participants": [
                _make_participant("agent-111", connected_time="2026-03-20T18:00:00Z"),
            ],
        }
        with caplog.at_level(logging.WARNING, logger="transcript-recorder"):
            start, end = _conversation_times(event_body)

        assert start == "2026-03-20T18:00:00Z"
        assert end is None

        warning_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_msgs) == 0

    def test_no_warning_when_no_agent_participants(self, caplog):
        """When there are no agent participants at all, no warning (nothing to report)."""
        event_body = {
            "id": "conv-noagent",
            "participants": [
                _make_participant("cust-1", purpose="customer"),
            ],
        }
        with caplog.at_level(logging.WARNING, logger="transcript-recorder"):
            start, end = _conversation_times(event_body)

        assert start is None
        assert end is None

        warning_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_msgs) == 0

    def test_debug_logs_agent_participant_dump(self, caplog):
        """At DEBUG level, all agent participants should be dumped as JSON."""
        event_body = {
            "id": "conv-debug",
            "participants": [
                _make_participant(
                    "agent-111",
                    connected_time=None,
                    end_time="2026-03-20T18:01:00Z",
                    state="terminated",
                ),
                _make_participant(
                    "agent-222",
                    connected_time="2026-03-20T18:01:05Z",
                    state="connected",
                ),
            ],
        }
        with caplog.at_level(logging.DEBUG, logger="transcript-recorder"):
            start, end = _conversation_times(event_body)

        assert start == "2026-03-20T18:01:05Z"
        assert end is None

        debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        # Should have the participant dump + a skip message for agent-111
        dump_msgs = [m for m in debug_msgs if "agent participant(s)" in m.message]
        assert len(dump_msgs) == 1
        assert "2 agent participant(s)" in dump_msgs[0].message
        assert "agent-111" in dump_msgs[0].message
        assert "agent-222" in dump_msgs[0].message

        skip_msgs = [m for m in debug_msgs if "skipping agent" in m.message]
        assert len(skip_msgs) == 1
        assert "agent-111" in skip_msgs[0].message
        assert "terminated" in skip_msgs[0].message

    def test_debug_logs_include_state_field(self, caplog):
        """The state field from Genesys should appear in debug participant dumps."""
        event_body = {
            "id": "conv-state",
            "participants": [
                _make_participant(
                    "agent-111",
                    connected_time="2026-03-20T18:00:00Z",
                    state="connected",
                ),
            ],
        }
        with caplog.at_level(logging.DEBUG, logger="transcript-recorder"):
            _conversation_times(event_body)

        debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        dump_msgs = [m for m in debug_msgs if "agent participant(s)" in m.message]
        assert len(dump_msgs) == 1
        # Parse the JSON from the log message to verify state is included
        log_text = dump_msgs[0].message
        json_start = log_text.index("[")
        participants_json = json.loads(log_text[json_start:])
        assert participants_json[0]["state"] == "connected"

    def test_warns_with_multiple_ended_agents_dumps_all(self, caplog):
        """Warning should include all agent participants for diagnosis."""
        event_body = {
            "id": "conv-multi-ended",
            "participants": [
                _make_participant(
                    "agent-111",
                    connected_time="2026-03-20T17:50:00Z",
                    end_time="2026-03-20T17:55:00Z",
                    state="disconnected",
                ),
                _make_participant(
                    "agent-222",
                    connected_time="2026-03-20T17:55:05Z",
                    end_time="2026-03-20T18:00:00Z",
                    state="disconnected",
                ),
            ],
        }
        with caplog.at_level(logging.WARNING, logger="transcript-recorder"):
            start, end = _conversation_times(event_body)

        assert start == "2026-03-20T17:55:05Z"
        assert end == "2026-03-20T18:00:00Z"

        warning_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_msgs) == 1
        assert "agent-111" in warning_msgs[0].message
        assert "agent-222" in warning_msgs[0].message

    def test_missed_call_no_connected_time_has_end_time(self, caplog):
        """Simulate exact issue #7 scenario: agent alerting timed out, no connectedTime, has endTime."""
        event_body = {
            "id": "conv-missed",
            "participants": [
                _make_participant(
                    "agent-111",
                    connected_time=None,
                    end_time="2026-03-20T19:45:00Z",
                    state="terminated",
                ),
            ],
        }
        with caplog.at_level(logging.DEBUG, logger="transcript-recorder"):
            start, end = _conversation_times(event_body)

        # No connectedTime means function returns (None, None)
        assert start is None
        assert end is None

        # Should have debug skip message
        debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        skip_msgs = [m for m in debug_msgs if "skipping agent" in m.message]
        assert len(skip_msgs) == 1
        assert "no connectedTime" in skip_msgs[0].message

    def test_missed_call_then_rerouted_second_alerting(self, caplog):
        """Issue #7 mid-state: first agent timed out, second alerting (not yet connected)."""
        event_body = {
            "id": "conv-reroute-alerting",
            "participants": [
                _make_participant(
                    "agent-111",
                    connected_time=None,
                    end_time="2026-03-20T19:45:00Z",
                    state="terminated",
                ),
                _make_participant(
                    "agent-111",
                    connected_time=None,
                    state="alerting",
                ),
            ],
        }
        with caplog.at_level(logging.DEBUG, logger="transcript-recorder"):
            start, end = _conversation_times(event_body)

        # Neither participant has connectedTime
        assert start is None
        assert end is None

        debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        skip_msgs = [m for m in debug_msgs if "skipping agent" in m.message]
        assert len(skip_msgs) == 2

    def test_missed_call_then_rerouted_second_connected(self, caplog):
        """Issue #7 recovery state: first timed out, second now connected."""
        event_body = {
            "id": "conv-reroute-connected",
            "participants": [
                _make_participant(
                    "agent-111",
                    connected_time=None,
                    end_time="2026-03-20T19:45:00Z",
                    state="terminated",
                ),
                _make_participant(
                    "agent-111",
                    connected_time="2026-03-20T19:46:00Z",
                    state="connected",
                ),
            ],
        }
        with caplog.at_level(logging.WARNING, logger="transcript-recorder"):
            start, end = _conversation_times(event_body)

        # Should find the connected participant
        assert start == "2026-03-20T19:46:00Z"
        assert end is None

        # No warning because an active agent was found
        warning_msgs = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warning_msgs) == 0
