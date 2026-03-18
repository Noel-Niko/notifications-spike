# Manual Test Directions: Cross-System Latency Measurement

Measure true end-to-end latency from spoken audio to Genesys transcription delivery using poc-deepgram as a ground-truth audio clock.

---

## One-Time Setup: BlackHole Audio Routing

BlackHole creates a virtual audio device that routes system audio into poc-deepgram so it can timestamp when speech actually occurs.

### 1. Install BlackHole

```bash
brew install blackhole-2ch
```

### 2. Restart Core Audio (required for macOS to detect the new driver)

```bash
sudo killall coreaudiod
```

> `sudo launchctl kickstart -kp system/com.apple.audio.coreaudiod` is an alternative but fails when SIP is enabled. `killall` works reliably — macOS auto-restarts the daemon.

### 3. Create Multi-Output Device

1. Open **Audio MIDI Setup** (Spotlight → "Audio MIDI Setup")
2. Click the **+** button in the bottom-left corner
3. Select **Create Multi-Output Device**
4. Check both:
   - Your speakers or headphones (so you can still hear the call)
   - **BlackHole 2ch** (routes audio to the virtual input)

### 4. Set System Output

1. In **System Settings → Sound → Output**, select the **Multi-Output Device** you just created
2. Alternatively, Option-click the volume icon in the menu bar and select it there

You now hear the call audio AND it routes to BlackHole for poc-deepgram to capture.

### 5. Configure Browser and Genesys Cloud

**Use Chrome for Genesys** — Safari's WebRTC implementation causes "Not Responding" errors when answering calls, even with correct audio device settings. Chrome handles WebRTC audio device negotiation reliably.

1. Open **Chrome** and navigate to `apps.mypurecloud.com`
2. When Chrome prompts for microphone access, select **MacBook Pro Microphone**
3. In Genesys Cloud, go to **Preferences → Sound → Audio Device Profile**
4. Create a profile (e.g., "Latency Testing") or edit the existing one:
   - **Microphone**: MacBook Pro Microphone
   - **Speaker**: Multi-Output Device
   - **Ringer**: Multi-Output Device
5. Click **Save**

See `docs/audio-settings-in-genesys.png` for reference.

**Verified working configuration:**
- **macOS System Input**: MacBook Pro Microphone (your voice → Genesys)
- **macOS System Output**: Multi-Output Device (call audio → speakers + BlackHole)
- **Chrome** (Genesys): microphone set to MacBook Pro Microphone
- **Any browser** (poc-deepgram at `localhost:8766`): audio source dropdown set to BlackHole 2ch

This configuration allows answering Genesys calls in Chrome while poc-deepgram captures the call audio via BlackHole for ground-truth timestamping.

---

## Before Each Test Call

### 5. Start notifications-spike (Terminal 1)

```bash
cd ~/PycharmProjects/notifications-spike
uv run uvicorn main:app --host 0.0.0.0 --port 8765
```

Wait for: `WebSocket connected (agents=N, max_concurrent_conversations=10)`

### 6. Start poc-deepgram (Terminal 2)

```bash
cd ~/PycharmProjects/poc-deepgram
uv run uvicorn poc_deepgram.app:create_app --factory --host 0.0.0.0 --port 8766
```

### 7. Open poc-deepgram in browser

Navigate to **http://localhost:8766**

### 8. Select BlackHole as audio input

In the **audio source dropdown** at the top of the poc-deepgram page (next to the Start button), select **BlackHole 2ch**.

> **Important**: Your macOS **System Settings → Sound → Input** should still be your physical microphone (not BlackHole). The dropdown in the browser is separate from the system input. BlackHole only carries system audio output — it does not carry your mic voice.

### 9. Click Start

Click the **Start** button in the poc-deepgram browser UI. The status indicator should turn green (Connected).

---

## During the Call

### 10. Take the Genesys call normally

Both systems capture data in parallel — no action needed from you during the call:

- **notifications-spike** receives Genesys transcription events via WebSocket and writes them to `conversation_events/<conversation-id>.jsonl`
- **poc-deepgram** captures the call audio via BlackHole, sends it to Deepgram, and timestamps each utterance with wall-clock time

---

## After the Call

### 11. Stop poc-deepgram

Click **Stop** in the poc-deepgram browser UI. This saves the session JSON to `~/PycharmProjects/poc-deepgram/results/`.

### 12. Identify your output files

```bash
# Most recent Deepgram session
ls -lt ~/PycharmProjects/poc-deepgram/results/ | head -3

# Most recent Genesys conversation
ls -lt ~/PycharmProjects/notifications-spike/conversation_events/ | head -3
```

### 13. Run the correlation tool

```bash
cd ~/PycharmProjects/notifications-spike

uv run python -m scripts.correlate_latency \
  --deepgram ../poc-deepgram/results/<SESSION_FILE>.json \
  --genesys conversation_events/<CONVERSATION_ID>.jsonl
```

Replace `<SESSION_FILE>` and `<CONVERSATION_ID>` with the actual filenames from step 12.

### Output

The tool prints:
- Number of matched utterance pairs
- Mean, median, min, max latency
- p95 and p99 latency
- Per-channel breakdown (INTERNAL vs EXTERNAL)
- A table of each matched pair with latency and text similarity score

CSV results are exported to `analysis_results/cross_system/correlation.csv`.

### 14. (Optional) Interactive analysis

For deeper analysis with visualizations:

```bash
cd ~/PycharmProjects/notifications-spike/notebooks
uv run jupyter notebook cross_system_latency.ipynb
```

Select the session files in the notebook and run all cells.

---

## Troubleshooting

### BlackHole not appearing in Audio MIDI Setup

Restart the Core Audio daemon and reopen Audio MIDI Setup:

```bash
sudo killall coreaudiod
```

> `sudo launchctl kickstart -kp system/com.apple.audio.coreaudiod` does not work when SIP is enabled. Use `killall` instead — macOS auto-restarts the daemon.

### Genesys "Not Responding" when answering calls

**Root cause**: Safari's WebRTC implementation does not reliably negotiate audio devices, especially with virtual devices like Multi-Output Device. Calls connect but immediately show "Not Responding".

**Fix**: Use **Chrome** for Genesys instead of Safari.

If the issue persists in Chrome:
1. Set system output back to **MacBook Pro Speakers** (not Multi-Output Device)
2. Quit and reopen Chrome
3. Navigate to `apps.mypurecloud.com` and try answering a call
4. If that works, switch system output back to **Multi-Output Device** and refresh the Genesys page — Chrome should re-detect the devices

**Chrome microphone settings**: Go to `chrome://settings/content/microphone` and verify it's set to **MacBook Pro Microphone**. You can also click the lock icon in the address bar next to `apps.mypurecloud.com` → **Site settings** → verify Microphone is **Allow**.

### No audio in poc-deepgram

- Verify system output is set to **Multi-Output Device** (not just MacBook Pro Speakers) — BlackHole only receives audio routed through the Multi-Output Device
- In the poc-deepgram browser UI, verify the **audio source dropdown** is set to **BlackHole 2ch** (not your physical microphone)
- Check that the Genesys call audio is playing through system audio (not a USB headset that bypasses system routing)
- Make sure a call is active — BlackHole receives silence when no audio is playing through the system output

### Genesys doesn't hear my voice

- Check **System Settings → Sound → Input** — must be **MacBook Pro Microphone** (not BlackHole)
- Check the Genesys Audio Device Profile — Microphone must be **MacBook Pro Microphone**
- BlackHole only carries system output audio, not microphone input — your voice goes through the physical mic directly to Genesys

### Fallback: Open mic approach (if BlackHole causes issues)

If the Multi-Output Device breaks Genesys audio:
1. Set system output to **MacBook Pro Speakers** (no Multi-Output Device)
2. Set system input to **MacBook Pro Microphone**
3. In Genesys, use **Default profile** or **Use Computer Settings**
4. In poc-deepgram, select **MacBook Pro Microphone** as the audio source (not BlackHole)
5. Turn speaker volume up so the mic picks up both your voice and the call audio

This is less clean (ambient noise) but works without any virtual audio device configuration.

### No matched utterances in correlation

- Lower the similarity threshold: `--threshold 0.4`
- Check that both files cover the same call (overlapping time windows)
- Verify poc-deepgram captured audio (check that the session JSON has transcripts)

### notifications-spike not capturing the conversation

- Confirm the agent on the call is listed in `agents.txt`
- Check the terminal for `Subscribed to transcripts for conversation` log messages
- Verify the `.env` file has correct Genesys credentials

---

## What This Measures

```
True Latency = genesys_receivedAt - deepgram_audio_wall_clock_end
```

| Component | Source | Meaning |
|-----------|--------|---------|
| `deepgram_audio_wall_clock_end` | poc-deepgram | Wall-clock time when words were spoken (ground truth) |
| `genesys_receivedAt` | notifications-spike | Wall-clock time when Genesys transcription event arrived |
| **True Latency** | Correlation tool | Full Genesys pipeline: audio capture + STT processing + WebSocket delivery |

Both apps use `time.time()` on the same machine — no clock sync issues.
