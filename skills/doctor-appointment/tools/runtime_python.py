"""Select package dependencies for a trusted helper, never launch an agent session."""
import os
import sys
from pathlib import Path


def ensure_package_interpreter(root):
    """Re-exec once into an existing package venv, even when binaries are symlinks.

    Missing venv is left to callers' dependency/readiness handling. sys.prefix
    identifies the environment; resolving sys.executable loses that information.
    """
    environment = Path(root) / '.venv'
    python = environment / 'bin' / 'python'
    if not python.is_file() or Path(sys.prefix).resolve() == environment.resolve():
        return
    # Preserve the original script and its arguments without shell interpolation.
    os.execv(str(python), [str(python), *sys.argv])
