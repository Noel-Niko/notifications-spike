"""Tests for active conversation recovery and conversation time extraction."""

from __future__ import annotations

import json
import logging

import pytest

from main import (
    extract_active_conversation_ids,
    _conversation_times,
    build_analytics_query,
    extract_active_from_analytics,
)


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


# ---------------------------------------------------------------------------
# Tests for build_analytics_query (issue #8 fix)
# ---------------------------------------------------------------------------


class TestBuildAnalyticsQuery:
    def test_includes_interval(self):
        query = build_analytics_query({"agent-111"})
        assert "interval" in query
        # Interval should contain "/" separator (ISO 8601 interval format)
        assert "/" in query["interval"]

    def test_includes_paging(self):
        query = build_analytics_query({"agent-111"})
        assert query["paging"]["pageSize"] == 100
        assert query["paging"]["pageNumber"] == 1

    def test_includes_all_agent_user_ids_in_predicates(self):
        agent_ids = {"agent-111", "agent-222", "agent-333"}
        query = build_analytics_query(agent_ids)

        # Find the OR segment filter (user IDs)
        segment_filters = query["segmentFilters"]
        or_filter = next(f for f in segment_filters if f["type"] == "or")
        predicate_values = {p["value"] for p in or_filter["predicates"]}
        assert predicate_values == agent_ids

    def test_all_user_predicates_use_userId_dimension(self):
        query = build_analytics_query({"agent-111", "agent-222"})
        or_filter = next(f for f in query["segmentFilters"] if f["type"] == "or")
        for pred in or_filter["predicates"]:
            assert pred["dimension"] == "userId"
            assert pred["operator"] == "matches"
            assert pred["type"] == "dimension"

    def test_includes_purpose_agent_filter(self):
        query = build_analytics_query({"agent-111"})
        and_filter = next(f for f in query["segmentFilters"] if f["type"] == "and")
        purpose_pred = and_filter["predicates"][0]
        assert purpose_pred["dimension"] == "purpose"
        assert purpose_pred["value"] == "agent"

    def test_predicates_sorted_for_deterministic_output(self):
        """User IDs should be sorted so query body is deterministic (testable)."""
        query = build_analytics_query({"z-agent", "a-agent", "m-agent"})
        or_filter = next(f for f in query["segmentFilters"] if f["type"] == "or")
        values = [p["value"] for p in or_filter["predicates"]]
        assert values == ["a-agent", "m-agent", "z-agent"]

    def test_interval_covers_24_hours(self):
        query = build_analytics_query({"agent-111"})
        start_str, end_str = query["interval"].split("/")
        # Both should be valid ISO timestamps ending in .000Z
        assert start_str.endswith(".000Z")
        assert end_str.endswith(".000Z")


# ---------------------------------------------------------------------------
# Tests for extract_active_from_analytics (issue #8 fix)
# ---------------------------------------------------------------------------


def _make_analytics_conversation(
    conv_id: str,
    participants: list[dict],
    conv_end: str | None = None,
) -> dict:
    conv = {"conversationId": conv_id, "participants": participants}
    if conv_end is not None:
        conv["conversationEnd"] = conv_end
    return conv


def _make_analytics_participant(
    user_id: str,
    purpose: str = "agent",
    segments: list[dict] | None = None,
) -> dict:
    if segments is None:
        segments = []
    return {
        "userId": user_id,
        "purpose": purpose,
        "sessions": [{"segments": segments}],
    }


def _make_segment(
    seg_type: str = "interact",
    seg_end: str | None = None,
) -> dict:
    seg = {"segmentType": seg_type, "segmentStart": "2026-03-20T18:00:00.000Z"}
    if seg_end is not None:
        seg["segmentEnd"] = seg_end
    return seg


class TestExtractActiveFromAnalytics:
    def test_active_agent_segment_returns_conversation(self):
        conversations = [
            _make_analytics_conversation("conv-1", [
                _make_analytics_participant("agent-111", segments=[
                    _make_segment("interact"),  # no segmentEnd = active
                ]),
            ]),
        ]
        result = extract_active_from_analytics(conversations, AGENT_USER_IDS)
        assert result == {"conv-1"}

    def test_ended_agent_segment_returns_empty(self):
        conversations = [
            _make_analytics_conversation("conv-1", [
                _make_analytics_participant("agent-111", segments=[
                    _make_segment("interact", seg_end="2026-03-20T18:30:00.000Z"),
                ]),
            ]),
        ]
        result = extract_active_from_analytics(conversations, AGENT_USER_IDS)
        assert result == set()

    def test_conversation_with_conv_end_skipped(self):
        conversations = [
            _make_analytics_conversation(
                "conv-1",
                [_make_analytics_participant("agent-111", segments=[_make_segment("interact")])],
                conv_end="2026-03-20T18:30:00.000Z",
            ),
        ]
        result = extract_active_from_analytics(conversations, AGENT_USER_IDS)
        assert result == set()

    def test_mixed_active_and_ended(self):
        conversations = [
            _make_analytics_conversation("conv-active", [
                _make_analytics_participant("agent-111", segments=[_make_segment("interact")]),
            ]),
            _make_analytics_conversation("conv-ended", [
                _make_analytics_participant("agent-222", segments=[
                    _make_segment("interact", seg_end="2026-03-20T18:30:00.000Z"),
                ]),
            ]),
        ]
        result = extract_active_from_analytics(conversations, AGENT_USER_IDS)
        assert result == {"conv-active"}

    def test_unmonitored_agent_ignored(self):
        conversations = [
            _make_analytics_conversation("conv-1", [
                _make_analytics_participant("agent-999", segments=[_make_segment("interact")]),
            ]),
        ]
        result = extract_active_from_analytics(conversations, AGENT_USER_IDS)
        assert result == set()

    def test_non_agent_purpose_ignored(self):
        conversations = [
            _make_analytics_conversation("conv-1", [
                _make_analytics_participant("agent-111", purpose="customer", segments=[
                    _make_segment("interact"),
                ]),
            ]),
        ]
        result = extract_active_from_analytics(conversations, AGENT_USER_IDS)
        assert result == set()

    def test_empty_conversations_returns_empty(self):
        result = extract_active_from_analytics([], AGENT_USER_IDS)
        assert result == set()

    def test_connected_segment_type_also_active(self):
        """Both 'interact' and 'connected' segment types indicate active participation."""
        conversations = [
            _make_analytics_conversation("conv-1", [
                _make_analytics_participant("agent-111", segments=[
                    _make_segment("connected"),
                ]),
            ]),
        ]
        result = extract_active_from_analytics(conversations, AGENT_USER_IDS)
        assert result == {"conv-1"}

    def test_alert_segment_without_interact_not_active(self):
        """An 'alert' segment (ringing, not answered) should not count as active."""
        conversations = [
            _make_analytics_conversation("conv-1", [
                _make_analytics_participant("agent-111", segments=[
                    _make_segment("alert"),
                ]),
            ]),
        ]
        result = extract_active_from_analytics(conversations, AGENT_USER_IDS)
        assert result == set()

    def test_multiple_segments_with_one_active(self):
        """If agent has ended segments plus one active, conversation is active."""
        conversations = [
            _make_analytics_conversation("conv-1", [
                _make_analytics_participant("agent-111", segments=[
                    _make_segment("interact", seg_end="2026-03-20T18:10:00.000Z"),
                    _make_segment("interact"),  # active
                ]),
            ]),
        ]
        result = extract_active_from_analytics(conversations, AGENT_USER_IDS)
        assert result == {"conv-1"}

    def test_no_conversation_id_skipped(self):
        conversations = [{"participants": []}]
        result = extract_active_from_analytics(conversations, AGENT_USER_IDS)
        assert result == set()

    def test_debug_logs_active_segment(self, caplog):
        conversations = [
            _make_analytics_conversation("conv-debug", [
                _make_analytics_participant("agent-111", segments=[_make_segment("interact")]),
            ]),
        ]
        with caplog.at_level(logging.DEBUG, logger="transcript-recorder"):
            extract_active_from_analytics(conversations, AGENT_USER_IDS)

        debug_msgs = [r for r in caplog.records if r.levelno == logging.DEBUG]
        active_msgs = [m for m in debug_msgs if "active interact segment" in m.message]
        assert len(active_msgs) == 1
        assert "conv-debug" in active_msgs[0].message
        assert "agent-111" in active_msgs[0].message
