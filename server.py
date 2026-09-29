"""HTTP wrapper around OmniVoice — Vietnamese TTS with voice cloning.

OmniVoice ships only a Gradio demo, so this exposes the one endpoint a pipeline
actually needs:

    POST /tts  {"text": "..."}  ->  audio/mpeg bytes

Pick the voice with VOICE=<name>, which loads voices/<name>.wav plus its
transcript voices/<name>.txt (both produced by prepare_voice.py). With no VOICE
set the server synthesises a timbre from OMNIVOICE_INSTRUCT instead — and locks
it in from the first request, because a fresh `instruct` generation picks a new
random voice every call, which would make every scene a different speaker.
"""

import io
import os
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import uvicorn
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
VOICES_DIR = Path(os.environ.get("VOICES_DIR", ROOT / "voices"))

MODEL_ID = os.environ.get("OMNIVOICE_MODEL", "k2-fsa/OmniVoice")
DEVICE = os.environ.get("OMNIVOICE_DEVICE", "cpu")
PORT = int(os.environ.get("PORT", "8123"))
SAMPLE_RATE = 24000

# `instruct` accepts only a fixed vocabulary — female/male, young adult,
# moderate pitch, "<nationality> accent", ... Free-form adjectives like "warm"
# or "news anchor" raise ValueError listing the valid set.
INSTRUCT = os.environ.get("INSTRUCT", "female, young adult, moderate pitch")

# Diffusion steps. 32 is OmniVoice's default and sounds best; on an 8-core CPU
# it costs ~58s for a 8s utterance, and ~2x that again once cloning is on.
# 16 roughly halves it for little audible loss. Raise it if your caller's HTTP
# timeout is generous and you want maximum quality.
NUM_STEP = int(os.environ.get("NUM_STEP", "16"))

VOICE = os.environ.get("VOICE")

model = None
voice_prompt = None
voice_source = None
# generate() is not safe to call concurrently on one model instance.
lock = threading.Lock()


class TtsRequest(BaseModel):
    text: str


def load_voice() -> tuple[str, str] | None:
    """Resolve VOICE=<name> to (wav path, transcript). None if unset."""
    if not VOICE:
        return None
    wav = VOICES_DIR / f"{VOICE}.wav"
    txt = VOICES_DIR / f"{VOICE}.txt"
    if not wav.exists() or not txt.exists():
        raise SystemExit(
            f"Voice '{VOICE}' incomplete — expected both:\n"
            f"  {wav}\n  {txt}\n"
            f"Create it with:  python prepare_voice.py <recording> --name {VOICE}"
        )
    return str(wav), txt.read_text(encoding="utf-8").strip()


def wav_to_mp3(audio: np.ndarray) -> bytes:
    """24 kHz float array -> mp3 bytes, via ffmpeg on stdin/stdout."""
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-i", "pipe:0", "-codec:a", "libmp3lame", "-b:a", "128k",
         "-f", "mp3", "pipe:1"],
        input=buf.getvalue(), capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.decode()[:400]}")
    return proc.stdout


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global model, voice_prompt, voice_source
    from omnivoice import OmniVoice

    ref = load_voice()

    torch.manual_seed(1234)
    dtype = torch.float16 if DEVICE.startswith("cuda") else torch.float32
    print(f"[voice] loading {MODEL_ID} on {DEVICE} ({dtype}), num_step={NUM_STEP}",
          flush=True)
    model = OmniVoice.from_pretrained(MODEL_ID, device_map=DEVICE, dtype=dtype)

    if ref:
        ref_wav, ref_text = ref
        print(f"[voice] cloning '{VOICE}' from {ref_wav}", flush=True)
        voice_prompt = model.create_voice_clone_prompt(
            ref_audio=ref_wav, ref_text=ref_text
        )
        voice_source = VOICE
        print(f"[voice] cloned '{VOICE}'", flush=True)
    else:
        print(f"[voice] no VOICE set — synthesising from instruct: {INSTRUCT}",
              flush=True)

    print("[voice] ready", flush=True)
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "ok": model is not None,
        "voice": voice_source,
        "cloned": VOICE is not None,
        "num_step": NUM_STEP,
        "device": DEVICE,
    }


@app.get("/voices")
def voices():
    """List voices that have BOTH a wav and its transcript."""
    if not VOICES_DIR.exists():
        return {"voices": []}
    names = sorted(
        p.stem for p in VOICES_DIR.glob("*.wav")
        if (VOICES_DIR / f"{p.stem}.txt").exists()
    )
    return {"voices": names, "dir": str(VOICES_DIR)}


@app.post("/tts")
def tts(req: TtsRequest):
    global voice_prompt, voice_source
    text = req.text.strip()
    if not text:
        return Response(status_code=400, content="empty text")

    with lock:
        print(f"[voice] tts ({len(text)} chars): {text[:60]}...", flush=True)
        if voice_prompt is None:
            # No reference voice: synthesise one, then immediately make it the
            # clone prompt so every later request keeps the same speaker.
            audio = model.generate(
                text=text, instruct=INSTRUCT, num_step=NUM_STEP
            )[0]
            tmp_ref = "/tmp/ai-voice-taki-instruct-ref.wav"
            sf.write(tmp_ref, audio, SAMPLE_RATE)
            voice_prompt = model.create_voice_clone_prompt(
                ref_audio=tmp_ref, ref_text=text
            )
            voice_source = "instruct (locked from first request)"
            print("[voice] timbre locked from first utterance", flush=True)
        else:
            audio = model.generate(
                text=text, voice_clone_prompt=voice_prompt, num_step=NUM_STEP
            )[0]

    return Response(content=wav_to_mp3(audio), media_type="audio/mpeg")


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"),
                port=PORT, log_level="warning")
