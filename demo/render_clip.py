from __future__ import annotations

import re
import subprocess
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
PROXY = ROOT / "packages" / "proxy"
OUTPUT = ROOT / "demo" / "artifacts" / "bouncer-demo.mp4"
FONT_PATH = Path("/System/Library/Fonts/SFNSMono.ttf")


def capture_demo() -> list[str]:
    completed = subprocess.run(
        [
            "node",
            "--import",
            "tsx",
            str(ROOT / "demo" / "run-counterfactual.ts"),
            "--offline",
            "--no-color",
        ],
        cwd=PROXY,
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stderr:
        raise RuntimeError(completed.stderr)
    lines: list[str] = []
    for raw_line in completed.stdout.splitlines():
        line = re.sub(r"\x1b\[[0-9;]*m", "", raw_line)
        if not line:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(line, width=102, subsequent_indent="    ", replace_whitespace=False))
    return lines


def line_color(line: str) -> tuple[int, int, int]:
    if "BOUNCER OFF" in line or "BOUNCER ON" in line or "DECISION TRACE" in line:
        return (77, 208, 225)
    if "[HARM]" in line:
        return (255, 92, 92)
    if "[BLOCKED]" in line or line.startswith("ALLOW"):
        return (91, 220, 142)
    if "[COMPLETE]" in line:
        return (255, 206, 84)
    if line.startswith("BLOCK"):
        return (255, 120, 120)
    if line.startswith("Goal:") or line.startswith("          "):
        return (151, 163, 184)
    return (226, 232, 240)


def render_frame(lines: list[str], visible: int, path: Path) -> None:
    width, height = 1440, 900
    image = Image.new("RGB", (width, height), (6, 10, 22))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((35, 35, width - 35, height - 35), radius=24, fill=(12, 19, 36), outline=(45, 61, 91), width=2)
    draw.ellipse((65, 62, 81, 78), fill=(255, 95, 86))
    draw.ellipse((91, 62, 107, 78), fill=(255, 189, 46))
    draw.ellipse((117, 62, 133, 78), fill=(39, 201, 63))
    title_font = ImageFont.truetype(str(FONT_PATH), 24)
    body_font = ImageFont.truetype(str(FONT_PATH), 21)
    draw.text((170, 55), "Bouncer · counterfactual MCP replay", font=title_font, fill=(196, 210, 232))

    shown = lines[:visible]
    max_lines = 29
    viewport = shown[-max_lines:]
    on_index = next((index for index, line in enumerate(viewport) if "BOUNCER ON" in line), None)
    if on_index is not None:
        viewport = viewport[on_index:]
    y = 105
    for line in viewport:
        safe_line = line[:104]
        draw.text((70, y), safe_line, font=body_font, fill=line_color(line))
        y += 25
    image.save(path, optimize=True)


def main() -> None:
    lines = capture_demo()
    fps = 12
    hold_frames = 24
    reveal_frames = 5
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="bouncer-frames-") as temp:
        frame_dir = Path(temp)
        frame_number = 0
        for visible in range(1, len(lines) + 1):
            for _ in range(reveal_frames):
                render_frame(lines, visible, frame_dir / f"frame_{frame_number:04d}.png")
                frame_number += 1
        for _ in range(hold_frames):
            render_frame(lines, len(lines), frame_dir / f"frame_{frame_number:04d}.png")
            frame_number += 1

        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-framerate",
                str(fps),
                "-i",
                str(frame_dir / "frame_%04d.png"),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-g",
                str(fps),
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(OUTPUT),
            ],
            check=True,
        )
    print(OUTPUT)


if __name__ == "__main__":
    main()
