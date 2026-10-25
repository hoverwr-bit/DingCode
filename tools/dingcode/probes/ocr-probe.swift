// OCR 探针:对指定 PNG 跑与 App 相同的 Vision 配置,输出行数与前 8 行
import Vision
import AppKit

let path = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : ""
guard !path.isEmpty, let img = NSImage(contentsOfFile: path),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    print("cannot load image: \(path)"); exit(1)
}
let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.recognitionLanguages = ["zh-Hans", "en-US", "vi-VN"]
req.usesLanguageCorrection = true
let h = VNImageRequestHandler(cgImage: cg)
do { try h.perform([req]) } catch { print("ocr error: \(error)"); exit(2) }
let obs = req.results ?? []
print("total_lines=\(obs.count)")
for o in obs.prefix(8) {
    let b = o.boundingBox
    print(String(format: "(%.0f,%.0f) %@", b.midX * Double(cg.width), (1 - b.midY) * Double(cg.height),
                 o.topCandidates(1).first?.string ?? ""))
}
