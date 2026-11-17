# vice

A voice-first background AI assistant for macOS (Apple Silicon) and Ubuntu.
Hold **Right Option** (macOS) or **Right Ctrl** (Ubuntu) to talk; a pill drops from the top bar while Vice is active.

Early development. Architecture and roadmap live in [CLAUDE.md](CLAUDE.md).

```bash
git clone https://github.com/chro11os/vice.git && cd vice
./scripts/install.sh   # deps, Kokoro voice model, Ollama + qwen3:8b, smoke test (safe to re-run)
uv run vice          # start the daemon
uv run vice status
uv run vice quit
```
