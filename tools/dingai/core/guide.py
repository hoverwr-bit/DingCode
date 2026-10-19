"""Numbered step bundles. SOP markdown for people, repro JSON for an agent."""

import json
from pathlib import Path


def sop_markdown(steps):
    lines = ["# DingAI steps", ""]
    for index, step in enumerate(steps or [], 1):
        text = (step.get("note") or step.get("text") or "Step").strip()
        lines.append("%d. %s" % (index, text))
        shot = step.get("shot") or ""
        if shot:
            lines.append("")
            lines.append("![](%s)" % shot)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_bundle(directory, steps):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    clean = []
    for index, step in enumerate(steps or [], 1):
        row = {key: value for key, value in dict(step).items() if key != "png"}
        row["n"] = index
        png = step.get("png") or b""
        if png and row.get("shot"):
            (directory / row["shot"]).write_bytes(png)
        clean.append(row)
    (directory / "sop.md").write_text(sop_markdown(clean), encoding="utf-8")
    bundle = {"schema": "dingai-steps-v1", "steps": clean}
    (directory / "repro.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return bundle
