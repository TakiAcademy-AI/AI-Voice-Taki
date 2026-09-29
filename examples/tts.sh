#!/usr/bin/env bash
# Smallest possible client: text in, mp3 out.
set -euo pipefail
TEXT="${1:-Xin chào, đây là bản thử giọng đọc tiếng Việt.}"
OUT="${2:-out.mp3}"
curl -sS -X POST "http://127.0.0.1:${PORT:-8123}/tts" \
  -H 'Content-Type: application/json' \
  --data "$(jq -Rn --arg t "$TEXT" '{text:$t}')" \
  -o "$OUT" --fail
ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT" \
  | xargs printf '%s -> %ss\n' "$OUT"
