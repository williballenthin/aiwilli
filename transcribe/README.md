# VoxtralDictate

A macOS menubar dictation app powered by [voxtral.c](https://github.com/antirez/voxtral.c) — antirez's pure C implementation of Mistral's Voxtral Realtime 4B speech-to-text model.

Hold **Ctrl+Shift+Space** to record. While held, audio is streamed continuously and transcription output is emitted incrementally to the focused text field. Release the hotkey to stop capture immediately; the app then flushes the final transcription tail and returns to idle.

## Architecture

Unlike a typical subprocess approach, voxtral.c is compiled as a **static library** and linked directly into the Swift binary. The model is loaded once at startup and stays warm in memory for instant transcriptions.

```
┌─────────────────────────────────────────────────────────┐
│  VoxtralDictate (single binary)                         │
│                                                         │
│  ┌──────────┐   ┌──────────────┐   ┌────────────────┐  │
│  │ AVAudio  │──▶│ Resample to  │──▶│ vox_stream_*() │  │
│  │ Engine   │   │ 16kHz mono   │   │ (C API)        │  │
│  └──────────┘   └──────────────┘   └───────┬────────┘  │
│                                            │ tokens    │
│  ┌──────────┐                    ┌─────────▼────────┐  │
│  │ Menubar  │                    │ CGEvent keystrokes│  │
│  │ UI + HK  │                    │ → focused app     │  │
│  └──────────┘                    └──────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**No subprocess, no temp files, no pipes.** Audio flows from the microphone through AVAudioEngine → sample rate conversion → voxtral's streaming C API → CGEvent keystroke injection.

## Prerequisites

### 1. Xcode Command Line Tools

```bash
xcode-select --install
```

### 2. Clone and download voxtral.c + model

```bash
git clone https://github.com/antirez/voxtral.c ~/voxtral.c
cd ~/voxtral.c
./download_model.sh    # ~8.9 GB
```

Verify the build works standalone first:

```bash
cd ~/voxtral.c
make mps
./voxtral -d voxtral-model -i samples/test_speech.wav
```

## Build

```bash
cd voxtral-dictate
make
```

This will:
1. Compile voxtral's C and Objective-C sources into object files
2. Compile the Metal shaders into `default.metallib`
3. Archive everything into `libvoxtral.a`
4. Compile the Swift app with the bridging header
5. Link the final binary

If voxtral.c is cloned somewhere other than `~/voxtral.c`:

```bash
make VOXTRAL_SRC=/path/to/voxtral.c
```

### Build Troubleshooting

**Metal define mismatch (`USE_MPS` vs `USE_METAL`):**
voxtral.c uses `USE_METAL` (not `USE_MPS`). If acceleration is unexpectedly slow, verify `MPS_CFLAGS` includes `-DUSE_METAL` (and ideally `-DUSE_BLAS`) in this project's Makefile.

**Header conflicts with Swift:**
If `#include "voxtral.h"` causes issues, edit `VoxtralBridge.h` — comment out the `#include` and uncomment the forward-declaration fallback block.

**Linker errors (missing symbols):**
Make sure no voxtral source files were added since this was written. Check `ls ~/voxtral.c/*.c ~/voxtral.c/*.m` and add any new files to `VOX_C_SRCS` or `VOX_OBJC_SRCS` in the Makefile.

**Function signature mismatch:**
The bridging header's fallback declarations are based on the README API examples. If voxtral.h uses different signatures (e.g. `int64_t` instead of `int`), update the fallback declarations or switch to directly including voxtral.h.

## Run

```bash
make run
```

Or manually:

```bash
# The metallib must be findable — place it next to the binary
cp build/default.metallib .
./VoxtralDictate
```

On first launch, macOS will prompt for:
1. **Microphone access** — to record audio
2. **Accessibility access** — for the global hotkey and keystroke injection

Grant both in **System Settings → Privacy & Security**.

## Usage

| Action | Effect |
|--------|--------|
| **Hold Ctrl+Shift+Space** | Start recording + incremental transcription (menubar turns red; output may be bursty) |
| **Release Ctrl+Shift+Space** | Stop recording immediately, flush final transcription output, then return idle |
| **Press while finishing** | Ignored until the previous session finishes flushing |

The first transcription after launch may take a few extra seconds while macOS pages in the model weights. Subsequent transcriptions are faster.

## Known Limitation: Streaming Latency (Upstream)

This app already feeds audio to `vox_stream_feed()` continuously and emits tokens as soon as `vox_stream_get()` returns them.

However, the current upstream `voxtral.c` C implementation is still chunk-oriented and does **not** yet implement the full low-latency online decode schedule described in its model notes (see upstream `MODEL.md`: "Online Decode Schedule (not yet implemented in C)"). In practice, this means output may still feel delayed or bursty, especially before the final flush.

So if dictation does not feel truly real-time, the main bottleneck is currently upstream decoding strategy rather than app hotkey/audio plumbing. If/when upstream lands full online decode support, this app can adopt it and reduce latency significantly.

## Configuration

Edit the `Config` struct in `main.swift`:

```swift
struct Config {
    // Model path (or set VOXTRAL_MODEL_DIR env var)
    static var modelDirectory: String { ... }

    // Hotkey
    static let hotkeyKeyCode: Int64 = 49  // Space
    static let hotkeyModifiers: CGEventFlags = [.maskControl, .maskShift]

    // Keystroke delay (increase if chars drop in slow apps)
    static let keystrokeDelay: useconds_t = 3000
}
```

### Hotkey alternatives

| Combo | keyCode | Modifiers |
|-------|---------|-----------|
| Ctrl+Shift+Space | 49 | `[.maskControl, .maskShift]` |
| Cmd+Shift+D | 2 | `[.maskCommand, .maskShift]` |
| F5 | 96 | `[]` |

### Environment variables

| Variable | Purpose |
|----------|---------|
| `VOXTRAL_MODEL_DIR` | Override model path at runtime without recompiling |

## Install

```bash
make install
```

Copies the binary and metallib to `~/.local/bin/`. To auto-start on login, create a LaunchAgent:

```bash
cat > ~/Library/LaunchAgents/com.voxtral.dictate.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.voxtral.dictate</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOURUSERNAME/.local/bin/VoxtralDictate</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/YOURUSERNAME/.local/bin</string>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/voxtral-dictate.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/voxtral-dictate.log</string>
</dict>
</plist>
EOF

# Edit the plist — replace YOURUSERNAME
launchctl load ~/Library/LaunchAgents/com.voxtral.dictate.plist
```

## Memory & Performance

| | Value |
|---|---|
| Binary size | ~few KB (model weights are separate) |
| Model weights | 8.9 GB (memory-mapped, paged in on demand) |
| GPU memory (MPS) | ~8.4 GB for weights + ~1.8 GB KV cache |
| RAM (app itself) | ~50 MB |
| Transcription speed (M-series) | ~43ms/token, ~5s for short clips |
| Startup (model load) | ~2-5s first time, near-instant after |

## How It Differs from v1 (subprocess approach)

| | v1 (subprocess) | v2 (linked library) |
|---|---|---|
| Architecture | Spawns voxtral binary via Process | Calls C API directly |
| Model loading | Cold start every transcription | Loaded once, stays warm |
| Audio handling | Write WAV to /tmp, pass file path | In-memory float buffers |
| Distribution | Two binaries (app + voxtral) | Single binary |
| Latency | Process spawn + file I/O overhead | Direct function calls |
| Memory | Model loaded/unloaded each time | Always resident (~10 GB) |

## Future Ideas

- **Adopt upstream true online decode** (once available in voxtral.c) for lower-latency token emission
- **Configurable hotkey UI** via a preferences panel
- **Language selection** in the menubar
- **Audio level indicator** in the menubar during recording

## License

MIT (same as voxtral.c)
