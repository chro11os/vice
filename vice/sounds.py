"""Earcons, synthesized at startup instead of shipped as WAV files."""
import numpy as np

try:
    import sounddevice as sd
except OSError as e:  # Linux without libportaudio2; macOS wheels bundle it
    sd = None
    print(f"vice: audio disabled ({e}); on Ubuntu run: sudo apt install libportaudio2", flush=True)

RATE = 48_000


def _chime(f_start: float, f_end: float, ms: int = 90, volume: float = 0.2) -> np.ndarray:
    t = np.linspace(0, ms / 1000, int(RATE * ms / 1000), endpoint=False)
    freq = np.linspace(f_start, f_end, t.size)
    phase = 2 * np.pi * np.cumsum(freq) / RATE  # integrate freq so the sweep has no clicks
    fade = 0.005  # 5 ms ramps at both ends; a hard start/stop is an audible click
    envelope = np.minimum(1, t / fade) * np.minimum(1, (ms / 1000 - t) / fade) * np.exp(-t * 30)
    return (volume * envelope * np.sin(phase)).astype(np.float32)


CUES = {
    "start": _chime(660, 990),
    "stop": _chime(990, 660),
    "error": np.concatenate([_chime(300, 300, 70), np.zeros(RATE // 25, np.float32), _chime(300, 300, 70)]),
}


def play(name: str) -> None:
    """Non-blocking. Never raises: a missing audio device must not kill the daemon."""
    if sd is None:
        return
    try:
        sd.play(CUES[name], RATE)
    except sd.PortAudioError as e:
        print(f"vice: audio unavailable ({e})")
