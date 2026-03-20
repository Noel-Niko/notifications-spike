# iMessage Notifications - Quick Start

Get phone approvals working in 5 minutes.

## Installation (One-time setup)

### 1. Copy skill files
```bash
# If you received these from another developer
cp -r /path/to/imessage-notify ~/.claude/skills/
```

### 2. Configure your phone + whitelist permissions
Run from inside your repo:
```bash
cd /path/to/your/repo
~/.claude/skills/imessage-notify/whitelist_commands.sh +15551234567
```

Accepts: `+15551234567`, `1-555-123-4567`, `"(555) 123-4567"`, `555-123-4567`, `5551234567`, or `your.email@icloud.com`

For subsequent repos (phone already configured):
```bash
cd /path/to/another/repo
~/.claude/skills/imessage-notify/whitelist_commands.sh
```

### 3. Grant Full Disk Access
```bash
# Check if needed
~/.claude/skills/imessage-notify/check_fda.sh
```

If needed:
1. System Settings → Privacy & Security → Full Disk Access
2. Add your terminal app (PyCharm, VS Code, iTerm, Terminal, Cursor, Warp)
3. Toggle ON
4. **Quit and restart your terminal app completely**

### 4. Create iMessage chat with yourself
Open Messages app and send yourself a test message to create the conversation.

### 5. Verify scripts are executable
Step 2 handles this automatically. If needed manually:
```bash
chmod +x ~/.claude/skills/imessage-notify/*.sh
```

## Testing (Verify setup works)

### Test 1: Send a message
```bash
~/.claude/skills/imessage-notify/send.sh "Test message"
```
✅ You should receive this on your phone within 1-2 seconds

### Test 2: Send and wait for reply
```bash
reply=$(~/.claude/skills/imessage-notify/notify.sh "Reply with TEST" 60 10)
echo "You replied: $reply"
```
✅ Reply from your phone, should echo your reply

If both work, setup is complete!

## Usage in Claude Code

### Basic usage (copy/paste to Claude)
```
Test the iMessage notification system with me using a 5-step simulated workflow:

STEP 1: Start in IDE mode (default) and ask me a simple approval question

STEP 2: Since this is a multi-step task (5 approvals total), offer to switch to phone mode

STEP 3: If I accept, switch to phone mode and send the next 3 approvals via iMessage ONLY using notify.sh (NO IDE prompts during phone mode)

STEP 4: Watch for "switch to IDE" in my phone replies. When detected, switch back to IDE mode

STEP 5: Complete the remaining approvals in IDE mode using AskUserQuestion

Follow the protocol in ~/.claude/skills/imessage-notify/SKILL.md strictly:
- In IDE mode: Use AskUserQuestion or ExitPlanMode (NOT notify.sh)
- In phone mode: Use ONLY notify.sh (NO IDE prompts)
- NEVER show both IDE and phone prompts for the same approval

Begin the 5-step demo workflow now.
```

### What to expect

**IDE mode (default):**
- Approvals show in IDE
- No phone messages (unless status updates)

**Phone mode (multi-step tasks):**
- Messages arrive on your phone immediately
- Reply from phone
- NO IDE interruption during phone mode

**Mode switching:**
- Say "switch to iMessage" in IDE → switches to phone mode
- Text "switch to IDE" to phone → switches to IDE mode

### First use: Command approval

If you ran `whitelist_commands.sh` (Step 2), commands are pre-approved and you should not see any prompts.

If you still see "Do you want to proceed?", click **"Yes"** — it will be remembered for all future uses in that session. Re-run `whitelist_commands.sh` from the repo to fix permanently.

## Troubleshooting

### Messages not arriving
1. Check RECIPIENT is correct in both send.sh and read.sh
2. Verify Messages app is signed into iMessage
3. Check Full Disk Access: `~/.claude/skills/imessage-notify/check_fda.sh`
4. Test manually: `~/.claude/skills/imessage-notify/send.sh "test"`

### "ERROR: Messages app is not running"
```bash
open /System/Applications/Messages.app
```
Sign into iMessage: Messages → Settings → iMessage

### "Do you want to proceed?" keeps appearing
- Re-run the whitelist script from inside the affected repo:
  ```bash
  cd /path/to/your/repo
  ~/.claude/skills/imessage-notify/whitelist_commands.sh
  ```
- If it still appears, click "Yes" once — it will be remembered for that session
- Check that scripts have execute permissions: `ls -la ~/.claude/skills/imessage-notify/*.sh`

### IDE prompts appear during phone mode
- Run `whitelist_commands.sh` from inside the repo (see above)
- Fallback: click "Yes" once and it won't happen again
- Alternative: pre-approve in plan mode with allowedPrompts

## Full Documentation

- **Setup Guide:** `docs/imessage-setup.md` - Comprehensive installation instructions
- **Demo Script:** `docs/imessage-demo.md` - Full feature demo (5-10 minutes)
- **Skill Reference:** `~/.claude/skills/imessage-notify/SKILL.md` - Technical details for LLMs

## Support

Run the diagnostic script:
```bash
~/.claude/skills/imessage-notify/check_fda.sh
```

Common fixes:
1. Restart Messages app
2. Re-grant Full Disk Access
3. Verify RECIPIENT matches in both scripts
4. Approve commands when prompted (click "Yes")

---

**That's it!** You now have mobile-first approvals with Claude Code.

Try saying: *"switch to iMessage"* during your next multi-step task.
