"""Tests for ~/.claude/skills/imessage-notify/whitelist_commands.sh

Verifies phone number normalization, permission injection, RECIPIENT
configuration, idempotency, and edge cases.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

SKILL_DIR = Path.home() / ".claude" / "skills" / "imessage-notify"
WHITELIST_SCRIPT = SKILL_DIR / "whitelist_commands.sh"

EXPECTED_PERMISSIONS = [
    "Bash(~/.claude/skills/imessage-notify/notify.sh *)",
    "Bash(~/.claude/skills/imessage-notify/send.sh *)",
    "Bash(~/.claude/skills/imessage-notify/read.sh *)",
    "Bash(~/.claude/skills/imessage-notify/check_fda.sh)",
]


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Create an isolated sandbox with a fake repo and fake skill dir.

    Yields a dict with paths to key locations. The real send.sh/read.sh
    are NOT modified — copies are used instead.
    """
    repo = tmp_path / "fake-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    home = tmp_path / "home"
    home.mkdir()

    skill = home / ".claude" / "skills" / "imessage-notify"
    skill.mkdir(parents=True)

    # Copy real scripts into sandbox skill dir
    for script in ["send.sh", "read.sh", "notify.sh", "check_fda.sh"]:
        src = SKILL_DIR / script
        if src.exists():
            shutil.copy2(src, skill / script)

    # Copy whitelist_commands.sh itself
    shutil.copy2(WHITELIST_SCRIPT, skill / "whitelist_commands.sh")

    # Global settings location
    global_settings = home / ".claude" / "settings.json"

    monkeypatch.setenv("HOME", str(home))

    return {
        "repo": repo,
        "home": home,
        "skill": skill,
        "script": skill / "whitelist_commands.sh",
        "global_settings": global_settings,
        "local_settings": repo / ".claude" / "settings.local.json",
        "send_sh": skill / "send.sh",
        "read_sh": skill / "read.sh",
    }


def run_whitelist(sandbox, *args, expect_fail=False):
    """Run whitelist_commands.sh in the sandbox repo with optional args."""
    result = subprocess.run(
        [str(sandbox["script"]), *args],
        capture_output=True,
        text=True,
        cwd=str(sandbox["repo"]),
        env={**os.environ, "HOME": str(sandbox["home"])},
    )
    if not expect_fail:
        assert result.returncode == 0, (
            f"Script failed (exit {result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    return result


def read_settings(path):
    """Read and parse a settings JSON file."""
    with open(path) as f:
        return json.load(f)


def get_recipient(script_path):
    """Extract the RECIPIENT value from a script file."""
    for line in script_path.read_text().splitlines():
        if line.startswith("RECIPIENT="):
            return line.split("=", 1)[1].strip('"')
    return None


# =============================================================================
# Phone Number Normalization
# =============================================================================


class TestPhoneNormalization:
    """Verify phone numbers in various formats are normalized to +1XXXXXXXXXX."""

    def test_plus_country_code(self, sandbox):
        run_whitelist(sandbox, "+13522339160")
        assert get_recipient(sandbox["send_sh"]) == "+13522339160"
        assert get_recipient(sandbox["read_sh"]) == "+13522339160"

    def test_dashes_with_country_code(self, sandbox):
        run_whitelist(sandbox, "1-352-233-9160")
        assert get_recipient(sandbox["send_sh"]) == "+13522339160"

    def test_dashes_without_country_code(self, sandbox):
        run_whitelist(sandbox, "352-233-9160")
        assert get_recipient(sandbox["send_sh"]) == "+13522339160"

    def test_parens_format(self, sandbox):
        run_whitelist(sandbox, "(352) 233-9160")
        assert get_recipient(sandbox["send_sh"]) == "+13522339160"

    def test_digits_only_10(self, sandbox):
        run_whitelist(sandbox, "3522339160")
        assert get_recipient(sandbox["send_sh"]) == "+13522339160"

    def test_digits_only_11(self, sandbox):
        run_whitelist(sandbox, "13522339160")
        assert get_recipient(sandbox["send_sh"]) == "+13522339160"

    def test_dots_format(self, sandbox):
        run_whitelist(sandbox, "352.233.9160")
        assert get_recipient(sandbox["send_sh"]) == "+13522339160"

    def test_spaces_format(self, sandbox):
        run_whitelist(sandbox, "352 233 9160")
        assert get_recipient(sandbox["send_sh"]) == "+13522339160"


class TestPhoneNormalizationErrors:
    """Verify invalid phone numbers are rejected."""

    def test_too_few_digits(self, sandbox):
        result = run_whitelist(sandbox, "123", expect_fail=True)
        assert result.returncode == 1
        assert "ERROR" in result.stderr

    def test_too_many_digits(self, sandbox):
        result = run_whitelist(sandbox, "123456789012345", expect_fail=True)
        assert result.returncode == 1
        assert "ERROR" in result.stderr

    def test_letters_only(self, sandbox):
        result = run_whitelist(sandbox, "abcdefghij", expect_fail=True)
        assert result.returncode == 1
        assert "ERROR" in result.stderr


# =============================================================================
# Email Configuration
# =============================================================================


class TestEmailConfiguration:
    """Verify email addresses are passed through as-is."""

    def test_email_recipient(self, sandbox):
        run_whitelist(sandbox, "user@example.com")
        assert get_recipient(sandbox["send_sh"]) == "user@example.com"
        assert get_recipient(sandbox["read_sh"]) == "user@example.com"

    def test_icloud_email(self, sandbox):
        run_whitelist(sandbox, "john.doe@icloud.com")
        assert get_recipient(sandbox["send_sh"]) == "john.doe@icloud.com"

    def test_edu_email(self, sandbox):
        run_whitelist(sandbox, "nnosse@wgu.edu")
        assert get_recipient(sandbox["send_sh"]) == "nnosse@wgu.edu"


# =============================================================================
# Permission Injection
# =============================================================================


class TestPermissionInjection:
    """Verify permission entries are injected into settings files."""

    def test_creates_local_settings_from_scratch(self, sandbox):
        assert not sandbox["local_settings"].exists()
        run_whitelist(sandbox)
        assert sandbox["local_settings"].exists()
        settings = read_settings(sandbox["local_settings"])
        for perm in EXPECTED_PERMISSIONS:
            assert perm in settings["permissions"]["allow"]

    def test_creates_global_settings_from_scratch(self, sandbox):
        assert not sandbox["global_settings"].exists()
        run_whitelist(sandbox)
        assert sandbox["global_settings"].exists()
        settings = read_settings(sandbox["global_settings"])
        for perm in EXPECTED_PERMISSIONS:
            assert perm in settings["permissions"]["allow"]

    def test_preserves_existing_local_permissions(self, sandbox):
        sandbox["local_settings"].parent.mkdir(parents=True, exist_ok=True)
        existing = {
            "permissions": {
                "allow": ["Bash(git status)", "WebFetch(domain:example.com)"]
            }
        }
        sandbox["local_settings"].write_text(json.dumps(existing))

        run_whitelist(sandbox)

        settings = read_settings(sandbox["local_settings"])
        allow = settings["permissions"]["allow"]
        assert "Bash(git status)" in allow
        assert "WebFetch(domain:example.com)" in allow
        for perm in EXPECTED_PERMISSIONS:
            assert perm in allow

    def test_preserves_existing_global_settings_keys(self, sandbox):
        sandbox["global_settings"].parent.mkdir(parents=True, exist_ok=True)
        existing = {
            "env": {"SOME_VAR": "value"},
            "permissions": {"allow": ["Bash(echo hello)"]},
        }
        sandbox["global_settings"].write_text(json.dumps(existing))

        run_whitelist(sandbox)

        settings = read_settings(sandbox["global_settings"])
        assert settings["env"]["SOME_VAR"] == "value"
        assert "Bash(echo hello)" in settings["permissions"]["allow"]
        for perm in EXPECTED_PERMISSIONS:
            assert perm in settings["permissions"]["allow"]

    def test_creates_permissions_key_if_missing(self, sandbox):
        sandbox["global_settings"].parent.mkdir(parents=True, exist_ok=True)
        sandbox["global_settings"].write_text(json.dumps({"env": {"A": "B"}}))

        run_whitelist(sandbox)

        settings = read_settings(sandbox["global_settings"])
        assert settings["env"]["A"] == "B"
        for perm in EXPECTED_PERMISSIONS:
            assert perm in settings["permissions"]["allow"]


# =============================================================================
# Idempotency
# =============================================================================


class TestIdempotency:
    """Verify running the script multiple times produces consistent results."""

    def test_permissions_not_duplicated(self, sandbox):
        run_whitelist(sandbox)
        run_whitelist(sandbox)
        run_whitelist(sandbox)

        settings = read_settings(sandbox["local_settings"])
        allow = settings["permissions"]["allow"]
        for perm in EXPECTED_PERMISSIONS:
            assert allow.count(perm) == 1, f"Duplicate entry: {perm}"

    def test_recipient_idempotent(self, sandbox):
        run_whitelist(sandbox, "+15551234567")
        result = run_whitelist(sandbox, "+15551234567")
        assert "already set to" in result.stdout
        assert get_recipient(sandbox["send_sh"]) == "+15551234567"

    def test_second_run_reports_all_present(self, sandbox):
        run_whitelist(sandbox)
        result = run_whitelist(sandbox)
        assert "all entries already present" in result.stdout


# =============================================================================
# RECIPIENT Update Consistency
# =============================================================================


class TestRecipientConsistency:
    """Verify send.sh and read.sh always have matching RECIPIENT values."""

    def test_both_files_updated_phone(self, sandbox):
        run_whitelist(sandbox, "555-867-5309")
        assert get_recipient(sandbox["send_sh"]) == get_recipient(sandbox["read_sh"])

    def test_both_files_updated_email(self, sandbox):
        run_whitelist(sandbox, "test@example.com")
        assert get_recipient(sandbox["send_sh"]) == get_recipient(sandbox["read_sh"])

    def test_overwrite_previous_recipient(self, sandbox):
        run_whitelist(sandbox, "old@example.com")
        assert get_recipient(sandbox["send_sh"]) == "old@example.com"

        run_whitelist(sandbox, "new@example.com")
        assert get_recipient(sandbox["send_sh"]) == "new@example.com"
        assert get_recipient(sandbox["read_sh"]) == "new@example.com"

    def test_switch_phone_to_email(self, sandbox):
        run_whitelist(sandbox, "+15551234567")
        assert get_recipient(sandbox["send_sh"]) == "+15551234567"

        run_whitelist(sandbox, "me@icloud.com")
        assert get_recipient(sandbox["send_sh"]) == "me@icloud.com"
        assert get_recipient(sandbox["read_sh"]) == "me@icloud.com"


# =============================================================================
# No-Argument Mode (permissions only)
# =============================================================================


class TestNoArgument:
    """Verify the script works without a phone/email argument."""

    def test_no_arg_skips_recipient(self, sandbox):
        original = get_recipient(sandbox["send_sh"])
        run_whitelist(sandbox)
        assert get_recipient(sandbox["send_sh"]) == original

    def test_no_arg_still_injects_permissions(self, sandbox):
        run_whitelist(sandbox)
        settings = read_settings(sandbox["local_settings"])
        for perm in EXPECTED_PERMISSIONS:
            assert perm in settings["permissions"]["allow"]


# =============================================================================
# Combined Phone + Permissions
# =============================================================================


class TestCombinedSetup:
    """Verify phone configuration and permission injection work together."""

    def test_phone_and_permissions_in_one_call(self, sandbox):
        run_whitelist(sandbox, "1-555-867-5309")

        # Phone configured
        assert get_recipient(sandbox["send_sh"]) == "+15558675309"
        assert get_recipient(sandbox["read_sh"]) == "+15558675309"

        # Permissions injected
        local = read_settings(sandbox["local_settings"])
        for perm in EXPECTED_PERMISSIONS:
            assert perm in local["permissions"]["allow"]

        global_ = read_settings(sandbox["global_settings"])
        for perm in EXPECTED_PERMISSIONS:
            assert perm in global_["permissions"]["allow"]
