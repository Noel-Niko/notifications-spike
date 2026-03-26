#!/bin/bash
# =============================================================
# Download YouTube subtitle tracks for manual correction
# Filenames include quality suffix: .manual.srt or .auto.srt
# Prerequisites: pip install yt-dlp
# =============================================================

mkdir -p subs
cd subs

download_subs() {
  local name="$1"
  local url="$2"

  echo ""
  echo "============================================"
  echo "  $name"
  echo "============================================"

  # Check what's available
  local listing
  listing=$(yt-dlp --list-subs "$url" 2>/dev/null)
  echo "$listing"

  # Detect if manual (human-written) subs exist
  # "Available subtitles" (without "automatic") = human-written
  if echo "$listing" | grep -q "^.info. Available subtitles"; then
    echo ""
    echo "[*] Manual (human-written) subs detected. Downloading..."
    yt-dlp --write-sub --sub-lang en --sub-format srt \
           --skip-download -o "${name}" "$url" 2>/dev/null

    if [ -f "${name}.en.srt" ]; then
      mv "${name}.en.srt" "${name}.en.manual.srt"
      echo "[✓] Saved as ${name}.en.manual.srt"
      return
    fi
  fi

  # Fall back to auto-generated
  echo ""
  echo "[*] No manual subs. Trying auto-generated..."
  yt-dlp --write-auto-sub --sub-lang en --sub-format srt \
         --skip-download -o "${name}" "$url" 2>/dev/null

  if [ -f "${name}.en.srt" ]; then
    mv "${name}.en.srt" "${name}.en.auto.srt"
    echo "[✓] Saved as ${name}.en.auto.srt"
  else
    echo "[✗] No subtitles available at all for ${name}"
  fi
}

# =============================================================
# VIDEO LIST — add new entries here:
#   download_subs "Name" "https://youtu.be/XXXXX"
# =============================================================

download_subs "Maleficent"   "https://youtu.be/kCV0hy6ex1c"
download_subs "Cyrano"       "https://youtu.be/YpHwm5EFVbY"
download_subs "Glengarry"    "https://youtu.be/zCf46yHIzSo"
download_subs "IronMan"      "https://youtu.be/tjTrFo-bITU"
download_subs "Mockingbird"  "https://youtu.be/-x6njs-cGUE"
download_subs "Shawshank"    "https://youtu.be/Di7vbNJwzZQ"

# =============================================================

echo ""
echo "============================================"
echo "  Done! Files saved in ./subs/"
echo "============================================"
echo ""
echo "FILES DOWNLOADED:"
ls -la *.srt 2>/dev/null || echo "(no .srt files found)"