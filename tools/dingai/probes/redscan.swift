// 全图红像素扫描:输出红色像素总数与前若干个红色簇的坐标(顶左原点)
import AppKit

guard CommandLine.arguments.count > 1,
      let img = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    print("cannot load"); exit(1)
}
let W = cg.width, H = cg.height
let data = cg.dataProvider!.data! as Data
let bpr = cg.bytesPerRow, bpp = cg.bitsPerPixel / 8

var clusters: [(Int, Int, Int)] = []   // x, y, count
var total = 0
for y in stride(from: 2, to: H - 2, by: 2) {
    let row = y * bpr
    for x in stride(from: 2, to: W - 2, by: 2) {
        let off = row + x * bpp
        let b = [UInt8](data.subdata(in: off..<off+bpp))
        let isRed = (Int(b[0]) > 170 && Int(b[1]) < 110 && Int(b[2]) < 110) ||
                   (Int(b[2]) > 170 && Int(b[0]) < 110 && Int(b[1]) < 110)
        if isRed {
            total += 1
            if let last = clusters.last, abs(last.0 - x) < 60, abs(last.1 - y) < 60 {
                clusters[clusters.count - 1].2 += 1
            } else {
                clusters.append((x, y, 1))
            }
        }
    }
}
print("image \(W)x\(H) red_total(sampled)=\(total) clusters=\(clusters.count)")
for c in clusters.prefix(15) { print("  cluster @(\(c.0),\(c.1)) n=\(c.2)") }
