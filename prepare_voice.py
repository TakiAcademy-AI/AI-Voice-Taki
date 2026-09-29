"""Turn a raw recording into a reference voice the server can clone.

    python prepare_voice.py recording.m4a --name kiem

Writes voices/<name>.wav (the clip) and voices/<name>.txt (its transcript).

Why this is not just "convert the file":

* OmniVoice clones from a clip PLUS a transcript of that exact clip. If the
  transcript does not match what is spoken, the clone drifts.
* Cloning roughly doubles generation cost per second of output, and the cost
  scales with reference length. A 10s reference is meaningfully slower than a
  6s one for no quality gain, so we trim.
* Cutting mid-sentence hurts the clone, so we cut on sentence boundaries found
  from Whisper word timestamps rather than at a fixed offset.
* Whisper reliably mangles proper nouns (it heard "Nguyễn Tất Kiểm" as
  "Nguyễn Tất Kiển"). The transcript is therefore written to a .txt you are
  expected to read and fix — that is the point of keeping it a separate file.
"""

import argparse
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_VOICES = ROOT / "voices"
SAMPLE_RATE = 24000
SENTENCE_END = ".?!…"


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"Command failed: {' '.join(cmd[:3])}...\n{proc.stderr[-600:]}")


def to_wav(src: Path, dst: Path) -> None:
    """Any input -> mono 24 kHz wav, high-passed and loudness-normalised."""
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src),
         "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-af", "highpass=f=60,loudnorm=I=-20:TP=-2", str(dst)])


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def transcribe(wav: Path, lang: str, model_size: str):
    """Return [(start, end, text)] per word."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper is not installed. pip install -r requirements.txt")

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        str(wav), language=lang, beam_size=5, word_timestamps=True
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append((w.start, w.end, w.word.strip()))
    return words


def sentence_spans(words):
    """Group words into sentences, splitting after . ? ! …"""
    spans, cur = [], []
    for w in words:
        cur.append(w)
        if w[2] and w[2][-1] in SENTENCE_END:
            spans.append(cur)
            cur = []
    if cur:
        spans.append(cur)
    return spans


def pick_window(spans, lo: float, hi: float, target: float):
    """Best run of consecutive whole sentences with duration in [lo, hi].

    Prefers the run closest to `target`; among equals, the earlier one (early
    speech is usually the cleanest — the speaker has not yet trailed off).
    """
    best = None
    for i in range(len(spans)):
        for j in range(i, len(spans)):
            start = spans[i][0][0]
            end = spans[j][-1][1]
            dur = end - start
            if dur > hi:
                break
            if dur < lo:
                continue
            score = abs(dur - target)
            if best is None or score < best[0]:
                text = " ".join(w[2] for s in spans[i:j + 1] for w in s)
                best = (score, start, end, text)
    return best


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", type=Path, help="recording in any ffmpeg-readable format")
    ap.add_argument("--name", required=True, help="voice id, e.g. kiem")
    ap.add_argument("--lang", default="vi", help="language code (default vi)")
    ap.add_argument("--whisper", default="small",
                    help="faster-whisper model size (default small)")
    ap.add_argument("--min", type=float, default=5.0, dest="lo",
                    help="shortest acceptable clip, seconds (default 5)")
    ap.add_argument("--max", type=float, default=9.0, dest="hi",
                    help="longest acceptable clip, seconds (default 9)")
    ap.add_argument("--target", type=float, default=6.5,
                    help="preferred clip length, seconds (default 6.5)")
    ap.add_argument("--start", type=float, help="skip detection, cut from here")
    ap.add_argument("--end", type=float, help="skip detection, cut to here")
    ap.add_argument("--text", help="skip transcription, use this transcript")
    ap.add_argument("--voices-dir", type=Path, default=DEFAULT_VOICES)
    args = ap.parse_args()

    if not args.audio.exists():
        sys.exit(f"No such file: {args.audio}")
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found in PATH")

    args.voices_dir.mkdir(parents=True, exist_ok=True)
    out_wav = args.voices_dir / f"{args.name}.wav"
    out_txt = args.voices_dir / f"{args.name}.txt"

    full = args.voices_dir / f".{args.name}.full.wav"
    print(f"Converting {args.audio.name} -> mono {SAMPLE_RATE} Hz ...")
    to_wav(args.audio, full)
    try:
        total = duration(full)
        print(f"  {total:.2f}s")

        if args.start is not None and args.end is not None:
            start, end = args.start, args.end
            text = args.text or ""
            if not text:
                print("Transcribing the chosen window ...")
                run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-to", str(end),
                     "-i", str(full), str(out_wav)])
                words = transcribe(out_wav, args.lang, args.whisper)
                text = " ".join(w[2] for w in words)
        else:
            print(f"Transcribing with faster-whisper '{args.whisper}' ...")
            words = transcribe(full, args.lang, args.whisper)
            if not words:
                sys.exit("Whisper found no speech. Pass --start/--end/--text manually.")
            spans = sentence_spans(words)
            pick = pick_window(spans, args.lo, args.hi, args.target)
            if pick is None:
                sys.exit(
                    f"No run of whole sentences lands in {args.lo}-{args.hi}s.\n"
                    f"Found {len(spans)} sentence(s) across {total:.1f}s. Either widen "
                    f"the range (--min/--max) or cut manually with --start/--end."
                )
            _, start, end, text = pick

        # A little air either side so the clip does not clip a consonant.
        start = max(0.0, start - 0.08)
        end = min(total, end + 0.12)

        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
             "-i", str(full), "-ac", "1", "-ar", str(SAMPLE_RATE), str(out_wav)])
    finally:
        # Also runs on sys.exit above, so a failed run leaves no stray temp wav.
        full.unlink(missing_ok=True)

    text = unicodedata.normalize("NFC", text.strip())
    out_txt.write_text(text + "\n", encoding="utf-8")

    print(f"\n  clip : {out_wav}  ({duration(out_wav):.2f}s, cut {start:.2f}-{end:.2f})")
    print(f"  text : {out_txt}")
    print(f"\n  \"{text}\"\n")
    print("READ THAT LINE. Whisper mishears proper nouns and brand names, and the")
    print("clone drifts when the transcript does not match the audio. Fix the .txt")
    print("by hand if anything is wrong — then:")
    print(f"\n    VOICE={args.name} ./start.sh\n")


if __name__ == "__main__":
    main()
