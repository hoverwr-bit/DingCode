"""DingCode editions: community (free / open source), pro (cockpit), team.

License sources, first match wins:
  1. env DINGAI_LICENSE (raw key, "pro", or "team")
  2. env DINGAI_EDITION ("pro" / "team")
  3. <project>/.dingai/license.json  {"key": "DGA1-..."}
  4. ~/DingAI/license.json          {"key": "DGA1-..."}

Key format: DGA1-<edition>-<yyyymmdd>-<hmac16>
  hmac16 = HMAC-SHA256(secret, "DGA1|<edition>|<yyyymmdd>")[:8].hex()

The default secret is built in and overridable with DINGAI_LICENSE_SECRET so a
self-hosted team server can be its own license authority (see the
/api/license/issue endpoint in team-server). Offline verification is an honest
gate for honest users; the team server check is the enforcement path for teams.

Default edition is community.
"""

import hashlib
import hmac
import json
import os
import time

KEY_PREFIX = "DGA1"
EDITIONS = ("community", "pro", "team")

# Dev/self-host default. Override with DINGAI_LICENSE_SECRET in production.
_DEFAULT_SECRET = b"dingcode-license-dev-secret-v1"

# feature -> minimum edition
_FEATURE_MIN = {
    "pin": "community",
    "prompt": "community",        # 复制 JS 描述给 agent
    "mcp-handoff": "community",
    "marks": "pro",               # 箭头/方框/椭圆/聚光/文字
    "sync": "pro",                # 共享目录 / 服务器上传
    "scope": "pro",               # 改动范围检查与回退
    "release": "pro",             # 发布评审 / 归档 / 回退
    "session": "pro",             # 会话冲突检测
    "workflow": "pro",            # agent 工作流配置与直接执行
    "cockpit": "pro",             # 驾驶台
    "team-board": "team",         # 团队服务端看板（团队版，开发中）
}

_RANK = {name: i for i, name in enumerate(EDITIONS)}


class EditionError(Exception):
    """Raised when a feature needs a higher edition."""


def _secret():
    env = os.environ.get("DINGAI_LICENSE_SECRET", "").strip()
    return env.encode("utf-8") if env else _DEFAULT_SECRET


def issue_key(edition, expires_yyyymmdd, secret=None):
    """Mint a license key. Used by the vendor or a self-hosted team server."""
    edition = edition.lower()
    if edition not in ("pro", "team"):
        raise ValueError("edition must be pro or team")
    payload = "%s|%s|%s" % (KEY_PREFIX, edition, expires_yyyymmdd)
    mac = hmac.new(secret or _secret(), payload.encode("ascii"), hashlib.sha256)
    return "%s-%s-%s-%s" % (KEY_PREFIX, edition, expires_yyyymmdd, mac.hexdigest()[:16])


def parse_key(key):
    """Return (edition, expires_yyyymmdd) for a valid key, else (None, None)."""
    if not key:
        return None, None
    parts = str(key).strip().split("-")
    if len(parts) != 4 or parts[0] != KEY_PREFIX:
        return None, None
    edition, expiry, mac = parts[1].lower(), parts[2], parts[3]
    if edition not in ("pro", "team") or not (expiry.isdigit() and len(expiry) == 8):
        return None, None
    payload = "%s|%s|%s" % (KEY_PREFIX, edition, expiry)
    expect = hmac.new(_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(expect, mac):
        return None, None
    return edition, expiry


def _expired(expiry):
    try:
        year, month, day = int(expiry[:4]), int(expiry[4:6]), int(expiry[6:8])
        return time.time() > time.mktime((year, month, day, 23, 59, 59, 0, 0, -1))
    except (ValueError, OverflowError):
        return True


def _read_license_file(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return ""
    if isinstance(data, dict):
        return str(data.get("key") or data.get("license") or "")
    return ""


def detect(project=""):
    """Return (edition, source). One of community / pro / team."""
    env = os.environ
    raw = (env.get("DINGAI_LICENSE") or "").strip()
    if raw:
        if raw.lower() in ("pro", "team"):
            return raw.lower(), "env"
        edition, expiry = parse_key(raw)
        if edition and not _expired(expiry):
            return edition, "env"
    name = (env.get("DINGAI_EDITION") or "").strip().lower()
    if name in ("pro", "team"):
        return name, "env"
    candidates = []
    if project:
        candidates.append(os.path.join(project, ".dingai", "license.json"))
    candidates.append(os.path.join(os.path.expanduser("~"), "DingAI", "license.json"))
    for path in candidates:
        edition, expiry = parse_key(_read_license_file(path))
        if edition and not _expired(expiry):
            return edition, path
    return "community", ""


def features(edition=None):
    """Feature set available in an edition."""
    if edition is None:
        edition = detect()[0]
    return {name for name, minimum in _FEATURE_MIN.items()
            if _RANK[edition] >= _RANK[minimum]}


def enabled(feature, edition=None):
    return feature in features(edition)


def require(feature, edition=None):
    """Raise EditionError unless the edition has the feature."""
    if edition is None:
        edition = detect()[0]
    if not enabled(feature, edition):
        minimum = _FEATURE_MIN.get(feature, "pro")
        raise EditionError(
            "%s needs the %s edition (current: %s). "
            "免费开源版只包含定位钉与 JS 描述复制；升级到专业版可使用全部功能。"
            % (feature, minimum, edition)
        )
    return True


def describe(edition=None):
    if edition is None:
        edition, source = detect()
    else:
        source = ""
    return {"edition": edition, "source": source, "features": sorted(features(edition))}
