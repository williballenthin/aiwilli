# Model Download & Cache Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automatically download the Voxtral model to cache directory on first start with progress bar.

**Architecture:** Extend AppState with downloading state, add URLSession-based downloader with delegate for progress, update UI to show download progress in status bar menu.

**Tech Stack:** Swift, URLSession, URLSessionDownloadDelegate, FileManager

---

### Task 1: Update AppState enum

**Files:**
- Modify: `transcribe/main.swift:53-58`

**Step 1: Update AppState to include downloading state**

Change:
```swift
enum AppState {
    case loading       // Model loading at startup
    case idle          // Ready to record
    case recording     // Recording audio
    case transcribing  // Transcription in progress
}
```

To:
```swift
enum AppState: Equatable {
    case downloading(progress: Double)  // Model downloading (0.0-1.0)
    case loading                        // Model loading at startup
    case idle                           // Ready to record
    case recording                      // Recording audio
    case transcribing                   // Transcription in progress
}
```

**Step 2: Build to verify syntax**

Run: `cd ~/code/aiwilli/transcribe && make`
Expected: Build succeeds (may have warnings about switch cases - that's expected, we'll fix next)

**Step 3: Commit**

```bash
cd ~/code/aiwilli && git add transcribe/main.swift
git commit -m "feat(transcribe): add downloading state to AppState"
```

---

### Task 2: Update Config for cache directory

**Files:**
- Modify: `transcribe/main.swift:19-27`

**Step 1: Replace modelDirectory with cache-based path**

Change:
```swift
struct Config {
    // Path to model directory (consolidated.safetensors, tekken.json, params.json)
    // Override with VOXTRAL_MODEL_DIR environment variable
    static var modelDirectory: String {
        if let env = ProcessInfo.processInfo.environment["VOXTRAL_MODEL_DIR"] {
            return env
        }
        return "\(NSHomeDirectory())/voxtral.c/voxtral-model"
    }
```

To:
```swift
struct Config {
    static let modelName = "Voxtral-Mini-4B-Realtime-2602"
    static let modelBaseURL = "https://huggingface.co/mistralai/\(modelName)/resolve/main"
    static let modelFiles = ["params.json", "tekken.json", "consolidated.safetensors"]

    static var modelDirectory: String {
        let cacheDir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first!
        return cacheDir.appendingPathComponent("aiwilli/transcribe/\(modelName)").path
    }
```

**Step 2: Build to verify**

Run: `cd ~/code/aiwilli/transcribe && make`
Expected: Build succeeds

**Step 3: Commit**

```bash
cd ~/code/aiwilli && git add transcribe/main.swift
git commit -m "feat(transcribe): use cache directory for model storage"
```

---

### Task 3: Add ModelDownloader class

**Files:**
- Modify: `transcribe/main.swift` (add new class after Config struct, around line 48)

**Step 1: Add ModelDownloader class**

Insert after Config struct closing brace:

```swift
// ============================================================================
// MARK: - Model Downloader
// ============================================================================

class ModelDownloader: NSObject, URLSessionDownloadDelegate {
    private var session: URLSession!
    private var currentFileIndex = 0
    private var onProgress: ((Double) -> Void)?
    private var onComplete: ((Result<Void, Error>) -> Void)?

    override init() {
        super.init()
        let config = URLSessionConfiguration.default
        session = URLSession(configuration: config, delegate: self, delegateQueue: .main)
    }

    func downloadModel(onProgress: @escaping (Double) -> Void, onComplete: @escaping (Result<Void, Error>) -> Void) {
        self.onProgress = onProgress
        self.onComplete = onComplete
        self.currentFileIndex = 0

        let modelDir = Config.modelDirectory
        do {
            try FileManager.default.createDirectory(atPath: modelDir, withIntermediateDirectories: true)
        } catch {
            onComplete(.failure(error))
            return
        }

        downloadNextFile()
    }

    private func downloadNextFile() {
        guard currentFileIndex < Config.modelFiles.count else {
            onComplete?(.success(()))
            return
        }

        let filename = Config.modelFiles[currentFileIndex]
        let destPath = "\(Config.modelDirectory)/\(filename)"

        if FileManager.default.fileExists(atPath: destPath) {
            print("[ModelDownloader] \(filename) already exists, skipping")
            currentFileIndex += 1
            downloadNextFile()
            return
        }

        guard let url = URL(string: "\(Config.modelBaseURL)/\(filename)") else {
            onComplete?(.failure(NSError(domain: "ModelDownloader", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid URL"])))
            return
        }

        print("[ModelDownloader] Downloading \(filename)...")
        let task = session.downloadTask(with: url)
        task.resume()
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        let filename = Config.modelFiles[currentFileIndex]
        let destPath = "\(Config.modelDirectory)/\(filename)"
        let destURL = URL(fileURLWithPath: destPath)

        do {
            if FileManager.default.fileExists(atPath: destPath) {
                try FileManager.default.removeItem(atPath: destPath)
            }
            try FileManager.default.moveItem(at: location, to: destURL)
            print("[ModelDownloader] Downloaded \(filename)")

            currentFileIndex += 1
            downloadNextFile()
        } catch {
            onComplete?(.failure(error))
        }
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didWriteData bytesWritten: Int64, totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        let filename = Config.modelFiles[currentFileIndex]
        if filename == "consolidated.safetensors" && totalBytesExpectedToWrite > 0 {
            let progress = Double(totalBytesWritten) / Double(totalBytesExpectedToWrite)
            onProgress?(progress)
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error = error {
            print("[ModelDownloader] Error: \(error.localizedDescription)")
            onComplete?(.failure(error))
        }
    }
}
```

**Step 2: Build to verify**

Run: `cd ~/code/aiwilli/transcribe && make`
Expected: Build succeeds

**Step 3: Commit**

```bash
cd ~/code/aiwilli && git add transcribe/main.swift
git commit -m "feat(transcribe): add ModelDownloader class with progress"
```

---

### Task 4: Add downloader property and update loadModel

**Files:**
- Modify: `transcribe/main.swift` (AppDelegate class)

**Step 1: Add downloader property to AppDelegate**

After line `private var cancelTranscription = false` add:

```swift
    private var downloader: ModelDownloader?
```

**Step 2: Update loadModel to check files and trigger download**

Replace the entire `loadModel()` method with:

```swift
    private func loadModel() {
        let modelDir = Config.modelDirectory
        print("[VoxtralDictate] Model directory: \(modelDir)")

        let allFilesExist = Config.modelFiles.allSatisfy { filename in
            FileManager.default.fileExists(atPath: "\(modelDir)/\(filename)")
        }

        if !allFilesExist {
            print("[VoxtralDictate] Model not found, starting download...")
            DispatchQueue.main.async {
                currentState = .downloading(progress: 0.0)
                self.updateUI()
            }

            downloader = ModelDownloader()
            downloader?.downloadModel(
                onProgress: { [weak self] progress in
                    currentState = .downloading(progress: progress)
                    self?.updateUI()
                },
                onComplete: { [weak self] result in
                    switch result {
                    case .success:
                        print("[VoxtralDictate] Download complete, loading model...")
                        DispatchQueue.global(qos: .userInitiated).async {
                            self?.doLoadModel()
                        }
                    case .failure(let error):
                        print("[VoxtralDictate] Download failed: \(error.localizedDescription)")
                        DispatchQueue.main.async {
                            let alert = NSAlert()
                            alert.messageText = "Download Failed"
                            alert.informativeText = error.localizedDescription
                            alert.alertStyle = .critical
                            alert.addButton(withTitle: "Retry")
                            alert.addButton(withTitle: "Quit")
                            let response = alert.runModal()
                            if response == .alertFirstButtonReturn {
                                DispatchQueue.global(qos: .userInitiated).async {
                                    self?.loadModel()
                                }
                            } else {
                                NSApplication.shared.terminate(nil)
                            }
                        }
                    }
                }
            )
            return
        }

        doLoadModel()
    }

    private func doLoadModel() {
        let modelDir = Config.modelDirectory
        print("[VoxtralDictate] Loading model from: \(modelDir)")

        DispatchQueue.main.async {
            currentState = .loading
            self.updateUI()
        }

        let start = CFAbsoluteTimeGetCurrent()
        let ctx = vox_load(modelDir)
        let elapsed = CFAbsoluteTimeGetCurrent() - start

        guard ctx != nil else {
            print("[VoxtralDictate] Failed to load model")
            DispatchQueue.main.async {
                let alert = NSAlert()
                alert.messageText = "Model Load Failed"
                alert.informativeText = "Failed to load model from:\n\(modelDir)"
                alert.alertStyle = .critical
                alert.runModal()
            }
            return
        }

        self.voxCtx = ctx
        print("[VoxtralDictate] Model loaded in \(String(format: "%.1f", elapsed))s")

        DispatchQueue.main.async { [weak self] in
            currentState = .idle
            self?.setupGlobalHotkey()
            self?.updateUI()
            print("[VoxtralDictate] Ready. Press Ctrl+Shift+Space to toggle recording.")
        }
    }
```

**Step 3: Build to verify**

Run: `cd ~/code/aiwilli/transcribe && make`
Expected: Build succeeds (may have switch warnings still)

**Step 4: Commit**

```bash
cd ~/code/aiwilli && git add transcribe/main.swift
git commit -m "feat(transcribe): integrate downloader into loadModel flow"
```

---

### Task 5: Update UI for downloading state

**Files:**
- Modify: `transcribe/main.swift` (updateUI method)

**Step 1: Update updateUI to handle downloading state**

In the `updateUI()` method, update the switch statement for icon selection. Change:

```swift
                let (symbolName, tint): (String, NSColor?) = {
                    switch currentState {
                    case .loading:      return ("hourglass", .systemGray)
                    case .idle:         return ("mic.fill", nil)
                    case .recording:    return ("record.circle.fill", .systemRed)
                    case .transcribing: return ("text.bubble.fill", .systemOrange)
                    }
                }()
```

To:

```swift
                let (symbolName, tint): (String, NSColor?) = {
                    switch currentState {
                    case .downloading:  return ("arrow.down.circle.fill", .systemBlue)
                    case .loading:      return ("hourglass", .systemGray)
                    case .idle:         return ("mic.fill", nil)
                    case .recording:    return ("record.circle.fill", .systemRed)
                    case .transcribing: return ("text.bubble.fill", .systemOrange)
                    }
                }()
```

**Step 2: Update the fallback icon switch (for older macOS)**

Change:

```swift
                let icon: String = {
                    switch currentState {
                    case .loading:      return "⏳"
                    case .idle:         return "🎙"
                    case .recording:    return "🔴"
                    case .transcribing: return "💬"
                    }
                }()
```

To:

```swift
                let icon: String = {
                    switch currentState {
                    case .downloading:  return "⬇️"
                    case .loading:      return "⏳"
                    case .idle:         return "🎙"
                    case .recording:    return "🔴"
                    case .transcribing: return "💬"
                    }
                }()
```

**Step 3: Update the status menu item text switch**

Change:

```swift
            if let statusItem = self.statusItem.menu?.item(withTag: 100) {
                switch currentState {
                case .loading:      statusItem.title = "Status: Loading model..."
                case .idle:         statusItem.title = "Status: Ready"
                case .recording:    statusItem.title = "Status: Recording..."
                case .transcribing: statusItem.title = "Status: Transcribing..."
                }
            }
```

To:

```swift
            if let statusItem = self.statusItem.menu?.item(withTag: 100) {
                switch currentState {
                case .downloading(let progress):
                    statusItem.title = "Status: Downloading model... \(Int(progress * 100))%"
                case .loading:      statusItem.title = "Status: Loading model..."
                case .idle:         statusItem.title = "Status: Ready"
                case .recording:    statusItem.title = "Status: Recording..."
                case .transcribing: statusItem.title = "Status: Transcribing..."
                }
            }
```

**Step 4: Build to verify**

Run: `cd ~/code/aiwilli/transcribe && make`
Expected: Build succeeds with no warnings

**Step 5: Commit**

```bash
cd ~/code/aiwilli && git add transcribe/main.swift
git commit -m "feat(transcribe): update UI to show download progress"
```

---

### Task 6: Update toggle to handle downloading state

**Files:**
- Modify: `transcribe/main.swift` (toggle method)

**Step 1: Update toggle to ignore during download**

Change:

```swift
    func toggle() {
        switch currentState {
        case .loading:
            return  // Model still loading — ignore
        case .idle:
            startRecording()
        case .recording:
            stopRecording(cancelled: false)
        case .transcribing:
            doCancelTranscription()
        }
    }
```

To:

```swift
    func toggle() {
        switch currentState {
        case .downloading:
            return  // Model downloading — ignore
        case .loading:
            return  // Model still loading — ignore
        case .idle:
            startRecording()
        case .recording:
            stopRecording(cancelled: false)
        case .transcribing:
            doCancelTranscription()
        }
    }
```

**Step 2: Build and verify**

Run: `cd ~/code/aiwilli/transcribe && make`
Expected: Build succeeds

**Step 3: Commit**

```bash
cd ~/code/aiwilli && git add transcribe/main.swift
git commit -m "feat(transcribe): ignore hotkey during download"
```

---

### Task 7: Manual testing

**Step 1: Clear cache to test fresh download**

```bash
rm -rf ~/Library/Caches/aiwilli/transcribe/
```

**Step 2: Build and run**

```bash
cd ~/code/aiwilli/transcribe && make && ./VoxtralDictate
```

**Step 3: Verify behavior**

Expected:
- Status bar shows download icon (blue arrow)
- Menu shows "Status: Downloading model... X%"
- Progress updates as consolidated.safetensors downloads
- After download, transitions to loading then idle
- Hotkey works after model loads

**Step 4: Test with existing model**

Kill app, restart:
```bash
./VoxtralDictate
```

Expected:
- Skips download (files exist)
- Goes straight to loading then idle

**Step 5: Final commit with any fixes**

```bash
cd ~/code/aiwilli && git add -A
git commit -m "feat(transcribe): complete model download/cache feature"
```

---

### Task 8: Create PR and update project

**Step 1: Push branch**

```bash
cd ~/code/aiwilli && git push -u origin HEAD
```

**Step 2: Create PR**

```bash
gh pr create --title "feat(transcribe): download model to cache on first start" --body "$(cat <<'EOF'
## Summary
- Adds automatic model download on first start
- Uses ~/Library/Caches/aiwilli/transcribe/Voxtral-Mini-4B-Realtime-2602/
- Shows download progress in status bar menu
- Skips download if model already cached

Fixes williballenthin/idawilli#80

## Test plan
- [ ] Clear cache, run app, verify download starts with progress
- [ ] Verify model loads after download completes
- [ ] Restart app, verify skips download when cached
- [ ] Verify hotkey works after model loads

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

**Step 3: Move task to "In review"**

```bash
gh project item-edit --project-id "PVT_kwHOAAJjkM4BOd3T" --id "PVTI_lAHOAAJjkM4BOd3Tzgk8utc" --field-id "PVTSSF_lAHOAAJjkM4BOd3Tzg9KTSM" --single-select-option-id "df73e18b"
```

**Step 4: Add comment to issue**

```bash
gh issue comment 80 --repo williballenthin/idawilli --body "PR created with implementation. Model downloads to ~/Library/Caches/aiwilli/transcribe/Voxtral-Mini-4B-Realtime-2602/ on first start with progress bar in status menu."
```
