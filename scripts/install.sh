#!/usr/bin/env bash
# Set up Vice for development on macOS (Apple Silicon) or Ubuntu. Safe to re-run.
# Usage: ./scripts/install.sh            (VICE_MODEL=qwen3:4b ./scripts/install.sh to pick a smaller LLM)
set -euo pipefail

cd "$(dirname "$0")/.."
MODEL="${VICE_MODEL:-qwen3:8b}"
MODELS_DIR="$HOME/.cache/vice/models"
KOKORO_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
OS="$(uname -s)"

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
die()  { printf '\033[31mvice install: %s\033[0m\n' "$1" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---------- 1. system prerequisites ----------
step "System prerequisites ($OS)"
if [ "$OS" = "Darwin" ]; then
  [ "$(uname -m)" = "arm64" ] || die "Vice targets Apple Silicon (arm64)."
  if ! xcode-select -p >/dev/null 2>&1; then
    xcode-select --install || true
    die "Installing Xcode Command Line Tools. Finish the dialog, then re-run this script."
  fi
  echo "Xcode Command Line Tools: ok (PortAudio ships inside the sounddevice wheel on macOS)"
elif [ "$OS" = "Linux" ]; then
  need=""
  ldconfig -p 2>/dev/null | grep -q libportaudio.so.2 || need="$need libportaudio2"
  have espeak-ng || need="$need espeak-ng"
  if [ -n "$need" ]; then
    echo "Installing:$need (needs sudo)"
    sudo apt-get install -y $need
  fi
  echo "PortAudio + espeak-ng: ok"
else
  die "Unsupported OS: $OS"
fi

# ---------- 2. uv + Python deps ----------
step "uv and Python dependencies"
if ! have uv; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
uv sync
echo "venv: $(pwd)/.venv"

# ---------- 3. Kokoro voice model (verified by SHA-256) ----------
step "Kokoro TTS model -> $MODELS_DIR"
mkdir -p "$MODELS_DIR"
sha256() { if have sha256sum; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }
fetch() {  # fetch <file> <expected sha256>
  local f="$MODELS_DIR/$1"
  if [ -f "$f" ] && [ "$(sha256 "$f")" = "$2" ]; then echo "$1: ok (cached)"; return; fi
  echo "downloading $1 ..."
  curl -fL --progress-bar -o "$f.part" "$KOKORO_URL/$1"
  [ "$(sha256 "$f.part")" = "$2" ] || { rm -f "$f.part"; die "$1 failed its checksum; download corrupted or tampered with."; }
  mv "$f.part" "$f"   # atomic: a half-finished download never looks like a real model file
  echo "$1: ok"
}
fetch kokoro-v1.0.onnx 7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5
fetch voices-v1.0.bin  bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d

# ---------- 4. Ollama + LLM ----------
step "Ollama + $MODEL"
if ! have ollama; then
  if [ "$OS" = "Darwin" ] && have brew; then
    brew install ollama
  elif [ "$OS" = "Darwin" ]; then
    die "Install Ollama from https://ollama.com/download (or install Homebrew), then re-run."
  else
    die "Install Ollama: curl -fsSL https://ollama.com/install.sh | sh   then re-run."
  fi
fi
if ! ollama list >/dev/null 2>&1; then
  if [ "$OS" = "Darwin" ] && have brew && brew list ollama >/dev/null 2>&1; then
    brew services start ollama
  else
    die "Ollama is installed but not running. Open the Ollama app (macOS) or: sudo systemctl start ollama"
  fi
  for _ in 1 2 3 4 5 6 7 8 9 10; do ollama list >/dev/null 2>&1 && break; sleep 1; done
  ollama list >/dev/null 2>&1 || die "Ollama did not start."
fi
ollama pull "$MODEL"

# ---------- 5. smoke test ----------
step "Smoke test: start daemon, query it, stop it"
uv run vice >/dev/null 2>&1 &
for _ in 1 2 3 4 5 6 7 8 9 10; do uv run vice status >/dev/null 2>&1 && break; sleep 0.5; done
uv run vice status || die "daemon did not start; run 'uv run vice' to see the error."
uv run vice quit >/dev/null
echo "(you should have heard a start and a stop chime)"

step "Done"
cat <<EOF
Next:
  uv run vice                                # run the daemon
  uv run python scripts/bench_llm.py $MODEL  # LLM latency + tool-calling check
  uv run python scripts/voice_samples.py     # hear the voice options (WAVs in ~/.cache/vice/voice-samples)
EOF
