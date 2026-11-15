from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

from .. import config


async def _run(cmd: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _, err = await proc.communicate()
    return proc.returncode, err.decode(errors="ignore")


async def probe(path: str) -> dict:
    rc, err = await _run([config.FFMPEG_BIN, "-hide_banner", "-i", path])
    dur = re.search(r"Duration: (\d+):(\d+):(\d+\.?\d*)", err)
    size = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", err)
    fps = re.search(r"(\d+(?:\.\d+)?) fps", err)
    seconds = None
    if dur:
        h, m, s = dur.groups()
        seconds = int(h) * 3600 + int(m) * 60 + float(s)
    return {
        "duration": seconds,
        "width": int(size.group(1)) if size else None,
        "height": int(size.group(2)) if size else None,
        "fps": float(fps.group(1)) if fps else None,
        "has_audio": "Audio:" in err,
    }


async def extract_frame(video: str, out: str, last: bool = True) -> str:
    cmd = [config.FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error"]
    if last:
        cmd += ["-sseof", "-0.25"]
    else:
        cmd += ["-ss", "0.05"]
    cmd += ["-i", video, "-frames:v", "1", "-q:v", "2", out]
    rc, err = await _run(cmd)
    if rc != 0 or not Path(out).is_file():
        raise RuntimeError("ffmpeg frame extraction failed: " + err[-300:])
    return out


async def concat(videos: list[str], out: str) -> dict:
    """Normalise every clip to one size/fps and concatenate with audio."""
    if not videos:
        raise ValueError("no videos")
    infos = [await probe(v) for v in videos]
    w = max(i["width"] or 1280 for i in infos)
    h = max(i["height"] or 720 for i in infos)
    fps = infos[0]["fps"] or 24
    with_audio = all(i["has_audio"] for i in infos)

    cmd = [config.FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error"]
    for v in videos:
        cmd += ["-i", v]
    parts, labels = [], []
    for idx, info in enumerate(infos):
        parts.append(
            f"[{idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{idx}]"
        )
        labels.append(f"[v{idx}]")
        if with_audio:
            parts.append(f"[{idx}:a]aresample=48000[a{idx}]")
            labels.append(f"[a{idx}]")
    parts.append("".join(labels) + f"concat=n={len(videos)}:v=1:a={1 if with_audio else 0}[v]" + ("[a]" if with_audio else ""))
    cmd += ["-filter_complex", ";".join(parts), "-map", "[v]"]
    if with_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-movflags", "+faststart", out]
    rc, err = await _run(cmd)
    if rc != 0 or not Path(out).is_file():
        raise RuntimeError("ffmpeg concat failed: " + err[-500:])
    return {"width": w, "height": h, "fps": fps, "clips": len(videos), "audio": with_audio}
