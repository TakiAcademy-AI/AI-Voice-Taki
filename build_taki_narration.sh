#!/usr/bin/env bash
# Narrate the TAKI AI-training blurb in the cloned voice, one sentence per
# request. The server sends whole text straight to model.generate(), so long
# paragraphs would be one giant utterance — split here instead.
#
# Acronyms are spelled phonetically: the model reads Vietnamese, so "AI" and
# "CEO" come out wrong unless written as they are spoken.
set -euo pipefail

cd "$(dirname "$0")"
OUT="${OUT:-out/taki_ai_training.mp3}"
BUILD="${BUILD:-out/parts}"
URL="http://127.0.0.1:${PORT:-8123}/tts"

mkdir -p "$BUILD" "$(dirname "$OUT")"

# Each entry: gap-after-in-seconds | text
LINES=(
  "0.5|Thiết kế lộ trình ứng dụng ây ai riêng cho từng doanh nghiệp."
  "0.5|Không có một công thức ây ai chung cho tất cả."
  "0.5|Ta Ki xây dựng chương trình đào tạo ây ai được thiết kế riêng theo ngành nghề, phòng ban và mục tiêu kinh doanh, giúp doanh nghiệp ứng dụng ây ai trực tiếp vào công việc thực tế."
  "0.6|Từ xi i âu, Ban lãnh đạo đến Marketing, Sales, Nhân sự và Vận hành, đội ngũ được hướng dẫn cách."
  "0.35|Tối ưu quy trình làm việc bằng ây ai."
  "0.35|Giảm thời gian xử lý các công việc thủ công."
  "0.35|Nâng cao năng suất cá nhân và đội nhóm."
  "0.7|Xây dựng văn hóa làm việc cùng ây ai trong doanh nghiệp."
  "0.4|Không chỉ học cách dùng ây ai."
  "0|Doanh nghiệp xây dựng được hệ thống làm việc hiệu quả hơn với ây ai."
)

list="$BUILD/concat.txt"
: > "$list"

i=0
for entry in "${LINES[@]}"; do
  i=$((i + 1))
  gap="${entry%%|*}"
  text="${entry#*|}"
  part=$(printf '%s/p%02d.mp3' "$BUILD" "$i")

  if [[ -s "$part" ]]; then
    echo "[$i/${#LINES[@]}] cached  $part"
  else
    printf '[%d/%d] %s\n' "$i" "${#LINES[@]}" "${text:0:58}..."
    start=$SECONDS
    curl -sS --fail -m 900 -X POST "$URL" \
      -H 'Content-Type: application/json' \
      --data "$(jq -Rn --arg t "$text" '{text:$t}')" \
      -o "$part"
    dur=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$part")
    printf '        %ss audio in %ds\n' "$dur" "$((SECONDS - start))"
  fi
  printf "file '%s'\n" "p$(printf '%02d' $i).mp3" >> "$list"

  if [[ "$gap" != "0" ]]; then
    sil="$BUILD/sil_$gap.mp3"
    [[ -s "$sil" ]] || ffmpeg -hide_banner -loglevel error -y \
      -f lavfi -i anullsrc=r=24000:cl=mono -t "$gap" -b:a 128k "$sil"
    printf "file 'sil_%s.mp3'\n" "$gap" >> "$list"
  fi
done

# Re-encode rather than -c copy: each part carries its own mp3 encoder delay and
# padding, so a bit-for-bit concat leaves a click at every join.
ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i "$list" \
  -c:a libmp3lame -b:a 128k -ar 24000 -ac 1 "$OUT"
total=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$OUT")
printf '\ndone: %s (%ss)\n' "$OUT" "$total"
