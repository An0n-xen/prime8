"""Download service — yt-dlp, gallery-dl, and direct HTTP downloads."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from config import settings as config
from utils.logger import get_logger
from utils.metrics import download_duration, download_invocations

logger = get_logger(__name__)

MAX_BYTES = config.DOWNLOAD_MAX_FILESIZE_MB * 1024 * 1024


DISCORD_FILE_LIMIT = 25 * 1024 * 1024  # 25MB


@dataclass
class DownloadResult:
    """Result of a download operation."""

    files: list[Path] = field(default_factory=list)
    title: str = ""
    source: str = ""  # "yt-dlp", "gallery-dl", or "direct"
    error: str | None = None
    compressed: bool = False


# ---------------------------------------------------------------------------
# yt-dlp
# ---------------------------------------------------------------------------

def _ytdlp_download(url: str, output_dir: Path) -> DownloadResult:
    """Download media using yt-dlp. Runs in a thread."""
    import yt_dlp

    t0 = time.monotonic()
    outtmpl = str(output_dir / "%(title).80s.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_BYTES,
        "noplaylist": True,
        # Prefer formats with known filesize under limit, but fall back to
        # best available when filesize isn't reported (common for Shorts/live)
        "format": (
            f"best[filesize<={MAX_BYTES}]/"
            f"bestvideo[filesize<={MAX_BYTES}]+bestaudio[filesize<={MAX_BYTES}]/"
            "bestvideo+bestaudio/best"
        ),
        "merge_output_format": "mp4",
    }

    if config.YTDLP_COOKIES_FILE:
        ydl_opts["cookiefile"] = config.YTDLP_COOKIES_FILE

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "download") if info else "download"

    files = [f for f in sorted(output_dir.iterdir()) if f.is_file()]
    download_invocations.labels(tool="yt-dlp", status="success").inc()
    download_duration.labels(tool="yt-dlp").observe(time.monotonic() - t0)
    return DownloadResult(files=files, title=title, source="yt-dlp")


# ---------------------------------------------------------------------------
# gallery-dl
# ---------------------------------------------------------------------------

def _gallerydl_download(url: str, output_dir: Path) -> DownloadResult:
    """Download images/galleries using gallery-dl. Runs in a thread."""
    from gallery_dl import config as gdl_config
    from gallery_dl import job

    t0 = time.monotonic()

    gdl_config.clear()
    gdl_config.set(("extractor",), "base-directory", str(output_dir))
    gdl_config.set(("extractor",), "directory", [""])
    gdl_config.set(("extractor",), "filename", "{filename}.{extension}")
    gdl_config.set(("output",), "mode", "null")

    job.DownloadJob(url).run()

    files = sorted(output_dir.iterdir())
    # Filter out files exceeding size limit
    files = [f for f in files if f.is_file() and f.stat().st_size <= MAX_BYTES]

    download_invocations.labels(tool="gallery-dl", status="success").inc()
    download_duration.labels(tool="gallery-dl").observe(time.monotonic() - t0)
    return DownloadResult(files=files, title=url.split("/")[-1] or "gallery", source="gallery-dl")


# ---------------------------------------------------------------------------
# Direct HTTP (replaces wget/curl)
# ---------------------------------------------------------------------------

async def _direct_download(url: str, output_dir: Path) -> DownloadResult:
    """Download a file directly via HTTP. Async-native."""
    t0 = time.monotonic()

    async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client, client.stream("GET", url) as resp:
        resp.raise_for_status()

        # Reject HTML/text responses — these are web pages, not downloadable files
        content_type = resp.headers.get("content-type", "")
        if any(t in content_type for t in ("text/html", "text/xml", "application/xhtml")):
            download_invocations.labels(tool="direct", status="error").inc()
            return DownloadResult(error="URL points to a web page, not a downloadable file.")

        # Derive filename from URL or Content-Disposition
        content_disp = resp.headers.get("content-disposition", "")
        if "filename=" in content_disp:
            fname = content_disp.split("filename=")[-1].strip('" ')
        else:
            fname = url.split("/")[-1].split("?")[0] or "file"

        dest = output_dir / fname
        total = 0
        with dest.open("wb") as f:
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                total += len(chunk)
                if total > MAX_BYTES:
                    dest.unlink(missing_ok=True)
                    download_invocations.labels(tool="direct", status="error").inc()
                    return DownloadResult(
                        error=f"File exceeds {config.DOWNLOAD_MAX_FILESIZE_MB}MB limit"
                    )
                f.write(chunk)

    download_invocations.labels(tool="direct", status="success").inc()
    download_duration.labels(tool="direct").observe(time.monotonic() - t0)
    return DownloadResult(files=[dest], title=fname, source="direct")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _ytdlp_download_audio(url: str, output_dir: Path) -> DownloadResult:
    """Download audio-only using yt-dlp. Runs in a thread."""
    import yt_dlp

    t0 = time.monotonic()
    outtmpl = str(output_dir / "%(title).80s.%(ext)s")

    ydl_opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_BYTES,
        "noplaylist": True,
        "format": "bestaudio/best",
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }

    if config.YTDLP_COOKIES_FILE:
        ydl_opts["cookiefile"] = config.YTDLP_COOKIES_FILE

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title", "audio") if info else "audio"

    files = sorted(output_dir.iterdir())
    download_invocations.labels(tool="yt-dlp", status="success").inc()
    download_duration.labels(tool="yt-dlp").observe(time.monotonic() - t0)
    return DownloadResult(files=files, title=title, source="yt-dlp")


async def download_audio(url: str) -> DownloadResult:
    """Download audio-only from a URL using yt-dlp."""
    output_dir = config.DOWNLOAD_PATH / uuid.uuid4().hex[:12]
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = await asyncio.to_thread(_ytdlp_download_audio, url, output_dir)
        if result.files:
            return result
    except Exception as e:
        logger.error(f"Audio download failed for {url}: {e}")
        download_invocations.labels(tool="yt-dlp", status="error").inc()
        cleanup(output_dir)
        return DownloadResult(error=f"Audio extraction failed: {e}")

    cleanup(output_dir)
    return DownloadResult(error="No audio could be extracted from this URL.")


async def download(url: str) -> DownloadResult:
    """
    Download content from a URL using the best available tool.

    Strategy: try yt-dlp first (supports 1000+ sites), then gallery-dl
    (image galleries), then fall back to direct HTTP download.
    """
    output_dir = config.DOWNLOAD_PATH / uuid.uuid4().hex[:12]
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Try yt-dlp (videos, audio, social media)
    try:
        result = await asyncio.to_thread(_ytdlp_download, url, output_dir)
        if result.files:
            return result
    except Exception as e:
        logger.debug(f"yt-dlp failed for {url}: {e}")
        download_invocations.labels(tool="yt-dlp", status="error").inc()
        # Clean any partial files
        _clean_dir(output_dir)

    # 2. Try gallery-dl (image galleries)
    try:
        result = await asyncio.to_thread(_gallerydl_download, url, output_dir)
        if result.files:
            return result
    except Exception as e:
        logger.debug(f"gallery-dl failed for {url}: {e}")
        download_invocations.labels(tool="gallery-dl", status="error").inc()
        _clean_dir(output_dir)

    # 3. Fall back to direct HTTP download
    try:
        result = await _direct_download(url, output_dir)
        if result.files or result.error:
            return result
    except Exception as e:
        logger.debug(f"Direct download failed for {url}: {e}")
        download_invocations.labels(tool="direct", status="error").inc()

    # All methods failed
    cleanup(output_dir)
    return DownloadResult(error="Could not download from this URL. No supported extractor found.")


# ---------------------------------------------------------------------------
# FFmpeg compression
# ---------------------------------------------------------------------------

_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv", ".m4v"}


def _compress_video(filepath: Path, target_bytes: int = DISCORD_FILE_LIMIT) -> Path:
    """Re-encode a video with ffmpeg to fit under target_bytes. Runs in a thread."""
    import subprocess

    # Get duration via ffprobe
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(filepath),
        ],
        capture_output=True, text=True, timeout=30,
    )
    duration = float(probe.stdout.strip())

    # Target bitrate: (target_bytes * 8) / duration, with 10% headroom for audio + container
    audio_bitrate = 96_000  # 96kbps audio
    total_bitrate = int((target_bytes * 0.90 * 8) / duration)
    video_bitrate = max(total_bitrate - audio_bitrate, 100_000)  # at least 100kbps

    output = filepath.with_stem(filepath.stem + "_compressed").with_suffix(".mp4")

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(filepath),
            "-c:v", "libx264", "-preset", "fast",
            "-b:v", str(video_bitrate),
            "-maxrate", str(int(video_bitrate * 1.2)),
            "-bufsize", str(int(video_bitrate * 2)),
            "-c:a", "aac", "-b:a", str(audio_bitrate),
            "-movflags", "+faststart",
            str(output),
        ],
        capture_output=True, timeout=600,
        check=True,
    )

    # Verify it fits
    if output.stat().st_size > target_bytes:
        output.unlink(missing_ok=True)
        raise ValueError("Compressed video still exceeds Discord's 25MB limit")

    return output


async def compress_oversized_files(result: DownloadResult) -> DownloadResult:
    """Compress any video files that exceed Discord's 25MB upload limit."""
    new_files = []
    compressed = False

    for filepath in result.files:
        if not filepath.is_file():
            continue

        size = filepath.stat().st_size
        if size <= DISCORD_FILE_LIMIT:
            new_files.append(filepath)
            continue

        # Only compress video files
        if filepath.suffix.lower() not in _VIDEO_EXTENSIONS:
            logger.info(f"Skipping non-video oversized file: {filepath.name} ({size / 1024 / 1024:.1f}MB)")
            continue

        logger.info(f"Compressing {filepath.name} ({size / 1024 / 1024:.1f}MB) to fit Discord limit")
        try:
            compressed_path = await asyncio.to_thread(_compress_video, filepath)
            new_files.append(compressed_path)
            filepath.unlink(missing_ok=True)  # remove original
            compressed = True
        except Exception as e:
            logger.warning(f"Compression failed for {filepath.name}: {e}")
            # Don't include the oversized file

    result.files = new_files
    result.compressed = compressed
    return result


def cleanup(output_dir: Path) -> None:
    """Remove a download directory and all its contents."""
    try:
        shutil.rmtree(output_dir, ignore_errors=True)
    except Exception as e:
        logger.warning(f"Failed to clean up {output_dir}: {e}")


def _clean_dir(output_dir: Path) -> None:
    """Remove all files in a directory without deleting the directory."""
    for f in output_dir.iterdir():
        with contextlib.suppress(Exception):
            f.unlink()


def cleanup_stale(max_age_seconds: int = 600) -> int:
    """Remove download directories older than max_age_seconds. Returns count removed."""
    removed = 0
    download_root = config.DOWNLOAD_PATH
    if not download_root.exists():
        return 0

    now = time.time()
    for entry in download_root.iterdir():
        if not entry.is_dir():
            continue
        try:
            age = now - entry.stat().st_mtime
            if age > max_age_seconds:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        except Exception:
            pass

    if removed:
        logger.info(f"Cleaned up {removed} stale download directory/directories")
    return removed
