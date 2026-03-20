# iMessage Notifications Setup for Claude Code

This guide explains how to set up iMessage notifications with Claude Code, enabling dynamic mode-switching between IDE and phone approvals.

## What This Does

Claude Code can send iMessages to your phone for approvals and notifications, allowing you to:
- Get notified when long tasks complete
- Approve plans and decisions from your phone
- Switch between IDE and phone approval modes dynamically
- Respond from anywhere without being at your computer

## Prerequisites

- macOS with Messages app
- iMessage account (Apple ID)
- Terminal app with Full Disk Access permission

## Installation

### 1. Copy the iMessage Skill Files

Copy the entire `~/.claude/skills/imessage-notify/` directory to your `~/.claude/skills/` directory:

```bash
# If you received these files from another user:
cp -r /path/to/imessage-notify ~/.claude/skills/
```

The directory should contain:
- `send.sh` - Send fire-and-forget notifications
- `notify.sh` - Send and wait for reply
- `read.sh` - Poll for replies
- `check_fda.sh` - Verify Full Disk Access
- `SKILL.md` - Claude Code skill documentation
- `README.md` - Technical documentation

### 2. Configure Your Phone Number and Whitelist Permissions

Run the setup script **from inside your repo**, passing your phone number or Apple ID email:

```bash
cd /path/to/your/repo
~/.claude/skills/imessage-notify/whitelist_commands.sh +15551234567
```

This single command:
- Configures your phone number in both `send.sh` and `read.sh`
- Injects wildcard permission entries into the repo's `.claude/settings.local.json`
- Injects the same entries into the global `~/.claude/settings.json`
- Ensures all skill scripts are executable

**Accepted phone number formats** (all normalized to `+1XXXXXXXXXX`):

| Format | Example |
|---|---|
| With country code | `+15551234567` |
| With dashes | `1-555-123-4567` |
| With parentheses | `"(555) 123-4567"` (quote the parens) |
| Without country code | `555-123-4567` |
| Digits only | `5551234567` |
| Apple ID email | `your.email@icloud.com` |

**For subsequent repos**, run without the phone number (it's already configured):
```bash
cd /path/to/another/repo
~/.claude/skills/imessage-notify/whitelist_commands.sh
```

The script is idempotent — safe to run multiple times.

### 3. Grant Full Disk Access to Your Terminal App

The scripts need to read your iMessage database (`~/Library/Messages/chat.db`), which requires Full Disk Access.

#### Check if FDA is already granted:
```bash
~/.claude/skills/imessage-notify/check_fda.sh
```

#### If FDA is missing, grant it:

1. Open **System Settings** (or System Preferences)
2. Navigate to **Privacy & Security** → **Full Disk Access**
3. Click the **+** button (or toggle the lock to make changes)
4. Add your terminal application:
   - **PyCharm**: `/Applications/PyCharm.app`
   - **VS Code**: `/Applications/Visual Studio Code.app`
   - **Cursor**: `/Applications/Cursor.app`
   - **iTerm2**: `/Applications/iTerm.app`
   - **Terminal**: `/System/Applications/Utilities/Terminal.app`
   - **Warp**: `/Applications/Warp.app`
5. Toggle it **ON**
6. **Completely quit and restart your terminal app** (not just close the window)

### 4. Create an iMessage Chat with Yourself

Send yourself a test iMessage to create the conversation:

1. Open **Messages** app
2. Start a new message
3. Send to your own phone number or email (the RECIPIENT you configured)
4. Send any test message (e.g., "test")

This creates the chat thread that the scripts will use.

### 5. Make Scripts Executable (if not already)

The setup script in Step 2 handles this automatically. If you need to do it manually:

```bash
chmod +x ~/.claude/skills/imessage-notify/*.sh
```

## Testing the Setup

### Test 1: Send a message (fire-and-forget)

```bash
~/.claude/skills/imessage-notify/send.sh "Test notification from Claude Code"
```

You should receive an iMessage on your phone tagged like:
```
[notifications-spike|REQ-a1b2c3d4] Test notification from Claude Code
```

### Test 2: Send and wait for reply

```bash
reply=$(~/.claude/skills/imessage-notify/notify.sh "Reply with TEST to confirm" 120 10)
echo "You replied: $reply"
```

1. You'll receive the iMessage on your phone
2. Reply with "TEST"
3. The script should output: `You replied: TEST`

If both tests work, setup is complete!

## Using with Claude Code

### CLAUDE.md Integration

Copy the **iMessage Notifications** section from the reference CLAUDE.md to your `~/.claude/CLAUDE.md`:

```markdown
## iMessage Notifications (MANDATORY) - Dynamic Mode Switching

**Approval modes:**
- **IDE mode** (default): Use IDE tools (`AskUserQuestion`, `ExitPlanMode`) for approvals
- **Phone mode**: Use `notify.sh` for phone-only approvals

**Mode switching protocol:**
1. **Default**: Start in IDE mode
2. **Offer phone mode** when you detect multi-step tasks (3+ approval points):
   - Ask: "This is a multi-step task. Want to switch to phone approvals? [Yes/No]"
3. **Manual switch to phone**: When user says "switch to iMessage" anywhere
4. **Manual switch to IDE**: When user texts "switch to IDE" to phone (only works in phone mode)
5. **Track current mode**: Remember which mode you're in throughout the session

**In IDE mode:**
- Use `AskUserQuestion` or `ExitPlanMode` for approvals
- Optionally use `send.sh` for fire-and-forget notifications (no reply expected)
- Watch for user saying "switch to iMessage"

**In Phone mode:**
- Use `notify.sh` to wait for phone replies:
  ```bash
  reply=$(~/.claude/skills/imessage-notify/notify.sh "Your message here" 600 10)
  ```
- Check every reply for "switch to IDE" command
- If detected, switch back to IDE mode and confirm the switch
- Include full context in messages (options, questions, everything user needs)

**When in doubt:**
- For single approvals: Use IDE mode
- For 3+ step tasks: Offer phone mode
- Let user choose their preference

**Setup:**
- Read `~/.claude/skills/imessage-notify/SKILL.md` for the full protocol on first use
- If scripts fail, run `~/.claude/skills/imessage-notify/check_fda.sh` and relay setup instructions
```

### How It Works in Practice

**Single approvals** (default IDE mode):
```
Claude: "Ready to deploy. Proceed? [Yes/No]" (shows in IDE)
You: Click "Yes" in IDE
```

**Multi-step tasks** (offered phone mode):
```
Claude: "This is a 5-step refactoring. Switch to phone approvals? [Yes/No]"
You: "Yes"
Claude: [sends all subsequent approvals via iMessage only]
You: [reply from your phone, no IDE interruption]
```

**Manual mode switching**:
```
You: "switch to iMessage"
Claude: [switches to phone-only approvals]
... later ...
You: [text "switch to IDE" to your phone]
Claude: [switches back to IDE mode]
```

## Multi-Session Support

The system supports multiple Claude Code sessions (in different repos) simultaneously:

- Each message is tagged: `[repo-name|REQ-<unique-id>] message`
- To reply to a specific session when you have multiple pending: `a1b2c3d4 yes`
- To reply to the most recent: just reply normally: `yes`

## Troubleshooting

### Messages send successfully but you don't receive them

**This was a known bug - now fixed!** The scripts now include:
- Proper escaping of special characters (quotes, backslashes)
- Validation that Messages app is running before sending
- Comprehensive error checking with helpful diagnostics
- Non-zero exit codes on failures

If you still don't receive messages:
1. Check RECIPIENT is correct in **both** `send.sh` and `read.sh`
2. Verify Messages app is signed into iMessage
3. Send a manual test message to yourself in Messages app first
4. Check iMessage service status: https://www.apple.com/support/systemstatus/

### "ERROR: Messages app is not running"
- Open `/System/Applications/Messages.app`
- Sign in to iMessage (Messages > Settings > iMessage)
- Verify your Apple ID is active and connected

### "ERROR: Failed to send iMessage via AppleScript"

The script will show specific troubleshooting steps:
1. Check Messages is signed in: Messages > Settings > iMessage
2. Verify you have an existing conversation with yourself
3. Try sending a manual test message in Messages app
4. Run FDA check: `~/.claude/skills/imessage-notify/check_fda.sh`

### "TIMEOUT: No reply received"
- Check that you replied to the correct iMessage conversation
- Look for the message tag: `[repo-name|REQ-abc123]`
- Verify the RECIPIENT matches in both `send.sh` and `read.sh`
- Ensure you have cellular/WiFi connectivity

### "Unable to read chat.db"
- Run `~/.claude/skills/imessage-notify/check_fda.sh`
- Grant Full Disk Access to your terminal app
- **Completely quit and restart** your terminal app (required!)
- Verify the path exists: `ls ~/Library/Messages/chat.db`

### Special characters in messages causing issues

**This is now fixed!** The scripts properly escape:
- Quotes (`"` and `'`)
- Backslashes (`\`)
- Other AppleScript special characters

Messages with quotes, newlines, or complex formatting should now work correctly.

## Architecture Notes

- **send.sh**: Uses AppleScript to send messages via Messages app
- **read.sh**: Polls `~/Library/Messages/chat.db` (SQLite) for replies
- **Atomic claiming**: Uses `mkdir` (atomic operation) to prevent race conditions between multiple sessions
- **Pending tracking**: Tracks requests in `/tmp/imessage-notify-pending/`
- **Reply routing**: Matches by request ID first, then timestamp for most-recent fallback

## Security Considerations

- Full Disk Access grants read access to your Messages database
- Only grant FDA to trusted terminal applications
- The scripts only read from `chat.db`, they never modify it
- Messages are sent via AppleScript using the official Messages app API

## Credits

This system was developed for seamless integration between Claude Code and iMessage, enabling mobile-first approval workflows for software development tasks.
