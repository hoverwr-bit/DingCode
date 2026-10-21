"""Home directory and environment names.

DINGCODE_* is the name to set. DINGAI_* still works when the new name is unset.
~/DingCode is the data directory. An existing ~/DingAI is renamed once; if that
rename fails, the old directory is used as-is.
"""

import os
from pathlib import Path


def env(*names, default=None):
    for name in names:
        if name in os.environ and os.environ[name] != "":
            return os.environ[name]
    return default


def data_home():
    override = env("DINGCODE_HOME", "DINGAI_HOME")
    if override:
        return override
    new = Path.home() / "DingCode"
    old = Path.home() / "DingAI"
    if new.exists():
        return str(new)
    if old.exists():
        try:
            old.rename(new)
            return str(new)
        except OSError:
            return str(old)
    return str(new)


def project_root_name(project):
    """'.dingcode' or '.dingai', whichever directory is already in the project."""
    if not project:
        return ".dingcode"
    new_dir = os.path.join(project, ".dingcode")
    old_dir = os.path.join(project, ".dingai")
    if os.path.isdir(new_dir):
        return ".dingcode"
    if os.path.isdir(old_dir):
        return ".dingai"
    return ".dingcode"


def project_file(project, name):
    """A file under the project config dir. Reads the old dir when that is the one in use."""
    if not project:
        return ""
    folder = project_root_name(project)
    return os.path.join(project, folder, name)


def state_dir(share_dir=""):
    if share_dir:
        new = os.path.join(share_dir, "dingcode-state")
        old = os.path.join(share_dir, "dingai-state")
        if os.path.isdir(new) or not os.path.isdir(old):
            return new
        return old
    override = env("DINGCODE_STATE_DIR", "DINGAI_STATE_DIR")
    if override:
        return override
    return data_home()
