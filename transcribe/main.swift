// VoxtralDictate — macOS menubar dictation with voxtral.c linked as a library
//
// The voxtral model is loaded once at startup and stays warm in memory.
// Press the hotkey to start recording, press again to stop.
// Audio is resampled to 16kHz mono and fed directly to the voxtral streaming
// API. Tokens are typed into the focused text field as they're generated.
//
// Build: see Makefile (handles compiling voxtral.c sources, Metal shaders,
//        and linking everything into a single binary)

import Cocoa
import AVFoundation
import Carbon.HIToolbox

// ============================================================================
// MARK: - Configuration
// ============================================================================

struct Config {
    static let modelName = "Voxtral-Mini-4B-Realtime-2602"
    static let modelBaseURL = "https://huggingface.co/mistralai/\(modelName)/resolve/main"
    static let modelFiles = ["params.json", "tekken.json", "consolidated.safetensors"]

    static var modelDirectory: String {
        let cacheDir = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first!
        return cacheDir.appendingPathComponent("aiwilli/transcribe/\(modelName)").path
    }

    // Hotkey: Control + Shift + Space (keyCode 49 = Space)
    static let hotkeyKeyCode: Int64 = 49
    static let hotkeyModifiers: CGEventFlags = [.maskControl, .maskShift]

    // Target sample rate for voxtral (fixed — do not change)
    static let targetSampleRate: Double = 16000.0

    // Delay between injected keystrokes (microseconds)
    // Increase if characters get dropped in slow apps
    static let keystrokeDelay: useconds_t = 3000

    // Processing interval for the streaming encoder/decoder (seconds).
    // 0 = process on every feed (lowest latency, higher CPU).
    // 0.5-1.0 = batch processing (more efficient for long recordings).
    static let processingInterval: Float = 0.0

    // How often to poll vox_stream_get() for new tokens during transcription (seconds)
    static let tokenPollInterval: TimeInterval = 0.02
}

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

// ============================================================================
// MARK: - Global state
// ============================================================================

enum AppState: Equatable {
    case downloading(progress: Double)  // Model downloading (0.0-1.0)
    case loading                        // Model loading at startup
    case idle                           // Ready to record
    case recording                      // Recording audio
    case transcribing                   // Transcription in progress
}

var currentState: AppState = .loading
var appDelegateRef: AppDelegate?
var globalEventTap: CFMachPort?

// ============================================================================
// MARK: - AppDelegate
// ============================================================================

class AppDelegate: NSObject, NSApplicationDelegate {

    private var statusItem: NSStatusItem!
    private var eventTap: CFMachPort?

    // Voxtral model context — loaded once, kept warm
    private var voxCtx: UnsafeMutablePointer<vox_ctx_t>?

    // Audio recording
    private var audioEngine: AVAudioEngine?
    private var recordedBuffers: [(AVAudioPCMBuffer, AVAudioFormat)] = []

    // Transcription
    private var transcriptionThread: Thread?
    private var cancelTranscription = false

    // Model download
    private var downloader: ModelDownloader?

    // MARK: - Lifecycle

    func applicationDidFinishLaunching(_ notification: Notification) {
        appDelegateRef = self
        setupStatusItem()
        updateUI()
        checkPermissions()

        // Load model in background to keep UI responsive
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            self?.loadModel()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let tap = eventTap {
            CGEvent.tapEnable(tap: tap, enable: false)
        }
        stopRecording(cancelled: true)
        if let ctx = voxCtx {
            vox_free(ctx)
            voxCtx = nil
        }
    }

    // MARK: - Model Loading

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

    // MARK: - Status Bar

    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)

        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "VoxtralDictate", action: nil, keyEquivalent: ""))
        menu.addItem(NSMenuItem.separator())

        let hotkeyItem = NSMenuItem(title: "Hotkey: ⌃⇧Space", action: nil, keyEquivalent: "")
        hotkeyItem.isEnabled = false
        menu.addItem(hotkeyItem)

        let statusMenuItem = NSMenuItem(title: "Status: Loading model...", action: nil, keyEquivalent: "")
        statusMenuItem.isEnabled = false
        statusMenuItem.tag = 100  // tag to find and update later
        menu.addItem(statusMenuItem)

        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(quitApp), keyEquivalent: "q"))

        statusItem.menu = menu
    }

    private func updateUI() {
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }

            // Update menu bar icon
            if #available(macOS 11.0, *) {
                let (symbolName, tint): (String, NSColor?) = {
                    switch currentState {
                    case .downloading:  return ("arrow.down.circle.fill", .systemBlue)
                    case .loading:      return ("hourglass", .systemGray)
                    case .idle:         return ("mic.fill", nil)
                    case .recording:    return ("record.circle.fill", .systemRed)
                    case .transcribing: return ("text.bubble.fill", .systemOrange)
                    }
                }()
                self.statusItem.button?.image = NSImage(
                    systemSymbolName: symbolName,
                    accessibilityDescription: "VoxtralDictate"
                )
                self.statusItem.button?.contentTintColor = tint
            } else {
                let icon: String = {
                    switch currentState {
                    case .downloading:  return "DL"
                    case .loading:      return "..."
                    case .idle:         return "mic"
                    case .recording:    return "REC"
                    case .transcribing: return "txt"
                    }
                }()
                self.statusItem.button?.title = icon
            }

            // Update status menu item
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
        }
    }

    @objc private func quitApp() {
        NSApplication.shared.terminate(nil)
    }

    // MARK: - Permissions

    private func checkPermissions() {
        let trusted = AXIsProcessTrusted()
        if !trusted {
            print("[VoxtralDictate] ⚠️  Accessibility permission needed.")
            print("  → System Settings → Privacy & Security → Accessibility")
            let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue(): true] as CFDictionary
            AXIsProcessTrustedWithOptions(options)
        }

        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: break
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                if !granted {
                    print("[VoxtralDictate] ⚠️  Microphone permission denied.")
                }
            }
        default:
            print("[VoxtralDictate] ⚠️  Microphone permission needed.")
        }
    }

    // MARK: - Global Hotkey

    private func setupGlobalHotkey() {
        let mask: CGEventMask = (1 << CGEventType.keyDown.rawValue)
            | (1 << CGEventType.keyUp.rawValue)
            | (1 << CGEventType.flagsChanged.rawValue)

        guard let tap = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .defaultTap,
            eventsOfInterest: mask,
            callback: globalHotkeyCallback,
            userInfo: nil
        ) else {
            print("[VoxtralDictate] ❌ Failed to create CGEventTap — grant Accessibility permission and restart.")
            return
        }

        self.eventTap = tap
        globalEventTap = tap
        let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
        CGEvent.tapEnable(tap: tap, enable: true)
        print("[VoxtralDictate] Global hotkey registered.")
    }

    // MARK: - Toggle

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

    // MARK: - Audio Recording

    private func startRecording() {
        guard voxCtx != nil else {
            print("[VoxtralDictate] Model not loaded yet.")
            return
        }

        let engine = AVAudioEngine()
        let inputNode = engine.inputNode
        let hwFormat = inputNode.outputFormat(forBus: 0)

        guard hwFormat.sampleRate > 0 else {
            print("[VoxtralDictate] ❌ No audio input available.")
            return
        }

        recordedBuffers = []

        // Install tap — capture at hardware format, we'll resample later
        inputNode.installTap(onBus: 0, bufferSize: 4096, format: hwFormat) {
            [weak self] buffer, _ in
            self?.recordedBuffers.append((buffer, hwFormat))
        }

        do {
            engine.prepare()
            try engine.start()
            audioEngine = engine
            currentState = .recording
            updateUI()
            playSound(.beginRecording)
            print("[VoxtralDictate] 🔴 Recording...")
        } catch {
            print("[VoxtralDictate] ❌ Failed to start recording: \(error)")
        }
    }

    private func stopRecording(cancelled: Bool) {
        guard let engine = audioEngine else { return }

        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        audioEngine = nil

        if cancelled {
            recordedBuffers = []
            currentState = .idle
            updateUI()
            return
        }

        playSound(.endRecording)
        print("[VoxtralDictate] ⏹ Stopped. Transcribing \(recordedBuffers.count) chunks...")
        transcribe()
    }

    // MARK: - Audio Resampling

    /// Convert recorded buffers to 16kHz mono Float32 array for voxtral
    private func resampleTo16kMono() -> [Float]? {
        guard let (firstBuffer, srcFormat) = recordedBuffers.first else { return nil }
        _ = firstBuffer  // suppress unused warning

        // Target format: 16kHz, mono, float32, non-interleaved
        guard let dstFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: Config.targetSampleRate,
            channels: 1,
            interleaved: false
        ) else {
            print("[VoxtralDictate] ❌ Failed to create target audio format")
            return nil
        }

        guard let converter = AVAudioConverter(from: srcFormat, to: dstFormat) else {
            print("[VoxtralDictate] ❌ Failed to create audio converter")
            return nil
        }

        // Calculate total frames at target sample rate
        var totalSourceFrames: AVAudioFrameCount = 0
        for (buf, _) in recordedBuffers {
            totalSourceFrames += buf.frameLength
        }
        let ratio = Config.targetSampleRate / srcFormat.sampleRate
        let estimatedOutputFrames = AVAudioFrameCount(Double(totalSourceFrames) * ratio) + 1024

        guard let outputBuffer = AVAudioPCMBuffer(
            pcmFormat: dstFormat,
            frameCapacity: estimatedOutputFrames
        ) else {
            print("[VoxtralDictate] ❌ Failed to allocate output buffer")
            return nil
        }

        // Feed buffers through converter
        var bufferIndex = 0
        var bufferOffset: AVAudioFrameCount = 0

        let inputBlock: AVAudioConverterInputBlock = { inNumPackets, outStatus in
            while bufferIndex < self.recordedBuffers.count {
                let (srcBuf, _) = self.recordedBuffers[bufferIndex]
                let remaining = srcBuf.frameLength - bufferOffset

                if remaining > 0 {
                    // Create a slice of the current buffer
                    let framesToCopy = min(AVAudioFrameCount(inNumPackets), remaining)
                    guard let sliceBuffer = AVAudioPCMBuffer(
                        pcmFormat: srcBuf.format,
                        frameCapacity: framesToCopy
                    ) else {
                        outStatus.pointee = .endOfStream
                        return nil
                    }

                    // Copy audio data
                    let srcChannels = srcBuf.format.channelCount
                    for ch in 0..<Int(srcChannels) {
                        if let srcData = srcBuf.floatChannelData?[ch],
                           let dstData = sliceBuffer.floatChannelData?[ch] {
                            dstData.update(from: srcData.advanced(by: Int(bufferOffset)),
                                           count: Int(framesToCopy))
                        }
                    }
                    sliceBuffer.frameLength = framesToCopy
                    bufferOffset += framesToCopy

                    outStatus.pointee = .haveData
                    return sliceBuffer
                }

                bufferIndex += 1
                bufferOffset = 0
            }

            outStatus.pointee = .endOfStream
            return nil
        }

        var error: NSError?
        let status = converter.convert(to: outputBuffer, error: &error, withInputFrom: inputBlock)

        if status == .error {
            print("[VoxtralDictate] ❌ Audio conversion failed: \(error?.localizedDescription ?? "unknown")")
            return nil
        }

        // Extract float samples
        guard let channelData = outputBuffer.floatChannelData else { return nil }
        let count = Int(outputBuffer.frameLength)
        return Array(UnsafeBufferPointer(start: channelData[0], count: count))
    }

    // MARK: - Transcription (direct C API)

    private func transcribe() {
        guard let ctx = voxCtx else { return }

        currentState = .transcribing
        cancelTranscription = false
        updateUI()

        // Resample on a background thread
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self = self else { return }

            guard var samples = self.resampleTo16kMono() else {
                print("[VoxtralDictate] ❌ Failed to resample audio")
                DispatchQueue.main.async {
                    currentState = .idle
                    self.updateUI()
                }
                return
            }

            // Clear recorded buffers — no longer needed
            DispatchQueue.main.async { self.recordedBuffers = [] }

            let sampleCount = samples.count
            print("[VoxtralDictate] Feeding \(sampleCount) samples (\(String(format: "%.1f", Double(sampleCount) / Config.targetSampleRate))s of audio)")

            // Create stream and feed audio
            guard let stream = vox_stream_init(ctx) else {
                print("[VoxtralDictate] ❌ Failed to create voxtral stream")
                DispatchQueue.main.async {
                    currentState = .idle
                    self.updateUI()
                }
                return
            }

            if Config.processingInterval > 0 {
                vox_set_processing_interval(stream, Config.processingInterval)
            }

            // Feed all samples
            _ = samples.withUnsafeMutableBufferPointer { ptr in
                vox_stream_feed(stream, ptr.baseAddress!, Int32(sampleCount))
            }

            // Signal end of audio
            vox_stream_finish(stream)

            // Collect tokens and type them
            let maxTokens = 64
            let tokenPtrs = UnsafeMutablePointer<UnsafePointer<CChar>?>.allocate(capacity: maxTokens)
            defer { tokenPtrs.deallocate() }

            var totalTokens = 0
            while !self.cancelTranscription {
                let n = vox_stream_get(stream, tokenPtrs, Int32(maxTokens))
                if n <= 0 { break }

                totalTokens += Int(n)

                // Collect token strings
                var text = ""
                for i in 0..<Int(n) {
                    if let cStr = tokenPtrs[i] {
                        text += String(cString: cStr)
                    }
                }

                // Type on main thread
                if !text.isEmpty {
                    DispatchQueue.main.sync {
                        self.typeText(text)
                    }
                }
            }

            vox_stream_free(stream)

            print("[VoxtralDictate] ✅ Done — \(totalTokens) tokens")

            DispatchQueue.main.async {
                currentState = .idle
                self.updateUI()
                self.playSound(.transcriptionDone)
            }
        }
    }

    private func doCancelTranscription() {
        cancelTranscription = true
        currentState = .idle
        updateUI()
        print("[VoxtralDictate] ⛔ Transcription cancelled.")
    }

    // MARK: - Text Injection (CGEvent keystrokes)

    private func typeText(_ text: String) {
        let utf16 = Array(text.utf16)
        let chunkSize = 18  // CGEvent limit is ~20 UTF-16 units

        for i in stride(from: 0, to: utf16.count, by: chunkSize) {
            let end = min(i + chunkSize, utf16.count)
            var chunk = Array(utf16[i..<end])

            guard let keyDown = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true) else { continue }
            keyDown.keyboardSetUnicodeString(stringLength: chunk.count, unicodeString: &chunk)
            keyDown.post(tap: .cgSessionEventTap)

            guard let keyUp = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: false) else { continue }
            keyUp.post(tap: .cgSessionEventTap)

            usleep(Config.keystrokeDelay)
        }
    }

    // MARK: - Sound Feedback

    enum SoundEvent {
        case beginRecording
        case endRecording
        case transcriptionDone
    }

    private func playSound(_ event: SoundEvent) {
        let name: NSSound.Name
        switch event {
        case .beginRecording:    name = NSSound.Name("Morse")
        case .endRecording:      name = NSSound.Name("Tink")
        case .transcriptionDone: name = NSSound.Name("Glass")
        }
        NSSound(named: name)?.play()
    }
}

// ============================================================================
// MARK: - CGEventTap callback
// ============================================================================

func globalHotkeyCallback(
    proxy: CGEventTapProxy,
    type: CGEventType,
    event: CGEvent,
    userInfo: UnsafeMutableRawPointer?
) -> Unmanaged<CGEvent>? {

    if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
        if let tap = globalEventTap {
            CGEvent.tapEnable(tap: tap, enable: true)
        }
        return Unmanaged.passRetained(event)
    }

    guard type == .keyDown else {
        return Unmanaged.passRetained(event)
    }

    let keyCode = event.getIntegerValueField(.keyboardEventKeycode)
    let flags = event.flags

    let significantFlags: CGEventFlags = [.maskCommand, .maskControl, .maskShift, .maskAlternate]
    let active = flags.intersection(significantFlags)
    let expected = Config.hotkeyModifiers.intersection(significantFlags)

    if active == expected && keyCode == Config.hotkeyKeyCode {
        DispatchQueue.main.async {
            appDelegateRef?.toggle()
        }
        return nil  // Suppress the hotkey
    }

    return Unmanaged.passRetained(event)
}

// ============================================================================
// MARK: - Entry Point
// ============================================================================

let app = NSApplication.shared
app.setActivationPolicy(.accessory)  // Menubar only — no Dock icon
let delegate = AppDelegate()
app.delegate = delegate
app.run()
