import AppKit
import Darwin
import WebKit

// A small native shell; all teaching, consent and saved-course logic stays in
// the shared application. No API keys pass through the native bridge.
final class StudyApp: NSObject, NSApplicationDelegate, NSWindowDelegate,
    WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var process: Process?
    var input: Pipe?
    var output: Pipe?
    var outputBuffer = Data()
    var baseURL: URL?
    var workspace: URL!
    var quitPending = false
    var stopping = false
    var allowQuit = false
    var secondary: [NSWindow] = []
    var downloads: [WKDownload] = []
    var downloadPaths: [ObjectIdentifier: (target: URL, temporary: URL)] = [:]
    var completedDownloads = 0
    var checkScript: String?
    var checkReport: URL?
    var exitStatus: Int32 = 0

    func argument(_ flag: String) -> String? {
        let args = CommandLine.arguments
        guard let index = args.firstIndex(of: flag), index + 1 < args.count else { return nil }
        return args[index + 1]
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        workspace = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Multimodal Study Tutor", isDirectory: true)
        if let path = argument("--workspace") { workspace = URL(fileURLWithPath: path, isDirectory: true) }
        if let script = argument("--check-script"), let report = argument("--check-report"), argument("--workspace") != nil {
            checkScript = script
            checkReport = URL(fileURLWithPath: report)
        }
        buildMenu()
        web = WKWebView(frame: .zero)
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = true
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1120, height: 800),
                          styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.minSize = NSSize(width: 420, height: 560)
        window.title = "听课助手 · 正在打开课程"
        window.contentView = web
        window.delegate = self
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        startBackend()
    }

    func buildMenu() {
        let main = NSMenu()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "关于听课助手", action: #selector(about), keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "退出听课助手", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let appItem = NSMenuItem(); appItem.submenu = appMenu; main.addItem(appItem)
        let edit = NSMenu(title: "编辑")
        for (title, selector, key) in [("撤销", "undo:", "z"), ("重做", "redo:", "Z"),
            ("剪切", "cut:", "x"), ("拷贝", "copy:", "c"), ("粘贴", "paste:", "v"), ("全选", "selectAll:", "a")] {
            edit.addItem(withTitle: title, action: Selector(selector), keyEquivalent: key)
        }
        let editItem = NSMenuItem(); editItem.submenu = edit; main.addItem(editItem)
        let file = NSMenu(title: "文件")
        file.addItem(withTitle: "在访达查看课程数据", action: #selector(showData), keyEquivalent: "")
        file.addItem(withTitle: "关闭窗口", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        let fileItem = NSMenuItem(); fileItem.submenu = file; main.addItem(fileItem)
        NSApp.mainMenu = main
    }

    @objc func showData() { NSWorkspace.shared.open(workspace) }
    @objc func about() {
        let alert = NSAlert()
        alert.messageText = "听课助手 · 桌面预览版"
        alert.informativeText = "将课件与教师转写整理为可追溯的学习讲义。默认在本机处理；模型讲解需另行选择并确认。\n\n课程和学习记录保存在应用之外。退出或更新应用不会删除它们。"
        alert.runModal()
    }

    func startBackend() {
        guard let resource = Bundle.main.resourceURL else { fail("应用文件缺失，请重新下载。"); return }
        let backend = resource.appendingPathComponent("backend/study-backend")
        let child = Process()
        child.executableURL = backend
        child.arguments = ["--workspace", workspace.path]
        // An installed application must work without a terminal/venv PATH.
        // Only normal OS utilities are discoverable; optional renderers are
        // not bundled and missing ones remain visible material limitations.
        var environment = ProcessInfo.processInfo.environment
        for key in Array(environment.keys) where key.hasPrefix("PYTHON") || key.hasPrefix("DYLD_") {
            environment.removeValue(forKey: key)
        }
        environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        child.environment = environment
        child.currentDirectoryURL = FileManager.default.temporaryDirectory
        let stdinPipe = Pipe(), stdoutPipe = Pipe()
        input = stdinPipe; output = stdoutPipe
        child.standardInput = stdinPipe
        child.standardOutput = stdoutPipe
        child.standardError = FileHandle.nullDevice
        process = child
        stdoutPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { self?.receive(data) }
        }
        child.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self = self else { return }
                if self.stopping { self.finishQuit() }
                else { self.fail("本地课程服务已停止。请重新打开应用，材料和已保存的学习记录仍在本机。") }
            }
        }
        do { try child.run() }
        catch { fail("无法启动课程服务。请确认应用已完整解压，再重新打开。"); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in
            guard let self = self, self.baseURL == nil, !self.stopping else { return }
            self.fail("打开课程超时，请退出后重新打开。已有课程不会被删除。")
        }
    }

    func receive(_ data: Data) {
        guard baseURL == nil, !stopping else { return }
        outputBuffer.append(data)
        guard outputBuffer.count < 8192 else { fail("课程服务返回了无效状态，请重新下载应用。"); return }
        guard let end = outputBuffer.firstIndex(of: 10) else { return }
        let line = outputBuffer[..<end]
        guard let value = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else {
            fail("课程服务未能启动，请重新打开应用。"); return
        }
        if let error = value["error"] as? String { fail(error); return }
        guard let raw = value["url"] as? String, let url = URL(string: raw),
              url.scheme == "http", url.host == "127.0.0.1", let port = url.port, port > 0 else {
            fail("课程服务地址无效，请重新打开应用。"); return
        }
        baseURL = url
        window.title = "听课助手 · 自学讲义"
        web.load(URLRequest(url: url))
    }

    func isLocal(_ url: URL) -> Bool {
        return url.scheme == baseURL?.scheme && url.host == baseURL?.host && url.port == baseURL?.port
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url, isLocal(url) else {
            if action.navigationType == .linkActivated, let url = action.request.url,
               ["https", "http"].contains(url.scheme ?? ""), url.user == nil, url.password == nil {
                NSWorkspace.shared.open(url)
            }
            decisionHandler(.cancel); return
        }
        decisionHandler(action.shouldPerformDownload ? .download : .allow)
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        let attachment = (response.response as? HTTPURLResponse)?.value(forHTTPHeaderField: "Content-Disposition")?.hasPrefix("attachment") == true
        decisionHandler(attachment || !response.canShowMIMEType ? .download : .allow)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard let url = action.request.url, isLocal(url) else { return nil }
        let source = WKWebView(frame: .zero, configuration: configuration)
        source.navigationDelegate = self; source.uiDelegate = self
        let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 850, height: 720),
                             styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        panel.title = "材料页面"; panel.contentView = source; panel.isReleasedWhenClosed = false
        panel.center(); panel.makeKeyAndOrderFront(nil); secondary.append(panel)
        return source
    }

    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters,
                 initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = false; panel.canChooseFiles = true
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.beginSheetModal(for: webView.window ?? window) { result in
            completionHandler(result == .OK ? panel.urls : nil)
        }
    }

    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) {
        downloads.append(download); download.delegate = self
    }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) {
        downloads.append(download); download.delegate = self
    }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse,
                  suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        if checkReport != nil, let directory = argument("--check-download-dir") {
            prepareDownload(download, target: URL(fileURLWithPath: directory, isDirectory: true)
                .appendingPathComponent((suggestedFilename as NSString).lastPathComponent), completionHandler: completionHandler)
            return
        }
        let panel = NSSavePanel()
        panel.nameFieldStringValue = (suggestedFilename as NSString).lastPathComponent
        panel.beginSheetModal(for: window) { result in
            guard result == .OK, let target = panel.url else { completionHandler(nil); return }
            self.prepareDownload(download, target: target, completionHandler: completionHandler)
        }
    }

    func prepareDownload(_ download: WKDownload, target: URL, completionHandler: @escaping (URL?) -> Void) {
        // WKDownload requires a non-existing destination. Do not remove an
        // earlier export until a complete new download can replace it.
        let temporary = target.deletingLastPathComponent().appendingPathComponent(".mst-download-\(UUID().uuidString).partial")
        downloadPaths[ObjectIdentifier(download)] = (target, temporary)
        completionHandler(temporary)
    }

    func downloadDidFinish(_ download: WKDownload) {
        downloads.removeAll { $0 === download }
        guard let paths = downloadPaths.removeValue(forKey: ObjectIdentifier(download)) else { return }
        do {
            if FileManager.default.fileExists(atPath: paths.target.path) {
                _ = try FileManager.default.replaceItemAt(paths.target, withItemAt: paths.temporary)
            } else { try FileManager.default.moveItem(at: paths.temporary, to: paths.target) }
            completedDownloads += 1
            if checkReport != nil {
                web.evaluateJavaScript("window.__mstNativeDownloads = \(completedDownloads)", completionHandler: nil)
            }
        } catch {
            try? FileManager.default.removeItem(at: paths.temporary)
            downloadFailure()
        }
    }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloads.removeAll { $0 === download }
        if let paths = downloadPaths.removeValue(forKey: ObjectIdentifier(download)) {
            try? FileManager.default.removeItem(at: paths.temporary)
        }
        if (error as NSError).code == NSURLErrorCancelled { return }
        downloadFailure()
    }
    func downloadFailure() {
        if checkReport != nil { fail("原生讲义下载未通过。"); return }
        let alert = NSAlert(); alert.messageText = "讲义未能下载"
        alert.informativeText = "请重新点击导出并选择保存位置。课程仍保存在应用中。"; alert.runModal()
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard webView === web, let script = checkScript else { return }
        checkScript = nil
        do {
            let source = try String(contentsOfFile: script, encoding: .utf8)
            let ready = "for(let i=0;i<600 && !window.StudyDesktop?.ready;i++) await new Promise(r=>setTimeout(r,100)); if(!window.StudyDesktop?.ready) throw new Error('UI ready timeout');\n"
            web.callAsyncJavaScript(ready + source, arguments: [:], in: nil, in: .page) { result in
                switch result {
                case .success(let value): self.completeCheck(value)
                case .failure(let error):
                    let message = (error as NSError).userInfo["WKJavaScriptExceptionMessage"] as? String ?? error.localizedDescription
                    self.fail("桌面界面检查未通过：" + message)
                }
            }
        } catch { fail("无法读取桌面检查脚本。") }
    }

    func writeCheck(_ value: Any) {
        guard let path = checkReport else { return }
        if let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: path, options: .atomic)
        }
    }

    func completeCheck(_ value: Any) {
        var report = value as? [String: Any] ?? [:]
        if let child = process { report["backend_pid"] = child.processIdentifier }
        guard let snapshot = argument("--check-snapshot") else { writeCheck(report); NSApp.terminate(nil); return }
        web.takeSnapshot(with: nil) { image, error in
            if let image = image, let tiff = image.tiffRepresentation,
               let bitmap = NSBitmapImageRep(data: tiff), let png = bitmap.representation(using: .png, properties: [:]) {
                try? png.write(to: URL(fileURLWithPath: snapshot))
            }
            self.writeCheck(report); NSApp.terminate(nil)
        }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        if webView === web { fail("学习窗口已停止响应，请重新打开应用。已保存的记录和课程仍在本机。") }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if allowQuit { return .terminateNow }
        if quitPending { return .terminateCancel }
        quitPending = true
        if baseURL == nil { stopBackend(); return .terminateLater }
        var checked = false
        let complete: (Bool, Bool) -> Void = { saved, busy in
            guard !checked, self.quitPending else { return }
            checked = true
            self.confirmClose(saved: saved, busy: busy)
        }
        web.callAsyncJavaScript("return window.StudyDesktop ? await window.StudyDesktop.prepareToClose() : {saved:false,busy:false};",
                                arguments: [:], in: nil, in: .page) { result in
            var saved = false, busy = false
            if case .success(let value) = result, let info = value as? [String: Any] {
                saved = info["saved"] as? Bool == true; busy = info["busy"] as? Bool == true
            }
            complete(saved, busy)
        }
        // A hung WebKit process cannot be relied upon to run its JS timeout.
        DispatchQueue.main.asyncAfter(deadline: .now() + 8) { complete(false, false) }
        return .terminateLater
    }

    func confirmClose(saved: Bool, busy: Bool) {
        let exporting = !downloads.isEmpty
        if (!saved || busy || exporting) && checkReport == nil {
            let alert = NSAlert()
            alert.messageText = busy ? "讲义还在生成，要退出吗？" : exporting ? "讲义还在导出，要退出吗？" : "最后的学习记录尚未保存"
            alert.informativeText = busy
                ? "退出会中断本次生成，已接收的材料和上次讲义仍保留。下次打开后可重新生成；模型调用不会自动继续。"
                : exporting ? "退出会中断尚未完成的下载。请等待导出完成，或下次重新导出。"
                : "请返回学习并等待“已保存在本机”的提示，再退出。现在退出可能丢失刚写的答案或阅读位置。"
            alert.addButton(withTitle: busy ? "继续生成" : exporting ? "继续导出" : "返回学习")
            alert.addButton(withTitle: "仍然退出")
            if alert.runModal() == .alertFirstButtonReturn {
                quitPending = false; NSApp.reply(toApplicationShouldTerminate: false); return
            }
        }
        stopBackend()
    }

    func stopBackend() {
        stopping = true
        for download in downloads { download.cancel { _ in } }
        for paths in downloadPaths.values { try? FileManager.default.removeItem(at: paths.temporary) }
        downloadPaths.removeAll()
        if let handle = input?.fileHandleForWriting {
            try? handle.write(contentsOf: Data("shutdown\n".utf8)); try? handle.close()
        }
        guard let child = process, child.isRunning else { finishQuit(); return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
            guard let self = self, !self.allowQuit else { return }
            if child.isRunning { child.terminate() }
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                if child.isRunning { kill(child.processIdentifier, SIGKILL) }
                self.finishQuit()
            }
        }
    }

    func finishQuit() {
        guard !allowQuit else { return }
        allowQuit = true
        if quitPending { NSApp.reply(toApplicationShouldTerminate: true) }
        else { NSApp.terminate(nil) }
    }

    func fail(_ message: String) {
        guard !stopping else { return }
        exitStatus = 1
        if checkReport != nil { writeCheck(["error": message]) }
        else {
            let alert = NSAlert(); alert.messageText = "暂时无法打开听课助手"; alert.informativeText = message; alert.runModal()
        }
        stopBackend()
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool { NSApp.terminate(nil); return false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        window?.makeKeyAndOrderFront(nil); return true
    }
}

let application = NSApplication.shared
let delegate = StudyApp()
application.delegate = delegate
application.setActivationPolicy(.regular)
application.run()
exit(delegate.exitStatus)
