#!/usr/bin/env bash
# Start the TTS server.
#
#   VOICE=kiem ./start.sh              # clone a prepared voice
#   ./start.sh                         # synthetic voice, no clone (fastest)
#   VOICE=kiem QUALITY=high ./start.sh # 32 diffusion steps instead of 16
#   DEVICE=cuda:0 ./start.sh           # GPU — needs well over 4 GB free VRAM
set -euo pipefail
cd "$(dirname "$0")"

export DEVICE="${DEVICE:-cpu}"
export OMNIVOICE_DEVICE="$DEVICE"
export NUM_STEP="${NUM_STEP:-$([ "${QUALITY:-}" = high ] && echo 32 || echo 16)}"
export PORT="${PORT:-8123}"
# Keep a globally pip-installed torch/transformers from shadowing the env's.
export PYTHONNOUSERSITE=1

if [ -n "${VOICE:-}" ]; then
  echo "Voice   : $VOICE (cloned)"
else
  echo "Voice   : synthetic — set VOICE=<name> to clone a prepared voice"
fi
echo "Device  : $DEVICE"
echo "Steps   : $NUM_STEP"
echo "Port    : $PORT"

# Prefer an activated env; otherwise fall back to a micromamba env named by
# VOICE_ENV (default "omnivoice"), which is how the install docs set it up.
if python -c "import omnivoice" 2>/dev/null; then
  exec python server.py
elif command -v micromamba >/dev/null; then
  exec micromamba run -n "${VOICE_ENV:-omnivoice}" python server.py
else
  echo "omnivoice not importable and micromamba not found — see README Install." >&2
  exit 1
fi
