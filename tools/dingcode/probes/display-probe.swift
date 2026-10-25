// 显示配置诊断:NSScreen(点空间) vs ScreenCaptureKit displays(可截屏源) 对照
import AppKit
import ScreenCaptureKit

print("== NSScreen.screens(点空间,AppKit 底左原点)==")
for (i, s) in NSScreen.screens.enumerated() {
    let id = s.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? CGDirectDisplayID ?? 0
    let f = s.frame
    print("[\(i)] displayID=\(id) frame=\(Int(f.width))x\(Int(f.height)) @(\(Int(f.minX)),\(Int(f.minY))) name=\(s.localizedName)")
    if let bs = s.deviceDescription[NSDeviceDescriptionKey("NSBackingScale")] as? Double {
        print("     backingScale=\(bs)")
    }
}

print("== SCShareableContent.displays(可截屏源)==")
let sem = DispatchSemaphore(value: 0)
Task {
    if let content = try? SCShareableContent.current {
        for (i, d) in content.displays.enumerated() {
            print("[\(i)] displayID=\(d.displayID) px=\(d.width)x\(d.height) frame=\(Int(d.frame.width))x\(Int(d.frame.height)) @(\(Int(d.frame.minX)),\(Int(d.frame.minY)))")
        }
        print("     displays.first = \(content.displays.first.map { "ID\($0.displayID) \($0.width)x\($0.height)" } ?? "nil")")
    } else {
        print("SCShareableContent 获取失败(权限?)")
    }
    sem.signal()
}
sem.wait()
