// 截图链路探针:完全复刻 App 的 captureImage 调用,打印各级尺寸真相
import AppKit
import ScreenCaptureKit

let sem = DispatchSemaphore(value: 0)
Task {
    guard let content = try? await SCShareableContent.current else {
        print("SCShareableContent 失败"); sem.signal(); exit(1)
    }
    guard let disp = content.displays.first else {
        print("无 display"); sem.signal(); exit(1)
    }
    print("SCDisplay: displayID=\(disp.displayID) w=\(disp.width) h=\(disp.height)")

    let filter = SCContentFilter(display: disp, excludingApplications: [], exceptingWindows: [])
    let cfg = SCStreamConfiguration()
    cfg.showsCursor = false
    if let cg = try? await SCScreenshotManager.captureImage(contentFilter: filter, configuration: cfg) {
        print("captureImage 默认配置 → CGImage \(cg.width)x\(cg.height)")

        // 显式指定输出尺寸 = 屏点尺寸×2(Retina 全采样)
        let cfg2 = SCStreamConfiguration()
        cfg2.showsCursor = false
        cfg2.width = disp.width * 2
        cfg2.height = disp.height * 2
        if let cg2 = try? await SCScreenshotManager.captureImage(contentFilter: filter, configuration: cfg2) {
            print("captureImage 显式 %dx%d → CGImage %dx%d", disp.width * 2, disp.height * 2, cg2.width, cg2.height)
        } else { print("显式尺寸 capture 失败") }
    } else {
        print("captureImage 失败(权限?)")
    }
    sem.signal()
}
sem.wait()
