// 行/列红像素直方图:批注 XY 辅助线是横贯全屏的虚线,会在直方图上形成尖峰
import AppKit

guard CommandLine.arguments.count > 1,
      let img = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    print("cannot load"); exit(1)
}
let W = cg.width, H = cg.height
let data = cg.dataProvider!.data! as Data
let bpr = cg.bytesPerRow, bpp = cg.bitsPerPixel / 8

var colCount = [Int](repeating: 0, count: W)
var rowCount = [Int](repeating: 0, count: H)
for y in 0..<H {
    let row = y * bpr
    for x in 0..<W {
        let off = row + x * bpp
        let i = data.startIndex + off
        let b0 = Int(data[i]), b1 = Int(data[i+1]), b2 = Int(data[i+2])
        let isRed = (b0 > 165 && b1 < 120 && b2 < 120) || (b2 > 165 && b0 < 120 && b1 < 120)
        if isRed { colCount[x] += 1; rowCount[y] += 1 }
    }
}
let colTop = colCount.enumerated().sorted { $0.element > $1.element }.prefix(8)
let rowTop = rowCount.enumerated().sorted { $0.element > $1.element }.prefix(8)
print("image \(W)x\(H)")
print("top columns (x, red_px):", colTop.map { "(\($0.offset),\($0.element))" }.joined(separator: " "))
print("top rows (y, red_px):", rowTop.map { "(\($0.offset),\($0.element))" }.joined(separator: " "))
// 期望:三颗钉 → 三条竖虚线(约 x=1175/1821/1411)与三条横虚线(约 y=684/1062/1434)
