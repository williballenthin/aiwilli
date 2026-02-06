# Model Download & Cache Feature

**Issue:** [#80](https://github.com/williballenthin/idawilli/issues/80)
**Date:** 2026-02-06

## Overview

Add automatic model download on first start with progress indication. Model cached in standard macOS cache directory.

## Cache Location

```
~/Library/Caches/aiwilli/transcribe/Voxtral-Mini-4B-Realtime-2602/
├── params.json         (~1KB)
├── tekken.json         (~2MB)
└── consolidated.safetensors  (~8.9GB)
```

## Model Source

```
Base URL: https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602/resolve/main/
```

## State Machine

```swift
enum AppState {
    case downloading(progress: Double)  // 0.0-1.0, tracks consolidated.safetensors
    case loading
    case idle
    case recording
    case transcribing
}
```

## Download Strategy

1. Create cache directory if needed
2. Download files sequentially: params.json → tekken.json → consolidated.safetensors
3. Write to `.tmp` suffix, rename on completion (atomic)
4. Skip files that already exist
5. Track progress only for consolidated.safetensors (others negligible)

## Implementation Approach

- Use `URLSessionDownloadTask` with `URLSessionDownloadDelegate`
- Progress callbacks update UI on main thread
- Simple download (no resume support) - delete partial and restart if interrupted
- `.tmp` files cleaned up automatically by URLSession on failure

## Error Handling

- Network failure → alert with retry option
- Disk full → alert and quit
- Partial download → automatic cleanup

## UI Changes

Status bar icon and menu item show download progress:
- Icon: cloud.arrow.down (or similar)
- Menu: "Status: Downloading model... 45%"

## Decisions Made

- No VOXTRAL_MODEL_DIR env var override - always use cache directory
- No resumable downloads - simple restart on failure
- Sequential download (not parallel) for simplicity
