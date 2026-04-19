"""modules/metadata_writer.py — IPTC/XMP metadata read/write via exiftool"""

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

from modules.logger import setup_logger

log = setup_logger("metadata_writer")

# Max seconds to wait for one line from exiftool before killing the process.
# Picked to be longer than any reasonable tag write on a large JPEG but short
# enough that a genuinely hung exiftool doesn't freeze the worker pool.
EXIFTOOL_READ_TIMEOUT_SEC = 30.0


class ExiftoolMissingError(RuntimeError):
    """Raised when the exiftool binary can't be located / launched.

    Distinct type so the pipeline / API layer can show an actionable
    install hint instead of a generic 'metadata write failed'. The
    default message includes the Homebrew one-liner because that's how
    every macOS dogfood machine in映奧 installs it."""

    def __init__(self, message: str | None = None):
        super().__init__(
            message
            or "exiftool not found. Install with: brew install exiftool"
        )


def _get_exiftool_cmd() -> str:
    """Find exiftool binary, checking PyInstaller bundle first."""
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "exiftool"
        if bundled.exists():
            return str(bundled)
    return "exiftool"


def check_exiftool_available() -> bool:
    """Lightweight probe: is exiftool launchable from the current PATH /
    bundle? Returns True/False. Safe to call on every UI load — does one
    `-ver` invocation capped at 2s. Does NOT raise."""
    cmd = _get_exiftool_cmd()
    try:
        proc = subprocess.run(
            [cmd, "-ver"],
            capture_output=True, text=True, timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


def build_exiftool_args(result: dict) -> list[str]:
    """Build exiftool CLI arguments from an analysis result dict."""
    # IPTC (IIM) defaults to Latin-1 in historical readers. Setting
    # CodedCharacterSet=UTF8 marks the file's IPTC payload as UTF-8 so
    # exiftool + Lightroom + Finder read CJK / Japanese / Korean keywords
    # correctly instead of rendering as `??`. Must come BEFORE the text
    # tags so it applies in the same write transaction.
    args = ["-IPTC:CodedCharacterSet=UTF8"]

    if result.get("title"):
        args.append(f"-IPTC:Headline={result['title']}")
        args.append(f"-XMP:Title={result['title']}")

    if result.get("description"):
        args.append(f"-IPTC:Caption-Abstract={result['description']}")
        args.append(f"-XMP:Description={result['description']}")

    all_keywords = list(result.get("keywords", []))
    for person in result.get("identified_people", []):
        if person not in all_keywords:
            all_keywords.append(person)
    # Use `+=` rather than `=` for list-type tags so we don't wipe user-
    # curated keywords (e.g., Lightroom-imported "wedding, bride"). The
    # trade-off is that re-running Happy Vision on the same photo would
    # dup these entries — folder_watcher's HappyVisionProcessed check is
    # what prevents that in practice.
    for kw in all_keywords:
        args.append(f"-IPTC:Keywords+={kw}")
        args.append(f"-XMP:Subject+={kw}")

    if result.get("category"):
        args.append(f"-XMP:Category={result['category']}")

    if result.get("mood"):
        args.append(f"-XMP:Scene={result['mood']}")

    if result.get("ocr_text"):
        ocr_combined = " | ".join(result["ocr_text"])
        args.append(f"-XMP:Comment={ocr_combined}")

    args.append("-XMP:UserComment=HappyVisionProcessed")

    return args


def write_metadata(photo_path: str, result: dict, backup: bool = False) -> bool:
    """Write analysis result as IPTC/XMP metadata into a photo file."""
    path = Path(photo_path)
    if not path.exists():
        log.error("File not found: %s", photo_path)
        return False

    args = build_exiftool_args(result)
    if not args:
        return True

    cmd = [_get_exiftool_cmd()]
    if not backup:
        cmd.append("-overwrite_original")
    cmd.extend(args)
    cmd.append(str(path))

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            log.error("exiftool failed for %s: %s", photo_path, proc.stderr)
            return False
        log.info("Metadata written to %s", path.name)
        return True
    except subprocess.TimeoutExpired:
        log.error("exiftool timed out for %s", photo_path)
        return False
    except FileNotFoundError:
        log.error("exiftool not found. Install with: brew install exiftool")
        return False


def read_metadata(photo_path: str) -> dict:
    """Read existing IPTC/XMP metadata from a photo."""
    try:
        proc = subprocess.run(
            [_get_exiftool_cmd(), "-json", "-IPTC:all", "-XMP:all", str(photo_path)],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode == 0:
            data = json.loads(proc.stdout)
            return data[0] if data else {}
    except Exception as e:
        log.error("Failed to read metadata from %s: %s", photo_path, e)
    return {}


def has_happy_vision_tag(photo_path: str) -> bool:
    """Check if a photo has already been processed by Happy Vision.

    WARNING: This forks a new exiftool process per call (~200 ms startup
    each). For bulk scans (folder_watcher), use `has_happy_vision_tag_batch`
    with a shared `ExiftoolBatch` instance — cuts scan time for 150k photos
    from ~8 hours to ~30 seconds.
    """
    metadata = read_metadata(photo_path)
    user_comment = metadata.get("UserComment", "")
    return "HappyVisionProcessed" in str(user_comment)


def has_happy_vision_tag_batch(batch: "ExiftoolBatch", photo_path: str) -> bool:
    """Batched version of has_happy_vision_tag. Uses a persistent exiftool
    session for ~100x speedup on bulk scans."""
    data = batch.read_json(photo_path, ["-XMP:UserComment", "-EXIF:UserComment"])
    user_comment = data.get("UserComment", "") if isinstance(data, dict) else ""
    return "HappyVisionProcessed" in str(user_comment)


def read_rating_batch(batch: "ExiftoolBatch", photo_path: str) -> int:
    """Return Lightroom-compatible XMP:Rating (0-5), or 0 if absent/unreadable.

    Lightroom writes rating to XMP-xmp:Rating as an integer 0-5. We also
    check EXIF (camera-written ratings) as a fallback. 0 means "no rating"
    which in Lightroom UI is displayed as zero stars."""
    data = batch.read_json(photo_path, ["-XMP:Rating", "-EXIF:Rating", "-Rating"])
    if not isinstance(data, dict):
        return 0
    raw = data.get("Rating")
    if raw is None or raw == "":
        return 0
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, min(5, n))


class ExiftoolBatch:
    """Persistent exiftool process using -stay_open mode.

    One exiftool invocation handles many files via stdin, avoiding
    ~200ms Perl startup per photo. Instances are thread-safe.
    """

    _UNSAFE_CHARS = ("\n", "\r", "\x00")
    _EOF = object()  # sentinel on the queue for "reader thread saw EOF"

    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None  # set by _spawn; keep assigned so close() is always safe
        self._output_queue: queue.Queue = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._spawn()

    def _spawn(self) -> None:
        """Start a fresh exiftool -stay_open session. Safe to call again after
        a previous session died or was killed on stall — drains the old
        queue, spins up a new Popen + reader thread.

        Raises ExiftoolMissingError if the binary can't be found — caller
        can show an actionable install hint instead of FileNotFoundError."""
        # Fresh queue so leftover lines from a previous session don't poison
        # the new one (the old reader will drop its EOF sentinel, which is
        # fine because we won't be consuming from it).
        self._output_queue = queue.Queue()
        try:
            self._proc = subprocess.Popen(
                [_get_exiftool_cmd(), "-stay_open", "True", "-@", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as e:
            raise ExiftoolMissingError() from e
        # Background reader drains stdout into the queue so the main thread
        # can wait with a timeout. Avoids the select/TextIOWrapper-buffer
        # trap where select on the raw fd misses data already buffered in
        # Python. Bind the reader to THIS proc + queue via closure so a
        # later respawn doesn't leak old output into the new queue.
        proc = self._proc
        q = self._output_queue
        def _reader_loop() -> None:
            stdout = proc.stdout
            try:
                for line in iter(stdout.readline, ""):
                    q.put(line)
            except (ValueError, OSError):
                pass
            finally:
                q.put(self._EOF)
        self._reader_thread = threading.Thread(
            target=_reader_loop, daemon=True, name="exiftool-reader",
        )
        self._reader_thread.start()

    def _ensure_alive(self) -> None:
        """Respawn exiftool if the process is dead. Call under self._lock."""
        if self._proc is None or self._proc.poll() is not None:
            log.warning("exiftool process not alive — respawning")
            self._spawn()

    def _readline_with_timeout(self, timeout: float) -> str | None:
        """Return next line from reader thread's queue, or None on timeout,
        '' on EOF."""
        try:
            item = self._output_queue.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is self._EOF:
            return ""
        return item

    def _run_batch(self, args: list[str]) -> tuple[bool, str]:
        """Feed args + -execute, read output until {ready}. Returns (ok, output)."""
        # The -stay_open -@ - protocol uses newline as arg separator; any arg
        # containing \n / \r / NUL would corrupt the session for every
        # subsequent write. Reject at the gate instead of silently breaking.
        for arg in args:
            if any(c in arg for c in self._UNSAFE_CHARS):
                log.error("Rejecting exiftool arg with unsafe chars: %r", arg)
                return False, "unsafe arg"

        with self._lock:
            # Ensure the session is alive before writing — previous stall/
            # kill or OS-level kill leaves self._proc terminated, and every
            # subsequent write would otherwise BrokenPipe forever. Respawn
            # once and retry; if the respawn itself fails, bail cleanly.
            self._ensure_alive()
            try:
                for arg in args:
                    self._proc.stdin.write(arg + "\n")
                self._proc.stdin.write("-execute\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, ValueError, OSError) as e:
                # Pipe died between _ensure_alive and flush — try one respawn.
                log.warning("exiftool stdin died (%s), respawning once", e)
                self._ensure_alive()
                try:
                    for arg in args:
                        self._proc.stdin.write(arg + "\n")
                    self._proc.stdin.write("-execute\n")
                    self._proc.stdin.flush()
                except (BrokenPipeError, ValueError, OSError) as e2:
                    return False, f"exiftool process died (after respawn): {e2}"

            output_lines = []
            while True:
                line = self._readline_with_timeout(EXIFTOOL_READ_TIMEOUT_SEC)
                if line is None:
                    log.error("exiftool unresponsive after %.1fs, killing; next call will respawn",
                              EXIFTOOL_READ_TIMEOUT_SEC)
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                    # Mark dead so the NEXT _run_batch call triggers _ensure_alive
                    # respawn rather than returning False forever.
                    self._proc = None
                    return False, "exiftool read timeout"
                if not line:
                    # EOF — process died mid-write. Mark so next call respawns.
                    self._proc = None
                    return False, "".join(output_lines)
                if line.strip() == "{ready}":
                    break
                output_lines.append(line)

        output = "".join(output_lines)
        # Only treat lines starting with "Error" as failures. A case-insensitive
        # substring match would false-positive on tag values like a caption that
        # contains "error" or filenames like "error_log.jpg".
        ok = not any(line.lstrip().startswith("Error") for line in output.splitlines())
        return ok, output

    def write(self, photo_path: str, args: list[str]) -> bool:
        """Run exiftool args against photo_path. Returns True on success."""
        ok, output = self._run_batch(args + [photo_path])
        if not ok:
            log.error("exiftool batch write failed for %s: %s", photo_path, output.strip())
        return ok

    def read_json(self, photo_path: str, tags: list[str] | None = None) -> dict:
        """Read metadata as JSON. Returns {} on failure."""
        args = ["-j"]
        if tags:
            args.extend(tags)
        args.append(photo_path)
        ok, output = self._run_batch(args)
        if not ok:
            return {}
        try:
            data = json.loads(output)
            return data[0] if isinstance(data, list) and data else {}
        except (json.JSONDecodeError, IndexError):
            return {}

    def close(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.stdin.write("-stay_open\nFalse\n")
                    self._proc.stdin.flush()
                except (BrokenPipeError, ValueError):
                    pass
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
