# Vice

A **voice-first** background assistant with tool calling and desktop automation. There's no window and no text box: you talk to it, and it talks back. The only visual is a small **pill** that drops down from the top bar while Vice is active.
**Hold the hotkey** to speak: **Right Option (⌥) on macOS**, **Right Ctrl on Ubuntu**. It starts at login and stays running.

**Current focus: macOS.** Ubuntu keeps the voice pipeline in the plan, but the Ubuntu pill is **deferred** (see *Deferred: Ubuntu pill*).

**Targets:** macOS on Apple Silicon (M3 Pro, arm64, latest macOS) and Ubuntu LTS (GNOME on Wayland, x86_64/arm64).

**Status:** Planning only. No code yet. This file holds the architecture.

---

## Principles

- **Voice in, voice out. The only thing on screen is the pill.** The pill shows *state*, never a conversation. No windows, no text boxes, no GUI toolkit.
- **The pill is a dumb view.** The daemon broadcasts state; the pill draws it. The pill never makes decisions, so it can crash or be disabled without affecting Vice.
- **One process, one language.** A headless Python daemon owns everything: hotkey, mic, STT, agent loop, tools, TTS. Don't split it into services until something forces it.
- **Platform code stays behind one seam.** Anything specific to macOS or Linux lives in `vice/platform/{macos,linux}.py`. The rest of the code never checks `sys.platform`.
- **Tools are plain functions.** A tool is a typed Python function plus a docstring. Its JSON schema is generated from that. No plugin framework.
- **Latency is the product.** Target **< 1 s** from key release to the first audible word. Every stage streams into the next; nothing waits for a full result if it can start on a partial one.
- **It should sound like a person, not a screen reader.** Personality, spoken phrasing, and an expressive voice matter as much as correctness.
- **Dangerous actions are confirmed out loud.** Vice says what it's about to do and waits for a spoken "yes".

## Stack

| Concern | Choice | Why |
|---|---|---|
| Language / env | Python 3.12+, managed with `uv` | Strongest AI ecosystem. `uv` is the current standard for fast, lockfile-based Python env management. |
| LLM | Claude API via the `anthropic` SDK, with native tool use and streaming | Native tool use means no hand-rolled JSON parsing. Streaming lets speech start before the full reply arrives. Default `claude-sonnet-5-5`, `claude-haiku-5-5` for fast turns. |
| Hotkey (macOS) | Quartz `CGEventTap` listening for `flagsChanged`, **keycode 61 (`kVK_RightOption`)** | MacBook keyboards have no Right Control, and Right Option sits under the right thumb. Pressed alone it does nothing in macOS. Lowest-level reliable way to catch a lone modifier key. Needs Accessibility + Input Monitoring. |
| Hotkey (Ubuntu) | `evdev` reading `/dev/input/event*` for `KEY_RIGHTCTRL` | Wayland blocks global key grabs. evdev works on any compositor. The user must be in the `input` group. |
| Mic capture | `sounddevice` (PortAudio), 16 kHz mono float32 | Works the same on CoreAudio and PipeWire. 16 kHz mono is what Whisper expects. |
| STT (macOS) | `mlx-whisper`, model `large-v3-turbo` | MLX runs on the M3 Pro's GPU and unified memory, which is much faster than CPU. |
| STT (Ubuntu) | `faster-whisper` (CTranslate2), `int8` CPU / `float16` CUDA | The fastest Whisper implementation that doesn't need Apple hardware. Same models, so behavior matches across OSes. |
| TTS (primary) | Cloud streaming TTS over WebSocket: **Cartesia Sonic** or **ElevenLabs Flash**. Pick by ear in a short bake-off. | ~100–200 ms to first audio, and far more expressive than local models (laughs, emphasis, natural intonation). Text streams in and audio streams out. |
| TTS (fallback) | Kokoro (82M) via `kokoro-onnx`, then `say` / `espeak-ng` | Offline, or when the API fails. Vice keeps talking with a plainer voice. |
| Pill (macOS) | PyObjC: borderless non-activating `NSPanel` at status-bar window level, Core Animation for motion. Runs in the daemon process. | Native, so it can sit over the menu bar and around the notch, on every Space, without stealing focus. Qt can't place a window there reliably. |
| Audio out / earcons | `sounddevice` playback of chimes synthesized at startup (`sounds.py`) | One audio library for both input and output. |
| Automation (mac) | `osascript` (AppleScript/JXA), `open`, `pbcopy`/`pbpaste`, `screencapture` | Built into the OS. |
| Automation (linux) | `xdg-open`, `wl-clipboard`, `ydotool`, portal screenshot, `gdbus` | Tools that work on Wayland. |
| Config | TOML at `~/.config/vice/config.toml`, read with stdlib `tomllib` | No dependency. |
| Secrets | `keyring`, which uses macOS Keychain / GNOME Secret Service | Keeps the API key out of plaintext. |
| Autostart (mac) | LaunchAgent `~/Library/LaunchAgents/dev.vice.agent.plist`, `RunAtLoad` + `KeepAlive` | The native per-user daemon supervisor. |
| Autostart (linux) | systemd user unit `~/.config/systemd/user/vice.service`, `WantedBy=graphical-session.target` | Restarts on crash; logs go to `journalctl --user -u vice`. |
| IPC / single instance | Unix socket at `$XDG_RUNTIME_DIR/vice.sock` (mac: `~/Library/Application Support/vice/vice.sock`), newline-delimited JSON | `vice status|quit` CLI, and blocks a second instance. Later, also the state stream for the Ubuntu pill. |

## Architecture

```
┌──────────────────── vice daemon (headless, one process) ────────────────────┐
│                                                                             │
│  hotkey listener ──► gesture state machine ──► asyncio event loop           │
│  (main thread:                                   │                          │
│   CFRunLoop / evdev)              hold ─► mic recorder ─► STT ─┐            │
│                                                                ▼            │
│                                         agent loop ◄──► Claude API          │
│                                           │    ▲                            │
│                                  tool registry ─┘ ──► platform/{macos,linux}│
│                                           │                                 │
│                          sentence splitter ──► TTS queue ──► speaker        │
│                                                  ▲                          │
│                                     tap / new hold = barge-in (flush)       │
│                                                                             │
│  state bus: idle | listening(level) | thinking | speaking(level) | confirm  │
│        └──► macOS: NSPanel pill (same process, main thread)                 │
│             (Ubuntu: no pill yet, earcons only)                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Threading model.**
- **macOS:** AppKit requires the main thread, so the main thread runs the `NSApplication` run loop. The CGEventTap also attaches to that run loop. The asyncio loop runs on a background thread. Pill updates go back to the main thread through `AppHelper.callAfter`.
- **Ubuntu:** There's no UI in the daemon. The main thread runs asyncio, and the evdev reader is a background thread.
- **Both:** Hotkey events enter asyncio via `loop.call_soon_threadsafe`. STT and TTS synthesis run via `asyncio.to_thread`, so the loop stays responsive to the hotkey.

### Hotkey gestures

Every gesture must be a **lone** hotkey press (Right Option on mac, Right Ctrl on Ubuntu). Any other key cancels it, so ⌥-combos for special characters (`⌥E` for accents, `⌥2` for ™) and Ctrl+C never trigger Vice. The key is a config value (`hotkey = "right_option"`).

| Gesture | Action |
|---|---|
| **Hold** (down for more than ~300 ms) | Push-to-talk. **Recording starts on key-down**, not when the hold is recognized. If it turns out to be a tap, the audio is discarded. Otherwise the first ~300 ms of speech would be clipped. End chime on release, then transcribe and send to the agent. |
| **Tap** (down, then up in under ~300 ms) | **Stop.** Cancels whatever is happening: speech, the agent turn, or a pending confirmation. |
| Hold **while Vice is speaking** | Barge-in: cuts off TTS immediately and starts recording. |

**Why push-to-talk:** there's no wake-word model, no false triggers, and no mic open all the time. Release marks exactly where speech ends, so no VAD is needed. The threshold is a config value.

Keep the gesture logic as a **pure state machine** in `hotkey.py`: `(event, timestamp) → action`. The platform listeners just feed it events, so it can be tested without a keyboard.

### Voice experience: latency, naturalness, personality

**Why cascaded (STT → LLM → TTS) and not a speech-to-speech model.** Realtime speech-to-speech models (one model hears audio and speaks audio) have the lowest latency and the most natural turn-taking. The cost is that they lock you to one vendor's model, which is weaker at multi-step tool calling, and swapping or debugging individual stages becomes impossible. Vice is an *agent* first, so it keeps Claude for reasoning and tools, and wins back the latency through streaming. Revisit this if the tool calling in a speech-to-speech model catches up.

**Latency budget (key release → first word):**

| Stage | Budget | How |
|---|---|---|
| STT | ~250 ms | Local Whisper on a short clip, with the model already loaded. Commands are usually < 5 s of audio. |
| LLM time-to-first-token | ~400–600 ms | Streaming + **prompt caching** on the system prompt and tool schemas, so they're cached on the server instead of re-processed each turn. |
| Sentence buffer | ~0–150 ms | Send to TTS at the first clause boundary (`, . ? ! —`), not the end of the full reply. |
| TTS time-to-first-audio | ~100–200 ms | Streaming WebSocket. The connection is opened and kept warm before it's needed. |
| **Total** | **~0.8–1.2 s** | Log every stage's timing per turn from day one. You can't tune what you don't measure. |

**Hiding latency that can't be removed:**
- **Speak before acting.** The prompt tells Claude to start with a short spoken lead-in before any tool call ("Sure, pulling that up."). The text plays while the tool runs, so the silence never reaches the user.
- **Pre-cached fillers.** A handful of short acknowledgements ("Mm-hm.", "One sec.") are synthesized once at startup in the persona's voice. If the first token takes longer than ~1.2 s, one plays instantly.
- **Warm everything at startup:** the Whisper model, the TTS socket, the HTTPS connection pool to the Claude API.

**Sounding natural:**
- The system prompt enforces **spoken register**: contractions, short sentences, no lists or markdown, numbers and dates written the way they're said ("about twenty past three"). Long tool output gets summarized, never read out.
- **Expressive markup:** if the chosen TTS supports emotion or style tags, the LLM may emit a small allowed set, and `tts.py` strips any it doesn't recognize. Keep it subtle; overdone emotion sounds fake fast.
- One consistent voice for everything, fillers included, so Vice always sounds like the same person.

**Personality:**
- Lives in `~/.config/vice/persona.md`: name, temperament, humor, how it addresses you, what it never does. It's plain prose you can edit. The system prompt is built as **persona + voice rules + tool rules + user facts**, in that order.
- Include 4–6 short **example exchanges** in the persona. Models copy demonstrated style far better than adjectives like "witty".
- **User facts** (`~/.config/vice/memory.md`): your name, preferences, recurring context. Short, injected every turn. Vice can append to it through a `remember(fact)` tool, and saying "forget that" removes an entry.
- Personality never overrides the safety rules. The voice confirmation flow stays plain and unambiguous.

**Frictionless follow-ups (later, after the base loop works):** After Vice finishes speaking, keep the mic open for ~4 s with VAD (`silero-vad`), so you can reply without touching the key. A soft cue marks the window, and when it closes nothing is recorded. This needs **echo cancellation** so Vice doesn't hear itself: macOS voice-processing audio unit, PipeWire `echo-cancel` module on Linux. That's why it's deferred.

### The pill

A small black capsule, centered at the top of the screen. On a MacBook with a notch it **grows out of the notch** (detected via `NSScreen.safeAreaInsets` / `auxiliaryTopLeftArea`), so it looks like part of the hardware. **macOS only for now.**

**Why it helps with latency:** The pill reacts on **key-down**, within one frame. It confirms "I heard the key" instantly, long before any audio can. Because you can see Vice working, a delay that would be awkward as silence feels acceptable. That buys a little room in the latency budget, but it doesn't replace the < 1 s target.

| State | Pill | Driven by |
|---|---|---|
| idle | Hidden (retracted into the bar / notch) | – |
| key-down | Starts dropping (~150 ms ease-out) | Hotkey state machine. A tap that resolves to "nothing to stop" retracts it. |
| listening | Expanded, live waveform | **Real mic RMS** (root-mean-square loudness), ~30 updates/s |
| thinking | Waveform settles to a still, dim line | Stays still until the first audio arrives. No spinner. |
| speaking | Live waveform in the accent color | **Real TTS output amplitude** |
| confirm | Widens to show one short line, e.g. `run: rm ~/Downloads/*.dmg` | The pending tool call. Seeing the exact command is safer than only hearing it. |
| error | Brief red flash, then retract | |

**Design rules:** All motion comes from **real data** (mic level, speaker level). No decorative animations, no gradients, no glow, no icons beyond a dot. It's flat black so it blends with the notch and the top bar, and it ignores the mouse (click-through). It never takes keyboard focus.

**Earcons become optional** (`sounds = true|false` in config). The pill now carries the "recording started/stopped" signal. They stay on for times you aren't looking at the screen.

### Agent loop

1. A transcript arrives. Drop it if it's empty or the recording was under ~0.3 s. Append it to the history.
2. Call Claude with streaming, prompt caching, and the tool schemas. The system prompt is persona + spoken-register rules + tool rules + user facts (see *Voice experience*).
3. Stream the text through a clause splitter into the TTS socket, so the first clause plays while the rest is still generating.
4. On `stop_reason == "tool_use"`: run the tools (with a spoken confirmation where required), append the `tool_result` blocks, and loop.
5. Cap the loop at about 15 tool rounds. A tap cancels the API stream and flushes the TTS queue.
6. The conversation is kept for a short follow-up window (~5 min idle). After that it resets so old context doesn't bleed into new requests.

### Tools (first set)

| Tool | Risk | Notes |
|---|---|---|
| `open_app(name)` / `open_url(url)` | low | `open -a` / `gtk-launch`, `xdg-open` |
| `clipboard_get` / `clipboard_set` | low | "Read what I copied", "copy that" |
| `screenshot()` | low | Sent to Claude as an image (vision) so it can describe what's on screen |
| `read_file(path)` / `list_dir(path)` | low | |
| `write_file(path, content)` | **confirm** | |
| `run_shell(cmd)` | **confirm** | Runs with a timeout. Output is truncated. |
| `type_text(text)` | **confirm** | Types into the focused app (`osascript` keystroke / `ydotool type`). Dictation-style automation. |
| `notify(title, body)` | low | |

**Spoken confirmation flow:** Vice describes the action in one sentence ("I'll delete 3 files in Downloads. Should I?"). You hold the hotkey and say yes or no. A tap means no. If there's no answer within ~10 s, it's treated as no. Yes/no is matched locally on the transcript (yes/yeah/do it vs no/stop/cancel), with no extra LLM call. Anything ambiguous counts as no.

### Planned layout

```
vice/
├── pyproject.toml
├── vice/
│   ├── __main__.py      # `python -m vice` → daemon; `vice status|quit|install|uninstall`
│   ├── daemon.py        # asyncio loop, wiring, state (idle/recording/thinking/speaking)
│   ├── agent.py         # Claude tool-use loop + speakable system prompt
│   ├── tools.py         # tool functions + schema generation + confirm policy
│   ├── stt.py           # recorder + whisper (mlx on mac, faster-whisper on linux)
│   ├── tts.py           # cloud streaming TTS + Kokoro fallback, clause splitter, fillers, interruptible
│   ├── persona.py       # builds system prompt from persona.md + memory.md + voice rules
│   ├── sounds.py        # earcons synthesized with numpy (no WAV assets)
│   ├── hotkey.py        # pure gesture state machine
│   ├── ipc.py           # unix socket server/client (status, quit)
│   ├── config.py        # tomllib load + defaults
│   └── platform/
│       ├── macos.py     # CGEventTap, NSPanel pill, osascript, LaunchAgent install
│       └── linux.py     # evdev, wl-clipboard/ydotool, systemd unit + extension install
└── tests/
    └── test_hotkey.py   # gesture state machine + yes/no matcher
```

## Build order

1. Daemon skeleton: config, IPC socket, `vice status`/`quit`, earcon playback.
2. Hotkey: gesture state machine + test, then the macOS and Linux listeners (chime on hold/release).
3. Pill (macOS): state bus in the daemon + the NSPanel pill. Driven by the hotkey alone at first (drop on key-down, retract on release).
4. STT: hold to record (pill waveform from real mic level), release to transcribe, log the transcript.
5. TTS: speak a fixed string, then the clause-streamed socket + tap to stop (pill waveform from output level).
6. Agent loop: transcript → Claude → speech, with persona + per-stage latency logging. **The first full voice loop works here.** Tune until release-to-first-word is < 1 s.
7. Tools + spoken confirmation flow (pill shows the pending action).
8. `vice install` autostart (LaunchAgent first, systemd unit after).
9. Later (not now): open-mic follow-ups with VAD + echo cancellation, MCP client support, persistent memory, scheduled automations, optional wake word.

## Platform gotchas

- **macOS permissions:** CGEventTap fails silently until Vice is granted Accessibility and Input Monitoring. Without Microphone access it records **silence** instead of raising an error. All three grants are per binary, so the launchd-started Python needs its own. Check `AXIsProcessTrusted()` and the RMS level of the first recording, and say out loud which permission is missing.
- **STT warm-up:** Load the Whisper model when the daemon starts, not on the first key hold. The first run downloads it. `large-v3-turbo` uses ~1.5 GB of RAM. Allow `small`/`base` in config for weak Linux machines.
- **Ubuntu Wayland:** Run `sudo usermod -aG input $USER`, then log back in. `ydotool` needs `ydotoold` running (also with `input`/uinput access).
- **macOS pill:** Use `NSWindowCollectionBehaviorCanJoinAllSpaces | Stationary | FullScreenAuxiliary` so it shows on every Space and over fullscreen apps. Set `ignoresMouseEvents = True`. Show the pill on the screen that currently has the menu bar, not a fixed one, for external-monitor setups.
- **PortAudio on Ubuntu:** `sounddevice` needs `sudo apt install libportaudio2` (the macOS wheel bundles it). Without it the daemon still runs, silently.
- **Autostart env:** launchd and systemd start with a minimal environment (no shell PATH, possibly no audio session yet). Use absolute paths to the `uv` venv's python. On Linux, order the unit `After=pipewire.service` so the mic exists when Vice starts.

## Deferred: Ubuntu pill

Parked, not dropped. When it's picked up: on GNOME Wayland, ordinary apps can't position windows or draw over the top bar, and Mutter doesn't support layer-shell. So it has to be a **GNOME Shell extension** (`gnome-extension/vice@vice.dev`, ESM, GNOME 45+). It would subscribe to a `subscribe` state stream on the existing IPC socket and render the same states as the mac pill. Known costs: new extensions only load after logging out and back in, `shell-version` has to be re-tested on every Ubuntu LTS bump, and it must retry quietly when the daemon is down.

## Commands

```bash
uv sync                 # install deps into .venv
uv run vice             # start the daemon in the foreground (Ctrl+C or `vice quit` to stop)
uv run vice status      # {"ok": true, "state": "idle", ...}
uv run vice quit
```
