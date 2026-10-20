"""Assemble the demo: voice track placed on the scene marks, burned-in subtitles, MP4 (H.264 + AAC).

Usage: python build.py --ffmpeg <path\\to\\ffmpeg.exe> [--out-dir out-1920x1080] [--output <file.mp4>]
Inputs: <out-dir>/timeline.json and frames/ (record.mjs), audio/s1..s7.wav (tts.ps1), script.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import wave
from pathlib import Path

DIR = Path(__file__).resolve().parent


def ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def split_sentences(text: str, max_len: int) -> list[str]:
    parts = re.split(r"(?<=[.?!])\s+", text.strip())
    out: list[str] = []
    for p in parts:  # long sentences: split once more on ", " near the middle
        if len(p) > max_len and ", " in p:
            cut = min((m.start() for m in re.finditer(", ", p)), key=lambda i: abs(i - len(p) / 2))
            out += [p[: cut + 1], p[cut + 2 :]]
        else:
            out.append(p)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ffmpeg", required=True)
    ap.add_argument("--out-dir", default="out-1920x1080")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    out_dir = DIR / args.out_dir
    tl = json.loads((out_dir / "timeline.json").read_text(encoding="utf-8"))
    width, height = tl.get("size", [1920, 1080])
    output = Path(args.output) if args.output else out_dir / f"fedis-planner-demo-{width}x{height}.mp4"
    script = {s["id"]: s["text"] for s in json.loads((DIR / "script.json").read_text(encoding="utf-8"))}
    frames, marks = tl["frames"], tl["marks"]
    t0, t_end = frames[0]["t"], marks[-1]["start"]
    total = t_end - t0

    # ---- video: concat demuxer with real frame durations (screencast frames arrive only on repaint)
    lines = ["ffconcat version 1.0"]
    for i, f in enumerate(frames):
        nxt = frames[i + 1]["t"] if i + 1 < len(frames) else t_end
        lines += [f"file 'frames/{f['file']}'", f"duration {max(0.001, nxt - f['t']):.4f}"]
    lines.append(f"file 'frames/{frames[-1]['file']}'")
    (out_dir / "frames.ffconcat").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- audio: each clip at its scene's voice mark
    clips = [(m["voice"], m["voiceStart"] - t0) for m in marks if m.get("voice")]
    params, track = None, bytearray()
    for vid, start in clips:
        with wave.open(str(DIR / "audio" / f"{vid}.wav"), "rb") as w:
            if params is None:
                params = w.getparams()
                track = bytearray(int(total * params.framerate) * params.sampwidth * params.nchannels)
            data = w.readframes(w.getnframes())
        off = int(start * params.framerate) * params.sampwidth * params.nchannels
        end = min(len(track), off + len(data))
        track[off:end] = data[: end - off]
    with wave.open(str(out_dir / "voice.wav"), "wb") as w:
        w.setparams(params)
        w.writeframes(bytes(track))

    # ---- subtitles (ASS): sentences of each clip, timed by character share of the clip duration
    portrait = width < height
    events = []
    for vid, start in clips:
        dur = tl["voice"][vid]
        chunks = split_sentences(script[vid], 60 if portrait else 95)
        total_chars = sum(len(c) for c in chunks)
        t = start
        for c in chunks:
            d = dur * len(c) / total_chars
            events.append(f"Dialogue: 0,{ass_time(t)},{ass_time(t + d + 0.15)},Sub,,0,0,0,,{c}")
            t += d
    margin_lr, margin_v = (70, 110) if portrait else (220, 70)
    ass = "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        # white text on a translucent deep-green box (app palette)
        f"Style: Sub,Segoe UI Semibold,46,&H00FFFFFF,&H00FFFFFF,&H5A2E3316,&H5A2E3316,0,0,0,0,100,100,0,0,3,14,0,2,"
        f"{margin_lr},{margin_lr},{margin_v},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text", *events, "",
    ])
    (out_dir / "subs.ass").write_text(ass, encoding="utf-8-sig")

    cmd = [
        args.ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-stats",
        "-f", "concat", "-safe", "0", "-i", "frames.ffconcat",
        "-i", "voice.wav",
        "-vf", f"fps=30,scale={width}:{height}:flags=lanczos,format=yuv420p,subtitles=subs.ass",
        "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-profile:v", "high", "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        "-shortest", str(output),
    ]
    print(f"{width}x{height}: {total:.1f} s, {len(frames)} frames, {len(events)} subtitle lines")
    subprocess.run(cmd, cwd=out_dir, check=True)
    print("written", output)


if __name__ == "__main__":
    main()
