from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


class IntegrityError(RuntimeError):
    pass


def canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def immutable(path: Path, value):
    """Atomic create-only publication; a repeated identical write is harmless."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if read(path) != value:
            raise IntegrityError(f"Refusing to replace artifact: {path.name}")
        return
    fd, name = tempfile.mkstemp(prefix=".publishing-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if read(path) != value:
                raise IntegrityError(f"Concurrent conflicting artifact: {path.name}") from None
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def seal(value) -> dict:
    return {"sha256": digest(value), "data": value}


def unseal(path: Path):
    envelope = read(path)
    if set(envelope) != {"sha256", "data"} or digest(envelope["data"]) != envelope["sha256"]:
        raise IntegrityError(f"Invalid artifact checksum: {path.name}")
    return envelope["data"]


@contextmanager
def exclusive_run(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".run.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise IntegrityError("This run is already executing") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
