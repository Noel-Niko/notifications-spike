# iMessage Notification Demo Script

This script demonstrates the dynamic mode-switching functionality between IDE and phone approvals in Claude Code.

## Prerequisites

Before running this demo, ensure:
- ✅ iMessage skill installed at `~/.claude/skills/imessage-notify/`
- ✅ RECIPIENT configured in `send.sh` and `read.sh`
- ✅ Full Disk Access granted to your terminal app
- ✅ Messages app running and signed into iMessage
- ✅ CLAUDE.md includes iMessage notification instructions

**Quick verification:**
```bash
~/.claude/skills/imessage-notify/send.sh "Setup verified - ready for demo"
```
You should receive that message on your phone within seconds.

**⚠️ CRITICAL: Whitelist Commands for Phone Mode**

Run this once before the demo:
```bash
~/.claude/skills/imessage-notify/whitelist_commands.sh
```

**Why:** Without whitelisting, IDE approval prompts will block phone mode. The first time you use `notify.sh`, Claude Code will ask "Do you want to proceed?" - click **"Yes"** and the command will be remembered for all future uses.

**If you see "Do you want to proceed?" during the demo:** This is normal on first use. Click "Yes" and the demo will continue seamlessly. Subsequent uses won't require approval.

## Demo Overview

This demo will show:
1. **IDE mode** (default) - Approvals in the IDE
2. **Mode switching** - Offering phone mode for multi-step tasks
3. **Phone mode** - Approvals via iMessage only
4. **Switch back** - Returning to IDE mode from phone

**Total time:** ~3-5 minutes

---

## How to Run the Demo

### Step 1: Start a New Claude Code Session

Open any repository and start Claude Code.

### Step 2: Copy and Paste This Prompt

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

### Step 3: Follow the Workflow

#### Expected Flow:

**1. IDE Approval (Step 1)**
- Claude shows an approval prompt in the IDE
- Respond in the IDE (click an option)

**2. Mode Switch Offer**
- Claude asks: "This is a multi-step task. Want to switch to phone approvals?"
- Choose: **"Yes, switch to phone"**

**3. Phone Approvals (Steps 2-4)**
- Check your phone - you should see iMessages like:
  ```
  [your-repo|REQ-abc123] STEP 2/5: [description]. Reply APPROVE to proceed, or 'switch to IDE' to return to IDE mode.
  ```
- Reply from your phone: **"APPROVE"** (or just "approve")
- Repeat for steps 3 and 4
- **IMPORTANT:** During phone mode, NO IDE prompts should appear

**4. Switch Back to IDE**
- On step 3 or 4, reply from your phone: **"switch to IDE"**
- Claude should detect this and confirm switching back

**5. IDE Approval (Final Step)**
- Claude shows remaining approvals in the IDE
- Respond in the IDE

---

## What You Should See

### ✅ Correct Behavior

1. **IDE mode**: Approvals show in IDE, no phone messages
2. **Phone mode**: Approvals come to phone, NO IDE interruptions
3. **Mode switching**: Works in both directions smoothly
4. **No double-approval**: You only respond once per step (either phone OR IDE)
5. **Immediate delivery**: Phone messages arrive within 1-2 seconds

### ❌ Incorrect Behavior (Report if you see this)

1. **Messages delayed**: Phone messages arrive AFTER IDE approval
2. **Double prompts**: Both IDE and phone ask for approval simultaneously
3. **No messages**: Phone messages never arrive (check troubleshooting)
4. **Mode stuck**: Can't switch between modes
5. **Errors**: AppleScript errors or send failures

### ⚠️ "Do you want to proceed?" Prompt During Phone Mode

**If you see this during the demo:**

```
Do you want to proceed?
❯ 1. Yes
  2. No
```

This is the **bash command approval prompt** for `notify.sh`. This is NORMAL on first use.

**What to do:**
1. Click **"Yes"** (or press 1)
2. The command will be approved and remembered
3. The demo will continue seamlessly
4. Future uses won't require approval

**Why this happens:**
- Claude Code's safety feature requires approving bash commands
- After first approval, the command is whitelisted
- Subsequent uses of phone mode work without IDE interruption

**Prevention:**
Run `~/.claude/skills/imessage-notify/whitelist_commands.sh` before starting the demo to understand the approval process.

---

## Troubleshooting

### Messages not arriving on phone

```bash
# Test send directly
~/.claude/skills/imessage-notify/send.sh "Direct test message"
```

If this fails, check:
1. Messages app is running and signed into iMessage
2. RECIPIENT is set correctly in both `send.sh` and `read.sh`
3. You have an existing conversation with yourself
4. Full Disk Access is granted: `~/.claude/skills/imessage-notify/check_fda.sh`

### "ERROR: Messages app is not running"

```bash
# Open Messages app
open /System/Applications/Messages.app
```

Verify you're signed into iMessage (Messages > Settings > iMessage)

### Wrong mode behavior

Ensure your `~/.claude/CLAUDE.md` includes the mode-switching protocol. Check:
```bash
cat ~/.claude/CLAUDE.md | grep -A 20 "iMessage Notifications"
```

Should show the mode-switching section with IDE mode and Phone mode instructions.

### Claude not following protocol

The LLM should read `~/.claude/skills/imessage-notify/SKILL.md` automatically. Verify it exists:
```bash
cat ~/.claude/skills/imessage-notify/SKILL.md | head -50
```

Should show the "Mode-Switching Protocol" and "Quick Decision Tree" sections.

---

## Advanced Demo Scenarios

### Scenario 1: IDE-Only Workflow (Single Approval)

**Prompt:**
```
I need approval to delete a test file. Ask me for approval in the IDE.
```

**Expected:** Single IDE approval, no phone mode offered (not multi-step)

---

### Scenario 2: Manual Mode Switch

**Prompt:**
```
Ask me 3 approval questions. Start in IDE mode.
```

After the first approval, respond: **"switch to iMessage"**

**Expected:** Claude switches to phone mode for remaining approvals

---

### Scenario 3: Fire-and-Forget Notifications

**Prompt:**
```
Run a simulated long task (10 seconds) and notify me on my phone when complete. Don't wait for a reply.
```

**Expected:**
- Claude runs `sleep 10`
- Uses `send.sh` to notify (not `notify.sh`)
- Continues without waiting for reply

---

## Demo Checklist

Use this to verify all features work:

- [ ] IDE mode: Single approval in IDE (no phone)
- [ ] Multi-step detection: Offers phone mode for 3+ steps
- [ ] Switch to phone: Accepts "Yes" and switches modes
- [ ] Phone approvals: Messages arrive immediately
- [ ] No IDE interrupts: IDE doesn't prompt during phone mode
- [ ] Switch to IDE: Detects "switch to IDE" from phone
- [ ] Mode persists: Stays in chosen mode across steps
- [ ] Error handling: Shows helpful messages on failure
- [ ] Fire-and-forget: `send.sh` works for status updates
- [ ] Multi-repo: Works correctly with multiple Claude sessions

---

## Sharing This Demo

To share with team members:

1. **Copy skill files:**
   ```bash
   cp -r ~/.claude/skills/imessage-notify /path/to/share/
   ```

2. **Update RECIPIENT in their copy:**
   - Edit `send.sh` line 11
   - Edit `read.sh` line 15
   - Set to their phone number or Apple ID email

3. **Share CLAUDE.md section:**
   - Copy the "iMessage Notifications (MANDATORY)" section from your `~/.claude/CLAUDE.md`

4. **Share this demo script:**
   - Send them `docs/imessage-demo.md` and `docs/imessage-setup.md`

---

## Expected Output Example

Here's what a successful demo looks like:

```
Claude: "Let me test a 5-step workflow..."

[IDE Approval]
Claude: "STEP 1/5: Initialize project. Proceed?"
You: [Click "Yes" in IDE]

[Mode Switch Offer]
Claude: "This is a multi-step task. Switch to phone approvals?"
You: [Click "Yes, switch to phone"]

[Phone Approvals - Check your phone]
Message 1: [demo-repo|REQ-abc123] STEP 2/5: Setup database...
You: "approve"

Message 2: [demo-repo|REQ-def456] STEP 3/5: Create tables...
You: "approve"

Message 3: [demo-repo|REQ-ghi789] STEP 4/5: Seed data...
You: "switch to IDE"

[Back to IDE]
Claude: "Detected 'switch to IDE' command! Switching back..."
Claude: "STEP 5/5: Run tests?"
You: [Click "Yes" in IDE]

Claude: "Demo complete! All 5 steps approved."
```

---

## Reporting Issues

If you encounter issues during the demo:

1. **Check error messages** - Scripts now show detailed troubleshooting
2. **Verify setup** - Run `~/.claude/skills/imessage-notify/check_fda.sh`
3. **Test directly** - Try `send.sh "test"` and `notify.sh "test" 60 5`
4. **Check logs** - Look for AppleScript errors in terminal output

**Common fixes:**
- Restart Messages app
- Grant/re-grant Full Disk Access
- Verify RECIPIENT matches in both scripts
- Check iMessage is signed in and connected

---

## Next Steps

After completing the demo:

1. **Use in real workflows** - Try with actual multi-step tasks
2. **Customize CLAUDE.md** - Adjust when phone mode is offered (3+ steps, or different threshold)
3. **Share with team** - Help others set up for mobile approvals
4. **Integrate with CI/CD** - Use `send.sh` for build/deploy notifications

**Pro tip:** Use phone mode when you're:
- Away from your desk
- In meetings but available for quick approvals
- Working on long-running tasks that need periodic check-ins
- Reviewing plans during commute or breaks

---

## Success Criteria

The demo is successful when:

✅ All messages arrive on your phone within 1-2 seconds
✅ You can approve from either IDE or phone (not both)
✅ Mode switching works in both directions
✅ No duplicate approvals required
✅ Error messages are clear and helpful
✅ Multi-repo sessions don't interfere with each other

**Enjoy mobile-first approvals with Claude Code!** 🎉
