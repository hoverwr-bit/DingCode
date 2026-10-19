#!/usr/bin/env python3
"""DingAI on Linux. X11 live session, optional Wayland still capture, AT-SPI, Tesseract.

The overlay is a small toolbar plus a pointer grab, so the app underneath keeps
working. The screenshot is taken when the session ends. Wayland stills use grim
when it is installed; the interactive overlay needs X11 or XWayland.
"""

import ctypes
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import handoff
from core.guide import write_bundle
from core.layout import layout_callouts
from core.redact import hits, redact_note
from core.schema import normalize_note
from core.sync import load_settings, publish_note
from core.voice import transcribe

PIN_TYPES = ("bug", "change", "question")


def write_png(width, height, rgb):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def _x11():
    lib = ctypes.CDLL("libX11.so.6")
    lib.XOpenDisplay.restype = ctypes.c_void_p
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    lib.XDefaultScreen.argtypes = [ctypes.c_void_p]
    lib.XDefaultScreen.restype = ctypes.c_int
    lib.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.XDisplayWidth.restype = ctypes.c_int
    lib.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.XDisplayHeight.restype = ctypes.c_int
    lib.XRootWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.XRootWindow.restype = ctypes.c_ulong
    lib.XGetImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
    lib.XGetImage.restype = ctypes.c_void_p
    lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    return lib


class _XImage(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_int), ("height", ctypes.c_int), ("xoffset", ctypes.c_int),
        ("format", ctypes.c_int), ("data", ctypes.c_void_p), ("byte_order", ctypes.c_int),
        ("bitmap_unit", ctypes.c_int), ("bitmap_bit_order", ctypes.c_int), ("bitmap_pad", ctypes.c_int),
        ("depth", ctypes.c_int), ("bytes_per_line", ctypes.c_int), ("bits_per_pixel", ctypes.c_int),
        ("red_mask", ctypes.c_ulong), ("green_mask", ctypes.c_ulong), ("blue_mask", ctypes.c_ulong),
    ]


def capture_x11(width=None, height=None, origin_x=0, origin_y=0):
    lib = _x11()
    display = lib.XOpenDisplay(None)
    if not display:
        return None
    try:
        screen = lib.XDefaultScreen(display)
        full_w = lib.XDisplayWidth(display, screen)
        full_h = lib.XDisplayHeight(display, screen)
        origin_x = max(0, min(int(origin_x), max(full_w - 1, 0)))
        origin_y = max(0, min(int(origin_y), max(full_h - 1, 0)))
        width = min(width or full_w, full_w - origin_x)
        height = min(height or full_h, full_h - origin_y)
        root = lib.XRootWindow(display, screen)
        image = lib.XGetImage(display, root, origin_x, origin_y, width, height, ctypes.c_ulong(-1).value, 2)
        if not image:
            return None
        info = ctypes.cast(image, ctypes.POINTER(_XImage)).contents
        raw = ctypes.string_at(info.data, info.bytes_per_line * info.height)
        rgb = bytearray(width * height * 3)
        bpp = max(info.bits_per_pixel // 8, 1)
        endian = "little" if info.byte_order == 0 else "big"
        for y in range(height):
            row = y * info.bytes_per_line
            for x in range(width):
                pixel = int.from_bytes(raw[row + x * bpp:row + x * bpp + min(bpp, 4)], endian)
                rgb[(y * width + x) * 3] = (pixel & info.red_mask) >> _shift(info.red_mask)
                rgb[(y * width + x) * 3 + 1] = (pixel & info.green_mask) >> _shift(info.green_mask)
                rgb[(y * width + x) * 3 + 2] = (pixel & info.blue_mask) >> _shift(info.blue_mask)
        return width, height, write_png(width, height, bytes(rgb))
    finally:
        lib.XCloseDisplay(display)


def _shift(mask):
    if not mask:
        return 0
    shift = 0
    while mask and (mask & 1) == 0:
        mask >>= 1
        shift += 1
    return shift


def capture_wayland(dest):
    if not shutil.which("grim") or not os.environ.get("WAYLAND_DISPLAY"):
        return False
    proc = subprocess.run(["grim", str(dest)], capture_output=True)
    return proc.returncode == 0 and Path(dest).exists()


def ocr_boxes(png_bytes):
    """Tesseract TSV boxes. Empty when the binary is missing."""
    if not shutil.which("tesseract") or not png_bytes:
        return []
    proc = subprocess.run(["tesseract", "stdin", "stdout", "-l", "eng", "tsv"], input=png_bytes, capture_output=True)
    if proc.returncode != 0:
        return []
    lines = proc.stdout.decode("utf-8", "replace").splitlines()
    if len(lines) < 2:
        return []
    header = lines[0].split("\t")

    def col(name):
        return header.index(name) if name in header else -1

    boxes = []
    for line in lines[1:]:
        parts = line.split("\t")
        try:
            text = parts[col("text")]
            if not str(text).strip():
                continue
            boxes.append({
                "x": int(float(parts[col("left")])),
                "y": int(float(parts[col("top")])),
                "w": int(float(parts[col("width")])),
                "h": int(float(parts[col("height")])),
                "text": text,
            })
        except (ValueError, IndexError):
            continue
    return boxes


def face_boxes(png_path):
    """Optional local command. Prints 'x y w h' lines. No network."""
    cmd = os.environ.get("DINGAI_FACE_CMD", "").strip()
    if not cmd or not png_path:
        return []
    proc = subprocess.run(cmd.split() + [str(png_path)], capture_output=True, text=True)
    boxes = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            boxes.append({"x": int(float(parts[0])), "y": int(float(parts[1])), "w": int(float(parts[2])), "h": int(float(parts[3]))})
        except ValueError:
            continue
    return boxes


def ocr_png(png_bytes):
    if not shutil.which("tesseract") or not png_bytes:
        return ""
    proc = subprocess.run(["tesseract", "stdin", "stdout", "-l", "eng"], input=png_bytes, capture_output=True)
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", "replace").strip()


def atspi_at_point(x, y):
    """Ask AT-SPI which accessible sits under a screen point. Empty when the bus is down."""
    if not shutil.which("busctl") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return None
    address = subprocess.run(
        ["busctl", "--user", "call", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress"],
        capture_output=True, text=True,
    )
    if address.returncode != 0 or '"' not in address.stdout:
        return None
    bus = address.stdout.split('"', 2)[1]
    env = dict(os.environ)
    env["DBUS_SESSION_BUS_ADDRESS"] = bus
    call = subprocess.run(
        ["busctl", "--user", "call", "org.a11y.atspi.Registry", "/org/a11y/atspi/accessible/root",
         "org.a11y.atspi.Component", "GetAccessibleAtPoint", "iiu", str(int(x)), str(int(y)), "0"],
        capture_output=True, text=True, env=env,
    )
    if call.returncode != 0:
        return None
    return {"kind": "atspi", "raw": call.stdout.strip()[:240]}


def capabilities():
    opened = False
    size = None
    try:
        if os.environ.get("DISPLAY"):
            shot = capture_x11(32, 32)
            opened = bool(shot and shot[2].startswith(b"\x89PNG"))
            if shot:
                size = [shot[0], shot[1]]
    except OSError:
        opened = False
    return {
        "x11": opened,
        "capture_px": size,
        "wayland": bool(os.environ.get("WAYLAND_DISPLAY")),
        "grim": bool(shutil.which("grim")),
        "tesseract": bool(shutil.which("tesseract")),
        "atspi_bus": bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")),
    }


def build_note(pins, width, height, capture_ok, platform_extra=None):
    placed = []
    for pin in pins:
        kind = pin.get("pin_type") if pin.get("pin_type") in PIN_TYPES else "bug"
        placed.append({
            "id": pin["id"],
            "x_px": int(pin["x"]),
            "y_px": int(pin["y"]),
            "ocr_nearby": pin.get("ocr") or "",
            "note": pin.get("note") or "",
            "pin_type": kind,
            "status": "open",
            "anchor": pin.get("anchor") or {"kind": "viewport", "dx": 0, "dy": 0},
        })
    bounds = {"x": 0, "y": 0, "w": max(width, 1), "h": max(height, 1)}
    obstacles = [{"x": p["x_px"] - 12, "y": p["y_px"] - 12, "w": 24, "h": 24} for p in placed]
    callouts = [{"id": p["id"], "ax": p["x_px"], "ay": p["y_px"], "w": 120, "h": 22} for p in placed]
    labels = []
    for box in layout_callouts(callouts, obstacles, bounds):
        labels.append({
            "id": box["id"], "x_px": int(box["x"]), "y_px": int(box["y"]),
            "w_px": int(box["w"]), "h_px": int(box["h"]),
            "text": next(p["pin_type"] for p in placed if p["id"] == box["id"]),
            "color": "red", "leader": box["leader"],
        })
    note = normalize_note({
        "platform": "linux",
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "screen": {"width_px": width, "height_px": height},
        "pins": placed,
        "labels": labels,
        "screen_capture_ok": capture_ok,
        "live": True,
        "handoff_rules": handoff.load_rules(),
        "screenshot": "anno-linux.png" if capture_ok else "",
    })
    if platform_extra:
        note.update(platform_extra)
    return note


class Session:
    def __init__(self):
        self.pins = []
        self.arrows = []
        self.boxes = []
        self.pin_type = "bug"
        self.next_id = 1
        self.drag_from = None
        self.voice = None
        self.voice_wav = ""
        self.steps_on = False
        self.steps = []

    def start_voice(self):
        if self.voice is not None or not shutil.which("arecord"):
            return
        handle = tempfile.NamedTemporaryFile(prefix="dingai-voice-", suffix=".wav", delete=False)
        self.voice_wav = handle.name
        handle.close()
        self.voice = subprocess.Popen(
            ["arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", self.voice_wav],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def stop_voice(self):
        proc = self.voice
        self.voice = None
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        text = transcribe(self.voice_wav) if self.voice_wav else ""
        if text and self.pins:
            note = self.pins[-1].get("note") or ""
            self.pins[-1]["note"] = (note + " " + text).strip()
        return text

    def add_pin(self, x, y, note=""):
        anchor = atspi_at_point(x, y) or {"kind": "viewport", "dx": 0, "dy": 0}
        pin = {"id": self.next_id, "x": int(x), "y": int(y), "note": note, "ocr": "", "pin_type": self.pin_type, "anchor": anchor}
        self.next_id += 1
        self.pins.append(pin)
        if self.steps_on:
            shot = capture_x11(480, 320, max(0, int(x) - 240), max(0, int(y) - 160))
            png = shot[2] if shot else b""
            name = "step-%d.png" % (len(self.steps) + 1)
            self.steps.append({"n": len(self.steps) + 1, "x_px": int(x), "y_px": int(y), "note": note or ("Pin at %d,%d" % (x, y)), "shot": name, "png": png})
            pin["step"] = len(self.steps)
        return pin

    def add_mark(self, kind, x0, y0, x1, y1):
        if kind == "arrow":
            self.arrows.append({
                "id": self.next_id, "from_px": [int(x0), int(y0)], "to_px": [int(x1), int(y1)],
                "color": "red", "width": 4,
            })
        else:
            self.boxes.append({
                "id": self.next_id,
                "rect_px": [int(min(x0, x1)), int(min(y0, y1)), int(abs(x1 - x0)), int(abs(y1 - y0))],
                "color": "red", "width": 4, "shape": "rect" if kind == "box" else "spotlight",
            })
        self.next_id += 1

    def export(self, out_dir):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        shot = capture_x11()
        png = b""
        width = height = 0
        if shot:
            width, height, png = shot
            (out / "anno-linux.png").write_bytes(png)
            text = ocr_png(png)
            if text and self.pins:
                self.pins[-1]["ocr"] = text[:180]
        elif os.environ.get("WAYLAND_DISPLAY"):
            dest = out / "anno-linux.png"
            if capture_wayland(dest):
                png = dest.read_bytes()
                width, height = 0, 0
        note = build_note(self.pins, width, height, bool(png))
        note["arrows"] = self.arrows
        note["boxes"] = self.boxes
        note["arrow_count"] = len(self.arrows)
        note["box_count"] = len(self.boxes)
        settings = load_settings()
        if settings.get("redact"):
            boxes = [box for box in ocr_boxes(png) if hits(box.get("text") or "")] if png else []
            if png:
                (out / "anno-linux.png").write_bytes(png)
                boxes.extend(face_boxes(out / "anno-linux.png"))
            note, png = redact_note(note, png or None, boxes)
            if png:
                (out / "anno-linux.png").write_bytes(png)
        if self.steps:
            note["steps"] = [{key: value for key, value in step.items() if key != "png"} for step in self.steps]
            write_bundle(out, self.steps)
        (out / "anno-linux.json").write_text(json.dumps(note, ensure_ascii=False, indent=2), encoding="utf-8")
        publish_note(note, png or None, settings)
        return note


def notice_banner(path=None):
    file = Path(path) if path else Path.home() / "DingAI" / "notices.json"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    parts = [item.get("text") or "" for item in data.get("banners") or []]
    return " · ".join(part for part in parts if part)


def toolbar_title(pins=None, banner=""):
    base = "DingAI pins %d" % pins if pins is not None else "DingAI  p pin  b/c/q type  a arrow  r box  s spot  hold v  Esc done"
    if banner:
        return (base + " | " + banner)[:240]
    return base


def run_toolbar():
    """X11 toolbar. p then click drops a pin. a, r, and s take two clicks for an arrow, box, or spotlight. Esc exports."""
    lib = _x11()
    lib.XCreateSimpleWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_ulong]
    lib.XCreateSimpleWindow.restype = ctypes.c_ulong
    lib.XMapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    lib.XSelectInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_long]
    lib.XStoreName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_char_p]
    lib.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    lib.XGrabPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    lib.XGrabPointer.restype = ctypes.c_int
    lib.XUngrabPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    lib.XFlush.argtypes = [ctypes.c_void_p]
    display = lib.XOpenDisplay(None)
    if not display:
        print("No X11 display. On Wayland, run: grim anno-linux.png", file=sys.stderr)
        return 1
    screen = lib.XDefaultScreen(display)
    root = lib.XRootWindow(display, screen)
    window = lib.XCreateSimpleWindow(display, root, 40, 40, 720, 36, 1, 0, 0xFFFFFF)
    banner = notice_banner()
    if banner:
        print(banner, file=sys.stderr)
    lib.XStoreName(display, window, toolbar_title(banner=banner).encode())
    lib.XSelectInput(display, window, (1 << 0) | (1 << 1) | (1 << 2))
    lib.XMapWindow(display, window)
    lib.XFlush(display)
    session = Session()
    armed = None
    event = ctypes.create_string_buffer(256)
    print("DingAI Linux: focus the toolbar, press p then click, Esc to export.")
    while True:
        lib.XNextEvent(display, event)
        kind = struct.unpack_from("i", event.raw, 0)[0]
        if kind == 4:  # ButtonPress. XButtonEvent on LP64: x, y, x_root, y_root at 64, 68, 72, 76.
            x = struct.unpack_from("i", event.raw, 64)[0]
            y = struct.unpack_from("i", event.raw, 68)[0]
            if armed in ("pin", "arrow", "box", "spotlight"):
                # x_root, y_root sit just after x, y in XButtonEvent
                xr = struct.unpack_from("i", event.raw, 72)[0]
                yr = struct.unpack_from("i", event.raw, 76)[0]
                if armed == "pin":
                    session.add_pin(xr, yr)
                    lib.XUngrabPointer(display, 0)
                    armed = None
                elif session.drag_from is None:
                    session.drag_from = (xr, yr)
                else:
                    session.add_mark(armed, session.drag_from[0], session.drag_from[1], xr, yr)
                    session.drag_from = None
                    lib.XUngrabPointer(display, 0)
                    armed = None
                lib.XStoreName(display, window, toolbar_title(len(session.pins), notice_banner()).encode())
                lib.XFlush(display)
            elif 0 <= x <= 80:
                armed = "pin"
                lib.XGrabPointer(display, root, 0, 1 << 2, 1, 1, 0, 0, 0)
                lib.XFlush(display)
        if kind == 2:
            keysym = _keysym(lib, display, event)
            if keysym in (0xFF1B,):  # Escape
                break
            if keysym in (ord("p"), ord("P")):
                armed = "pin"
                lib.XGrabPointer(display, root, 0, 1 << 2, 1, 1, 0, 0, 0)
                lib.XFlush(display)
            elif keysym in (ord("b"),):
                session.pin_type = "bug"
            elif keysym in (ord("c"),):
                session.pin_type = "change"
            elif keysym in (ord("q"),):
                session.pin_type = "question"
            elif keysym in (ord("v"), ord("V")):
                session.start_voice()
            elif keysym in (ord("g"),):
                session.steps_on = not session.steps_on
        if kind == 3:  # KeyRelease
            keysym = _keysym(lib, display, event)
            if keysym in (ord("v"), ord("V")):
                session.stop_voice()
            elif keysym in (ord("a"),):
                armed = "arrow"
                session.drag_from = None
                lib.XGrabPointer(display, root, 0, 1 << 2, 1, 1, 0, 0, 0)
                lib.XFlush(display)
            elif keysym in (ord("r"),):
                armed = "box"
                session.drag_from = None
                lib.XGrabPointer(display, root, 0, 1 << 2, 1, 1, 0, 0, 0)
                lib.XFlush(display)
            elif keysym in (ord("s"),):
                armed = "spotlight"
                session.drag_from = None
                lib.XGrabPointer(display, root, 0, 1 << 2, 1, 1, 0, 0, 0)
                lib.XFlush(display)
    out = Path.home() / "DingAI" / "linux"
    note = session.export(out)
    lib.XCloseDisplay(display)
    print(json.dumps({"pins": note["pin_count"], "dir": str(out)}))
    return 0


def _keysym(lib, display, event):
    try:
        lib.XLookupKeysym.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XLookupKeysym.restype = ctypes.c_ulong
        return lib.XLookupKeysym(event, 0)
    except Exception:
        return 0


def main(argv):
    if "--check" in argv:
        print(json.dumps(capabilities()))
        return 0
    if "--export-demo" in argv:
        session = Session()
        session.add_pin(40, 50, "demo")
        session.pin_type = "question"
        session.add_pin(80, 90, "follow-up")
        out = Path(argv[argv.index("--export-demo") + 1]) if len(argv) > argv.index("--export-demo") + 1 else Path.home() / "DingAI" / "linux"
        note = session.export(out)
        print(note["pin_count"])
        return 0
    if os.environ.get("DISPLAY"):
        return run_toolbar()
    print("Set DISPLAY for the X11 session, or pass --check.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
