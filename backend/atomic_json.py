"""Atomic JSON writes for the backend's JSON data files.

A plain `open(path, 'w')` truncates the file before anything is written, so
a crash, a killed worker or a failed json.dump() part-way through leaves a
truncated or half-written file behind. write_json_atomic() instead writes
the complete new contents to a temporary file in the same directory and
only then swaps it into place with os.replace(), which is atomic on the
same filesystem: the destination always holds either the old or the new
complete contents.

This only prevents partial files. It does not add locking, so concurrent
writers (e.g. two processes) can still overwrite each other's changes.
"""
import json
import os
import stat
import uuid


def write_json_atomic(path, data):
    """Writes `data` to `path` as JSON, exactly as
    `json.dump(data, f, indent=2)` into `open(path, 'w')` would, but
    atomically.

    The temporary file lives in the destination's own directory (a
    same-filesystem os.replace() is required for atomicity), has a random,
    exclusive name, and is always removed if anything fails before the
    replace - the error is then re-raised unchanged. File permissions match
    what `open(path, 'w')` gives: an existing destination keeps its mode,
    and a new one gets the usual umask-based default.
    """
    directory = os.path.dirname(os.path.abspath(path))
    try:
        existing_mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        existing_mode = None

    tmp_path = os.path.join(directory, f".{os.path.basename(path)}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        if existing_mode is not None:
            os.chmod(tmp_path, existing_mode)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
        raise
