"""Upload endpoint for importing a Google Takeout ``.zip`` into DailyMetric.

The heavy lifting lives in :func:`app.takeout_import.import_takeout`, which
walks a *directory*. This module accepts an uploaded ``.zip``, safely extracts
it to a temporary directory, and hands that directory to the existing importer.

Security: extraction is guarded against zip-slip (members whose paths escape the
extraction root) and against oversized uploads (``MAX_UPLOAD_MB``). The core
logic is the pure function :func:`import_takeout_zip`, which the route wraps.
"""

from __future__ import annotations

import io
import os
import tempfile
import zipfile

from fastapi import APIRouter, HTTPException, UploadFile

router = APIRouter(prefix="/import", tags=["import"])

# Max accepted upload size; a config change, not a code change. Default 200 MB.
MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "200"))


def _safe_extract(zf: zipfile.ZipFile, dest: str) -> None:
    """Extract every member of ``zf`` into ``dest``, rejecting zip-slip paths.

    A member whose resolved path is not inside ``dest`` (via ``..`` segments or
    an absolute path) raises :class:`ValueError` before anything is written.
    """
    dest_root = os.path.realpath(dest)
    for member in zf.namelist():
        target = os.path.realpath(os.path.join(dest, member))
        if target != dest_root and not target.startswith(dest_root + os.sep):
            raise ValueError(f"Unsafe path in zip: {member}")
    zf.extractall(dest)


def import_takeout_zip(data: bytes) -> dict:
    """Extract a Takeout ``.zip`` payload and run the daily-metric importer.

    Args:
        data: Raw bytes of an uploaded ``.zip`` file.

    Returns:
        The summary dict from :func:`app.takeout_import.import_takeout`.

    Raises:
        ValueError: the payload is empty, larger than ``MAX_UPLOAD_MB``, not a
            valid zip, or contains an unsafe (path-traversal) member.
    """
    if not data:
        raise ValueError("Empty upload.")
    max_bytes = int(MAX_UPLOAD_MB * 1024 * 1024)
    if len(data) > max_bytes:
        raise ValueError(f"Upload exceeds {MAX_UPLOAD_MB:.0f} MB limit.")

    buffer = io.BytesIO(data)
    if not zipfile.is_zipfile(buffer):
        raise ValueError("Upload is not a valid .zip file.")
    buffer.seek(0)

    # Imported lazily so a DATABASE_URL override set before the call is honoured
    # by app.db's module-level engine (same contract as import_takeout).
    from app.takeout_import import import_takeout

    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(buffer) as zf:
            _safe_extract(zf, tmp)
        return import_takeout(tmp)


@router.post("/takeout")
async def upload_takeout(file: UploadFile) -> dict:
    """Import a Google Takeout ``.zip`` uploaded via the web UI.

    Returns the importer's summary dict on success; a bad upload (not a zip,
    too large, unsafe) returns a 400 with an explanatory message.
    """
    data = await file.read()
    try:
        return import_takeout_zip(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
