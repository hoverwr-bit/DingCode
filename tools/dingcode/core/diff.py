"""Side-by-side and overlay comparison of two local PNG screenshots."""

from pathlib import Path

from core.redact import decode_png, encode_png


def compare_png(before, after, threshold=30):
    left = decode_png(before)
    right = decode_png(after)
    if not left or not right:
        return None
    width = min(left[0], right[0])
    height = min(left[1], right[1])
    if width < 1 or height < 1:
        return None
    side = bytearray(width * 2 * height * 3)
    overlay = bytearray(width * height * 3)
    changed = 0
    for y in range(height):
        for x in range(width):
            ia = (y * left[0] + x) * 3
            ib = (y * right[0] + x) * 3
            delta = 0
            for channel in range(3):
                side[(y * width * 2 + x) * 3 + channel] = left[2][ia + channel]
                side[(y * width * 2 + width + x) * 3 + channel] = right[2][ib + channel]
                delta += abs(left[2][ia + channel] - right[2][ib + channel])
            i = (y * width + x) * 3
            if delta > threshold:
                changed += 1
                overlay[i] = 220
                overlay[i + 1] = 40
                overlay[i + 2] = 40
            else:
                overlay[i] = left[2][ia] // 2
                overlay[i + 1] = left[2][ia + 1] // 2
                overlay[i + 2] = left[2][ia + 2] // 2
    ratio = changed / float(width * height)
    return {
        "width": width,
        "height": height,
        "changed_ratio": round(ratio, 4),
        "side_by_side": encode_png(width * 2, height, bytes(side)),
        "overlay": encode_png(width, height, bytes(overlay)),
    }


def write_diff(before_path, after_path, directory):
    before = Path(before_path).read_bytes()
    after = Path(after_path).read_bytes()
    result = compare_png(before, after)
    if not result:
        return {"ok": False, "error": "could not read both PNG files"}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "side-by-side.png").write_bytes(result["side_by_side"])
    (directory / "overlay.png").write_bytes(result["overlay"])
    return {"ok": True, "changed_ratio": result["changed_ratio"], "directory": str(directory)}
