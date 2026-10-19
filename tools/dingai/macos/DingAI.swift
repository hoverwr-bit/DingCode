//
//  DingAI.swift — screen-pin annotations for coding agents (macOS)
//  交互语言对齐网页批注层 web/anno.js:单击落钉(XY辅助线+坐标气泡+信息签)/拖拽画箭头/⌘Z撤销/Esc完成
//  产出:JSON(截图像素坐标、左上原点)+ 底图截图,复制进剪贴板并落盘
//
//  编译:  swiftc -O -swift-version 5 -o DingAI DingAI.swift
//          -framework AppKit -framework Carbon -framework Vision -framework ScreenCaptureKit
//  权限:  屏幕录制(截图/OCR/窗口标题需要);热键与绘制不需要任何权限
//

import AppKit
import Carbon
import Carbon.HIToolbox
import Vision
import ScreenCaptureKit
import Network
import ApplicationServices

// MARK: - 数据模型(截图像素坐标,左上原点)

struct AppInfo {
    var bundleId: String?
    var name: String?
    var path: String?
    var pid: Int
}

struct WindowInfo {
    var title: String?
    var framePx: [Int]?   // 全局顶左原点点数 [x, y, w, h]
}

struct ScrollSample {
    var v = 0.0, vMin = 0.0, vMax = 0.0, hasV = false
    var h = 0.0, hMin = 0.0, hMax = 0.0, hasH = false
}

struct PinRecord {
    var id: Int
    var x: Int            // 截图像素 x
    var y: Int            // 截图像素 y
    var ocrNearby: String
    var note: String?     // 人工备注(落钉后弹输入框)
    var windowOwner: String?   // 钉子真正落在的窗口(按坐标定位,可能≠前台主窗)
    var windowTitle: String?
    var windowFrame: [Int]?    // 钉所在窗口 frame(本屏局部,点)——归一化坐标的基准
    var pageInfo: [String: Any]?  // 页内桥结果(anno-bridge;桌面钉落在网页时=页面坐标+元素描述,与 anno-v7 同语义)
    var anchorKind: String = "viewport"   // ax | web | scroll | viewport
    var anchorDX: Double = 0              // 元素左上角到钉点的偏移(全局点,顶左)
    var anchorDY: Double = 0
    var anchorKey: String?
    var anchorNote: String?
    var scroll: ScrollSample?
}

struct ArrowRecord {
    var id: Int
    var fromX: Int
    var fromY: Int
    var toX: Int
    var toY: Int
    var color: String     // red / yellow / cyan
    var width: Int        // 2 / 4 / 6
}

struct BoxRecord {
    var id: Int
    var x: Int            // 左上角,截图像素
    var y: Int
    var w: Int
    var h: Int
    var color: String
    var width: Int
    var shape: String     // "rect" | "ellipse"(261014 区域标注;默认 rect 向后兼容)
    var note: String?     // 框选备注(261014 用户令:框选后直接弹输入框对框选内容批注)
}

struct TextRecord {
    var id: Int
    var x: Int
    var y: Int
    var w: Int
    var h: Int
    var text: String
    var color: String
}

enum ActionItem {
    case pin(PinRecord)
    case arrow(ArrowRecord)
    case box(BoxRecord)
    case text(TextRecord)
}

struct OcrTextItem {
    var text: String
    var cx: Double        // 截图像素
    var cy: Double
}

// MARK: - 页内桥服务(anno-bridge v1) anno-bridge
// 桌面钉↔页面钉同步:127.0.0.1:8763 回环 HTTP,页面(anno-v7.js 桥模式,管理员态)
// ping 注册取 token → 轮询 /pending 取 resolve 请求 → elementFromPoint 反查 → POST /answer;
// App 侧择优(窗矩形跨源校验+windowAt 窗匹配,不依赖 hasFocus——落钉瞬间浏览器必失焦)
// 写入 pin.page。全本机回环;启动失败→桥禁用,钉钉主流程不受影响(SPEC F5)。

final class BridgeServer {
    static let shared = BridgeServer()
    static let port: UInt16 = 8763

    private let lock = NSLock()
    private let queue = DispatchQueue(label: "anno-bridge")
    private var listener: NWListener?
    private(set) var running = false
    private var sessionToken = ""
    private var nextClientId = 1
    private var clients: [Int: String] = [:]        // client id → token

    struct ResolveReq {
        let id: Int
        let xPx: Int, yPx: Int
        let scale: Double
        let gx: Int, gy: Int                        // 钉点全局点(主屏左上原点,JS screenX 同系)
        let createdAt = Date()
        var answers: [[String: Any]] = []
    }
    private var requests: [ResolveReq] = []
    private var nextReqId = 1
    private var watchPins: [[String: Any]] = []
    var onTrack: (([[String: Any]]) -> Void)?
    private var pendingCompletions = 0     // 未回调完成的 resolve 数(drain 用)
    private var sseClients: [NWConnection] = []
    private var hbTimer: Timer?

    func start() {
        lock.lock(); defer { lock.unlock() }
        guard !running else { return }
        sessionToken = randomToken()
        let params = NWParameters.tcp
        params.requiredLocalEndpoint = NWEndpoint.hostPort(host: .ipv4(.loopback),
                                                           port: NWEndpoint.Port(rawValue: Self.port)!)
        guard let l = try? NWListener(using: params) else {
            NSLog("anno-bridge: port \(Self.port) unavailable, bridge disabled")
            return
        }
        l.newConnectionHandler = { [weak self] conn in self?.accept(conn) }
        l.stateUpdateHandler = { st in
            if case .failed(let e) = st { NSLog("anno-bridge listener failed: \(e)") }
        }
        l.start(queue: queue)
        listener = l
        running = true
        // SSE 心跳(15s):防中间层断连;主线程 Timer(runloop 由 App 事件循环驱动)
        hbTimer = Timer.scheduledTimer(withTimeInterval: 15, repeats: true) { [weak self] _ in
            self?.broadcastRaw(Data(": hb\n\n".utf8))
        }
        NSLog("anno-bridge: listening 127.0.0.1:\(Self.port)")
    }

    /// SSE 广播原始帧(心跳用)
    private func broadcastRaw(_ frame: Data) {
        lock.lock(); let conns = sseClients; lock.unlock()
        conns.forEach { $0.send(content: frame, completion: .contentProcessed { _ in }) }
    }

    /// resolve 请求广播给所有 SSE 订阅页(后台标签的轮询被浏览器节流到 ~1 次/分钟,
    /// 网络推送不受节流——SSE 是桌面钉时浏览器必在后台场景下的唯一可靠通道)
    private func broadcastResolve(_ r: ResolveReq) {
        let obj: [String: Any] = ["id": r.id, "x_px": r.xPx, "y_px": r.yPx,
                                  "scale": r.scale, "gx": r.gx, "gy": r.gy]
        let body = (try? JSONSerialization.data(withJSONObject: obj)) ?? Data()
        broadcastRaw(Data("data: ".utf8) + body + Data("\n\n".utf8))
    }

    private func addSSE(_ conn: NWConnection) {
        lock.lock(); sseClients.append(conn); lock.unlock()
    }

    private func dropSSE(_ conn: NWConnection) {
        lock.lock(); sseClients.removeAll { $0 === conn }; lock.unlock()
    }

    // MARK: App 侧:发起解析(异步,≤2.5s 回调;桥未运行/无合格 answer→nil 回退)

    func resolve(xPx: Int, yPx: Int, scale: Double, gx: Int, gy: Int,
                 windowFrame: [Int]?, cgX: Int, cgY: Int,
                 completion: @escaping ([String: Any]?) -> Void) {
        lock.lock()
        guard running else { lock.unlock(); completion(nil); return }
        let id = nextReqId; nextReqId += 1
        let req = ResolveReq(id: id, xPx: xPx, yPx: yPx, scale: scale, gx: gx, gy: gy)
        requests.append(req)
        pendingCompletions += 1
        lock.unlock()
        broadcastResolve(req)
        DispatchQueue.global().asyncAfter(deadline: .now() + 2.5) { [weak self] in
            guard let self else { completion(nil); return }
            self.lock.lock()
            self.pruneLocked()
            let answers: [[String: Any]]
            if let i = self.requests.firstIndex(where: { $0.id == id }) {
                answers = self.requests.remove(at: i).answers
            } else {
                answers = []
            }
            self.pendingCompletions -= 1
            self.lock.unlock()
            NSLog("anno-bridge: req %d answers=%d hit=%d", id, answers.count,
                  answers.filter { ($0["hit"] as? Bool) == true }.count)
            completion(Self.pickBest(answers: answers, pinGx: gx, pinGy: gy,
                                     windowFrame: windowFrame, cgX: cgX, cgY: cgY))
        }
    }

    /// finish 前排空未决请求。主线程调用:用 RunLoop 驱动等待(而非 usleep),
    /// 否则回填的 DispatchQueue.main.async 永远排不上队→buildJSON 读不到 page(竞态)。
    func drain(seconds: Double) {
        let deadline = Date().addingTimeInterval(seconds)
        while Date() < deadline {
            lock.lock()
            let busy = !requests.isEmpty || pendingCompletions > 0
            lock.unlock()
            if !busy {
                RunLoop.main.run(until: Date().addingTimeInterval(0.05))   // 收尾已入队的回填
                return
            }
            RunLoop.main.run(until: Date().addingTimeInterval(0.1))
        }
    }

    /// answer 择优(SPEC §3.3):①hit=true ②JS 窗屏幕矩形须含钉点(跨源校验坐标系假设)
    /// ③多窗都含→与 windowAt 窗(转全局)中心距最小;收敛为 page 契约对象
    static func pickBest(answers: [[String: Any]], pinGx: Int, pinGy: Int,
                         windowFrame: [Int]?, cgX: Int, cgY: Int) -> [String: Any]? {
        let hits = answers.filter { ($0["hit"] as? Bool) == true }
        var pool: [[String: Any]] = []
        for a in hits {
            guard let sx = num(a["winScreenX"]), let sy = num(a["winScreenY"]),
                  let ow = num(a["outerW"]), let oh = num(a["outerH"]) else {
                NSLog("anno-bridge pick: hit answer missing win fields: url=%@", String(describing: a["url"]))
                continue
            }
            guard Double(pinGx) >= sx && Double(pinGx) <= sx + ow &&
                  Double(pinGy) >= sy && Double(pinGy) <= sy + oh else {
                NSLog("anno-bridge pick: pin(gx=%d,gy=%d) outside js win [%.0f,%.0f %.0fx%.0f] url=%@",
                      pinGx, pinGy, sx, sy, ow, oh, String(describing: a["url"]))
                continue
            }
            pool.append(a)
        }
        guard !pool.isEmpty else { return nil }
        // 261019 修复钉批注抓错标签页：同窗多标签共享同一窗矩形(screenX/Y、outerW/H 全同)，
        // 几何包含+中心距对同窗标签完全同分 → 实际退化成「谁先到谁赢」的竞态，后台标签会赢。
        // JS answer 本就带 visibility(document.visibilityState，被看的那页=visible)——
        // 有 visible 答案时只在 visible 里挑；全 hidden(整浏览器被遮挡/最小化等)才回退几何老逻辑，不回归。
        let visibles = pool.filter { ($0["visibility"] as? String) == "visible" }
        if visibles.isEmpty {
            NSLog("anno-bridge pick: no visible answer among %d — fallback geometry-only", pool.count)
        } else if visibles.count < pool.count {
            NSLog("anno-bridge pick: dropped %d hidden answer(s) by visibility, %d left",
                  pool.count - visibles.count, visibles.count)
        }
        let cand = visibles.isEmpty ? pool : visibles
        var best: ([String: Any], Double)?
        for a in cand {
            guard let sx = num(a["winScreenX"]), let sy = num(a["winScreenY"]),
                  let ow = num(a["outerW"]), let oh = num(a["outerH"]) else { continue }
            var score = 0.0
            if let f = windowFrame, f.count == 4 {
                let cx = Double(cgX + f[0]) + Double(f[2]) / 2
                let cy = Double(cgY + f[1]) + Double(f[3]) / 2
                score = hypot(sx + ow / 2 - cx, sy + oh / 2 - cy)
            }
            if best == nil || score < best!.1 { best = (a, score) }
        }
        guard let b = best?.0 else {
            NSLog("anno-bridge pick: END hits=%d pool=%d best=nil", hits.count, pool.count)
            return nil
        }
        NSLog("anno-bridge pick: END hits=%d pool=%d vis=%d bestKey=%@ url=%@",
              hits.count, pool.count, visibles.count,
              String(describing: b["key"]), String(describing: b["url"]))
        return [
            "url": b["url"] ?? NSNull(),
            "title": b["title"] ?? NSNull(),      // 261019 加：document.title，肉眼可核对是否抓对标签页
            "clientX": b["clientX"] ?? NSNull(),
            "clientY": b["clientY"] ?? NSNull(),
            "pageX": b["pageX"] ?? NSNull(),
            "pageY": b["pageY"] ?? NSNull(),
            "scrollY": b["scrollY"] ?? NSNull(),
            "viewportW": b["viewportW"] ?? NSNull(),
            "viewportH": b["viewportH"] ?? NSNull(),
            "key": b["key"] ?? NSNull(),
            "field": b["field"] ?? NSNull(),
            "value": b["value"] ?? NSNull(),
            "text": b["text"] ?? NSNull(),
            "dpr": b["dpr"] ?? NSNull(),
        ]
    }

    private static func num(_ v: Any?) -> Double? {
        (v as? NSNumber)?.doubleValue ?? v as? Double
    }

    // MARK: HTTP 服务(NWConnection 手写极简 HTTP/1.1;一律 Connection: close)

    private func accept(_ conn: NWConnection) {
        conn.stateUpdateHandler = { [weak self, weak conn] st in
            if case .cancelled = st { if let conn { self?.dropSSE(conn) } }
            if case .failed = st { if let conn { self?.dropSSE(conn) } }
        }
        conn.start(queue: queue)
        recv(conn, data: Data())
    }

    private func recv(_ conn: NWConnection, data: Data) {
        conn.receive(minimumIncompleteLength: 1, maximumLength: 1 << 16) { [weak self] chunk, _, done, err in
            guard let self else { conn.cancel(); return }
            var buf = data
            if let c = chunk { buf.append(c) }
            if let req = Self.parseHttpRequest(buf) {
                let (resp, keepAlive) = self.route(req)
                if keepAlive {
                    conn.send(content: resp, completion: .contentProcessed { _ in
                        self.addSSE(conn)   // SSE:连接保持,挂表等推送
                    })
                } else {
                    self.send(conn, resp)
                }
            } else if err != nil || done || buf.count > (1 << 20) {
                conn.cancel()
            } else {
                self.recv(conn, data: buf)
            }
        }
    }

    static func parseHttpRequest(_ buf: Data) -> (method: String, path: String,
                                                 query: [String: String], body: Data)? {
        guard let headerEnd = buf.range(of: Data("\r\n\r\n".utf8)) else { return nil }
        let head = String(decoding: buf[..<headerEnd.lowerBound], as: UTF8.self)
        let lines = head.components(separatedBy: "\r\n")
        guard !lines.isEmpty else { return nil }
        let parts = lines[0].split(separator: " ")
        guard parts.count >= 2 else { return nil }
        let method = String(parts[0])
        let full = String(parts[1])
        var path = full
        var query: [String: String] = [:]
        if let q = full.firstIndex(of: "?") {
            path = String(full[..<q])
            for pair in full[full.index(after: q)...].split(separator: "&") {
                let kv = pair.split(separator: "=", maxSplits: 1)
                guard kv.count == 2 else { continue }
                query[urlDecode(String(kv[0]))] = urlDecode(String(kv[1]))
            }
        }
        var clen = 0
        for l in lines.dropFirst() {
            let kv = l.split(separator: ":", maxSplits: 1)
            if kv.count == 2, kv[0].lowercased() == "content-length" {
                clen = Int(kv[1].trimmingCharacters(in: .whitespaces)) ?? 0
            }
        }
        let bodyStart = headerEnd.upperBound
        guard buf.count - bodyStart >= clen else { return nil }   // body 未收齐
        return (method, path, query, Data(buf[bodyStart...]))
    }

    static func urlDecode(_ s: String) -> String {
        s.replacingOccurrences(of: "+", with: " ").removingPercentEncoding ?? s
    }

    private func route(_ req: (method: String, path: String,
                               query: [String: String], body: Data)) -> (Data, Bool) {
        if req.method == "OPTIONS" {
            // CORS preflight 兜底(含 Chrome PNA:内网页 fetch 127.0.0.1 会先 OPTIONS)
            let s = "HTTP/1.1 204 No Content\r\nAccess-Control-Allow-Origin: *\r\n" +
                    "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n" +
                    "Access-Control-Allow-Headers: Content-Type\r\n" +
                    "Access-Control-Allow-Private-Network: true\r\n" +
                    "Access-Control-Max-Age: 86400\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            return (Data(s.utf8), false)
        }
        switch (req.method, req.path) {
        case ("GET", "/events"):
            // SSE 订阅流(后台标签节流免疫);keepAlive=true 连接保持由 recv 挂表
            guard let id = Int(req.query["client"] ?? ""), let tok = req.query["token"],
                  clientValid(id, tok) else { return (plain(403, "bad token"), false) }
            let s = "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream; charset=utf-8\r\n" +
                    "Cache-Control: no-cache\r\nAccess-Control-Allow-Origin: *\r\n" +
                    "Connection: keep-alive\r\n\r\n"
            return (Data(s.utf8) + Data("retry: 3000\n\n".utf8), true)
        case ("GET", "/ping"):
            lock.lock()
            let id = nextClientId; nextClientId += 1
            clients[id] = sessionToken
            let tok = sessionToken
            lock.unlock()
            return (json(["app": "dingai-bridge", "compat": "anno-bridge", "version": 1, "client": id, "token": tok]), false)
        case ("GET", "/pending"):
            guard let id = Int(req.query["client"] ?? ""), let tok = req.query["token"],
                  clientValid(id, tok) else { return (plain(403, "bad token"), false) }
            let since = Int(req.query["since"] ?? "") ?? 0
            lock.lock()
            pruneLocked()
            var out: [[String: Any]] = []
            var maxSeq = since
            for r in requests where r.id > since {
                out.append(["id": r.id, "x_px": r.xPx, "y_px": r.yPx,
                            "scale": r.scale, "gx": r.gx, "gy": r.gy])
                maxSeq = max(maxSeq, r.id)
            }
            lock.unlock()
            return (json(["seq": maxSeq, "requests": out]), false)
        case ("POST", "/answer"):
            guard let obj = try? JSONSerialization.jsonObject(with: req.body) as? [String: Any],
                  let id = obj["client"] as? Int, let tok = obj["token"] as? String,
                  clientValid(id, tok), let rid = obj["reqId"] as? Int else {
                return (plain(403, "bad token"), false)
            }
            lock.lock()
            if let i = requests.firstIndex(where: { $0.id == rid }) {
                requests[i].answers.append(obj)
            }
            lock.unlock()
            return (json(["ok": 1]), false)
        case ("POST", "/track"):
            // 实时模式:页面按元素 key+偏移回报当前屏幕坐标。旧页面不订阅 event:track,不受影响。
            guard let obj = try? JSONSerialization.jsonObject(with: req.body) as? [String: Any],
                  let id = obj["client"] as? Int, let tok = obj["token"] as? String,
                  clientValid(id, tok),
                  let positions = obj["positions"] as? [[String: Any]] else {
                return (plain(403, "bad token"), false)
            }
            let copy = positions
            RunLoop.main.perform { [weak self] in self?.onTrack?(copy) }
            return (json(["ok": 1]), false)
        default:
            return (plain(404, "not found"), false)
        }
    }

    private func clientValid(_ id: Int, _ token: String) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return clients[id] == token && token == sessionToken
    }

    func setWatch(_ pins: [[String: Any]]) {
        lock.lock(); watchPins = pins; lock.unlock()
        let obj: [String: Any] = ["pins": pins]
        guard let body = try? JSONSerialization.data(withJSONObject: obj) else { return }
        var frame = Data("event: track\ndata: ".utf8)
        frame.append(body)
        frame.append(Data("\n\n".utf8))
        broadcastRaw(frame)
    }

    private func pruneLocked() {
        let cutoff = Date().addingTimeInterval(-5)
        requests.removeAll { $0.createdAt < cutoff }
    }

    private func send(_ conn: NWConnection, _ data: Data) {
        conn.send(content: data, completion: .contentProcessed { _ in conn.cancel() })
    }

    private func json(_ obj: [String: Any]) -> Data {
        let body = (try? JSONSerialization.data(withJSONObject: obj)) ?? Data("{}".utf8)
        return head(200, "OK", "application/json; charset=utf-8", body.count) + body
    }

    private func plain(_ code: Int, _ text: String) -> Data {
        let body = Data(text.utf8)
        return head(code, code == 403 ? "Forbidden" : "Not Found", "text/plain", body.count) + body
    }

    private func head(_ code: Int, _ msg: String, _ type: String, _ len: Int) -> Data {
        // CORS * :其他端口的 http 页面跨端口 fetch 本回环服务所必需
        let s = "HTTP/1.1 \(code) \(msg)\r\nContent-Type: \(type)\r\n" +
                "Access-Control-Allow-Origin: *\r\nConnection: close\r\nContent-Length: \(len)\r\n\r\n"
        return Data(s.utf8)
    }

    private func randomToken() -> String {
        var b = [UInt8](repeating: 0, count: 16)
        arc4random_buf(&b, 16)
        return b.map { String(format: "%02x", $0) }.joined()
    }
}

// MARK: - 全局控制器

final class AnnoController: NSObject, NSApplicationDelegate {
    static let shared = AnnoController()

    let outputRoot: URL   // notes/ 与 shots/ 的父目录
    var statusItem: NSStatusItem?
    var overlay: AnnotationWindow?
    var lastApp: NSRunningApplication?

    // 本次批注会话数据
    var appInfo = AppInfo(bundleId: nil, name: nil, path: nil, pid: 0)
    var windowInfo = WindowInfo(title: nil, framePx: nil)
    var shotCG: CGImage?
    var shotURL: URL?
    var sessionStart = Date()
    var ocrItems: [OcrTextItem] = []
    var ocrDone = false
    var shotReady = false
    var screenW = 0, screenH = 0, imgW = 0, imgH = 0   // 点数 与 截图像素
    var scale: Double = 1
    var scaleY: Double = 1          // 截图像素/点,高单独算;宽高比不一致时不能借用 scale
    var live = true                 // 默认不冻结画面;导出时才截图
    var passSticky = false
    var trackTimer: Timer?
    var targetFrame = NSRect.zero          // 本轮批注目标屏(光标所在屏)
    var windowCandidates: [(owner: String, title: String, frame: [Int])] = []
    var cgOriginX = 0, cgOriginY = 0       // 目标屏在 CG 顶左全局系的原点(JS window.screenX 同系;resolve 用)

    var hotKeyRef: EventHotKeyRef?
    var passHotKeyRef: EventHotKeyRef?

    override init() {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let env = ProcessInfo.processInfo.environment
        outputRoot = home.appendingPathComponent(env["DINGAI_OUTPUT_DIR"] ?? env["ANNO_OUTPUT_DIR"] ?? "DingAI")
        super.init()
        for sub in ["notes", "shots"] {
            try? FileManager.default.createDirectory(
                at: outputRoot.appendingPathComponent(sub),
                withIntermediateDirectories: true)
        }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApplication.shared.setActivationPolicy(.accessory)
        setupStatusBar()
        registerHotKey()
        trackFrontmostApp()
        BridgeServer.shared.start()   // 页内桥(-ANNOSYNC):失败静默禁用,不影响钉钉
        BridgeServer.shared.onTrack = { rows in
            AnnoController.shared.overlay?.annoView.applyWeb(rows)
        }
        if CommandLine.arguments.contains("--auto-test") {
            perform(#selector(autoTestBegin), with: nil, afterDelay: 0.8)
        }
    }

    @objc func autoTestBegin() {
        begin()
        DispatchQueue.main.asyncAfter(deadline: .now() + 7.0) {
            guard let view = self.overlay?.annoView else { exit(3) }
            let w = CGFloat(self.screenW), h = CGFloat(self.screenH)
            view.debugAddPin(atPoint: NSPoint(x: w * 0.40, y: h * 0.35))
            view.debugAddPin(atPoint: NSPoint(x: w * 0.62, y: h * 0.52))
            view.debugAddArrow(from: NSPoint(x: w * 0.30, y: h * 0.68),
                               to:   NSPoint(x: w * 0.52, y: h * 0.74))
            view.debugAddBox(from: NSPoint(x: w * 0.55, y: h * 0.30),
                             to:   NSPoint(x: w * 0.75, y: h * 0.40))
            view.debugAddBox(from: NSPoint(x: w * 0.58, y: h * 0.60),
                             to:   NSPoint(x: w * 0.78, y: h * 0.72), shape: "ellipse")
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                self.finish(copyToPasteboard: false) { exit(0) }
            }
        }
    }

    // MARK: 状态栏

    func setupStatusBar() {
        let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        // 图标:自绘图钉(模板图,深浅菜单栏自动适配)
        item.button?.image = statusIcon()
        let menu = NSMenu()
        menu.addItem(withTitle: "DingAI 开始批注  ⌥⌘A", action: #selector(toggle), keyEquivalent: "")
        menu.addItem(withTitle: "交互穿透  ⌥⌘P", action: #selector(togglePass), keyEquivalent: "")
        let axItem = NSMenuItem(title: AXIsProcessTrusted() ? "辅助功能:已允许(控件跟随)" : "辅助功能:未允许,点此请求",
                                action: #selector(askAX), keyEquivalent: "")
        menu.addItem(axItem)
        menu.addItem(.separator())
        let ok = CGPreflightScreenCaptureAccess()
        let st = NSMenuItem(title: ok ? "屏幕录制权限:正常" : "屏幕录制权限:缺失(截图/OCR 受限)",
                            action: nil, keyEquivalent: "")
        st.isEnabled = false
        menu.addItem(st)
        menu.addItem(withTitle: "退出", action: #selector(quit), keyEquivalent: "q")
        menu.autoenablesItems = false
        item.menu = menu
        statusItem = item
    }

    func statusIcon() -> NSImage? {
        let img = NSImage(size: NSSize(width: 18, height: 18))
        img.lockFocus()
        NSColor.black.setFill()
        NSColor.black.setStroke()
        // 钉头(实心圆)+ 颈(短梯形)+ 针杆
        let head = NSBezierPath(ovalIn: NSRect(x: 5, y: 9, width: 8, height: 8))
        head.fill()
        let neck = NSBezierPath()
        neck.lineWidth = 2.4
        neck.move(to: NSPoint(x: 9, y: 10)); neck.line(to: NSPoint(x: 9, y: 4))
        neck.stroke()
        let needle = NSBezierPath()
        needle.lineWidth = 1.4
        needle.move(to: NSPoint(x: 9, y: 4)); needle.line(to: NSPoint(x: 9, y: 0))
        needle.stroke()
        img.unlockFocus()
        img.isTemplate = true
        return img
    }

    @objc func toggle() { overlay == nil ? begin() : finish(copyToPasteboard: true) }
    @objc func togglePass() {
        passSticky.toggle()
        overlay?.ignoresMouseEvents = passSticky
    }
    @objc func askAX() {
        let key = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
        let opts = [key: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(opts)
    }
    @objc func quit() { NSApp.terminate(nil) }

    // MARK: 前台 App 跟踪(overlay 自己出现前的前一个 App 即批注对象)

    func trackFrontmostApp() {
        lastApp = NSWorkspace.shared.frontmostApplication
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: .main
        ) { [weak self] note in
            guard let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication else { return }
            guard app.processIdentifier != getpid() else { return }
            self?.lastApp = app
        }
    }

    // MARK: 全局热键(Carbon,免权限)

    func registerHotKey() {
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard),
                                 eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, event, _ -> OSStatus in
            var hkID = EventHotKeyID()
            GetEventParameter(event, EventParamName(kEventParamDirectObject),
                              EventParamType(typeEventHotKeyID), nil,
                              MemoryLayout<EventHotKeyID>.size, nil, &hkID)
            if hkID.signature == OSType(0x414E4E4F) { // 'ANNO'
                if hkID.id == 2 { AnnoController.shared.togglePass() }
                else { AnnoController.shared.toggle() }
            }
            return noErr
        }, 1, &spec, nil, nil)

        RegisterEventHotKey(UInt32(kVK_ANSI_A), UInt32(cmdKey | optionKey),
                            EventHotKeyID(signature: OSType(0x414E4E4F), id: 1),
                            GetApplicationEventTarget(), 0, &hotKeyRef)
        RegisterEventHotKey(UInt32(kVK_ANSI_P), UInt32(cmdKey | optionKey),
                            EventHotKeyID(signature: OSType(0x414E4E4F), id: 2),
                            GetApplicationEventTarget(), 0, &passHotKeyRef)
    }

    // MARK: 进入批注

    func begin() {
        guard overlay == nil else { return }

        // 1) 批注对象 = 之前的前台 App
        if let app = lastApp {
            appInfo = AppInfo(bundleId: app.bundleIdentifier,
                              name: app.localizedName,
                              path: app.bundleURL?.path,
                              pid: Int(app.processIdentifier))
        }

        // 3) 目标屏 = 光标所在屏(多屏语义:批注你正看着的那块屏)
        sessionStart = Date()
        ocrItems = []; ocrDone = false; shotReady = false

        let targetScreen = NSScreen.screens.first {
            NSMouseInRect(NSEvent.mouseLocation, $0.frame, false)
        } ?? NSScreen.main!
        let sf = targetScreen.frame
        targetFrame = sf
        screenW = Int(sf.width); screenH = Int(sf.height)
        let displayID = targetScreen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? 0
        let wanted = sf
        // CGWindowList 全局坐标(顶左原点)下目标屏的原点,用于把窗口 frame 转成本屏局部坐标
        let cgMinX = sf.origin.x
        let cgMinY = NSScreen.screens[0].frame.maxY - sf.maxY
        cgOriginX = Int(cgMinX); cgOriginY = Int(cgMinY)

        // 2) 批注对象的窗口:取该 App 与目标屏相交面积最大的窗口,frame 转本屏局部(顶左原点,点数)
        windowInfo = WindowInfo(title: nil, framePx: nil)
        if let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements],
                                                 kCGNullWindowID) as? [[String: Any]] {
            let pid32 = Int32(truncatingIfNeeded: appInfo.pid)
            let wins = list.filter {
                ($0[kCGWindowOwnerPID as String] as? Int32) == pid32 &&
                ($0[kCGWindowLayer as String] as? Int) == 0
            }.compactMap { dict -> (dict: [String: Any], inter: Int)? in
                guard let b = dict[kCGWindowBounds as String] as? [String: Any],
                      let x = cgInt(b["X"]), let y = cgInt(b["Y"]),
                      let w = cgInt(b["Width"]), let h = cgInt(b["Height"]) else { return nil }
                let ix = max(0, min(x + w, Int(cgMinX) + screenW) - max(x, Int(cgMinX)))
                let iy = max(0, min(y + h, Int(cgMinY) + screenH) - max(y, Int(cgMinY)))
                guard ix > 0 && iy > 0 else { return nil }
                return (dict, ix * iy)
            }.sorted { $0.inter > $1.inter }
            if let w = wins.first?.dict {
                windowInfo.title = w[kCGWindowName as String] as? String
                if let b = w[kCGWindowBounds as String] as? [String: Any],
                   let x = cgInt(b["X"]), let y = cgInt(b["Y"]),
                   let bw = cgInt(b["Width"]), let bh = cgInt(b["Height"]) {
                    windowInfo.framePx = [x - Int(cgMinX), y - Int(cgMinY), bw, bh]
                }
            }
        }

        // 2b) 全屏窗口候选(落钉按坐标定位「钉真正落在哪个窗口」,钉在副窗/浏览器页上时信息签才对)
        windowCandidates = []
        if let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements],
                                                 kCGNullWindowID) as? [[String: Any]] {
            for w in list {
                guard (w[kCGWindowLayer as String] as? Int) == 0,
                      let b = w[kCGWindowBounds as String] as? [String: Any],
                      let x = cgInt(b["X"]), let y = cgInt(b["Y"]),
                      let bw = cgInt(b["Width"]), let bh = cgInt(b["Height"]),
                      bw > 40, bh > 40 else { continue }
                let lx = x - Int(cgMinX), ly = y - Int(cgMinY)
                guard lx < screenW, ly < screenH, lx + bw > 0, ly + bh > 0 else { continue }
                windowCandidates.append((owner: w[kCGWindowOwnerName as String] as? String ?? "",
                                         title: w[kCGWindowName as String] as? String ?? "",
                                         frame: [lx, ly, bw, bh]))
            }
        }

        // 4) 实时模式先把透明层盖上,截图留到导出,这样滚动和点击可以交给下层。
        //    非实时(live=false)仍是原来的「先冻截图再画」。
        let pxScale = targetScreen.backingScaleFactor
        if live {
            scale = Double(pxScale)
            scaleY = scale
            imgW = Int((Double(screenW) * scale).rounded())
            imgH = Int((Double(screenH) * scaleY).rounded())
            shotArrived(nil)
            startLiveTracking()
        } else {
            captureDisplay(displayID: displayID, wanted: wanted, pxScale: pxScale) { [weak self] cg in
                self?.shotArrived(cg)
            }
        }
    }

    /// ScreenCaptureKit 截图。导出时排除本进程,避免把批注层画进底图。
    func captureDisplay(displayID: CGDirectDisplayID, wanted: NSRect, pxScale: CGFloat,
                        completion: @escaping (CGImage?) -> Void) {
        let myPid = pid_t(ProcessInfo.processInfo.processIdentifier)
        Task.detached {
            var captured: CGImage?
            if let content = try? await SCShareableContent.current {
                let disp = content.displays.first { $0.displayID == displayID }
                    ?? content.displays.first {
                        abs($0.frame.width - wanted.width) < 2 && abs($0.frame.height - wanted.height) < 2
                    } ?? content.displays.first
                if let disp {
                    let me = content.applications.filter { $0.processID == myPid }
                    let filter = SCContentFilter(display: disp,
                                                 excludingApplications: me,
                                                 exceptingWindows: [])
                    let cfg = SCStreamConfiguration()
                    cfg.showsCursor = false
                    // 必须显式指定输出尺寸:默认会给 1920x1080(与屏无关)。尺寸跟 backingScale 走。
                    cfg.width = Int((wanted.width * pxScale).rounded())
                    cfg.height = Int((wanted.height * pxScale).rounded())
                    captured = try? await SCScreenshotManager.captureImage(contentFilter: filter,
                                                                           configuration: cfg)
                }
            }
            let cg = captured
            DispatchQueue.main.async { completion(cg) }
        }
    }

    func startLiveTracking() {
        trackTimer?.invalidate()
        trackTimer = Timer.scheduledTimer(withTimeInterval: 0.15, repeats: true) { [weak self] _ in
            self?.tickLive()
        }
    }

    func tickLive() {
        guard live, let view = overlay?.annoView else { return }
        let pass = passSticky || NSEvent.modifierFlags.contains(.option)
        if overlay?.ignoresMouseEvents != pass { overlay?.ignoresMouseEvents = pass }
        view.followAnchors()
        BridgeServer.shared.setWatch(view.webWatches())
    }

    /// 截图像素坐标 → 钉所在窗口(含该点的候选中取面积最小者=最精确窗;无则 nil)
    func windowAt(x px: Int, y py: Int) -> (owner: String, title: String, frame: [Int])? {
        let sx = Double(px) / scale, sy = Double(py) / (scaleY == 0 ? scale : scaleY)
        // CGWindowList 返回序=Z 序前→后;取第一个包含该点的 layer0 窗(视觉最前=钉子所见)。
        // 261014 前旧法「包含点最小面积窗」在多窗重叠时记成被盖住的下层小窗
        // (实测 14 钉 owner 大量误记「系统信息/访达」),anno-bridge 修正。
        for c in windowCandidates {
            let f = c.frame
            if sx >= Double(f[0]) && sx <= Double(f[0] + f[2]) &&
               sy >= Double(f[1]) && sy <= Double(f[1] + f[3]) {
                return (c.owner, c.title, f)
            }
        }
        return nil
    }

    /// 截图回到主线程:建 overlay(挂背景或灰底)、存档、启动 OCR
    func shotArrived(_ cg: CGImage?) {
        guard overlay == nil else { return }
        shotCG = cg
        shotReady = true

        let win = AnnotationWindow(frame: targetFrame)
        win.annoView.controller = self

        if let cg {
            imgW = cg.width; imgH = cg.height
            scale = Double(cg.width) / Double(max(screenW, 1))
            scaleY = Double(cg.height) / Double(max(screenH, 1))
            let name = "anno-" + stamp() + ".png"
            let url = outputRoot.appendingPathComponent("shots").appendingPathComponent(name)
            if let dest = CGImageDestinationCreateWithURL(url as CFURL, "public.png" as CFString, 1, nil) {
                CGImageDestinationAddImage(dest, cg, nil)
                CGImageDestinationFinalize(dest)
                shotURL = url
            }
            // 逻辑尺寸=屏幕点尺寸(修「定格画面变形」:NSZeroSize 会把像素尺寸当逻辑尺寸,
            // 16:9 截图被硬拉到 1.538 纵横比的屏=压扁;钉子像素换算仍走 scale= imgW/屏宽)
            win.annoView.bgImage = NSImage(cgImage: cg,
                                           size: NSSize(width: self.screenW, height: self.screenH))
        } else {
            if !live {
                imgW = screenW; imgH = screenH; scale = 1; scaleY = 1
            }
            ocrDone = true
        }

        win.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)   // 修「首击不算」:无激活时第一次点击只激活窗口不进画布
        overlay = win
        if live && cg == nil {
            win.annoView.flashBubble("实时:滚轮穿透 · 按住⌥操作下层 · ⌥⌘P锁定")
        }

        if let cg {
            DispatchQueue.global(qos: .userInitiated).async {
                let items = Self.runOCR(cgImage: cg)
                DispatchQueue.main.async {
                    self.ocrItems = items
                    self.ocrDone = true
                    self.overlay?.annoView.refreshPinSigns()
                }
            }
        }
    }

    static func runOCR(cgImage: CGImage) -> [OcrTextItem] {
        let req = VNRecognizeTextRequest()
        req.recognitionLevel = .accurate
        req.recognitionLanguages = ["zh-Hans", "en-US", "vi-VN"]
        req.usesLanguageCorrection = true
        let h = VNImageRequestHandler(cgImage: cgImage)
        do { try h.perform([req]) } catch { return [] }
        let W = Double(cgImage.width), H = Double(cgImage.height)
        var out: [OcrTextItem] = []
        for obs in (req.results ?? []) {
            guard let top = obs.topCandidates(1).first else { continue }
            let b = obs.boundingBox
            let t = top.string.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !t.isEmpty else { continue }
            out.append(OcrTextItem(text: t, cx: b.midX * W, cy: (1.0 - b.midY) * H))
        }
        return out
    }

    /// 钉子近邻文本:半径内按距离取最近若干行(2x 截图上 220px≈110pt 视觉半径)
    func ocrNear(x: Int, y: Int, radius: Double = 220.0, limit: Int = 8) -> String {
        guard !ocrItems.isEmpty else { return ocrDone ? "" : "OCR…" }
        let px = Double(x), py = Double(y)
        let hits = ocrItems
            .map { (text: $0.text, d: hypot($0.cx - px, $0.cy - py)) }
            .filter { $0.d <= radius }
            .sorted { $0.d < $1.d }
            .prefix(limit)
        return hits.map { $0.text.count > 42 ? String($0.text.prefix(42)) + "…" : $0.text }
            .joined(separator: " | ")
    }

    // MARK: 完成与 JSON

    /// 钉所在窗属浏览器名单→发桥 resolve(-ANNOSYNC);结果异步回填 pin.pageInfo
    static let browserOwners = ["Safari", "Chrome", "Edge", "Firefox", "Arc", "浏览器"]
    func bridgeResolveIfBrowser(win: (owner: String, title: String, frame: [Int])?,
                                xPx: Int, yPx: Int,
                                completion: @escaping ([String: Any]?) -> Void) {
        guard let win, AnnoController.browserOwners.contains(where: { win.owner.contains($0) }) else {
            completion(nil); return
        }
        let gx = cgOriginX + Int((Double(xPx) / scale).rounded())
        let gy = cgOriginY + Int((Double(yPx) / scale).rounded())
        BridgeServer.shared.resolve(xPx: xPx, yPx: yPx, scale: scale, gx: gx, gy: gy,
                                    windowFrame: win.frame, cgX: cgOriginX, cgY: cgOriginY,
                                    completion: completion)
    }

    func finish(copyToPasteboard: Bool, done: (() -> Void)? = nil) {
        guard let view = overlay?.annoView else { done?(); return }
        view.endNoteEditing()
        trackTimer?.invalidate(); trackTimer = nil
        overlay?.ignoresMouseEvents = false
        if live && shotCG == nil {
            BridgeServer.shared.drain(seconds: 0.4)
            let displayID = (NSScreen.screens.first { $0.frame == targetFrame }
                ?? NSScreen.main)?.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? 0
            let pxScale = CGFloat(scale == 0 ? 2 : scale)
            captureDisplay(displayID: displayID, wanted: targetFrame, pxScale: pxScale) { [weak self] cg in
                guard let self else { done?(); return }
                self.storeShot(cg)
                self.writeSession(copy: copyToPasteboard, done: done)
            }
            return
        }
        BridgeServer.shared.drain(seconds: 2.5)   // 排空未决桥请求(无未决则零等待)
        writeSession(copy: copyToPasteboard, done: done)
    }

    /// 把刚截到的图记成这轮的底图,并按实际像素尺寸回写 scale。实时模式导出时才走到这里。
    func storeShot(_ cg: CGImage?) {
        shotCG = cg
        guard let cg, let view = overlay?.annoView else { ocrDone = true; return }
        let oldX = scale, oldY = scaleY
        imgW = cg.width; imgH = cg.height
        scale = Double(cg.width) / Double(max(screenW, 1))
        scaleY = Double(cg.height) / Double(max(screenH, 1))
        if oldX > 0, oldY > 0, (abs(oldX - scale) > 0.02 || abs(oldY - scaleY) > 0.02) {
            view.rescalePixels(x: scale / oldX, y: scaleY / oldY)
        }
        let name = "anno-" + stamp() + ".png"
        let url = outputRoot.appendingPathComponent("shots").appendingPathComponent(name)
        if let dest = CGImageDestinationCreateWithURL(url as CFURL, "public.png" as CFString, 1, nil) {
            CGImageDestinationAddImage(dest, cg, nil)
            CGImageDestinationFinalize(dest)
            shotURL = url
        }
        ocrDone = false
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let items = Self.runOCR(cgImage: cg)
            DispatchQueue.main.async {
                guard let self else { return }
                self.ocrItems = items
                self.ocrDone = true
                self.overlay?.annoView.refreshPinSigns()
            }
        }
    }

    func writeSession(copy copyToPasteboard: Bool, done: (() -> Void)? = nil) {
        guard let view = overlay?.annoView else { done?(); return }
        let deadline = Date().addingTimeInterval(ocrDone ? 0 : 1.2)
        while !ocrDone && Date() < deadline {
            RunLoop.main.run(until: Date().addingTimeInterval(0.05))
        }
        let json = buildJSON(items: view.items)
        let data = (try? JSONSerialization.data(withJSONObject: json,
                        options: [.prettyPrinted, .sortedKeys])) ?? Data()
        let url = outputRoot.appendingPathComponent("notes")
                        .appendingPathComponent("anno-" + stamp() + ".json")
        try? data.write(to: url)
        if copyToPasteboard {
            let text = String(data: data, encoding: .utf8) ?? ""
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(handoffPrompt(text), forType: .string)
        }
        let shotCopy = shotURL
        overlay?.orderOut(nil)
        overlay = nil
        shotCG = nil
        if let shotCopy { reportToTeam(jsonData: data, shotFile: shotCopy) }
        done?()
    }

    // MARK: 团队账本上报(configurable team server via ANNO_TEAM_URLS,失败静默跳过)

    static let teamHosts: [String] = (ProcessInfo.processInfo.environment["DINGAI_TEAM_URLS"] ?? ProcessInfo.processInfo.environment["ANNO_TEAM_URLS"] ?? "").split(separator: ",").map { String($0) }.filter { !$0.isEmpty }   // e.g. DINGAI_TEAM_URLS=http://team-host:8050

    func reportToTeam(jsonData: Data, shotFile: URL) {
        DispatchQueue.global(qos: .utility).async { [weak self] in
            guard let self else { return }
            for host in Self.teamHosts {
                guard let shotName = self.postJson(host, data: jsonData) else { continue }
                self.postShot(host, name: shotName, file: shotFile)
                return
            }
        }
    }

    @discardableResult
    func postJson(_ host: String, data: Data) -> String? {
        guard let url = URL(string: host + "/api/note") else { return nil }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 6
        req.httpBody = data
        var shotName: String?
        let sem = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: req) { body, resp, _ in
            defer { sem.signal() }
            guard let http = resp as? HTTPURLResponse, http.statusCode == 200,
                  let obj = try? JSONSerialization.jsonObject(with: body ?? Data()) as? [String: Any],
                  let name = obj["shot_name"] as? String else { return }
            shotName = name
        }.resume()
        sem.wait()
        return shotName
    }

    func postShot(_ host: String, name: String, file: URL) {
        guard let png = try? Data(contentsOf: file),
              let enc = name.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed),
              let url = URL(string: host + "/api/shot/" + enc) else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 20
        req.httpBody = png
        let sem = DispatchSemaphore(value: 0)
        URLSession.shared.dataTask(with: req) { _, _, _ in sem.signal() }.resume()
        sem.wait()
    }

    func buildJSON(items: [ActionItem]) -> [String: Any] {
        var pins: [[String: Any]] = []
        var arrows: [[String: Any]] = []
        var boxes: [[String: Any]] = []
        var labels: [[String: Any]] = []
        for it in items {
            switch it {
            case .pin(let p):
                var near = p.ocrNearby
                if near == "OCR…" { near = ocrNear(x: p.x, y: p.y) }
                var d: [String: Any] = ["id": p.id, "x_px": p.x, "y_px": p.y, "ocr_nearby": near]
                if let note = p.note { d["note"] = note }
                if let o = p.windowOwner {
                    d["window"] = ["owner": o, "title": p.windowTitle ?? ""] as [String: Any]
                }
                // 归一化坐标:优先相对「钉所在窗口」(语义正确:钉在该窗内的相对位置);
                // 无窗信息时退回会话主窗(此时 nx/ny 才可能是窗外负值)
                let base = p.windowFrame ?? windowInfo.framePx
                if let f = base {
                    let sy = scaleY == 0 ? scale : scaleY
                    let fx = Double(f[0]) * scale
                    let fy = Double(f[1]) * sy
                    let fw = Double(f[2]) * scale
                    let fh = Double(f[3]) * sy
                    let nx = (Double(p.x) - fx) / fw
                    let ny = (Double(p.y) - fy) / fh
                    d["window_nx"] = (nx * 1000).rounded() / 1000
                    d["window_ny"] = (ny * 1000).rounded() / 1000
                }
                if let pg = p.pageInfo { d["page"] = pg }   // 页内桥结果(可选;桥命中才有)
                var anch: [String: Any] = ["kind": p.anchorKind, "dx": (p.anchorDX * 10).rounded() / 10,
                                           "dy": (p.anchorDY * 10).rounded() / 10]
                if let key = p.anchorKey { anch["key"] = key }
                if let note = p.anchorNote { anch["scroll_tracking"] = note }
                d["anchor"] = anch
                pins.append(d)
            case .arrow(let a):
                arrows.append(["id": a.id, "from_px": [a.fromX, a.fromY], "to_px": [a.toX, a.toY],
                               "color": a.color, "width": a.width])
            case .box(let b):
                var bd: [String: Any] = ["id": b.id, "rect_px": [b.x, b.y, b.w, b.h],
                              "color": b.color, "width": b.width, "shape": b.shape]
                if let note = b.note { bd["note"] = note }
                boxes.append(bd)
            case .text(let t):
                labels.append(["id": t.id, "x_px": t.x, "y_px": t.y, "w_px": t.w, "h_px": t.h,
                               "text": t.text, "color": t.color])
            }
        }
        let json: [String: Any] = [
            "schema": "dingai-desktop-v1",
            "tool": "dingai",
            "schema_compat": "anno-desktop-v1",
            "ts": isoNow(),
            "duration_s": round(Date().timeIntervalSince(sessionStart) * 10) / 10,
            "machine": Host.current().localizedName ?? Host.current().name ?? "unknown",
            "user": NSUserName(),
            "app": ["pid": appInfo.pid,
                    "bundle_id": appInfo.bundleId ?? NSNull(),
                    "name": appInfo.name ?? NSNull(),
                    "path": appInfo.path ?? NSNull()] as [String: Any],
            "screen": ["width_px": imgW, "height_px": imgH,
                       "point_w": screenW, "point_h": screenH,
                       "scale": scale, "scale_x": scale, "scale_y": scaleY] as [String: Any],
            "window": ["title": windowInfo.title ?? NSNull(),
                       "frame_px": windowInfo.framePx ?? NSNull()] as [String: Any],
            "pins": pins,
            "arrows": arrows,
            "boxes": boxes,
            "labels": labels,
            "pin_count": pins.count,
            "arrow_count": arrows.count,
            "box_count": boxes.count,
            "label_count": labels.count,
            "screenshot": shotURL?.lastPathComponent ?? NSNull(),
            "screen_capture_ok": (shotCG != nil),
            "live": live,
            "handoff_rules": handoffRules(),
        ]
        return json
    }

    static let defaultHandoffRules = """
    - Make the smallest change that fixes the pinned issue. Do not refactor or rewrite surrounding code.
    - Follow the project's ARCHITECTURE or conventions file before adding code.
    - Touch only code related to the pinned element.
    - Do not add dependencies or files unless you state why.
    - Explain the diff and how it was verified.
    """

    func projectDir() -> String? {
        if let p = ProcessInfo.processInfo.environment["DINGAI_PROJECT"], !p.isEmpty { return p }
        let path = (NSHomeDirectory() as NSString).appendingPathComponent("DingAI/project.txt")
        if let s = try? String(contentsOfFile: path, encoding: .utf8) {
            let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
            if !t.isEmpty { return t }
        }
        return nil
    }

    func handoffRules() -> String {
        var paths: [String] = []
        if let project = projectDir() {
            paths.append((project as NSString).appendingPathComponent(".dingai/handoff-rules.md"))
        }
        paths.append((NSHomeDirectory() as NSString).appendingPathComponent("DingAI/handoff-rules.md"))
        for path in paths {
            if let s = try? String(contentsOfFile: path, encoding: .utf8) {
                let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
                if !t.isEmpty { return t }
            }
        }
        return Self.defaultHandoffRules
    }

    func handoffPrompt(_ json: String) -> String {
        handoffRules() + "\n\nApply the rules above to this DingAI note. The pinned element is the only scope.\n\n" + json
    }

    func stamp() -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyyMMdd-HHmmss"
        return f.string(from: Date())
    }
    func isoNow() -> String {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f.string(from: Date())
    }
}

/// CGWindow bounds 的 X/Y/Width/Height 是 CFNumber,常为小数。`as? Int` 会把小数帧整段丢掉,窗口就配错。
private func cgInt(_ v: Any?) -> Int? {
    let n: Double?
    if let num = v as? NSNumber { n = num.doubleValue }
    else if let d = v as? Double { n = d }
    else if let i = v as? Int { n = Double(i) }
    else { n = nil }
    guard let n, n.isFinite else { return nil }
    return Int(n.rounded())
}

private func area(_ b: [String: Any]?) -> Int {
    guard let b = b, let w = b["Width"] as? Int, let h = b["Height"] as? Int else { return 0 }
    return w * h
}

struct LayoutCallout {
    var id: Int
    var ax: Double
    var ay: Double
    var w: Double
    var h: Double
}
struct LayoutRect {
    var x: Double
    var y: Double
    var w: Double
    var h: Double
}
struct LayoutPlaced {
    var id: Int
    var x: Double
    var y: Double
    var w: Double
    var h: Double
    var leader: Bool
}

/// 与 web/anno.js 里 layoutCallouts 同一规则:优先放在锚点右侧,躲开已占矩形,超出 14px 画引线。
private func layoutCallouts(_ callouts: [LayoutCallout], obstacles: [LayoutRect], bounds: LayoutRect) -> [LayoutPlaced] {
    let dirs: [(Double, Double, Double)] = [
        (1, 0, 0), (1, -1, 6), (0, -1, 6), (-1, -1, 6),
        (-1, 0, 6), (-1, 1, 6), (0, 1, 6), (1, 1, 6)]
    let dists = [18.0, 32, 48, 68, 96, 132, 176]
    let gap = 4.0
    var placed = obstacles
    var out: [LayoutPlaced] = []
    for (k, c) in callouts.enumerated() {
        var bestCost = Double.greatestFiniteMagnitude
        var best = LayoutPlaced(id: c.id, x: bounds.x, y: bounds.y, w: c.w, h: c.h, leader: true)
        for d in dirs {
            for dist in dists {
                let len = max(1, hypot(d.0, d.1))
                let ox = d.0 / len * dist
                let oy = d.1 / len * dist
                var x = c.ax + ox + (d.0 < 0 ? -c.w : (d.0 == 0 ? -c.w / 2 : 0))
                var y = c.ay + oy + (d.1 < 0 ? -c.h : (d.1 == 0 ? -c.h / 2 : 0))
                x = min(max(x, bounds.x), bounds.x + bounds.w - c.w)
                y = min(max(y, bounds.y), bounds.y + bounds.h - c.h)
                let rect = LayoutRect(x: x, y: y, w: c.w, h: c.h)
                var overlap = 0.0
                for p in placed { overlap += layoutOverlap(rect, p, gap: gap) }
                let cost = overlap * 10000 + dist + d.2 + Double(k) * 0.01
                if cost < bestCost {
                    bestCost = cost
                    best = LayoutPlaced(id: c.id, x: x, y: y, w: c.w, h: c.h,
                                       leader: layoutPointDist(c.ax, c.ay, rect) > 14)
                }
            }
        }
        placed.append(LayoutRect(x: best.x, y: best.y, w: best.w, h: best.h))
        out.append(best)
    }
    return out
}

private func layoutOverlap(_ a: LayoutRect, _ b: LayoutRect, gap: Double) -> Double {
    let x1 = max(a.x, b.x - gap), y1 = max(a.y, b.y - gap)
    let x2 = min(a.x + a.w, b.x + b.w + gap), y2 = min(a.y + a.h, b.y + b.h + gap)
    return (x2 > x1 && y2 > y1) ? (x2 - x1) * (y2 - y1) : 0
}

private func layoutPointDist(_ px: Double, _ py: Double, _ r: LayoutRect) -> Double {
    let cx = min(max(px, r.x), r.x + r.w)
    let cy = min(max(py, r.y), r.y + r.h)
    return hypot(px - cx, py - cy)
}


// MARK: - 批注窗口

final class AnnotationWindow: NSWindow {
    var annoView: AnnotationView { contentView as! AnnotationView }
    init(frame: NSRect) {
        let v = AnnotationView(frame: NSRect(origin: .zero, size: frame.size))
        super.init(contentRect: frame, styleMask: .borderless, backing: .buffered, defer: false)
        contentView = v
        isOpaque = false
        backgroundColor = .clear
        level = .screenSaver
        ignoresMouseEvents = false
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        isMovable = false
        hasShadow = false
        sharingType = .none   // 导出截图不包含批注层
    }
    override var canBecomeKey: Bool { true }
}

// MARK: - 可拖动工具条容器(点空白区拖动避遮挡;点按钮不触发拖)

final class DragBar: NSView {
    var dragOrigin: NSPoint?
    override func mouseDown(with event: NSEvent) {
        dragOrigin = convert(event.locationInWindow, from: nil)
    }
    override func mouseDragged(with event: NSEvent) {
        guard let origin = dragOrigin else { return }
        let cur = convert(event.locationInWindow, from: nil)
        let dx = cur.x - origin.x, dy = cur.y - origin.y
        let px = frame.origin.x + dx, py = frame.origin.y + dy
        let parent = superview?.bounds ?? bounds
        let nx = min(max(px, 4), parent.width - frame.width - 4)
        let ny = min(max(py, 4), parent.height - frame.height - 4)
        setFrameOrigin(NSPoint(x: nx, y: ny))
    }
    override func mouseUp(with event: NSEvent) { dragOrigin = nil }
}

// MARK: - 批注画布

final class AnnotationView: NSView {
    weak var controller: AnnoController?
    var bgImage: NSImage?
    var items: [ActionItem] = []
    var nextId = 1
    var draftFrom: NSPoint?
    var draftTo: NSPoint?
    var hoverPoint: NSPoint?
    var curColor = "red"
    var curWidth = 4
    var drawMode = 1        // 0选择 1箭头 2方框 3椭圆 4聚光 5文字
    var selectedIndex: Int?
    var movingOrig: ActionItem?
    var movingStart: NSPoint?
    var resizeHandle: String?
    var textAnchor: NSPoint?

    // MARK: 坐标换算:AppKit 点(左下原点) ↔ 截图像素(左上原点)

    func ptToPx(_ p: NSPoint) -> (Int, Int) {
        let sx = controller?.scale ?? 1
        let sy = controller?.scaleY ?? sx
        let x = Double(p.x) * sx
        let y = (Double(bounds.height) - Double(p.y)) * sy
        return (Int(x.rounded()), Int(y.rounded()))
    }
    func pxToPt(_ x: Int, _ y: Int) -> NSPoint {
        let sx = controller?.scale ?? 1
        let sy = controller?.scaleY ?? sx
        let px = Double(x) / sx
        let py = bounds.height - CGFloat(Double(y) / sy)
        return NSPoint(x: CGFloat(px), y: py)
    }

    // MARK: 交互

    override var acceptsFirstResponder: Bool { true }
    /// 非激活状态下第一次点击直接进画布(修「点一下才进入批注」),配合 NSApp.activate 双保险
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func mouseDown(with event: NSEvent) {
        endNoteEditing()
        let p = convert(event.locationInWindow, from: nil)
        if drawMode == 0 {
            if let sel = selectedIndex, let handle = hitHandle(sel, p) {
                resizeHandle = handle
                movingOrig = items[sel]
                movingStart = p
            } else if let hit = hitItem(p) {
                selectedIndex = hit
                movingOrig = items[hit]
                movingStart = p
                resizeHandle = nil
                if event.clickCount == 2, case .text = items[hit] {
                    beginNoteEditing(pinIndex: hit, at: p)
                }
            } else {
                selectedIndex = nil
                movingOrig = nil
            }
            needsDisplay = true
            return
        }
        if drawMode == 5 {
            beginTextEditing(at: p)
            return
        }
        movingOrig = nil
        resizeHandle = nil
        draftFrom = p
        draftTo = p
    }
    override func mouseDragged(with event: NSEvent) {
        let p = convert(event.locationInWindow, from: nil)
        if let orig = movingOrig, let start = movingStart, let idx = selectedIndex, items.indices.contains(idx) {
            if let handle = resizeHandle { applyResize(idx, orig, handle, p) }
            else { applyMove(idx, orig, p.x - start.x, p.y - start.y) }
            needsDisplay = true
            return
        }
        draftTo = p
        needsDisplay = true
    }
    override func mouseUp(with event: NSEvent) {
        if movingOrig != nil {
            movingOrig = nil
            movingStart = nil
            resizeHandle = nil
            needsDisplay = true
            return
        }
        defer { draftFrom = nil; draftTo = nil; needsDisplay = true }
        guard let from = draftFrom, let to = draftTo else { return }
        let dist = hypot(to.x - from.x, to.y - from.y) * CGFloat(controller?.scale ?? 1)
        if dist < 7 { addPin(at: from) }
        else if drawMode == 1 { addArrow(from: from, to: to) }
        else {
            let shape = drawMode == 3 ? "ellipse" : (drawMode == 4 ? "spotlight" : "rect")
            addBox(from: from, to: to, shape: shape)
        }
    }
    override func mouseMoved(with event: NSEvent) {
        hoverPoint = convert(event.locationInWindow, from: nil)
        needsDisplay = true
    }

    /// 滚轮交给下层应用。批注层先忽略鼠标再把事件投回去,避免自己把滚动吃掉。
    var forwardingScroll = false
    override func scrollWheel(with event: NSEvent) {
        if forwardingScroll { return }
        guard controller?.live == true, let cg = event.cgEvent?.copy() else {
            super.scrollWheel(with: event); return
        }
        forwardingScroll = true
        window?.ignoresMouseEvents = true
        cg.post(tap: .cghidEventTap)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.06) { [weak self] in
            guard let self else { return }
            self.forwardingScroll = false
            let hold = (self.controller?.passSticky == true) || NSEvent.modifierFlags.contains(.option)
            if !hold { self.window?.ignoresMouseEvents = false }
        }
    }

    func addPin(at p: NSPoint) {
        let (x, y) = ptToPx(p)
        let near = controller?.ocrNear(x: x, y: y) ?? ""
        let win = controller?.windowAt(x: x, y: y)
        let pinId = nextId
        items.append(.pin(PinRecord(id: pinId, x: x, y: y, ocrNearby: near, note: nil,
                                    windowOwner: win?.owner, windowTitle: win?.title,
                                    windowFrame: win?.frame, pageInfo: nil)))
        let idx = items.count - 1
        nextId += 1
        selectedIndex = idx
        needsDisplay = true
        bridgeBackfill(idx: idx, pinId: pinId, win: win, xPx: x, yPx: y)
        rememberAnchor(pinId: pinId, xPx: x, yPx: y, win: win)
        beginNoteEditing(pinIndex: idx, at: p)
    }

    /// 桥 resolve 发起+异步回填(-ANNOSYNC);undo/clear 后按 id 防错位,主线程回填
    func bridgeBackfill(idx: Int, pinId: Int,
                        win: (owner: String, title: String, frame: [Int])?,
                        xPx: Int, yPx: Int) {
        controller?.bridgeResolveIfBrowser(win: win, xPx: xPx, yPx: yPx) { [weak self] page in
            guard let page else { return }
            // RunLoop.main.perform 而非 DispatchQueue.main.async:finish 的 drain 用
            // RunLoop.run 等待,dispatch 主队列块不保证被消费(auto-test 实测 exit 前丢失),
            // RunLoop.perform 的块与 drain 同一调度体系,RunLoop.run 必然执行它
            RunLoop.main.perform {
                guard let self, idx < self.items.count,
                      case .pin(var pin) = self.items[idx], pin.id == pinId else {
                    NSLog("anno-bridge backfill: SKIP idx=%d pinId=%d items=%d", idx, pinId, self?.items.count ?? -1)
                    return
                }
                if let key = page["anchorKey"] as? String ?? page["key"] as? String {
                    pin.anchorKind = "web"
                    pin.anchorKey = key
                    pin.anchorDX = (page["anchorDx"] as? NSNumber)?.doubleValue ?? pin.anchorDX
                    pin.anchorDY = (page["anchorDy"] as? NSNumber)?.doubleValue ?? pin.anchorDY
                }
                pin.pageInfo = page
                self.items[idx] = .pin(pin)
                NSLog("anno-bridge backfill: OK pin %d key=%@", pinId, String(describing: page["key"]))
            }
        }
    }

    // MARK: 钉子备注输入(单字段表单:回车确认 / Esc 或点空白跳过)

    var noteField: NSTextField?

    func beginNoteEditing(pinIndex: Int, at p: NSPoint) {
        noteField?.removeFromSuperview()
        let fx = min(p.x + 14, bounds.width - 240)
        let fy = min(max(p.y - 30, 8), bounds.height - 34)
        let f = NSTextField(frame: NSRect(x: fx, y: fy, width: 226, height: 26))
        f.placeholderString = "备注:回车确认,Esc 跳过"
        f.bezelStyle = .roundedBezel
        f.font = .systemFont(ofSize: 13)
        f.backgroundColor = .white
        f.tag = pinIndex
        f.target = self
        f.action = #selector(noteCommit(_:))
        f.delegate = self
        addSubview(f)
        window?.makeFirstResponder(f)
        noteField = f
    }

    @objc func noteCommit(_ sender: NSTextField) { noteFieldCommit(text: sender.stringValue) }

    /// 防御性收口:任何出口(新点击/撤销/清空/完成)前先把备注框内容落账
    func endNoteEditing() {
        if let f = noteField { noteFieldCommit(text: f.stringValue) }
    }

    func noteFieldCommit(text: String) {
        guard let f = noteField else { return }
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        // tag=items 下标:钉与框选图形共用同一备注框(261014 框选直接批注);负数=新建文字标签
        if f.tag >= 0 && f.tag < items.count {
            if case .pin(var pin) = items[f.tag] {
                pin.note = t.isEmpty ? nil : t
                items[f.tag] = .pin(pin)
            } else if case .box(var b) = items[f.tag] {
                b.note = t.isEmpty ? nil : t
                items[f.tag] = .box(b)
            } else if case .text(var label) = items[f.tag] {
                if !t.isEmpty { label.text = t; items[f.tag] = .text(label) }
            }
        } else if f.tag < 0, !t.isEmpty, let anchor = textAnchor {
            let (x, y) = ptToPx(anchor)
            let sx = controller?.scale ?? 1
            let sy = controller?.scaleY ?? sx
            let width = Int((Double(max(48, min(320, t.count * 9 + 16))) * sx).rounded())
            let height = Int((26.0 * sy).rounded())
            items.append(.text(TextRecord(id: nextId, x: x, y: y, w: width, h: height, text: t, color: curColor)))
            nextId += 1
            selectedIndex = items.count - 1
        }
        textAnchor = nil
        let field = f
        noteField = nil
        field.removeFromSuperview()
        window?.makeFirstResponder(self)
        needsDisplay = true
    }
    func addArrow(from: NSPoint, to: NSPoint) {
        let (fx, fy) = ptToPx(from)
        let (tx, ty) = ptToPx(to)
        let a = ArrowRecord(id: nextId, fromX: fx, fromY: fy, toX: tx, toY: ty,
                            color: curColor, width: curWidth)
        items.append(.arrow(a))
        nextId += 1
        selectedIndex = items.count - 1
        needsDisplay = true
    }

    func addBox(from: NSPoint, to: NSPoint, shape: String = "rect") {
        let (fx, fy) = ptToPx(from)
        let (tx, ty) = ptToPx(to)
        let b = BoxRecord(id: nextId,
                          x: min(fx, tx), y: min(fy, ty),
                          w: abs(tx - fx), h: abs(ty - fy),
                          color: curColor, width: curWidth, shape: shape, note: nil)
        items.append(.box(b))
        let idx = items.count - 1
        nextId += 1
        selectedIndex = idx
        needsDisplay = true
        beginNoteEditing(pinIndex: idx, at: to)   // 框选后直接弹备注框(对齐钉子交互)
    }

    // 自动测试直调(点坐标为视图坐标;不弹备注框,note 走 nil)
    func debugAddPin(atPoint p: NSPoint) {
        let (x, y) = ptToPx(p)
        let near = controller?.ocrNear(x: x, y: y) ?? ""
        let win = controller?.windowAt(x: x, y: y)
        let pinId = nextId
        items.append(.pin(PinRecord(id: pinId, x: x, y: y, ocrNearby: near, note: nil,
                                    windowOwner: win?.owner, windowTitle: win?.title,
                                    windowFrame: win?.frame, pageInfo: nil)))
        let idx = items.count - 1
        nextId += 1
        needsDisplay = true
        bridgeBackfill(idx: idx, pinId: pinId, win: win, xPx: x, yPx: y)
        rememberAnchor(pinId: pinId, xPx: x, yPx: y, win: win)
    }
    // 自动测试直调(不弹备注框,note 走 nil;生产路径=addBox 弹备注)
    func debugAddBox(from: NSPoint, to: NSPoint, shape: String = "rect") {
        let (fx, fy) = ptToPx(from)
        let (tx, ty) = ptToPx(to)
        items.append(.box(BoxRecord(id: nextId,
                          x: min(fx, tx), y: min(fy, ty),
                          w: abs(tx - fx), h: abs(ty - fy),
                          color: curColor, width: curWidth, shape: shape, note: nil)))
        nextId += 1
        needsDisplay = true
    }
    func debugAddArrow(from: NSPoint, to: NSPoint) { addArrow(from: from, to: to) }

    @objc func undo() {
        endNoteEditing()
        if !items.isEmpty { items.removeLast() }
        needsDisplay = true
    }
    @objc func clearAll() {
        endNoteEditing()
        items.removeAll()
        needsDisplay = true
    }
    func refreshPinSigns() {
        // OCR 就绪后,把落钉时尚未出结果的钉子("OCR…")补查回填
        for i in items.indices {
            if case .pin(var p) = items[i], p.ocrNearby == "OCR…" {
                p.ocrNearby = controller?.ocrNear(x: p.x, y: p.y) ?? ""
                items[i] = .pin(p)
            }
        }
        needsDisplay = true
    }

    override func keyDown(with event: NSEvent) {
        switch event.keyCode {
        case UInt16(kVK_Escape): controller?.finish(copyToPasteboard: true)
        case UInt16(kVK_ANSI_Z) where event.modifierFlags.contains(.command): undo()
        case UInt16(kVK_Delete), UInt16(kVK_ForwardDelete): deleteSelection()
        default: super.keyDown(with: event)
        }
    }

    func beginTextEditing(at p: NSPoint) {
        textAnchor = p
        beginNoteEditing(pinIndex: -1, at: p)
        noteField?.placeholderString = "文字:回车确认"
    }

    func deleteSelection() {
        guard let idx = selectedIndex, items.indices.contains(idx) else { return }
        endNoteEditing()
        items.remove(at: idx)
        selectedIndex = nil
        needsDisplay = true
    }

    func pxRect(_ x: Int, _ y: Int, _ w: Int, _ h: Int) -> NSRect {
        let tl = pxToPt(x, y + h)
        let sy = controller?.scaleY ?? controller?.scale ?? 1
        let sx = controller?.scale ?? 1
        return NSRect(origin: tl, size: NSSize(width: CGFloat(w) / CGFloat(sx),
                                                height: CGFloat(h) / CGFloat(sy)))
    }

    func pinNumber(_ id: Int) -> Int {
        var n = 0
        for it in items {
            if case .pin(let p) = it {
                n += 1
                if p.id == id { return n }
            }
        }
        return id
    }

    func distToSeg(_ p: NSPoint, _ a: NSPoint, _ b: NSPoint) -> CGFloat {
        let dx = b.x - a.x, dy = b.y - a.y
        let len2 = dx * dx + dy * dy
        if len2 < 0.01 { return hypot(p.x - a.x, p.y - a.y) }
        var t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2
        t = min(1, max(0, t))
        return hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))
    }

    func hitItem(_ p: NSPoint) -> Int? {
        for i in items.indices.reversed() {
            switch items[i] {
            case .pin(let pin):
                let pt = pxToPt(pin.x, pin.y)
                if hypot(p.x - pt.x, p.y - pt.y) <= 14 { return i }
            case .arrow(let a):
                let f = pxToPt(a.fromX, a.fromY), t = pxToPt(a.toX, a.toY)
                if distToSeg(p, f, t) <= CGFloat(a.width) + 6 { return i }
            case .box(let b):
                if pxRect(b.x, b.y, b.w, b.h).insetBy(dx: -6, dy: -6).contains(p) { return i }
            case .text(let label):
                if pxRect(label.x, label.y, label.w, label.h).insetBy(dx: -4, dy: -4).contains(p) { return i }
            }
        }
        return nil
    }

    func hitHandle(_ idx: Int, _ p: NSPoint) -> String? {
        guard items.indices.contains(idx) else { return nil }
        func near(_ q: NSPoint, _ name: String) -> String? {
            hypot(p.x - q.x, p.y - q.y) <= 8 ? name : nil
        }
        switch items[idx] {
        case .arrow(let a):
            if let n = near(pxToPt(a.fromX, a.fromY), "start") { return n }
            return near(pxToPt(a.toX, a.toY), "end")
        case .box(let b):
            return nearCorner(pxRect(b.x, b.y, b.w, b.h), p)
        case .text(let label):
            return nearCorner(pxRect(label.x, label.y, label.w, label.h), p)
        default:
            return nil
        }
    }

    func nearCorner(_ r: NSRect, _ p: NSPoint) -> String? {
        let corners: [(NSPoint, String)] = [
            (NSPoint(x: r.minX, y: r.maxY), "nw"),
            (NSPoint(x: r.maxX, y: r.maxY), "ne"),
            (NSPoint(x: r.minX, y: r.minY), "sw"),
            (NSPoint(x: r.maxX, y: r.minY), "se")]
        for (q, name) in corners where hypot(p.x - q.x, p.y - q.y) <= 8 { return name }
        return nil
    }

    func applyMove(_ idx: Int, _ orig: ActionItem, _ dxView: CGFloat, _ dyView: CGFloat) {
        let sx = controller?.scale ?? 1
        let sy = controller?.scaleY ?? sx
        let dpx = Int((Double(dxView) * sx).rounded())
        let dpy = Int((-Double(dyView) * sy).rounded())
        switch orig {
        case .pin(var p):
            p.x += dpx; p.y += dpy
            p.anchorDX += Double(dxView)
            p.anchorDY += -Double(dyView)
            items[idx] = .pin(p)
        case .arrow(var a):
            a.fromX += dpx; a.fromY += dpy; a.toX += dpx; a.toY += dpy
            items[idx] = .arrow(a)
        case .box(var b):
            b.x += dpx; b.y += dpy
            items[idx] = .box(b)
        case .text(var label):
            label.x += dpx; label.y += dpy
            items[idx] = .text(label)
        }
    }

    func applyResize(_ idx: Int, _ orig: ActionItem, _ handle: String, _ p: NSPoint) {
        switch orig {
        case .arrow(var a):
            let (x, y) = ptToPx(p)
            if handle == "start" { a.fromX = x; a.fromY = y } else { a.toX = x; a.toY = y }
            items[idx] = .arrow(a)
        case .box(var b):
            let nr = resizedRect(pxRect(b.x, b.y, b.w, b.h), handle, p)
            let (x1, y1) = ptToPx(NSPoint(x: nr.minX, y: nr.maxY))
            let (x2, y2) = ptToPx(NSPoint(x: nr.maxX, y: nr.minY))
            b.x = min(x1, x2); b.y = min(y1, y2)
            b.w = max(4, abs(x2 - x1)); b.h = max(4, abs(y2 - y1))
            items[idx] = .box(b)
        case .text(var label):
            let nr = resizedRect(pxRect(label.x, label.y, label.w, label.h), handle, p)
            let (x1, y1) = ptToPx(NSPoint(x: nr.minX, y: nr.maxY))
            let (x2, y2) = ptToPx(NSPoint(x: nr.maxX, y: nr.minY))
            label.x = min(x1, x2); label.y = min(y1, y2)
            label.w = max(4, abs(x2 - x1)); label.h = max(4, abs(y2 - y1))
            items[idx] = .text(label)
        default:
            break
        }
    }

    func resizedRect(_ r: NSRect, _ handle: String, _ p: NSPoint) -> NSRect {
        let anchor: NSPoint
        switch handle {
        case "nw": anchor = NSPoint(x: r.maxX, y: r.minY)
        case "ne": anchor = NSPoint(x: r.minX, y: r.minY)
        case "sw": anchor = NSPoint(x: r.maxX, y: r.maxY)
        default: anchor = NSPoint(x: r.minX, y: r.maxY)
        }
        return NSRect(x: min(p.x, anchor.x), y: min(p.y, anchor.y),
                      width: max(4, abs(p.x - anchor.x)), height: max(4, abs(p.y - anchor.y)))
    }

    // MARK: 绘制

    override func draw(_ dirtyRect: NSRect) {
        if let img = bgImage {
            img.draw(in: bounds)
        } else if controller?.live == true {
            // 下层应用保持可见、可滚动
        } else {
            NSColor(calibratedWhite: 0.12, alpha: 1).setFill()
            bounds.fill()
            let hint = "截图中…(若无授权,菜单栏「批」可查权限状态)"
            let attr: [NSAttributedString.Key: Any] = [
                .font: NSFont.systemFont(ofSize: 15),
                .foregroundColor: NSColor.white.withAlphaComponent(0.55)]
            (hint as NSString).draw(at: NSPoint(x: bounds.midX - 130, y: bounds.midY),
                                    withAttributes: attr)
        }

        // 拖拽预览(箭头/方框/椭圆/聚光,按当前模式)
        if let f = draftFrom, let t = draftTo, f != t {
            let preview = NSRect(x: min(f.x, t.x), y: min(f.y, t.y),
                                 width: abs(t.x - f.x), height: abs(t.y - f.y))
            if drawMode == 1 {
                drawArrow(from: f, to: t, color: colorNamed(curColor), width: curWidth)
            } else if drawMode == 4 {
                drawSpotlight(rect: preview, color: colorNamed(curColor), width: curWidth, dim: false)
            } else {
                drawBox(rect: preview, color: colorNamed(curColor), width: curWidth,
                        shape: drawMode == 3 ? "ellipse" : "rect")
            }
        }

        labelObstacles = []
        for it in items {
            if case .pin(let p) = it {
                labelObstacles.append(LayoutRect(x: Double(p.x) - 12, y: Double(p.y) - 12, w: 24, h: 24))
            }
        }
        for it in items {
            if case .box(let b) = it, b.shape == "spotlight" {
                drawSpotlight(rect: pxRect(b.x, b.y, b.w, b.h), color: colorNamed(b.color), width: b.width, dim: true)
                break
            }
        }
        for (i, it) in items.enumerated() {
            switch it {
            case .pin(let p): drawPin(p)
            case .arrow(let a): drawArrow(from: pxToPt(a.fromX, a.fromY), to: pxToPt(a.toX, a.toY),
                                          color: colorNamed(a.color), width: a.width)
            case .box(let b):
                let rect = pxRect(b.x, b.y, b.w, b.h)
                if b.shape == "spotlight" {
                    drawSpotlight(rect: rect, color: colorNamed(b.color), width: b.width, dim: false)
                } else {
                    drawBox(rect: rect, color: colorNamed(b.color), width: b.width, shape: b.shape)
                }
            case .text(let label):
                drawTextLabel(label)
            }
            if selectedIndex == i { drawSelection(i) }
        }

        // 悬停十字光标提示
        if let h = hoverPoint, draftFrom == nil {
            NSColor.white.withAlphaComponent(0.5).setStroke()
            let path = NSBezierPath()
            path.setLineDash([2, 6], count: 2, phase: 0)
            path.move(to: NSPoint(x: h.x - 14, y: h.y)); path.line(to: NSPoint(x: h.x + 14, y: h.y))
            path.move(to: NSPoint(x: h.x, y: h.y - 14)); path.line(to: NSPoint(x: h.x, y: h.y + 14))
            path.stroke()
        }

        if let t = flashText, Date() < flashUntil {
            let f = NSFont.systemFont(ofSize: 13, weight: .medium)
            let attr: [NSAttributedString.Key: Any] = [.font: f, .foregroundColor: NSColor.white]
            let size = (t as NSString).size(withAttributes: attr)
            let rect = NSRect(x: bounds.midX - size.width / 2 - 8, y: 74,
                              width: size.width + 16, height: size.height + 8)
            NSColor.black.withAlphaComponent(0.85).setFill()
            NSBezierPath(roundedRect: rect, xRadius: 8, yRadius: 8).fill()
            (t as NSString).draw(at: NSPoint(x: rect.minX + 8, y: rect.minY + 4), withAttributes: attr)
        }
    }

    func colorNamed(_ n: String) -> NSColor {
        switch n {
        case "yellow": return NSColor.systemYellow
        case "cyan": return NSColor.systemTeal
        default: return NSColor.systemRed
        }
    }

    /// 钉子:编号圆钉 + 坐标气泡 + 信息签(app/窗口/OCR)。辅助线只在悬停时画一小段。
    func drawPin(_ p: PinRecord) {
        let pt = pxToPt(p.x, p.y)
        let r: CGFloat = 11
        let dot = NSBezierPath(ovalIn: NSRect(x: pt.x - r, y: pt.y - r, width: r * 2, height: r * 2))
        NSColor.white.setFill(); dot.fill()
        let inner = NSBezierPath(ovalIn: NSRect(x: pt.x - r + 2, y: pt.y - r + 2,
                                                width: (r - 2) * 2, height: (r - 2) * 2))
        NSColor.systemRed.setFill(); inner.fill()
        let n = "\(pinNumber(p.id))"
        let nf = NSFont.systemFont(ofSize: 11, weight: .bold)
        let nattr: [NSAttributedString.Key: Any] = [.font: nf, .foregroundColor: NSColor.white]
        let nsize = (n as NSString).size(withAttributes: nattr)
        (n as NSString).draw(at: NSPoint(x: pt.x - nsize.width / 2, y: pt.y - nsize.height / 2),
                             withAttributes: nattr)

        var lines: [String] = []
        if let n = p.note {
            lines.append("✎ " + (n.count > 34 ? String(n.prefix(34)) + "…" : n))
        }
        if let o = p.windowOwner, !o.isEmpty {
            let t = (p.windowTitle ?? "").isEmpty ? "" : " · " + String(p.windowTitle!.prefix(24))
            lines.append("win: " + o + t)
        }
        if let n = controller?.appInfo.name, n != (p.windowOwner ?? "") { lines.append("app: " + n) }
        if !p.ocrNearby.isEmpty {
            let first = p.ocrNearby.components(separatedBy: " | ").first ?? ""
            lines.append("ocr: " + (first.count > 34 ? String(first.prefix(34)) + "…" : first))
        }
        let sx = controller?.scale ?? 1
        let sy = controller?.scaleY ?? sx
        let bubbleText = "⌗\(p.id)  \(p.x),\(p.y)"
        let bf = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .medium)
        let bsize = (bubbleText as NSString).size(withAttributes: [.font: bf])
        var specs = [LayoutCallout(id: 0, ax: Double(p.x), ay: Double(p.y),
                                   w: Double(bsize.width + 12) * sx, h: Double(bsize.height + 4) * sy)]
        if !lines.isEmpty {
            let sf = NSFont.systemFont(ofSize: 12)
            let wid = lines.map { ($0 as NSString).size(withAttributes: [.font: sf]).width }.max() ?? 0
            specs.append(LayoutCallout(id: 1, ax: Double(p.x), ay: Double(p.y),
                                       w: Double(wid + 16) * sx,
                                       h: Double(18 * lines.count + 8) * sy))
        }
        let boundsPx = LayoutRect(x: 0, y: 0, w: Double(bounds.width) * sx, h: Double(bounds.height) * sy)
        for box in layoutCallouts(specs, obstacles: labelObstacles, bounds: boundsPx) {
            labelObstacles.append(LayoutRect(x: box.x, y: box.y, w: box.w, h: box.h))
            let vr = viewRectFromPx(box.x, box.y, box.w, box.h)
            if box.leader { drawLeader(from: pt, to: vr) }
            if box.id == 0 { drawBubble(text: bubbleText, at: vr.origin) }
            else { drawSign(lines: lines, at: vr.origin) }
        }
    }

    func viewRectFromPx(_ x: Double, _ y: Double, _ w: Double, _ h: Double) -> NSRect {
        let sx = controller?.scale ?? 1
        let sy = controller?.scaleY ?? sx
        let origin = pxToPt(Int(x.rounded()), Int((y + h).rounded()))
        return NSRect(x: origin.x, y: origin.y, width: CGFloat(w / sx), height: CGFloat(h / sy))
    }

    func drawLeader(from pt: NSPoint, to rect: NSRect) {
        let x = min(max(pt.x, rect.minX), rect.maxX)
        let y = min(max(pt.y, rect.minY), rect.maxY)
        NSColor.white.withAlphaComponent(0.85).setStroke()
        let path = NSBezierPath()
        path.lineWidth = 1
        path.move(to: pt)
        path.line(to: NSPoint(x: x, y: y))
        path.stroke()
    }

    /// 箭头:深色描边托底 + 线 + 三角头
    func drawArrow(from: NSPoint, to: NSPoint, color: NSColor, width: Int) {
        NSColor.black.withAlphaComponent(0.55).setStroke()
        let halo = NSBezierPath()
        halo.lineWidth = CGFloat(width) + 3
        halo.lineCapStyle = .round
        halo.move(to: from); halo.line(to: to)
        halo.stroke()
        color.setStroke()
        let path = NSBezierPath()
        path.lineWidth = CGFloat(width)
        path.lineCapStyle = .round
        path.lineJoinStyle = .round
        path.move(to: from); path.line(to: to)
        path.stroke()

        let ang = atan2(to.y - from.y, to.x - from.x)
        let head: CGFloat = CGFloat(width) * 3.5 + 8
        let p1 = NSPoint(x: to.x - head * cos(ang - 0.42), y: to.y - head * sin(ang - 0.42))
        let p2 = NSPoint(x: to.x - head * cos(ang + 0.42), y: to.y - head * sin(ang + 0.42))
        let tri = NSBezierPath()
        tri.move(to: to); tri.line(to: p1); tri.line(to: p2); tri.close()
        color.setFill(); tri.fill()
    }

    /// 方框:描边 + 半透明填充
    func drawBox(rect: NSRect, color: NSColor, width: Int, shape: String = "rect") {
        color.withAlphaComponent(0.16).setFill()
        rect.fill()
        color.setStroke()
        let p = (shape == "ellipse")
            ? NSBezierPath(ovalIn: rect)
            : NSBezierPath(roundedRect: rect, xRadius: 4, yRadius: 4)
        p.lineWidth = CGFloat(width)
        p.lineJoinStyle = .round
        p.stroke()
    }

    /// 聚光:第一块用奇偶填充压暗选区外,其余只描边。
    func drawSpotlight(rect: NSRect, color: NSColor, width: Int, dim: Bool) {
        if dim {
            let path = NSBezierPath(rect: bounds)
            path.append(NSBezierPath(roundedRect: rect, xRadius: 8, yRadius: 8))
            path.windingRule = .evenOdd
            NSColor.black.withAlphaComponent(0.45).setFill()
            path.fill()
        }
        color.setStroke()
        let p = NSBezierPath(roundedRect: rect, xRadius: 8, yRadius: 8)
        p.lineWidth = CGFloat(max(width, 2))
        p.stroke()
    }

    func drawTextLabel(_ t: TextRecord) {
        let rect = pxRect(t.x, t.y, t.w, t.h)
        NSColor.black.withAlphaComponent(0.62).setFill()
        NSBezierPath(roundedRect: rect, xRadius: 4, yRadius: 4).fill()
        let f = NSFont.systemFont(ofSize: 13, weight: .medium)
        let attr: [NSAttributedString.Key: Any] = [.font: f, .foregroundColor: colorNamed(t.color)]
        (t.text as NSString).draw(in: rect.insetBy(dx: 6, dy: 3), withAttributes: attr)
    }

    func drawSelection(_ idx: Int) {
        guard items.indices.contains(idx) else { return }
        NSColor.white.setStroke()
        var handles: [NSPoint] = []
        switch items[idx] {
        case .pin(let p):
            let pt = pxToPt(p.x, p.y)
            let ring = NSBezierPath(ovalIn: NSRect(x: pt.x - 15, y: pt.y - 15, width: 30, height: 30))
            ring.lineWidth = 1.5
            ring.stroke()
            return
        case .arrow(let a):
            handles = [pxToPt(a.fromX, a.fromY), pxToPt(a.toX, a.toY)]
        case .box(let b):
            let r = pxRect(b.x, b.y, b.w, b.h)
            let outline = NSBezierPath(rect: r.insetBy(dx: -2, dy: -2))
            outline.lineWidth = 1
            outline.setLineDash([3, 3], count: 2, phase: 0)
            outline.stroke()
            handles = [NSPoint(x: r.minX, y: r.maxY), NSPoint(x: r.maxX, y: r.maxY),
                       NSPoint(x: r.minX, y: r.minY), NSPoint(x: r.maxX, y: r.minY)]
        case .text(let label):
            let r = pxRect(label.x, label.y, label.w, label.h)
            let outline = NSBezierPath(rect: r.insetBy(dx: -2, dy: -2))
            outline.lineWidth = 1
            outline.stroke()
            handles = [NSPoint(x: r.minX, y: r.maxY), NSPoint(x: r.maxX, y: r.maxY),
                       NSPoint(x: r.minX, y: r.minY), NSPoint(x: r.maxX, y: r.minY)]
        }
        for h in handles {
            NSColor.white.setFill()
            NSColor.black.setStroke()
            let sq = NSBezierPath(rect: NSRect(x: h.x - 4, y: h.y - 4, width: 8, height: 8))
            sq.fill(); sq.lineWidth = 1; sq.stroke()
        }
    }

    func drawBubble(text: String, at origin: NSPoint) {
        let f = NSFont.monospacedDigitSystemFont(ofSize: 12, weight: .medium)
        let attr: [NSAttributedString.Key: Any] = [.font: f, .foregroundColor: NSColor.white]
        let size = (text as NSString).size(withAttributes: attr)
        let pad: CGFloat = 6
        let rect = NSRect(x: origin.x, y: origin.y, width: size.width + pad * 2, height: size.height + 4)
        NSColor.black.withAlphaComponent(0.82).setFill()
        NSBezierPath(roundedRect: rect, xRadius: 6, yRadius: 6).fill()
        (text as NSString).draw(at: NSPoint(x: rect.minX + pad, y: rect.minY + 2), withAttributes: attr)
    }

    func drawSign(lines: [String], at origin: NSPoint) {
        let f = NSFont.systemFont(ofSize: 12)
        let attr: [NSAttributedString.Key: Any] = [.font: f, .foregroundColor: NSColor.white]
        let wid = lines.map { ($0 as NSString).size(withAttributes: attr).width }.max() ?? 0
        let h: CGFloat = 18
        let rect = NSRect(x: origin.x, y: origin.y, width: wid + 16, height: h * CGFloat(lines.count) + 8)
        NSColor.black.withAlphaComponent(0.72).setFill()
        NSBezierPath(roundedRect: rect, xRadius: 8, yRadius: 8).fill()
        NSColor.white.withAlphaComponent(0.25).setStroke()
        let b = NSBezierPath(roundedRect: rect, xRadius: 8, yRadius: 8); b.lineWidth = 1; b.stroke()
        for (i, line) in lines.enumerated() {
            (line as NSString).draw(at: NSPoint(x: rect.minX + 8, y: rect.maxY - 6 - h * CGFloat(i + 1)),
                                    withAttributes: attr)
        }
    }

    // MARK: 底部工具条(viewDidMoveToWindow 挂载,窗口就绪必然触发)

    var axByPin: [Int: AXUIElement] = [:]
    var scrollByPin: [Int: AXUIElement] = [:]

    func rescalePixels(x mx: Double, y my: Double) {
        for i in items.indices {
            switch items[i] {
            case .pin(var p):
                p.x = Int((Double(p.x) * mx).rounded()); p.y = Int((Double(p.y) * my).rounded())
                items[i] = .pin(p)
            case .arrow(var a):
                a.fromX = Int((Double(a.fromX) * mx).rounded()); a.fromY = Int((Double(a.fromY) * my).rounded())
                a.toX = Int((Double(a.toX) * mx).rounded()); a.toY = Int((Double(a.toY) * my).rounded())
                items[i] = .arrow(a)
            case .box(var b):
                b.x = Int((Double(b.x) * mx).rounded()); b.y = Int((Double(b.y) * my).rounded())
                b.w = Int((Double(b.w) * mx).rounded()); b.h = Int((Double(b.h) * my).rounded())
                items[i] = .box(b)
            case .text(var t):
                t.x = Int((Double(t.x) * mx).rounded()); t.y = Int((Double(t.y) * my).rounded())
                t.w = Int((Double(t.w) * mx).rounded()); t.h = Int((Double(t.h) * my).rounded())
                items[i] = .text(t)
            }
        }
    }

    func webWatches() -> [[String: Any]] {
        var out: [[String: Any]] = []
        for it in items {
            if case .pin(let p) = it, p.anchorKind == "web", let key = p.anchorKey {
                out.append(["id": p.id, "key": key, "dx": p.anchorDX, "dy": p.anchorDY])
            }
        }
        return out
    }

    func applyWeb(_ rows: [[String: Any]]) {
        let sx = controller?.scale ?? 1
        let sy = controller?.scaleY ?? sx
        let ox = Double(controller?.cgOriginX ?? 0)
        let oy = Double(controller?.cgOriginY ?? 0)
        var changed = false
        for row in rows {
            let ok = (row["ok"] as? Bool) == true || (row["ok"] as? NSNumber)?.boolValue == true
            guard ok, let id = (row["id"] as? NSNumber)?.intValue,
                  let screenX = (row["screenX"] as? NSNumber)?.doubleValue,
                  let screenY = (row["screenY"] as? NSNumber)?.doubleValue else { continue }
            for i in items.indices {
                guard case .pin(var p) = items[i], p.id == id else { continue }
                let nx = Int(((screenX - ox) * sx).rounded())
                let ny = Int(((screenY - oy) * sy).rounded())
                if nx != p.x || ny != p.y { p.x = nx; p.y = ny; changed = true }
                var page = p.pageInfo ?? [:]
                for k in ["pageX", "pageY", "scrollX", "scrollY", "clientX", "clientY"] {
                    if let v = row[k] { page[k] = v }
                }
                p.pageInfo = page
                items[i] = .pin(p)
            }
        }
        if changed { needsDisplay = true }
    }

    func followAnchors() {
        if draftFrom != nil { return }
        let sx = controller?.scale ?? 1
        let sy = controller?.scaleY ?? sx
        let ox = Double(controller?.cgOriginX ?? 0)
        let oy = Double(controller?.cgOriginY ?? 0)
        var changed = false
        for i in items.indices {
            guard case .pin(var p) = items[i] else { continue }
            if p.anchorKind == "ax", let el = axByPin[p.id], let f = axFrame(el) {
                let lx = f.x + p.anchorDX - ox
                let ly = f.y + p.anchorDY - oy
                let nx = Int((lx * sx).rounded()), ny = Int((ly * sy).rounded())
                if nx != p.x || ny != p.y { p.x = nx; p.y = ny; items[i] = .pin(p); changed = true }
            } else if p.anchorKind == "scroll", let area = scrollByPin[p.id], let next = readScroll(area), var prev = p.scroll {
                if let d = scrollPoints(prev.v, next.v, next.vMin, next.vMax), prev.hasV {
                    p.y = Int((Double(p.y) - d * sy).rounded()); changed = true
                } else if prev.hasV && abs(next.v - prev.v) > 0.0001 && (next.vMax - next.vMin) <= 1.5 {
                    p.anchorNote = "normalized-unmapped"
                }
                if let d = scrollPoints(prev.h, next.h, next.hMin, next.hMax), prev.hasH {
                    p.x = Int((Double(p.x) - d * sx).rounded()); changed = true
                } else if prev.hasH && abs(next.h - prev.h) > 0.0001 && (next.hMax - next.hMin) <= 1.5 {
                    p.anchorNote = "normalized-unmapped"
                }
                prev.v = next.v; prev.h = next.h; prev.vMax = next.vMax; prev.hMax = next.hMax
                p.scroll = prev
                items[i] = .pin(p)
            }
        }
        if changed { needsDisplay = true }
    }

    func scrollPoints(_ previous: Double, _ next: Double, _ minV: Double, _ maxV: Double) -> Double? {
        let span = maxV - minV
        if !(span > 1.5) || !span.isFinite || !previous.isFinite || !next.isFinite { return nil }
        return next - previous
    }

    func rememberAnchor(pinId: Int, xPx: Int, yPx: Int,
                        win: (owner: String, title: String, frame: [Int])?) {
        guard controller?.live == true else { return }
        let sx = controller?.scale ?? 1
        let sy = controller?.scaleY ?? sx
        let gx = Double(controller?.cgOriginX ?? 0) + Double(xPx) / sx
        let gy = Double(controller?.cgOriginY ?? 0) + Double(yPx) / sy
        let browser = AnnoController.browserOwners.contains { win?.owner.contains($0) == true }
        let host = window
        host?.alphaValue = 0
        host?.orderOut(nil)
        let el = axHit(gx, gy)
        host?.orderFront(nil)
        host?.alphaValue = 1
        guard let el, let f = axFrame(el) else { return }
        let big = f.w > bounds.width * 0.72 && f.h > bounds.height * 0.72
        guard let idx = items.firstIndex(where: { if case .pin(let p) = $0 { return p.id == pinId }; return false }),
              case .pin(var pin) = items[idx] else { return }
        if !big && !browser {
            pin.anchorKind = "ax"
            pin.anchorDX = gx - f.x
            pin.anchorDY = gy - f.y
            pin.anchorKey = axRole(el)
            if pin.ocrNearby.isEmpty, let text = axText(el), !text.isEmpty { pin.ocrNearby = text }
            axByPin[pinId] = el
        } else if !browser, let area = scrollArea(from: el), let sample = readScroll(area) {
            pin.anchorKind = "scroll"
            pin.scroll = sample
            scrollByPin[pinId] = area
        }
        items[idx] = .pin(pin)
    }

    func axHit(_ x: Double, _ y: Double) -> AXUIElement? {
        guard AXIsProcessTrusted() else { return nil }
        let sys = AXUIElementCreateSystemWide()
        var el: AXUIElement?
        guard AXUIElementCopyElementAtPosition(sys, Float(x), Float(y), &el) == .success, let el else { return nil }
        var pid: pid_t = 0
        if AXUIElementGetPid(el, &pid) == .success, pid == getpid() { return nil }
        return el
    }

    func axCopy(_ el: AXUIElement, _ name: String) -> CFTypeRef? {
        var ref: CFTypeRef?
        guard AXUIElementCopyAttributeValue(el, name as CFString, &ref) == .success else { return nil }
        return ref
    }

    func axFrame(_ el: AXUIElement) -> (x: Double, y: Double, w: Double, h: Double)? {
        guard let posRef = axCopy(el, kAXPositionAttribute), let sizeRef = axCopy(el, kAXSizeAttribute) else { return nil }
        var p = CGPoint.zero
        var s = CGSize.zero
        guard AXValueGetValue(unsafeBitCast(posRef, to: AXValue.self), .cgPoint, &p),
              AXValueGetValue(unsafeBitCast(sizeRef, to: AXValue.self), .cgSize, &s) else { return nil }
        return (Double(p.x), Double(p.y), Double(s.width), Double(s.height))
    }

    func axRole(_ el: AXUIElement) -> String? { axCopy(el, kAXRoleAttribute) as? String }

    func axText(_ el: AXUIElement) -> String? {
        for name in [kAXTitleAttribute, kAXDescriptionAttribute, kAXValueAttribute] {
            if let s = axCopy(el, name) as? String {
                let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
                if !t.isEmpty && t.count < 80 { return t }
            }
        }
        return nil
    }

    func axParent(_ el: AXUIElement) -> AXUIElement? {
        guard let ref = axCopy(el, kAXParentAttribute) else { return nil }
        return unsafeBitCast(ref, to: AXUIElement.self)
    }

    func axChild(_ el: AXUIElement, _ name: String) -> AXUIElement? {
        guard let ref = axCopy(el, name) else { return nil }
        return unsafeBitCast(ref, to: AXUIElement.self)
    }

    func axNum(_ el: AXUIElement, _ name: String) -> Double? {
        (axCopy(el, name) as? NSNumber)?.doubleValue
    }

    func scrollArea(from el: AXUIElement) -> AXUIElement? {
        var cur: AXUIElement? = el
        for _ in 0..<14 {
            guard let c = cur else { return nil }
            if axRole(c) == "AXScrollArea" || axRole(c) == kAXScrollAreaRole { return c }
            cur = axParent(c)
        }
        return nil
    }

    func readScroll(_ area: AXUIElement) -> ScrollSample? {
        var s = ScrollSample()
        if let bar = axChild(area, kAXVerticalScrollBarAttribute) {
            if let v = axNum(bar, kAXValueAttribute) {
                s.hasV = true; s.v = v
                s.vMin = axNum(bar, kAXMinValueAttribute) ?? 0
                s.vMax = axNum(bar, kAXMaxValueAttribute) ?? 1
            }
        }
        if let bar = axChild(area, kAXHorizontalScrollBarAttribute) {
            if let v = axNum(bar, kAXValueAttribute) {
                s.hasH = true; s.h = v
                s.hMin = axNum(bar, kAXMinValueAttribute) ?? 0
                s.hMax = axNum(bar, kAXMaxValueAttribute) ?? 1
            }
        }
        return (s.hasV || s.hasH) ? s : nil
    }

    override func viewDidMoveToWindow() {
        super.viewDidMoveToWindow()
        window?.makeFirstResponder(self)
        if window != nil, !toolBarAdded {
            toolBarAdded = true
            installToolBar()
            needsDisplay = true
        }
    }
    var toolBarAdded = false
    var modeSelectBtn: NSButton?
    var modeArrowBtn: NSButton?
    var modeBoxBtn: NSButton?
    var modeEllipseBtn: NSButton?
    var modeSpotBtn: NSButton?
    var modeTextBtn: NSButton?

    func installToolBar() {
        let bar = DragBar(frame: NSRect(x: bounds.midX - 560, y: 16, width: 1120, height: 44))
        bar.wantsLayer = true
        bar.layer?.backgroundColor = NSColor.black.withAlphaComponent(0.88).cgColor
        bar.layer?.cornerRadius = 10
        bar.layer?.borderColor = NSColor.white.withAlphaComponent(0.35).cgColor
        bar.layer?.borderWidth = 1

        var x: CGFloat = 12
        // 0选择 1箭头 2方框 3椭圆 4聚光 5文字。单击(非选择/文字)仍落钉。
        let sel = textBtn("选择", frame: NSRect(x: x, y: 8, width: 52, height: 28))
        sel.tag = 20; sel.action = #selector(pickMode(_:)); sel.target = self
        bar.addSubview(sel); modeSelectBtn = sel; x += 56
        let a = textBtn("➜ 箭头", frame: NSRect(x: x, y: 8, width: 70, height: 28))
        a.tag = 21; a.action = #selector(pickMode(_:)); a.target = self
        bar.addSubview(a); modeArrowBtn = a; x += 74
        let b = textBtn("▭ 方框", frame: NSRect(x: x, y: 8, width: 70, height: 28))
        b.tag = 22; b.action = #selector(pickMode(_:)); b.target = self
        bar.addSubview(b); modeBoxBtn = b; x += 74
        let e = textBtn("◯ 椭圆", frame: NSRect(x: x, y: 8, width: 70, height: 28))
        e.tag = 23; e.action = #selector(pickMode(_:)); e.target = self
        bar.addSubview(e); modeEllipseBtn = e; x += 74
        let spot = textBtn("◉ 聚光", frame: NSRect(x: x, y: 8, width: 70, height: 28))
        spot.tag = 24; spot.action = #selector(pickMode(_:)); spot.target = self
        bar.addSubview(spot); modeSpotBtn = spot; x += 74
        let tx = textBtn("T 文字", frame: NSRect(x: x, y: 8, width: 64, height: 28))
        tx.tag = 25; tx.action = #selector(pickMode(_:)); tx.target = self
        bar.addSubview(tx); modeTextBtn = tx; x += 72
        refreshModeButtons()

        for (c, tag) in [("red", 1), ("yellow", 2), ("cyan", 3)] {
            let dot = colorDot(colorNamed(c), frame: NSRect(x: x, y: 12, width: 20, height: 20))
            dot.action = #selector(pickColor(_:)); dot.tag = tag
            dot.target = self
            bar.addSubview(dot); x += 26
        }
        x += 8
        for (_, tag) in [(2, 11), (4, 12), (6, 13)] {
            let w = textBtn("—", frame: NSRect(x: x, y: 8, width: 34, height: 28))
            w.tag = tag; w.action = #selector(pickWidth(_:)); w.target = self
            bar.addSubview(w); x += 36
        }
        x += 10
        let acts: [(String, Selector)] = [("⌘Z撤销", #selector(undo)),
                                          ("清空", #selector(clearAll)),
                                          ("复制JSON", #selector(copyJSON)),
                                          ("完成✓", #selector(doneNow))]
        for (t, sel) in acts {
            let w = CGFloat(t.count * 15 + 20)
            let btn = textBtn(t, frame: NSRect(x: x, y: 8, width: w, height: 28))
            btn.action = sel; btn.target = self
            bar.addSubview(btn); x += w + 8
        }
        addSubview(bar)
    }

    func refreshModeButtons() {
        for (btn, mode) in [(modeSelectBtn, 0), (modeArrowBtn, 1), (modeBoxBtn, 2),
                            (modeEllipseBtn, 3), (modeSpotBtn, 4), (modeTextBtn, 5)] {
            btn?.layer?.borderColor = NSColor.white.cgColor
            btn?.layer?.borderWidth = (drawMode == mode) ? 2 : 0
            btn?.layer?.cornerRadius = 6
        }
    }

    @objc func pickMode(_ s: NSButton) {
        drawMode = s.tag - 20
        refreshModeButtons()
    }

    func colorDot(_ c: NSColor, frame: NSRect) -> NSButton {
        let b = NSButton(title: "", target: nil, action: nil)
        b.frame = frame
        b.bezelStyle = .texturedRounded
        b.wantsLayer = true
        b.layer?.backgroundColor = c.cgColor
        b.layer?.cornerRadius = 10
        b.layer?.borderColor = NSColor.white.withAlphaComponent(0.6).cgColor
        b.layer?.borderWidth = 1.5
        return b
    }
    func textBtn(_ t: String, frame: NSRect) -> NSButton {
        let b = NSButton(title: t, target: nil, action: nil)
        b.frame = frame
        b.isBordered = false
        b.wantsLayer = true
        b.layer?.backgroundColor = NSColor.white.withAlphaComponent(0.96).cgColor
        b.layer?.cornerRadius = 6
        b.font = .systemFont(ofSize: 12, weight: .medium)
        b.contentTintColor = .black
        return b
    }

    @objc func pickColor(_ s: NSButton) {
        curColor = ["red", "yellow", "cyan"][max(0, s.tag - 1)]
    }
    @objc func pickWidth(_ s: NSButton) {
        curWidth = [2, 4, 6][max(0, s.tag - 11)]
    }
    @objc func copyJSON() {
        guard let c = controller else { return }
        let json = c.buildJSON(items: items)
        let data = (try? JSONSerialization.data(withJSONObject: json,
                        options: [.prettyPrinted, .sortedKeys])) ?? Data()
        let text = String(data: data, encoding: .utf8) ?? ""
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(c.handoffPrompt(text), forType: .string)
        flashBubble("JSON 已复制(\(items.count) 笔)")
    }
    @objc func doneNow() { controller?.finish(copyToPasteboard: true) }

    var labelObstacles: [LayoutRect] = []

    var flashText: String?
    var flashUntil = Date.distantPast
    func flashBubble(_ t: String) {
        flashText = t
        flashUntil = Date().addingTimeInterval(1.5)
        needsDisplay = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) { self.needsDisplay = true }
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        for a in trackingAreas { removeTrackingArea(a) }
        addTrackingArea(NSTrackingArea(rect: bounds, options: [.mouseMoved, .activeAlways],
                                       owner: self, userInfo: nil))
    }
}

// MARK: - 备注输入框 delegate(回车走 action;Esc/失焦在这里收口)

extension AnnotationView: NSTextFieldDelegate {
    func controlTextDidEndEditing(_ obj: Notification) {
        // 失焦(点到别处/切换)也把已输入内容落账
        if let f = obj.object as? NSTextField, f == noteField {
            noteFieldCommit(text: f.stringValue)
        }
    }
    func control(_ control: NSControl, textView: NSTextView,
                 doCommandBy commandSelector: Selector) -> Bool {
        if commandSelector == #selector(NSResponder.cancelOperation) {
            noteFieldCommit(text: "")   // Esc = 跳过备注(钉子保留)
            return true
        }
        return false
    }
}

// MARK: - 入口

let app = NSApplication.shared
let ctrl = AnnoController.shared
app.delegate = ctrl
app.run()
