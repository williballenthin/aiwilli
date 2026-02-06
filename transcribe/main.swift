// VoxtralDictate — macOS menubar dictation with voxtral.c linked as a library
//
// The voxtral model is loaded once at startup and stays warm in memory.
// Hold the hotkey to record with live transcription; release to stop capture.
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
var hotkeyChordActive = false

// ============================================================================
// MARK: - AppDelegate
// ============================================================================

class AppDelegate: NSObject, NSApplicationDelegate {

    private final class LiveSession {
        let id: Int
        let stream: OpaquePointer
        let converter: AVAudioConverter
        let targetFormat: AVAudioFormat
        let typingGroup = DispatchGroup()

        var totalSamplesFed = 0
        var totalTokensEmitted = 0
        var streamFreed = false

        init(id: Int,
             stream: OpaquePointer,
             converter: AVAudioConverter,
             targetFormat: AVAudioFormat) {
            self.id = id
            self.stream = stream
            self.converter = converter
            self.targetFormat = targetFormat
        }
    }

    private var statusItem: NSStatusItem!
    private var eventTap: CFMachPort?

    // Voxtral model context — loaded once, kept warm
    private var voxCtx: UnsafeMutablePointer<vox_ctx_t>?

    // Live session + queues
    private var audioEngine: AVAudioEngine?
    private var liveSession: LiveSession?
    private var nextSessionID = 1
    private var warnedBusyDuringFlush = false
    private let streamQueue = DispatchQueue(label: "aiwilli.transcribe.stream", qos: .userInitiated)
    private let typingQueue = DispatchQueue(label: "aiwilli.transcribe.typing", qos: .userInitiated)

    // Model download
    private var downloader: ModelDownloader?

    // MARK: - Lifecycle

    func applicationDidFinishLaunching(_ notification: Notification) {
        appDelegateRef = self
        setupStatusItem()
        updateUI()
        checkPermissions()
        initializeAcceleration()

        // Load model in background to keep UI responsive
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            self?.loadModel()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let tap = eventTap {
            CGEvent.tapEnable(tap: tap, enable: false)
        }

        teardownLiveSessionSynchronously()

        if let ctx = voxCtx {
            vox_free(ctx)
            voxCtx = nil
        }

        vox_metal_shutdown()
    }

    // MARK: - Acceleration

    private func initializeAcceleration() {
        let metalReady = vox_metal_init()
        if metalReady != 0 {
            print("[VoxtralDictate] Metal GPU acceleration enabled.")
        } else {
            print("[VoxtralDictate] Metal GPU unavailable — falling back to CPU/Accelerate.")
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
            print("[VoxtralDictate] Ready. Hold Ctrl+Shift+Space to dictate.")
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

    // MARK: - Push-to-talk

    func onHotkeyDown() {
        switch currentState {
        case .downloading, .loading:
            return
        case .idle:
            startRecording()
        case .recording:
            return
        case .transcribing:
            if !warnedBusyDuringFlush {
                warnedBusyDuringFlush = true
                print("[VoxtralDictate] Finishing previous dictation — please wait.")
            }
        }
    }

    func onHotkeyUp() {
        if case .recording = currentState {
            stopRecording(cancelled: false)
        }
    }

    // MARK: - Live Audio + Streaming Transcription

    private func startRecording() {
        guard let ctx = voxCtx else {
            print("[VoxtralDictate] Model not loaded yet.")
            return
        }

        guard audioEngine == nil, liveSession == nil else {
            print("[VoxtralDictate] Session already active.")
            return
        }

        let engine = AVAudioEngine()
        let inputNode = engine.inputNode
        let hwFormat = inputNode.outputFormat(forBus: 0)

        guard hwFormat.sampleRate > 0 else {
            print("[VoxtralDictate] ❌ No audio input available.")
            return
        }

        guard let targetFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: Config.targetSampleRate,
            channels: 1,
            interleaved: false
        ) else {
            print("[VoxtralDictate] ❌ Failed to create target audio format")
            return
        }

        guard let converter = AVAudioConverter(from: hwFormat, to: targetFormat) else {
            print("[VoxtralDictate] ❌ Failed to create audio converter")
            return
        }

        guard let stream = vox_stream_init(ctx) else {
            print("[VoxtralDictate] ❌ Failed to create voxtral stream")
            return
        }

        if Config.processingInterval > 0 {
            vox_set_processing_interval(stream, Config.processingInterval)
        }

        let session = LiveSession(
            id: nextSessionID,
            stream: stream,
            converter: converter,
            targetFormat: targetFormat
        )
        nextSessionID += 1
        liveSession = session

        inputNode.installTap(onBus: 0, bufferSize: 4096, format: hwFormat) { [weak self, session] buffer, _ in
            guard let self = self else { return }
            guard let copy = self.copyPCMBuffer(buffer) else { return }
            self.streamQueue.async { [weak self] in
                self?.processAudioBuffer(copy, session: session)
            }
        }

        do {
            engine.prepare()
            try engine.start()
            audioEngine = engine
            warnedBusyDuringFlush = false
            currentState = .recording
            updateUI()
            playSound(.beginRecording)
            print("[VoxtralDictate] 🔴 Recording + live transcription...")
        } catch {
            inputNode.removeTap(onBus: 0)
            freeStreamIfNeeded(session)
            liveSession = nil
            print("[VoxtralDictate] ❌ Failed to start recording: \(error)")
        }
    }

    private func stopRecording(cancelled: Bool) {
        guard let session = liveSession else { return }

        if let engine = audioEngine {
            engine.inputNode.removeTap(onBus: 0)
            engine.stop()
            audioEngine = nil
        }

        if cancelled {
            streamQueue.async { [weak self] in
                guard let self = self else { return }
                self.freeStreamIfNeeded(session)
                DispatchQueue.main.async { [weak self] in
                    guard let self = self else { return }
                    if self.liveSession === session {
                        self.liveSession = nil
                        self.warnedBusyDuringFlush = false
                        currentState = .idle
                        self.updateUI()
                    }
                }
            }
            return
        }

        playSound(.endRecording)
        currentState = .transcribing
        updateUI()
        print("[VoxtralDictate] ⏹ Capture stopped. Flushing final transcription...")

        finishSessionAfterCaptureStops(session)
    }

    private func teardownLiveSessionSynchronously() {
        guard let session = liveSession else { return }

        if let engine = audioEngine {
            engine.inputNode.removeTap(onBus: 0)
            engine.stop()
            audioEngine = nil
        }

        streamQueue.sync {
            self.freeStreamIfNeeded(session)
        }

        liveSession = nil
        warnedBusyDuringFlush = false
    }

    private func processAudioBuffer(_ buffer: AVAudioPCMBuffer, session: LiveSession) {
        guard liveSession === session else { return }

        guard var samples = convertToTargetSamples(buffer, session: session) else { return }
        if samples.isEmpty { return }

        session.totalSamplesFed += samples.count

        let feedResult: Int32 = samples.withUnsafeMutableBufferPointer { ptr in
            guard let base = ptr.baseAddress else { return -1 }
            return vox_stream_feed(session.stream, base, Int32(ptr.count))
        }

        if feedResult != 0 {
            print("[VoxtralDictate] ❌ vox_stream_feed failed")
            return
        }

        pullAvailableTokensAndQueueTyping(for: session)
    }

    private func finishSessionAfterCaptureStops(_ session: LiveSession) {
        streamQueue.async { [weak self] in
            guard let self = self else { return }
            guard self.liveSession === session else { return }

            if var tailSamples = self.flushConverterRemainder(session: session), !tailSamples.isEmpty {
                session.totalSamplesFed += tailSamples.count
                let tailFeedResult: Int32 = tailSamples.withUnsafeMutableBufferPointer { ptr in
                    guard let base = ptr.baseAddress else { return -1 }
                    return vox_stream_feed(session.stream, base, Int32(ptr.count))
                }
                if tailFeedResult != 0 {
                    print("[VoxtralDictate] ❌ Failed to feed converter tail")
                }
                self.pullAvailableTokensAndQueueTyping(for: session)
            }

            let finishResult = vox_stream_finish(session.stream)
            if finishResult != 0 {
                print("[VoxtralDictate] ❌ vox_stream_finish failed")
            }

            self.pullAvailableTokensAndQueueTyping(for: session)
            self.freeStreamIfNeeded(session)

            let totalTokens = session.totalTokensEmitted
            let seconds = Double(session.totalSamplesFed) / Config.targetSampleRate

            session.typingGroup.notify(queue: .main) { [weak self] in
                guard let self = self else { return }
                guard self.liveSession === session else { return }

                self.liveSession = nil
                self.warnedBusyDuringFlush = false
                currentState = .idle
                self.updateUI()
                self.playSound(.transcriptionDone)
                print("[VoxtralDictate] ✅ Done — \(totalTokens) tokens (\(String(format: "%.1f", seconds))s audio)")
            }
        }
    }

    private func freeStreamIfNeeded(_ session: LiveSession) {
        if session.streamFreed { return }
        vox_stream_free(session.stream)
        session.streamFreed = true
    }

    private func pullAvailableTokensAndQueueTyping(for session: LiveSession) {
        let maxTokens = 64
        let tokenPtrs = UnsafeMutablePointer<UnsafePointer<CChar>?>.allocate(capacity: maxTokens)
        defer { tokenPtrs.deallocate() }

        while true {
            let n = vox_stream_get(session.stream, tokenPtrs, Int32(maxTokens))
            if n <= 0 { break }

            session.totalTokensEmitted += Int(n)

            var text = ""
            for i in 0..<Int(n) {
                if let cStr = tokenPtrs[i] {
                    text += String(cString: cStr)
                }
            }

            if !text.isEmpty {
                let sanitized = sanitizeTextForTyping(text)
                if !sanitized.isEmpty {
                    queueTextForTyping(sanitized, session: session)
                }
            }
        }
    }

    private func queueTextForTyping(_ text: String, session: LiveSession) {
        session.typingGroup.enter()
        typingQueue.async { [weak self] in
            defer { session.typingGroup.leave() }
            self?.typeText(text)
        }
    }

    private func flushConverterRemainder(session: LiveSession) -> [Float]? {
        guard let outputBuffer = AVAudioPCMBuffer(pcmFormat: session.targetFormat, frameCapacity: 1024) else {
            return nil
        }

        var outputSamples: [Float] = []
        var loops = 0

        while true {
            loops += 1
            if loops > 128 {
                print("[VoxtralDictate] ⚠️ Converter loop guard tripped (tail flush)")
                return outputSamples
            }

            outputBuffer.frameLength = 0

            var error: NSError?
            let status = session.converter.convert(to: outputBuffer, error: &error) { _, outStatus in
                outStatus.pointee = .endOfStream
                return nil
            }

            if status == .error {
                print("[VoxtralDictate] ❌ Converter tail flush failed: \(error?.localizedDescription ?? "unknown")")
                return nil
            }

            if outputBuffer.frameLength > 0, let channelData = outputBuffer.floatChannelData?[0] {
                let count = Int(outputBuffer.frameLength)
                outputSamples.append(contentsOf: UnsafeBufferPointer(start: channelData, count: count))
            }

            switch status {
            case .haveData:
                if outputBuffer.frameLength == 0 {
                    print("[VoxtralDictate] ⚠️ Converter produced empty .haveData during tail flush; stopping flush")
                    return outputSamples
                }
                continue
            case .inputRanDry, .endOfStream:
                return outputSamples
            case .error:
                return nil
            @unknown default:
                return outputSamples
            }
        }
    }

    private func copyPCMBuffer(_ buffer: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
        guard let copy = AVAudioPCMBuffer(pcmFormat: buffer.format, frameCapacity: buffer.frameLength) else {
            return nil
        }
        copy.frameLength = buffer.frameLength

        let srcList = UnsafeMutableAudioBufferListPointer(buffer.mutableAudioBufferList)
        let dstList = UnsafeMutableAudioBufferListPointer(copy.mutableAudioBufferList)

        for i in 0..<min(srcList.count, dstList.count) {
            guard let srcData = srcList[i].mData, let dstData = dstList[i].mData else { continue }
            memcpy(dstData, srcData, Int(srcList[i].mDataByteSize))
            dstList[i].mDataByteSize = srcList[i].mDataByteSize
        }

        return copy
    }

    private func convertToTargetSamples(_ buffer: AVAudioPCMBuffer, session: LiveSession) -> [Float]? {
        let ratio = session.targetFormat.sampleRate / buffer.format.sampleRate
        let estimatedFrames = AVAudioFrameCount(max(64, Int(Double(buffer.frameLength) * ratio) + 64))

        guard let outputBuffer = AVAudioPCMBuffer(pcmFormat: session.targetFormat, frameCapacity: estimatedFrames) else {
            print("[VoxtralDictate] ❌ Failed to allocate output buffer")
            return nil
        }

        var didProvideInput = false
        var outputSamples: [Float] = []
        var loops = 0

        while true {
            loops += 1
            if loops > 128 {
                print("[VoxtralDictate] ⚠️ Converter loop guard tripped (live buffer)")
                return outputSamples
            }

            outputBuffer.frameLength = 0

            var error: NSError?
            let status = session.converter.convert(to: outputBuffer, error: &error) { _, outStatus in
                if didProvideInput {
                    outStatus.pointee = .noDataNow
                    return nil
                }

                didProvideInput = true
                outStatus.pointee = .haveData
                return buffer
            }

            if status == .error {
                print("[VoxtralDictate] ❌ Audio conversion failed: \(error?.localizedDescription ?? "unknown")")
                return nil
            }

            if outputBuffer.frameLength > 0, let channelData = outputBuffer.floatChannelData?[0] {
                let count = Int(outputBuffer.frameLength)
                outputSamples.append(contentsOf: UnsafeBufferPointer(start: channelData, count: count))
            }

            switch status {
            case .haveData:
                if outputBuffer.frameLength == 0 {
                    print("[VoxtralDictate] ⚠️ Converter produced empty .haveData for live buffer; dropping remainder")
                    return outputSamples
                }
                continue
            case .inputRanDry, .endOfStream:
                return outputSamples
            case .error:
                return nil
            @unknown default:
                return outputSamples
            }
        }
    }

    // MARK: - Text Injection (CGEvent keystrokes)

    private func sanitizeTextForTyping(_ text: String) -> String {
        let controls = CharacterSet.controlCharacters
        let filtered = text.unicodeScalars.filter { scalar in
            if scalar == "\n" || scalar == "\t" || scalar == "\r" {
                return true
            }
            return !controls.contains(scalar)
        }
        return String(String.UnicodeScalarView(filtered))
    }

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
        return Unmanaged.passUnretained(event)
    }

    let keyCode = event.getIntegerValueField(.keyboardEventKeycode)
    let flags = event.flags

    let significantFlags: CGEventFlags = [.maskCommand, .maskControl, .maskShift, .maskAlternate]
    let active = flags.intersection(significantFlags)
    let expected = Config.hotkeyModifiers.intersection(significantFlags)

    if keyCode == Config.hotkeyKeyCode {
        let isRepeat = event.getIntegerValueField(.keyboardEventAutorepeat) == 1

        if type == .keyDown && !isRepeat && active == expected {
            hotkeyChordActive = true
            DispatchQueue.main.async {
                appDelegateRef?.onHotkeyDown()
            }
            return nil
        }

        if type == .keyUp && hotkeyChordActive {
            hotkeyChordActive = false
            DispatchQueue.main.async {
                appDelegateRef?.onHotkeyUp()
            }
            return nil
        }
    }

    if type == .flagsChanged && hotkeyChordActive && active != expected {
        hotkeyChordActive = false
        DispatchQueue.main.async {
            appDelegateRef?.onHotkeyUp()
        }
    }

    return Unmanaged.passUnretained(event)
}

// ============================================================================
// MARK: - Entry Point
// ============================================================================

let app = NSApplication.shared
app.setActivationPolicy(.accessory)  // Menubar only — no Dock icon
let delegate = AppDelegate()
app.delegate = delegate
app.run()
