# iMessage Notification Skill for Claude Code

## Goal

Build a Claude Code skill (SKILL.md) that allows any Claude Code session, in any repo, to:
1. **Send** an iMessage to the user's phone when it needs approval or wants to report results
2. **Read** the user's text response back from iMessage
3. **Route** messages so the user knows which repo/session sent the message, and each session only reads its own responses

User's iMessage address: `nnosse@wgu.edu`

---

## Status: ALL PHASES COMPLETE

### Phase 1: POC — COMPLETE
- [x] Confirmed AppleScript can send iMessages
- [x] Confirmed chat exists for `nnosse@wgu.edu`
- [x] Confirmed `~/Library/Messages/chat.db` is readable with FDA
- [x] Granted Full Disk Access to PyCharm, restarted
- [x] Verified DB reads work via sqlite3
- [x] Built `send.sh`, `read.sh`, `notify.sh`
- [x] POC round-trip: sent message, received "Ok" reply from phone
- [x] POC notify.sh round-trip: sent message, received "DONE" reply from phone

### Phase 2: Skill File — COMPLETE
- [x] Created `SKILL.md` with usage instructions
- [x] Scripts deployed to `~/.claude/skills/imessage-notify/`

### Phase 3: Multi-Repo Routing — COMPLETE
- [x] Auto-detect repo name from git (falls back to directory name)
- [x] Message tag format: `[repo-name|REQ-a1b2c3d4] message`
- [x] Pending request tracking in `/tmp/imessage-notify-pending/`
- [x] Request-ID-based reply matching (user replies `a1b2c3d4 yes`)
- [x] Most-recent-pending fallback for plain replies
- [x] Atomic claim via `mkdir` to prevent race conditions between sessions
- [x] Cleanup of pending state on reply match or timeout
- [x] Tested end-to-end with repo-tagged message

### Phase 4: Hooks — COMPLETE
- [x] Created `hook_notify.sh` wrapper with 30s debouncing and JSON context extraction
- [x] Added `Notification` hooks to `~/.claude/settings.json` for `idle_prompt` and `permission_prompt`
- [x] Hooks fire automatically at system level — no LLM instruction compliance required
- [x] Simplified CLAUDE.md iMessage section (hooks handle notifications, LLM can still use `notify.sh` for Q&A)
- [x] Strengthened Workflow section in CLAUDE.md for plan-approval enforcement

### Additional Features
- [x] FDA verification (`check_fda.sh`): auto-detects terminal app (PyCharm, VS Code, iTerm, Terminal, Cursor, Warp) and prints specific setup instructions if FDA is missing

---

## Files

```
~/.claude/skills/imessage-notify/
  SKILL.md          # Skill instructions for Claude Code
  send.sh           # Send iMessage with repo/session tagging
  read.sh           # Poll chat.db for response with ID matching
  notify.sh         # Combined send-and-wait
  check_fda.sh      # Verify Full Disk Access, print setup instructions if missing
  hook_notify.sh    # Hook wrapper with debouncing (called by settings.json hooks)
  README.md         # Human-readable documentation

~/.claude/settings.json  # Notification hooks (idle_prompt, permission_prompt)
```

---

## Technical Details

### Message Flow

1. `send.sh` detects repo name, generates `REQ-<uuid>`, sends `[repo|REQ-id] message` via AppleScript
2. `send.sh` registers pending request in `/tmp/imessage-notify-pending/REQ-<id>`
3. `read.sh` polls `chat.db` for inbound messages after the sent timestamp
4. Reply matching:
   - **Priority 1**: Reply contains the request ID → matched to that session
   - **Priority 2**: Plain reply → matched to the most-recent pending request
5. Atomic claim via `mkdir` prevents two sessions from grabbing the same reply
6. Pending request file is cleaned up on match or timeout (via `trap EXIT`)

### Messages Database Schema

- `chat` — Conversations (`chat_identifier` = `nnosse@wgu.edu`)
- `message` — Messages (`text`, `date`, `is_from_me`, `handle_id`)
- `chat_message_join` — Links chats to messages
- `handle` — Contact identifiers

### Date Format

Apple Core Data timestamp: nanoseconds since 2001-01-01. Convert to unix epoch:
```sql
datetime(date/1000000000 + 978307200, 'unixepoch', 'localtime')
```

### macOS Permissions Required

- **Full Disk Access** for the terminal app to read `~/Library/Messages/chat.db`
- **Automation** permission for Messages app (auto-prompted on first AppleScript send)

---

## Resume Instructions

1. Read this file: `docs/imessage_skill_plan.md`
2. All phases are complete. Scripts are at `~/.claude/skills/imessage-notify/`
3. Hooks are configured in `~/.claude/settings.json` — notifications fire automatically
4. To verify scripts work: `~/.claude/skills/imessage-notify/notify.sh "ping" 60 5`
5. To verify hooks are registered: run `/hooks` in Claude Code
