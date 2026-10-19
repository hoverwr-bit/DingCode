"""Local redaction. Off unless settings or DINGAI_REDACT turn it on.

Text rules and PNG pixelation use the standard library only. Face boxes are
supplied by the caller (Vision, Windows face detection, or a local command).
"""

import os
import re
import struct
import zlib
from pathlib import Path

REPLACEMENT = "[redacted]"

BUILTIN = (
    r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}",
    r"(?:\+?86[-\s]?)?1[3-9]\d{9}",
    r"(?:\+?84|0)(?:3|5|7|8|9)\d{8}",
    r"\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}",
    r"\b(?:PO|P\.O\.|SO|订单号|订单|订货单)\s*[#:\-]?\s*[A-Z0-9][A-Z0-9\-]{2,}",
    r"(?:[$€£₫]|¥|USD|CNY|VND)\s?\d[\d,]*(?:\.\d{1,2})?",
)


def pattern_files():
    home = Path.home() / "DingAI"
    project = os.environ.get("DINGAI_PROJECT", "").strip()
    paths = [home / "redact-patterns.txt", home / "redact-names.txt"]
    if project:
        paths.append(Path(project) / ".dingai" / "redact-names.txt")
        paths.append(Path(project) / ".dingai" / "redact-patterns.txt")
    return paths


def load_lists():
    patterns = list(BUILTIN)
    names = []
    for path in pattern_files():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if path.name.startswith("redact-names"):
                names.append(line)
            else:
                try:
                    re.compile(line)
                except re.error:
                    continue
                patterns.append(line)
    return patterns, names


def compiled(patterns=None, names=None):
    if patterns is None or names is None:
        loaded_p, loaded_n = load_lists()
        patterns = loaded_p if patterns is None else patterns
        names = loaded_n if names is None else names
    regs = []
    for pattern in patterns:
        try:
            regs.append(re.compile(pattern, re.I))
        except re.error:
            continue
    for name in names or []:
        if str(name).strip():
            regs.append(re.compile(re.escape(str(name).strip()), re.I))
    return regs


def redact_text(text, patterns=None, names=None):
    if not text:
        return ""
    out = str(text)
    for reg in compiled(patterns, names):
        out = reg.sub(REPLACEMENT, out)
    return out


def hits(text, patterns=None, names=None):
    if not text:
        return False
    raw = str(text)
    return redact_text(raw, patterns, names) != raw


def _paeth(left, up, ul):
    p = left + up - ul
    pa, pb, pc = abs(p - left), abs(p - up), abs(p - ul)
    if pa <= pb and pa <= pc:
        return left
    if pb <= pc:
        return up
    return ul


def encode_png(width, height, rgb):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def decode_png(png):
    if not png or png[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    width = height = color_type = bit_depth = 0
    idat = b""
    while pos + 8 <= len(png):
        length = struct.unpack(">I", png[pos:pos + 4])[0]
        tag = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + length]
        pos += 12 + length
        if tag == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", data[:10])
        elif tag == b"IDAT":
            idat += data
        elif tag == b"IEND":
            break
    if bit_depth != 8 or color_type not in (2, 6) or not idat:
        return None
    channels = 3 if color_type == 2 else 4
    try:
        raw = zlib.decompress(idat)
    except zlib.error:
        return None
    stride = width * channels
    if len(raw) < height * (stride + 1):
        return None
    rows = []
    index = 0
    prev = bytearray(stride)
    for _ in range(height):
        filter_type = raw[index]
        index += 1
        scan = raw[index:index + stride]
        index += stride
        recon = bytearray(stride)
        for x, value in enumerate(scan):
            left = recon[x - channels] if x >= channels else 0
            up = prev[x]
            ul = prev[x - channels] if x >= channels else 0
            if filter_type == 1:
                value = (value + left) & 255
            elif filter_type == 2:
                value = (value + up) & 255
            elif filter_type == 3:
                value = (value + ((left + up) // 2)) & 255
            elif filter_type == 4:
                value = (value + _paeth(left, up, ul)) & 255
            elif filter_type != 0:
                return None
            recon[x] = value
        prev = recon
        rows.append(recon)
    rgb = bytearray(width * height * 3)
    for y, row in enumerate(rows):
        for x in range(width):
            i = (y * width + x) * 3
            rgb[i] = row[x * channels]
            rgb[i + 1] = row[x * channels + 1]
            rgb[i + 2] = row[x * channels + 2]
    return width, height, bytes(rgb)


def pixelate_png(png, boxes, block=12):
    decoded = decode_png(png)
    if not decoded or not boxes:
        return png
    width, height, rgb = decoded
    out = bytearray(rgb)
    for box in boxes:
        x0 = max(0, int(box.get("x") or 0))
        y0 = max(0, int(box.get("y") or 0))
        x1 = min(width, x0 + max(1, int(box.get("w") or 1)))
        y1 = min(height, y0 + max(1, int(box.get("h") or 1)))
        y = y0
        while y < y1:
            x = x0
            while x < x1:
                bw = min(block, x1 - x)
                bh = min(block, y1 - y)
                rs = gs = bs = n = 0
                for yy in range(y, y + bh):
                    for xx in range(x, x + bw):
                        i = (yy * width + xx) * 3
                        rs += out[i]
                        gs += out[i + 1]
                        bs += out[i + 2]
                        n += 1
                if n:
                    rr, gg, bb = rs // n, gs // n, bs // n
                    for yy in range(y, y + bh):
                        for xx in range(x, x + bw):
                            i = (yy * width + xx) * 3
                            out[i], out[i + 1], out[i + 2] = rr, gg, bb
                x += block
            y += block
    return encode_png(width, height, bytes(out))


def redact_note(note, png=None, boxes=None, patterns=None, names=None):
    """Return a copy of the note and PNG with sensitive text and boxes removed."""
    note = dict(note or {})
    pins = []
    for pin in note.get("pins") or []:
        row = dict(pin)
        row["ocr_nearby"] = redact_text(row.get("ocr_nearby") or "", patterns, names)
        if row.get("note"):
            row["note"] = redact_text(row["note"], patterns, names)
        pins.append(row)
    note["pins"] = pins
    labels = []
    for label in note.get("labels") or []:
        row = dict(label)
        if row.get("text"):
            row["text"] = redact_text(row["text"], patterns, names)
        labels.append(row)
    note["labels"] = labels
    note["redacted"] = True
    if png and boxes:
        png = pixelate_png(png, boxes)
    return note, png
