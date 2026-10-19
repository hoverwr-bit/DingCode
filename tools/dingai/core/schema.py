"""dingai-desktop-v1 fields that every client must emit the same way."""

PIN_TYPES = ("bug", "change", "question")
PIN_STATUSES = ("open", "ai-fixed", "confirmed")


def normalize_pin(pin):
    out = dict(pin or {})
    kind = out.get("pin_type") or "bug"
    status = out.get("status") or "open"
    if kind not in PIN_TYPES:
        kind = "bug"
    if status not in PIN_STATUSES:
        status = "open"
    out["pin_type"] = kind
    out["status"] = status
    if "id" not in out:
        out["id"] = 0
    out["x_px"] = int(out.get("x_px") or 0)
    out["y_px"] = int(out.get("y_px") or 0)
    out["ocr_nearby"] = out.get("ocr_nearby") or ""
    return out


def normalize_note(note):
    src = dict(note or {})
    pins = [normalize_pin(p) for p in src.get("pins") or []]
    out = {
        "schema": "dingai-desktop-v1",
        "tool": "dingai",
        "schema_compat": src.get("schema_compat") or "anno-desktop-v1",
        "platform": src.get("platform") or "",
        "ts": src.get("ts") or "",
        "machine": src.get("machine") or "",
        "user": src.get("user") or "",
        "app": src.get("app") or {},
        "screen": src.get("screen") or {},
        "window": src.get("window") or {},
        "pins": pins,
        "arrows": list(src.get("arrows") or []),
        "boxes": list(src.get("boxes") or []),
        "labels": list(src.get("labels") or []),
        "pin_count": len(pins),
        "arrow_count": len(src.get("arrows") or []),
        "box_count": len(src.get("boxes") or []),
        "label_count": len(src.get("labels") or []),
        "screenshot": src.get("screenshot") or "",
        "screen_capture_ok": bool(src.get("screen_capture_ok")),
        "live": bool(src.get("live", True)),
        "handoff_rules": src.get("handoff_rules") or "",
        "project": src.get("project") or "inbox",
        "file": src.get("file") or src.get("id") or "",
    }
    return out
