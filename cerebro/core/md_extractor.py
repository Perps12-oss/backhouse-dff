# cerebro/core/md_extractor.py
"""Rich file metadata extraction.

Populates FileMetadata.metadata dicts with format-specific properties
(EXIF, audio tags, video streams, document properties).

Design constraints
------------------
- All subprocess calls use shell=False and an explicit timeout.
- Subprocess environment is stripped to PATH only — no user env leakage.
- Pure-Python libraries are always tried first; subprocess is a fallback.
- Every extractor degrades silently: missing tool → empty dict, not an error.
- No filesystem writes; read-only access only.
- String values are capped at 256 chars to prevent runaway memory use.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Subprocess sandbox: expose only PATH so the child cannot inherit credentials,
# proxy settings, or other sensitive environment variables.
_SAFE_ENV: Dict[str, str] = {"PATH": os.environ.get("PATH", "")}

_IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
    ".tiff", ".tif", ".heic", ".raw", ".cr2", ".nef", ".arw",
}
_AUDIO_EXTS = {".mp3", ".flac", ".wav", ".aac", ".ogg", ".m4a", ".wma", ".opus"}
_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv", ".flv"}
_DOCUMENT_EXTS = {".pdf", ".docx", ".xlsx", ".pptx"}


def extract(path: Path, *, timeout: int = 10) -> Dict[str, Any]:
    """Extract format-specific metadata from *path*.

    Returns a flat str→scalar dict suitable for FileMetadata.metadata.
    Never raises; returns {} on any failure or unsupported format.
    """
    ext = path.suffix.lower()
    try:
        if ext in _IMAGE_EXTS:
            return _extract_image(path, timeout=timeout)
        if ext in _AUDIO_EXTS:
            return _extract_audio(path)
        if ext in _VIDEO_EXTS:
            return _extract_video(path, timeout=timeout)
        if ext in _DOCUMENT_EXTS:
            return _extract_document(path)
    except Exception:
        logger.debug("md_extractor: unhandled exception for %s", path, exc_info=True)
    return {}


# ---------------------------------------------------------------------------
# Image
# ---------------------------------------------------------------------------

def _extract_image(path: Path, *, timeout: int = 10) -> Dict[str, Any]:
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS

        with Image.open(str(path)) as img:
            result: Dict[str, Any] = {
                "width": img.width,
                "height": img.height,
                "mode": img.mode,
                "format": img.format or "",
            }
            try:
                raw_exif = img._getexif()  # type: ignore[attr-defined]
            except AttributeError:
                raw_exif = None
            if raw_exif:
                for tag_id, value in raw_exif.items():
                    if isinstance(value, bytes):
                        continue
                    tag = TAGS.get(tag_id, str(tag_id))
                    try:
                        result[f"exif_{tag}"] = str(value)[:256]
                    except Exception:
                        pass
            return result
    except ImportError:
        pass
    except Exception:
        pass
    return _exiftool_fallback(path, timeout=timeout)


# ---------------------------------------------------------------------------
# Audio  (pure Python via mutagen — no subprocess)
# ---------------------------------------------------------------------------

def _extract_audio(path: Path) -> Dict[str, Any]:
    try:
        import mutagen  # type: ignore[import]

        f = mutagen.File(str(path))
        if f is None:
            return {}
        result: Dict[str, Any] = {}
        info = getattr(f, "info", None)
        if info is not None:
            if hasattr(info, "length"):
                result["duration_s"] = round(float(info.length), 2)
            if hasattr(info, "bitrate"):
                result["bitrate_kbps"] = int(info.bitrate // 1000)
            if hasattr(info, "sample_rate"):
                result["sample_rate_hz"] = int(info.sample_rate)
            if hasattr(info, "channels"):
                result["channels"] = int(info.channels)
        for key, val in (f.tags or {}).items():
            try:
                v = val[0] if hasattr(val, "__getitem__") else val
                result[f"tag_{key}"] = str(v)[:256]
            except Exception:
                pass
        return result
    except ImportError:
        return {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Video  (ffprobe subprocess — sandboxed, timed)
# ---------------------------------------------------------------------------

def _extract_video(path: Path, *, timeout: int = 10) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            env=_SAFE_ENV,
        )
        if proc.returncode != 0:
            return {}
        data = json.loads(proc.stdout)
    except FileNotFoundError:
        return {}
    except subprocess.TimeoutExpired:
        logger.debug("md_extractor: ffprobe timed out for %s", path)
        return {}
    except (json.JSONDecodeError, ValueError, OSError):
        return {}

    result: Dict[str, Any] = {}
    fmt = data.get("format", {})
    if "duration" in fmt:
        result["duration_s"] = round(float(fmt["duration"]), 2)
    if "bit_rate" in fmt:
        result["bitrate_kbps"] = int(int(fmt["bit_rate"]) // 1000)
    if "format_name" in fmt:
        result["container"] = str(fmt["format_name"])

    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type", "")
        if codec_type == "video" and "video_codec" not in result:
            result["video_codec"] = stream.get("codec_name", "")
            result["width"] = int(stream.get("width", 0))
            result["height"] = int(stream.get("height", 0))
            r = str(stream.get("r_frame_rate", ""))
            if "/" in r:
                try:
                    num, den = r.split("/", 1)
                    result["fps"] = round(int(num) / max(1, int(den)), 2)
                except (ValueError, ZeroDivisionError):
                    pass
        elif codec_type == "audio" and "audio_codec" not in result:
            result["audio_codec"] = stream.get("codec_name", "")
            result["audio_channels"] = int(stream.get("channels", 0))
            result["audio_sample_rate"] = str(stream.get("sample_rate", ""))

    return result


# ---------------------------------------------------------------------------
# Documents  (pure Python — no subprocess)
# ---------------------------------------------------------------------------

def _extract_document(path: Path) -> Dict[str, Any]:
    ext = path.suffix.lower()
    try:
        if ext == ".docx":
            return _extract_docx(path)
        if ext == ".xlsx":
            return _extract_xlsx(path)
        if ext in (".pdf",):
            return _extract_pdf(path)
    except ImportError:
        pass
    except Exception:
        pass
    return {}


def _extract_docx(path: Path) -> Dict[str, Any]:
    import docx  # type: ignore[import]
    doc = docx.Document(str(path))
    core = doc.core_properties
    return {
        "author": str(core.author or "")[:256],
        "title": str(core.title or "")[:256],
        "word_count": sum(len(p.text.split()) for p in doc.paragraphs),
    }


def _extract_xlsx(path: Path) -> Dict[str, Any]:
    import openpyxl  # type: ignore[import]
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        props = wb.properties
        return {
            "sheet_count": len(wb.sheetnames),
            "creator": str(props.creator or "")[:256],
            "title": str(props.title or "")[:256],
        }
    finally:
        wb.close()


def _extract_pdf(path: Path) -> Dict[str, Any]:
    try:
        import pypdf  # type: ignore[import]
        with open(str(path), "rb") as fh:
            reader = pypdf.PdfReader(fh)
            info = reader.metadata or {}
            return {
                "page_count": len(reader.pages),
                "author": str(info.get("/Author", ""))[:256],
                "title": str(info.get("/Title", ""))[:256],
                "creator": str(info.get("/Creator", ""))[:256],
            }
    except ImportError:
        pass
    return {}


# ---------------------------------------------------------------------------
# exiftool fallback  (sandboxed subprocess)
# ---------------------------------------------------------------------------

_EXIFTOOL_SKIP_KEYS = {"SourceFile", "ExifToolVersion", "Directory", "FileName", "FilePermissions"}


def _exiftool_fallback(path: Path, *, timeout: int = 10) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            ["exiftool", "-json", "-n", str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            env=_SAFE_ENV,
        )
        if proc.returncode != 0:
            return {}
        data = json.loads(proc.stdout)
        if not data:
            return {}
        return {
            k: str(v)[:256]
            for k, v in data[0].items()
            if k not in _EXIFTOOL_SKIP_KEYS and not isinstance(v, (dict, list))
        }
    except FileNotFoundError:
        return {}
    except subprocess.TimeoutExpired:
        logger.debug("md_extractor: exiftool timed out for %s", path)
        return {}
    except (json.JSONDecodeError, ValueError, OSError):
        return {}
