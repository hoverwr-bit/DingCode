"""Same placement rule as the marked block in web/anno.js and DingAI.swift."""


def layout_callouts(callouts, obstacles, bounds):
    dirs = [(1, 0, 0), (1, -1, 6), (0, -1, 6), (-1, -1, 6), (-1, 0, 6), (-1, 1, 6), (0, 1, 6), (1, 1, 6)]
    dists = (18, 32, 48, 68, 96, 132, 176)
    gap = 4
    placed = [{"x": o["x"], "y": o["y"], "w": o["w"], "h": o["h"]} for o in (obstacles or [])]

    def overlap(a, b):
        x1 = max(a["x"], b["x"] - gap)
        y1 = max(a["y"], b["y"] - gap)
        x2 = min(a["x"] + a["w"], b["x"] + b["w"] + gap)
        y2 = min(a["y"] + a["h"], b["y"] + b["h"] + gap)
        return (x2 - x1) * (y2 - y1) if x2 > x1 and y2 > y1 else 0

    def point_dist(px, py, rect):
        cx = min(max(px, rect["x"]), rect["x"] + rect["w"])
        cy = min(max(py, rect["y"]), rect["y"] + rect["h"])
        return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5

    out = []
    for k, c in enumerate(callouts or []):
        best = None
        for dx, dy, prefer in dirs:
            length = (dx * dx + dy * dy) ** 0.5 or 1
            for dist in dists:
                ox = dx / length * dist
                oy = dy / length * dist
                x = c["ax"] + ox + (-c["w"] if dx < 0 else (-c["w"] / 2 if dx == 0 else 0))
                y = c["ay"] + oy + (-c["h"] if dy < 0 else (-c["h"] / 2 if dy == 0 else 0))
                x = max(bounds["x"], min(x, bounds["x"] + bounds["w"] - c["w"]))
                y = max(bounds["y"], min(y, bounds["y"] + bounds["h"] - c["h"]))
                rect = {"x": x, "y": y, "w": c["w"], "h": c["h"]}
                hit = sum(overlap(rect, p) for p in placed)
                cost = hit * 10000 + dist + prefer + k * 0.01
                if best is None or cost < best["cost"]:
                    best = {"cost": cost, "x": x, "y": y, "leader": point_dist(c["ax"], c["ay"], rect) > 14}
        placed.append({"x": best["x"], "y": best["y"], "w": c["w"], "h": c["h"]})
        out.append({"id": c.get("id"), "x": best["x"], "y": best["y"], "w": c["w"], "h": c["h"], "leader": best["leader"]})
    return out
