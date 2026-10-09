"""Resolve persistent project data for both editable and server wheel installs."""
import os
from pathlib import Path


def project_root():
    configured = os.getenv("BANKIS_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    source_root = Path(__file__).resolve().parent.parent
    return source_root if (source_root / "pyproject.toml").exists() else Path.cwd().resolve()
