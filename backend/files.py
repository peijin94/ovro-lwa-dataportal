"""Safe file path resolution: only allow paths under configured NAS roots."""
import os
from pathlib import Path
from typing import Optional, Tuple

from backend.config import ALLOWED_FILE_ROOTS, ROOT_KEYS


def resolve_to_allowed_path(root_key: str, relative_path: str) -> Optional[Path]:
    """
    Resolve (root_key, relative_path) to a Path under an allowed root.
    root_key must be in ROOT_KEYS; relative_path must not contain '..' or start with /.
    Returns None if invalid or not under allowed root.
    """
    if root_key not in ROOT_KEYS:
        return None
    if ".." in relative_path or relative_path.startswith("/"):
        return None
    # Resolve both base and target so that symlinked NAS paths still pass the
    # relative_to check.
    base = Path(ROOT_KEYS[root_key]).resolve()
    resolved = (base / relative_path).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        return None
    return resolved if resolved.exists() else None


def full_path_to_root_and_relative(full_path: str) -> Optional[Tuple[str, str]]:
    """Given a full NAS path from DB, return (root_key, relative_path) or None."""
    full = Path(full_path).resolve()
    for key, root in ROOT_KEYS.items():
        root_p = Path(root).resolve()
        try:
            rel = full.relative_to(root_p)
            return (key, str(rel))
        except ValueError:
            continue
    return None
