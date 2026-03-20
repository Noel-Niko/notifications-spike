"""Tests for active conversation recovery and conversation time extraction."""

from __future__ import annotations

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
) -> dict:
    p = {"userId": user_id, "purpose": purpose}
    if connected_time is not None:
        p["connectedTime"] = connected_time
    if end_time is not None:
        p["endTime"] = end_time
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
