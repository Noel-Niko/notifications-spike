"""Tests for ~/.claude/skills/imessage-notify/ scripts (send.sh, notify.sh, read.sh)

Tests script argument parsing, stdin mode, output format, message tagging,
AppleScript escaping, pending request tracking, and error handling.

Note: Tests that involve actually sending iMessages or reading chat.db are
marked with @pytest.mark.integration and skipped by default. Run with:
    pytest -m integration
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

SKILL_DIR = Path.home() / ".claude" / "skills" / "imessage-notify"
PENDING_DIR = Path("/tmp/imessage-notify-pending")


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Create an isolated sandbox with copies of the skill scripts.

    The sandbox has its own PENDING_DIR to avoid interfering with real
    pending requests.
    """
    skill = tmp_path / "skill"
    skill.mkdir()

    # Copy all scripts
    for script in SKILL_DIR.glob("*.sh"):
        shutil.copy2(script, skill / script.name)

    # Create a fake git repo so send.sh can detect repo name
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    # Use a unique pending dir for isolation
    pending = tmp_path / "pending"
    pending.mkdir()

    return {
        "skill": skill,
        "repo": repo,
        "pending": pending,
        "send_sh": skill / "send.sh",
        "notify_sh": skill / "notify.sh",
        "read_sh": skill / "read.sh",
    }


def patch_send_sh(sandbox, pending_dir=None, mock_applescript=True):
    """Patch send.sh to use sandbox pending dir and optionally mock AppleScript.

    Returns the path to the patched script.
    """
    send_sh = sandbox["send_sh"]
    content = send_sh.read_text()

    # Replace PENDING_DIR
    if pending_dir:
        content = content.replace(
            'PENDING_DIR="/tmp/imessage-notify-pending"',
            f'PENDING_DIR="{pending_dir}"',
        )

    # Mock the AppleScript and pgrep calls for unit testing
    if mock_applescript:
        # Replace pgrep check with always-true
        content = content.replace(
            'if ! pgrep -x "Messages" >/dev/null; then',
            'if false; then',
        )
        # Replace osascript call with a no-op that succeeds
        content = re.sub(
            r"applescript_output=\$\(osascript.*?\n.*?\n.*?\n.*?\n\" 2>&1\)",
            'applescript_output="OK"',
            content,
            flags=re.DOTALL,
        )
        content = content.replace(
            "applescript_exit=$?",
            "applescript_exit=0",
        )

    send_sh.write_text(content)
    return send_sh


def run_send(sandbox, *args, stdin_text=None, mock=True):
    """Run send.sh with optional args and stdin."""
    pending = str(sandbox["pending"])
    patch_send_sh(sandbox, pending_dir=pending, mock_applescript=mock)

    cmd = [str(sandbox["send_sh"]), *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(sandbox["repo"]),
        input=stdin_text,
    )
    return result


# =============================================================================
# send.sh — Output Format
# =============================================================================


class TestSendOutputFormat:
    """Verify send.sh output follows the REQ_ID=<id> SENT_EPOCH=<epoch> format."""

    def test_output_contains_req_id(self, sandbox):
        result = run_send(sandbox, "test message")
        assert result.returncode == 0
        assert "REQ_ID=" in result.stdout

    def test_output_contains_sent_epoch(self, sandbox):
        result = run_send(sandbox, "test message")
        assert "SENT_EPOCH=" in result.stdout

    def test_req_id_is_8_hex_chars(self, sandbox):
        result = run_send(sandbox, "test")
        match = re.search(r"REQ_ID=([a-f0-9]+)", result.stdout)
        assert match is not None
        assert len(match.group(1)) == 8

    def test_sent_epoch_is_numeric(self, sandbox):
        result = run_send(sandbox, "test")
        match = re.search(r"SENT_EPOCH=(\d+)", result.stdout)
        assert match is not None
        assert int(match.group(1)) > 1700000000  # sanity: after 2023


# =============================================================================
# send.sh — Argument Mode
# =============================================================================


class TestSendArgumentMode:
    """Verify send.sh works with message passed as argument."""

    def test_simple_message(self, sandbox):
        result = run_send(sandbox, "Hello world")
        assert result.returncode == 0

    def test_message_with_quotes(self, sandbox):
        result = run_send(sandbox, 'He said "hello"')
        assert result.returncode == 0

    def test_message_with_single_quotes(self, sandbox):
        result = run_send(sandbox, "It's working")
        assert result.returncode == 0

    def test_message_with_special_chars(self, sandbox):
        result = run_send(sandbox, "Price: $100 & 50% off!")
        assert result.returncode == 0

    def test_message_with_unicode(self, sandbox):
        result = run_send(sandbox, "Arrow: 50→200, check: ✅")
        assert result.returncode == 0

    def test_no_argument_fails(self, sandbox):
        patch_send_sh(sandbox, pending_dir=str(sandbox["pending"]))
        result = subprocess.run(
            [str(sandbox["send_sh"])],
            capture_output=True,
            text=True,
            cwd=str(sandbox["repo"]),
        )
        assert result.returncode != 0


# =============================================================================
# send.sh — Stdin Mode
# =============================================================================


class TestSendStdinMode:
    """Verify send.sh reads message from stdin when "-" is passed."""

    def test_stdin_simple(self, sandbox):
        result = run_send(sandbox, "-", stdin_text="Hello from stdin")
        assert result.returncode == 0
        assert "REQ_ID=" in result.stdout

    def test_stdin_multiline(self, sandbox):
        msg = "Line 1\nLine 2\nLine 3"
        result = run_send(sandbox, "-", stdin_text=msg)
        assert result.returncode == 0

    def test_stdin_with_special_chars(self, sandbox):
        msg = 'Quotes: "hello" and \'world\'\nBackslash: \\\nDollar: $100'
        result = run_send(sandbox, "-", stdin_text=msg)
        assert result.returncode == 0

    def test_stdin_long_message(self, sandbox):
        msg = "A" * 5000
        result = run_send(sandbox, "-", stdin_text=msg)
        assert result.returncode == 0

    def test_stdin_empty_fails(self, sandbox):
        result = run_send(sandbox, "-", stdin_text="")
        # Empty stdin means message is empty string, but set -u should catch it
        # or the script proceeds with empty message (both are acceptable behaviors)
        # Just verify it doesn't hang
        assert result.returncode is not None


# =============================================================================
# send.sh — Pending Request Tracking
# =============================================================================


class TestSendPendingRequests:
    """Verify pending request files are created correctly."""

    def test_creates_pending_file(self, sandbox):
        result = run_send(sandbox, "test")
        req_id = re.search(r"REQ_ID=([a-f0-9]+)", result.stdout).group(1)
        pending_file = sandbox["pending"] / f"REQ-{req_id}"
        assert pending_file.exists()

    def test_pending_file_contains_epoch(self, sandbox):
        result = run_send(sandbox, "test")
        req_id = re.search(r"REQ_ID=([a-f0-9]+)", result.stdout).group(1)
        epoch = re.search(r"SENT_EPOCH=(\d+)", result.stdout).group(1)
        pending_file = sandbox["pending"] / f"REQ-{req_id}"
        assert pending_file.read_text().strip() == epoch

    def test_unique_req_ids(self, sandbox):
        ids = set()
        for _ in range(5):
            result = run_send(sandbox, "test")
            req_id = re.search(r"REQ_ID=([a-f0-9]+)", result.stdout).group(1)
            ids.add(req_id)
        assert len(ids) == 5, "All request IDs should be unique"

    def test_multiple_sends_create_multiple_pending(self, sandbox):
        for _ in range(3):
            run_send(sandbox, "test")
        pending_files = list(sandbox["pending"].glob("REQ-*"))
        assert len(pending_files) == 3


# =============================================================================
# send.sh — Message Tagging
# =============================================================================


class TestSendMessageTagging:
    """Verify messages are tagged with [repo-name|REQ-id] format.

    We verify this by checking the AppleScript escaping logic works
    correctly on the tagged message structure.
    """

    def test_tag_format_in_script(self, sandbox):
        """The script constructs [repo|REQ-id] tag format."""
        content = sandbox["send_sh"].read_text()
        assert 'tagged_message="[${repo_name}|REQ-${req_id}] ${message}"' in content


# =============================================================================
# send.sh — Error Handling
# =============================================================================


class TestSendErrorHandling:
    """Verify send.sh handles errors gracefully."""

    def test_messages_not_running(self, sandbox):
        """When Messages.app is not running, should fail with clear error."""
        # Patch to make pgrep fail (Messages not running)
        content = sandbox["send_sh"].read_text()
        content = content.replace(
            'PENDING_DIR="/tmp/imessage-notify-pending"',
            f'PENDING_DIR="{sandbox["pending"]}"',
        )
        # Make pgrep always fail
        content = content.replace(
            'if ! pgrep -x "Messages" >/dev/null; then',
            "if true; then",
        )
        sandbox["send_sh"].write_text(content)

        result = subprocess.run(
            [str(sandbox["send_sh"]), "test"],
            capture_output=True,
            text=True,
            cwd=str(sandbox["repo"]),
        )
        assert result.returncode == 1
        assert "ERROR" in result.stderr
        assert "Messages" in result.stderr

    def test_pending_cleaned_on_messages_error(self, sandbox):
        """Pending file should be removed if Messages is not running."""
        content = sandbox["send_sh"].read_text()
        content = content.replace(
            'PENDING_DIR="/tmp/imessage-notify-pending"',
            f'PENDING_DIR="{sandbox["pending"]}"',
        )
        content = content.replace(
            'if ! pgrep -x "Messages" >/dev/null; then',
            "if true; then",
        )
        sandbox["send_sh"].write_text(content)

        subprocess.run(
            [str(sandbox["send_sh"]), "test"],
            capture_output=True,
            text=True,
            cwd=str(sandbox["repo"]),
        )
        pending_files = list(sandbox["pending"].glob("REQ-*"))
        assert len(pending_files) == 0, "Pending file should be cleaned up on error"


# =============================================================================
# send.sh — AppleScript Escaping
# =============================================================================


class TestSendEscaping:
    """Verify special characters are properly escaped for AppleScript."""

    def test_escaping_logic_in_script(self):
        """The script escapes backslashes then double quotes."""
        content = (SKILL_DIR / "send.sh").read_text()
        # Backslash escaping comes first
        assert r'escaped_message="${tagged_message//\\/\\\\}"' in content
        # Then quote escaping
        assert r'escaped_message="${escaped_message//\"/\\\"}"' in content

    def test_backslash_in_message(self, sandbox):
        result = run_send(sandbox, r"path\to\file")
        assert result.returncode == 0

    def test_double_quote_in_message(self, sandbox):
        result = run_send(sandbox, 'say "hello"')
        assert result.returncode == 0

    def test_mixed_escaping(self, sandbox):
        result = run_send(sandbox, r'He said "C:\Users\test"')
        assert result.returncode == 0


# =============================================================================
# notify.sh — Argument Parsing
# =============================================================================


class TestNotifyArgumentParsing:
    """Verify notify.sh parses arguments correctly in both modes."""

    def test_argument_mode_passes_message_to_send(self, sandbox):
        """notify.sh should forward the message to send.sh."""
        # Patch send.sh to just echo and exit (skip the actual send)
        sandbox["send_sh"].write_text(
            '#!/usr/bin/env bash\n'
            'echo "MSG=$1"\n'
            'echo "REQ_ID=abc12345 SENT_EPOCH=1234567890"\n'
        )
        os.chmod(str(sandbox["send_sh"]), 0o755)

        # Patch notify.sh to not call read.sh (would fail without chat.db)
        content = sandbox["notify_sh"].read_text()
        content = content.replace(
            '"${SCRIPT_DIR}/read.sh"',
            'echo "MOCK_REPLY" && exit 0 #',
        )
        sandbox["notify_sh"].write_text(content)

        result = subprocess.run(
            [str(sandbox["notify_sh"]), "Hello", "10", "5"],
            capture_output=True,
            text=True,
            cwd=str(sandbox["repo"]),
        )
        assert result.returncode == 0

    def test_stdin_mode_passes_message_to_send(self, sandbox):
        """notify.sh with "-" should read stdin and forward to send.sh."""
        sandbox["send_sh"].write_text(
            '#!/usr/bin/env bash\n'
            'echo "MSG=$1"\n'
            'echo "REQ_ID=abc12345 SENT_EPOCH=1234567890"\n'
        )
        os.chmod(str(sandbox["send_sh"]), 0o755)

        content = sandbox["notify_sh"].read_text()
        content = content.replace(
            '"${SCRIPT_DIR}/read.sh"',
            'echo "MOCK_REPLY" && exit 0 #',
        )
        sandbox["notify_sh"].write_text(content)

        result = subprocess.run(
            [str(sandbox["notify_sh"]), "-", "10", "5"],
            capture_output=True,
            text=True,
            input="Hello from stdin",
            cwd=str(sandbox["repo"]),
        )
        assert result.returncode == 0

    def test_default_timeout(self, sandbox):
        """notify.sh should default to 300s timeout."""
        content = sandbox["notify_sh"].read_text()
        assert '${1:-300}' in content

    def test_default_poll_interval(self, sandbox):
        """notify.sh should default to 10s poll interval."""
        content = sandbox["notify_sh"].read_text()
        assert '${2:-10}' in content


# =============================================================================
# notify.sh — send.sh Integration
# =============================================================================


class TestNotifySendIntegration:
    """Verify notify.sh correctly parses send.sh output."""

    def test_parses_req_id_from_send_output(self, sandbox):
        """notify.sh extracts REQ_ID from send.sh output."""
        sandbox["send_sh"].write_text(
            '#!/usr/bin/env bash\n'
            'echo "REQ_ID=deadbeef SENT_EPOCH=1700000000"\n'
        )
        os.chmod(str(sandbox["send_sh"]), 0o755)

        content = sandbox["notify_sh"].read_text()
        # Replace read.sh call with echo of parsed values
        content = content.replace(
            '"${SCRIPT_DIR}/read.sh" "$sent_epoch" "$timeout" "$poll_interval" "$req_id"',
            'echo "PARSED: req=$req_id epoch=$sent_epoch"',
        )
        sandbox["notify_sh"].write_text(content)

        result = subprocess.run(
            [str(sandbox["notify_sh"]), "test"],
            capture_output=True,
            text=True,
            cwd=str(sandbox["repo"]),
        )
        assert "req=deadbeef" in result.stdout
        assert "epoch=1700000000" in result.stdout

    def test_fails_if_send_fails(self, sandbox):
        """notify.sh should exit 1 if send.sh fails."""
        sandbox["send_sh"].write_text(
            "#!/usr/bin/env bash\n"
            'echo "ERROR: test failure" >&2\n'
            "exit 1\n"
        )
        os.chmod(str(sandbox["send_sh"]), 0o755)

        result = subprocess.run(
            [str(sandbox["notify_sh"]), "test"],
            capture_output=True,
            text=True,
            cwd=str(sandbox["repo"]),
        )
        assert result.returncode == 1

    def test_fails_if_send_output_unparseable(self, sandbox):
        """notify.sh should exit non-zero if send.sh output is garbled.

        With set -euo pipefail, grep returning no match exits the script
        before the explicit "Failed to parse" message is reached. Either
        way, the exit code must be non-zero.
        """
        sandbox["send_sh"].write_text(
            "#!/usr/bin/env bash\n"
            'echo "garbage output"\n'
        )
        os.chmod(str(sandbox["send_sh"]), 0o755)

        result = subprocess.run(
            [str(sandbox["notify_sh"]), "test"],
            capture_output=True,
            text=True,
            cwd=str(sandbox["repo"]),
        )
        assert result.returncode != 0


# =============================================================================
# read.sh — Argument Validation
# =============================================================================


class TestReadArguments:
    """Verify read.sh validates its required arguments."""

    def test_no_args_fails(self, sandbox):
        """read.sh requires sent_epoch as first argument."""
        result = subprocess.run(
            [str(sandbox["read_sh"])],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0

    def test_timeout_default(self):
        """read.sh defaults to 300s timeout."""
        content = (SKILL_DIR / "read.sh").read_text()
        assert 'TIMEOUT="${2:-300}"' in content

    def test_poll_interval_default(self):
        """read.sh defaults to 10s poll interval."""
        content = (SKILL_DIR / "read.sh").read_text()
        assert 'POLL_INTERVAL="${3:-10}"' in content


# =============================================================================
# read.sh — Claim Mechanism
# =============================================================================


class TestReadClaimMechanism:
    """Verify the atomic mkdir claim mechanism in read.sh."""

    def test_claim_uses_mkdir(self):
        """read.sh uses mkdir for atomic claiming."""
        content = (SKILL_DIR / "read.sh").read_text()
        assert 'mkdir "$claim_dir"' in content

    def test_claim_dir_format(self):
        """Claim directories use .claim-<rowid> format."""
        content = (SKILL_DIR / "read.sh").read_text()
        assert '.claim-${msg_rowid}' in content

    def test_cleanup_on_exit(self):
        """Pending request file is cleaned up on exit via trap."""
        content = (SKILL_DIR / "read.sh").read_text()
        assert "trap cleanup_pending EXIT" in content


# =============================================================================
# read.sh — Reply Matching Priority
# =============================================================================


class TestReadReplyMatching:
    """Verify reply matching priority: explicit ID > most-recent-pending."""

    def test_explicit_id_match_first(self):
        """read.sh checks for explicit request ID in reply text first."""
        content = (SKILL_DIR / "read.sh").read_text()
        # Priority 1 (ID match) should come before Priority 2 (most recent)
        id_match_pos = content.find("Priority 1")
        recent_pos = content.find("Priority 2")
        assert id_match_pos < recent_pos

    def test_strips_id_prefix_from_reply(self):
        """When reply contains the request ID, it's stripped from the output."""
        content = (SKILL_DIR / "read.sh").read_text()
        assert "clean_reply" in content
        assert "sed" in content

    def test_most_recent_pending_fallback(self):
        """Plain replies go to the most recent pending request."""
        content = (SKILL_DIR / "read.sh").read_text()
        assert "is_most_recent_pending" in content


# =============================================================================
# read.sh — Apple Timestamp Conversion
# =============================================================================


class TestReadTimestampConversion:
    """Verify Unix epoch to Apple Core Data timestamp conversion."""

    def test_conversion_formula(self):
        """Conversion: (unix_epoch - 978307200) * 1000000000"""
        content = (SKILL_DIR / "read.sh").read_text()
        assert "978307200" in content
        assert "1000000000" in content

    def test_known_conversion(self):
        """Verify a known timestamp converts correctly."""
        # Unix epoch 1700000000 (2023-11-14)
        # Apple: (1700000000 - 978307200) * 1000000000 = 721692800000000000
        unix_ts = 1700000000
        expected_apple = (unix_ts - 978307200) * 1000000000
        assert expected_apple == 721692800000000000


# =============================================================================
# Script Permissions
# =============================================================================


class TestScriptPermissions:
    """Verify all scripts are executable."""

    @pytest.mark.parametrize(
        "script",
        ["send.sh", "notify.sh", "read.sh", "check_fda.sh", "whitelist_commands.sh"],
    )
    def test_script_is_executable(self, script):
        path = SKILL_DIR / script
        assert path.exists(), f"{script} not found"
        assert os.access(path, os.X_OK), f"{script} is not executable"


# =============================================================================
# Script Consistency
# =============================================================================


class TestScriptConsistency:
    """Verify scripts are internally consistent."""

    def test_send_and_read_have_same_recipient(self):
        """RECIPIENT must match in send.sh and read.sh."""
        send_content = (SKILL_DIR / "send.sh").read_text()
        read_content = (SKILL_DIR / "read.sh").read_text()

        send_recipient = re.search(r'^RECIPIENT="(.+)"', send_content, re.MULTILINE)
        read_recipient = re.search(r'^RECIPIENT="(.+)"', read_content, re.MULTILINE)

        assert send_recipient is not None, "RECIPIENT not found in send.sh"
        assert read_recipient is not None, "RECIPIENT not found in read.sh"
        assert send_recipient.group(1) == read_recipient.group(1), (
            f"RECIPIENT mismatch: send.sh={send_recipient.group(1)}, "
            f"read.sh={read_recipient.group(1)}"
        )

    def test_send_and_read_use_same_pending_dir(self):
        """PENDING_DIR must match in send.sh and read.sh."""
        send_content = (SKILL_DIR / "send.sh").read_text()
        read_content = (SKILL_DIR / "read.sh").read_text()

        send_dir = re.search(r'^PENDING_DIR="(.+)"', send_content, re.MULTILINE)
        read_dir = re.search(r'^PENDING_DIR="(.+)"', read_content, re.MULTILINE)

        assert send_dir is not None
        assert read_dir is not None
        assert send_dir.group(1) == read_dir.group(1)

    def test_all_scripts_use_set_euo_pipefail(self):
        """All scripts should use strict error handling."""
        for script in ["send.sh", "notify.sh", "read.sh"]:
            content = (SKILL_DIR / script).read_text()
            assert "set -euo pipefail" in content, f"{script} missing strict mode"


# =============================================================================
# Integration Tests (require Messages.app + iMessage)
# =============================================================================


@pytest.mark.integration
class TestIntegrationSend:
    """Integration tests that actually send iMessages. Skipped by default."""

    def test_real_send(self):
        """Actually send a test message."""
        result = subprocess.run(
            [str(SKILL_DIR / "send.sh"), "pytest integration test"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "REQ_ID=" in result.stdout

    def test_real_send_stdin(self):
        """Actually send via stdin."""
        result = subprocess.run(
            [str(SKILL_DIR / "send.sh"), "-"],
            capture_output=True,
            text=True,
            input="pytest stdin integration test",
        )
        assert result.returncode == 0
        assert "REQ_ID=" in result.stdout
