"""Generate a Kokoro sample pack to pick a voice by ear. Usage: uv run python scripts/voice_samples.py"""
import time
import wave
from pathlib import Path

import numpy as np
from kokoro_onnx import Kokoro

MODELS = Path.home() / ".cache/vice/models"
OUT = Path.home() / ".cache/vice/voice-samples"
OUT.mkdir(parents=True, exist_ok=True)

LINE = ("Sure. Moving your resume to Documents. ... Done. "
        "Oh, and you've got about twenty minutes before your reminder. Anything else?")

kokoro = Kokoro(str(MODELS / "kokoro-v1.0.onnx"), str(MODELS / "voices-v1.0.bin"))
style = kokoro.get_voice_style

VOICES = {
    "1_af_heart": "af_heart",
    "2_af_bella": "af_bella",
    "3_af_nicole": "af_nicole",
    "4_bf_emma": "bf_emma",
    "5_blend_heart60_bella40": 0.6 * style("af_heart") + 0.4 * style("af_bella"),
    "6_blend_heart70_nicole30": 0.7 * style("af_heart") + 0.3 * style("af_nicole"),
}


def save(path: Path, samples: np.ndarray, rate: int) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)  # stdlib wave wants int16
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


kokoro.create("warm up", voice="af_heart", lang="en-us")  # first call initializes onnxruntime
for name, voice in VOICES.items():
    t0 = time.perf_counter()
    samples, rate = kokoro.create(LINE, voice=voice, speed=1.0, lang="en-us")
    took = time.perf_counter() - t0
    audio = len(samples) / rate
    save(OUT / f"{name}.wav", samples, rate)
    print(f"{name:28s} {audio:4.1f}s audio in {took:4.2f}s  ({audio / took:4.1f}x real-time)")

t0 = time.perf_counter()
s, r = kokoro.create("Sure.", voice="af_heart", lang="en-us")
print(f"\nfirst clause 'Sure.' synthesized in {(time.perf_counter() - t0) * 1000:.0f} ms")
print(f"files in {OUT}")
