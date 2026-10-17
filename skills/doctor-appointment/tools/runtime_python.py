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
    if not python.is_file() or os.environ.get('CLINIC_HELPER_REEXEC') or _same_place(sys.prefix, environment):
        return
    # Guard against an endless re-exec loop if the check above ever disagrees.
    os.environ['CLINIC_HELPER_REEXEC'] = '1'
    # Preserve the original script and its arguments without shell interpolation.
    os.execv(str(python), [str(python), *sys.argv])


def _same_place(a, b):
    # Compare by file identity: macOS folders such as ~/work and ~/Work are one place.
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False
