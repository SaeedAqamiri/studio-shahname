from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from .. import config
from .video import probe


async def _run(cmd: list[str]) -> tuple[int, str]:
    p = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _, err = await p.communicate()
    return p.returncode, err.decode(errors="ignore")


async def duration(path: str) -> float:
    rc, err = await _run([config.FFMPEG_BIN, "-hide_banner", "-i", path])
    import re
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.?\d*)", err)
    if not m:
        return 0.0
    h, mm, s = m.groups()
    return int(h) * 3600 + int(mm) * 60 + float(s)


async def silence(seconds: float, out: str) -> str:
    rc, err = await _run([config.FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error",
                          "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{seconds:.3f}", out])
    if rc != 0:
        raise RuntimeError("silence failed: " + err[-200:])
    return out


async def concat_audio(files: list[str], out: str, gap: float = 0.3) -> str:
    import tempfile
    sil = out + ".sil.wav"
    await silence(gap, sil)
    lines = []
    for i, f in enumerate(files):
        lines.append(f"file '{Path(f).as_posix()}'")
        if i < len(files) - 1:
            lines.append(f"file '{Path(sil).as_posix()}'")
    lst = out + ".txt"
    Path(lst).write_text("\n".join(lines))
    rc, err = await _run([config.FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error",
                          "-f", "concat", "-safe", "0", "-i", lst, "-ar", "24000", "-ac", "1", out])
    Path(sil).unlink(missing_ok=True)
    Path(lst).unlink(missing_ok=True)
    if rc != 0:
        raise RuntimeError("audio concat failed: " + err[-300:])
    return out


async def dub_video(video: str, narration: str, out: str, duck: float = 0.22) -> str:
    vdur = await duration(video)
    ndur = await duration(narration)
    pad = max(0.0, ndur - vdur + 0.4)
    target = max(vdur + pad, ndur + 0.4)
    info = await probe(video)
    if info.get("has_audio"):
        bg = f"[0:a]volume={duck},apad=whole_dur={target:.3f}[bg];"
    else:
        bg = f"anullsrc=r=48000:cl=stereo,atrim=duration={target:.3f}[bg];"
    filters = (
        f"[0:v]tpad=stop_mode=clone:stop_duration={pad:.3f}[v];"
        + bg +
        f"[1:a]adelay=120|120,apad=whole_dur={target:.3f}[nar];"
        f"[bg][nar]amix=inputs=2:duration=longest:dropout_transition=0[a]"
    )
    rc, err = await _run([config.FFMPEG_BIN, "-y", "-hide_banner", "-loglevel", "error",
                          "-i", video, "-i", narration, "-filter_complex", filters,
                          "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
                          "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                          "-t", f"{target:.3f}", out])
    if rc != 0:
        raise RuntimeError("dub failed: " + err[-400:])
    return out
