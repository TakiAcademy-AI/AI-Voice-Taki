# AI-Voice-Taki

Local Vietnamese text-to-speech with voice cloning. Give it a recording of a
voice, get an HTTP endpoint that speaks any text in that voice.

```
POST http://127.0.0.1:8123/tts   {"text": "Xin chào"}   ->  audio/mpeg
```

Built on [k2-fsa/OmniVoice](https://github.com/k2-fsa/OmniVoice) (0.6B, Qwen3
based, 600+ languages). Runs offline — no API keys, nothing leaves the machine.

---

## Install

Needs **ffmpeg** and **ffprobe** in PATH, plus Python 3.12.

```bash
micromamba create -y -n omnivoice -c conda-forge python=3.12 pip
micromamba activate omnivoice

# torch and torchaudio must come from the SAME CUDA index — see requirements.txt
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
```

`python -m venv` also works if your system ships `python3-venv`.

---

## Use

**1. Prepare a voice** from any recording — 15 seconds of clear speech is plenty.

```bash
python prepare_voice.py recording.m4a --name kiem
```

It converts and normalises the audio, transcribes it, picks the best run of
whole sentences between 5 and 9 seconds, and writes `voices/kiem.wav` plus
`voices/kiem.txt`.

**Then read `voices/kiem.txt` and fix it.** Whisper mishears names — it wrote
"Nguyễn Tất Kiển" for "Nguyễn Tất Kiểm". The clone drifts when the transcript
disagrees with the audio, so this file is deliberately left for you to correct.

**2. Start the server.**

```bash
VOICE=kiem ./start.sh
```

Wait for `[voice] ready`, then:

```bash
curl -s -X POST http://127.0.0.1:8123/tts \
  -H 'Content-Type: application/json' \
  -d '{"text":"Xin chào, đây là giọng đã được nhân bản."}' \
  -o out.mp3
```

| Endpoint | Does |
| --- | --- |
| `POST /tts` | `{"text": "..."}` → mp3 bytes |
| `GET /health` | model loaded? which voice? |
| `GET /voices` | voices that have both a `.wav` and a `.txt` |

---

## Knobs

| Variable | Default | Notes |
| --- | --- | --- |
| `VOICE` | unset | Clone `voices/<name>`. Unset → synthetic voice from `INSTRUCT`, locked in from the first request so it stays consistent. |
| `DEVICE` | `cpu` | `cuda:0` for GPU. See the VRAM note below. |
| `NUM_STEP` | `16` | Diffusion steps. `QUALITY=high` sets 32 (OmniVoice's default — better, ~2× slower). |
| `PORT` | `8123` | |
| `INSTRUCT` | `female, young adult, moderate pitch` | Only used when `VOICE` is unset. |

---

## Speed, honestly

Measured on an 8-core i7-9700, CPU only, generating ~8 seconds of speech:

| Setting | Wall time | vs realtime |
| --- | --- | --- |
| No clone, `NUM_STEP=16` | ~29s | 3.7× |
| Clone, `NUM_STEP=16` | ~64s | 8× |
| Clone, `NUM_STEP=32` | not measured | expect ~2× the row above |

**Cloning roughly doubles the cost.** Budget ~50–70 seconds per sentence on CPU.
A 3-minute narration across 22 sentences took about 17 minutes.

If the caller has an HTTP timeout, check it before you start. A 60-second
timeout will fail on nearly every cloned request.

---

## Things that will bite you

**`libcudart.so.13` not found, at import.** torchaudio came from PyPI while
torch came from a `+cu128` index. They link different CUDA runtimes and it only
surfaces when `omnivoice` imports torchaudio. Reinstall torchaudio from the same
index as torch.

**CUDA out of memory on a 4 GB card.** The 0.6B weights fit in fp16, but the DAC
vocoder's activations do not once a desktop session is holding ~1.4 GB.
`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` does not save it. Use `cpu`,
or a card with real headroom.

**`ValueError: Unsupported instruct items`.** `INSTRUCT` takes a closed
vocabulary, not free text. Valid: `female`, `male`, `child`, `teenager`,
`young adult`, `middle-aged`, `elderly`, `very low pitch`, `low pitch`,
`moderate pitch`, `high pitch`, `very high pitch`, `whisper`, and
`<nationality> accent`. "warm", "clear", "news anchor" all fail.

**The clone sounds right but reads wrong.** It copies delivery, not just timbre.
A reference clip of someone explaining calmly produces calm narration even for
ad copy. Record the reference in the register you actually want.

**Numbers get read literally.** Vietnamese TTS says "5.5" as "năm rưỡi". Spell
numbers out in the text you send — "năm chấm năm".

---

## Layout

```
server.py         HTTP server — loads the model once, serves /tts
prepare_voice.py  recording -> voices/<name>.wav + voices/<name>.txt
start.sh          launcher, resolves the env and the knobs above
voices/           prepared voices — gitignored, see below
```

`voices/` is gitignored. A voice print is biometric data: it is enough to make
someone appear to say anything. Keep reference recordings and their clips off
shared remotes, and only clone voices you have permission to clone.
