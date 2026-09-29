"""Finding, keeping and publishing a run's artifacts.

Three jobs:

* **locate** a produced file wherever the tools actually wrote it. The
  runtime's sandbox folder and the tool layer's workspace root are not always
  the same directory (for the "default" workspace the tools write to the
  repository root), so both are searched, each with containment enforced.
* **capture** a copy of each produced file into the run's own folder when the
  run ends, so a later overwrite does not lose the version this run made.
* **publish** only the public shape to the browser (docs/INTERFACES.md 3.6):
  no filesystem paths, ever.
"""

from __future__ import annotations

import logging
import mimetypes
import posixpath
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.runtime import config
from app.runtime.ids import resolve_within

logger = logging.getLogger(__name__)

#: Fields that exist only for the server (locating/serving the file).
PRIVATE_FIELDS = ("path", "captured", "announced")

PREVIEWABLE_PREFIXES = ("text/", "image/")
PREVIEWABLE_TYPES = {"application/json", "application/pdf"}


def candidate_roots(workspace_id: str) -> List[Path]:
    """Every directory a tool may have written this workspace's files to."""
    roots: List[Path] = []
    try:
        from app.runtime.sessions.store import workspace_store

        roots.append(workspace_store.dir_for(workspace_id).resolve())
    except (ValueError, OSError):
        pass
    try:
        from app.workspace.manager import get_workspace_manager

        roots.append(Path(get_workspace_manager(workspace_id).root_path).resolve())
    except Exception:  # noqa: BLE001 - the tool layer may not be importable in tests
        pass
    unique: List[Path] = []
    for root in roots:
        if root not in unique:
            unique.append(root)
    return unique


def locate(workspace_id: str, path: str, roots: Optional[Iterable[Path]] = None) -> Optional[Path]:
    """Resolve a produced file's path to a real file inside an allowed root."""
    if not path:
        return None
    raw = Path(str(path))
    for root in roots if roots is not None else candidate_roots(workspace_id):
        try:
            if raw.is_absolute():
                target = raw.resolve()
                if not target.is_relative_to(root):
                    continue
            else:
                target = resolve_within(root, str(path))
        except (ValueError, OSError):
            continue
        if target.is_file():
            return target
    return None


def captured_file(artifacts_dir: Path, artifact_id: str) -> Optional[Path]:
    if not artifacts_dir.is_dir():
        return None
    for candidate in artifacts_dir.glob(f"{artifact_id}*"):
        if candidate.is_file():
            return candidate
    return None


def capture(result: Dict[str, Any], workspace_id: str, artifacts_dir: Path) -> Dict[str, Any]:
    """Copy each produced file into the run folder. Best effort, never raises."""
    if not config.ARTIFACT_CAPTURE:
        return result
    roots = candidate_roots(workspace_id)
    for artifact in result.get("artifacts", []):
        if artifact.get("type") not in ("file", "image"):
            continue
        if artifact.get("action") not in ("created", "modified"):
            continue
        try:
            source = locate(workspace_id, artifact.get("path", ""), roots)
            if source is None:
                continue
            size = source.stat().st_size
            if size > config.ARTIFACT_MAX_BYTES:
                continue
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            dest = artifacts_dir / f"{artifact['id']}{source.suffix}"
            shutil.copy2(source, dest)
            artifact["bytes"] = size
            artifact["captured"] = True
        except OSError as exc:
            logger.warning("could not capture artifact %s: %s", artifact.get("id"), exc)
    return result


def _is_previewable(mime: Optional[str]) -> bool:
    return bool(mime) and (mime.startswith(PREVIEWABLE_PREFIXES) or mime in PREVIEWABLE_TYPES)


def _display_path(path: str) -> str:
    """Keep workspace-relative paths; reduce anything absolute to its name."""
    text = str(path or "").replace("\\", "/")
    if text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        return posixpath.basename(text)
    return text


def public_artifact(artifact: Dict[str, Any]) -> Dict[str, Any]:
    """The browser's view of an artifact: the 3.6 contract plus display fields."""
    out = {k: v for k, v in artifact.items() if k not in PRIVATE_FIELDS}
    name = artifact.get("name") or artifact.get("filename") or ""
    mime = artifact.get("mime") or artifact.get("mime_type") or mimetypes.guess_type(name)[0]
    url = artifact.get("preview_url") or artifact.get("url")
    out.update(
        artifact_id=artifact.get("id") or artifact.get("artifact_id"),
        filename=name,
        mime_type=mime,
        size=artifact.get("bytes", artifact.get("size", 0)),
        preview_supported=artifact.get("type") == "url" or _is_previewable(mime),
        secure_url=url,
        download_url=artifact.get("download_url") or (f"{url}?download=1" if url and artifact.get("type") != "url" else None),
    )
    return out


def public_result(result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A RunResult with every filesystem path removed."""
    if not result:
        return result
    out = dict(result)
    out["artifacts"] = [public_artifact(a) for a in result.get("artifacts", [])]
    for key in ("files_created", "files_modified", "files_deleted"):
        out[key] = [_display_path(p) for p in result.get(key, [])]
    return out


__all__ = [
    "candidate_roots",
    "locate",
    "captured_file",
    "capture",
    "public_artifact",
    "public_result",
]
