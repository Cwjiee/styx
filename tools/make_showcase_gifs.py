#!/usr/bin/env python3
"""Render the README showcase GIFs from ``spritesheet.webp``.

Two assets are produced in ``assets/``:

* ``styx-walk.gif``   - the sprite actually travelling across a wide banner
* ``styx-states.gif`` - all nine animation rows playing side by side, labelled

The v2 atlas is an 8 column x 11 row grid of 192x208 frames. Rows 0-8 are the
nine animation states; rows 9-10 are the v2 look-direction rows and are not
part of the state showcase.

Frame extraction mirrors ``agent/pet/render.py``: rows are left-packed, so a
row's real frame count is the number of leading cells that are not fully
transparent.

Usage:  python3 tools/make_showcase_gifs.py
"""

from __future__ import annotations

import math
import random
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "spritesheet.webp"
WORK = ROOT / "tools" / ".frames"
OUT = ROOT / "assets"

FRAME_W, FRAME_H = 192, 208
BLANK_ALPHA = 8

# Row index -> state name (rows 0-8 of the v2 atlas).
STATE_ROWS = [
    ("idle", "stands and breathes"),
    ("running-right", "travels right"),
    ("running-left", "travels left"),
    ("waving", "waves"),
    ("jumping", "leaps"),
    ("failed", "deflates"),
    ("waiting", "sits and waits"),
    ("running", "works in place"),
    ("review", "reviews"),
]
# Every row's art is drawn facing right (muzzle right of the eye, tail plume to
# the left), which is also the direction `running-right` travels — so the walk
# banner uses the strip unmirrored.

BG_TOP = (14, 12, 20)
BG_BOTTOM = (30, 23, 30)
EMBER = (255, 138, 46)
LABEL = (236, 231, 226)
DIM = (150, 141, 154)
AMBER = (240, 166, 74)
PANEL = (26, 22, 32)
PANEL_EDGE = (48, 41, 58)

FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_MONO = "/System/Library/Fonts/Menlo.ttc"


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.truetype(path, size, index=0)


def load_rows() -> dict[str, list[Image.Image]]:
    """Every animation row -> its non-blank frames (RGBA, full 192x208 cell)."""
    sheet = Image.open(SHEET).convert("RGBA")
    cols, rows = sheet.width // FRAME_W, sheet.height // FRAME_H
    out: dict[str, list[Image.Image]] = {}
    for row_idx, (name, _blurb) in enumerate(STATE_ROWS):
        top = row_idx * FRAME_H
        frames: list[Image.Image] = []
        for col in range(cols):
            cell = sheet.crop((col * FRAME_W, top, (col + 1) * FRAME_W, top + FRAME_H))
            if cell.getchannel("A").getextrema()[1] <= BLANK_ALPHA:
                break
            frames.append(cell)
        if not frames:
            raise SystemExit(f"row {row_idx} ({name}) is empty — wrong atlas?")
        out[name] = frames
    return out


def gradient(
    size: tuple[int, int], *, ground: float | None = None, band: float = 0.0, band_sigma: int = 88, seed: int = 11
) -> Image.Image:
    """Vertical gradient + warm ground haze + fine noise.

    The noise matters: an 8-bit GIF palette bands badly on a smooth dark ramp,
    and a few levels of dither kill the visible steps.
    """
    w, h = size
    img = Image.new("RGB", (w, h))
    px = img.load()
    rnd = random.Random(seed)
    ground = h * 0.94 if ground is None else ground
    sigma = max(1.0, float(band_sigma))
    for y in range(h):
        t = y / max(1, h - 1)
        base = [round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)]
        # flat horizontal haze hugging the ground line (reads as ember light, not a blob)
        haze = math.exp(-(((y - ground) / sigma) ** 2)) * band
        for x in range(w):
            n = rnd.uniform(-2.5, 2.5)
            px[x, y] = tuple(
                max(0, min(255, round(c + boost + n))) for c, boost in zip(base, (haze, haze * 0.34, haze * 0.08))
            )
    return img


def sprinkle_embers(img: Image.Image, *, seed: int = 7, count: int = 90) -> None:
    """Static warm specks (identical every frame, so they cost nothing in the GIF)."""
    rnd = random.Random(seed)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    w, h = img.size
    for _ in range(count):
        x = rnd.uniform(0, w)
        y = rnd.uniform(h * 0.35, h)
        r = rnd.uniform(0.6, 1.9)
        a = int(rnd.uniform(30, 130) * (y / h))
        draw.ellipse((x - r, y - r, x + r, y + r), fill=EMBER + (a,))
    layer = layer.filter(ImageFilter.GaussianBlur(0.7))
    img.alpha_composite(layer) if img.mode == "RGBA" else img.paste(layer, (0, 0), layer)


def shadow(size: tuple[int, int], *, w: int, h: int) -> Image.Image:
    """Blurred ellipse used as the ground contact shadow."""
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse(((size[0] - w) / 2, (size[1] - h) / 2, (size[0] + w) / 2, (size[1] + h) / 2), fill=150)
    return mask.filter(ImageFilter.GaussianBlur(6))


def scale_frame(frame: Image.Image, scale: float) -> Image.Image:
    return frame.resize((max(1, round(FRAME_W * scale)), max(1, round(FRAME_H * scale))), Image.LANCZOS)


def draw_sprite(canvas: Image.Image, sprite: Image.Image, cx: float, bottom: float) -> None:
    """Drop *sprite* so its feet sit on *bottom* at horizontal centre *cx*."""
    x = round(cx - sprite.width / 2)
    y = round(bottom - sprite.height)
    canvas.alpha_composite(sprite, (x, y))


def build_walk(rows: dict[str, list[Image.Image]]) -> list[Image.Image]:
    W, H = 680, 210
    GROUND = 176
    SCALE = 0.72
    START, END = -150.0, float(W + 30)
    N = 56

    strip = [scale_frame(f, SCALE) for f in rows["running-right"]]
    sh_mask = shadow((int(strip[0].width * 0.9), 20), w=int(strip[0].width * 0.78), h=14)

    bg = gradient((W, H), ground=GROUND + 8, band=24, band_sigma=26).convert("RGBA")
    sprinkle_embers(bg)
    frames: list[Image.Image] = []
    for i in range(N):
        canvas = bg.copy()
        x = START + (END - START) * i / N
        sprite = strip[i % len(strip)]
        sx = round(x - sh_mask.width / 2)
        sy = GROUND - sh_mask.height // 2
        canvas.paste((0, 0, 0, 255), (sx, sy), sh_mask)
        draw_sprite(canvas, sprite, x, GROUND)
        frames.append(canvas)  # RGB(A) on purpose: ImageMagick owns the palette + dithering
    return frames


def build_states(rows: dict[str, list[Image.Image]]) -> list[Image.Image]:
    PAD, GAP, HEADER = 14, 12, 58
    CW, CH = 156, 170
    SCALE = 0.6
    N = 24

    W = PAD * 2 + CW * 3 + GAP * 2
    H = HEADER + PAD + CH * 3 + GAP * 2
    bg = gradient((W, H), band=26).convert("RGBA")

    title_f, sub_f = font(FONT_BOLD, 26), font(FONT_REGULAR, 13)
    label_f, meta_f = font(FONT_BOLD, 13), font(FONT_MONO, 11)
    LABEL_BAND = 52  # reserved for the two label lines, so no sprite can cover them

    base = bg.copy()  # static chrome: header + panels, drawn once
    draw = ImageDraw.Draw(base)
    draw.text((PAD + 2, 14), "Styx", font=title_f, fill=LABEL)
    draw.text((PAD + 3, 44), "an infernal Underworld hound-whelp · nine animation states", font=sub_f, fill=DIM)
    for idx in range(9):
        col, row = idx % 3, idx // 3
        x0 = PAD + col * (CW + GAP)
        y0 = HEADER + PAD // 2 + row * (CH + GAP)
        draw.rounded_rectangle((x0, y0, x0 + CW, y0 + CH), radius=8, fill=PANEL, outline=PANEL_EDGE)
        name, blurb = STATE_ROWS[idx]
        cx = x0 + CW / 2
        draw.text((cx, y0 + CH - 34), name, font=label_f, fill=LABEL, anchor="mm")
        draw.text((cx, y0 + CH - 16), f"{blurb} · {len(rows[name])}f", font=meta_f, fill=DIM, anchor="mm")

    frames: list[Image.Image] = []
    for i in range(N):
        canvas = base.copy()
        for idx in range(9):
            name, _blurb = STATE_ROWS[idx]
            strip = rows[name]
            col, row = idx % 3, idx // 3
            x0 = PAD + col * (CW + GAP)
            y0 = HEADER + PAD // 2 + row * (CH + GAP)
            sprite = scale_frame(strip[(i * len(strip)) // N], SCALE)
            cx = x0 + CW / 2
            feet = y0 + CH - LABEL_BAND
            sh = shadow((int(sprite.width * 0.9), 18), w=int(sprite.width * 0.72), h=12)
            canvas.paste((0, 0, 0, 255), (round(cx - sh.width / 2), round(feet - sh.height / 2)), sh)
            draw_sprite(canvas, sprite, cx, feet)
        frames.append(canvas)  # RGB(A) on purpose: ImageMagick owns the palette + dithering
    return frames


def global_palette(frames: list[Image.Image]) -> Image.Image:
    """255-colour palette median-cut from *every* frame stacked together.

    ImageMagick's own quantizer crushes this artwork to ~30 colours (its
    `-remap` also skips dithering here), which posterizes the night-sky ramp into
    visible bands; Pillow's median cut + Floyd-Steinberg keeps the ramp smooth.
    """
    rgb = [f.convert("RGB") for f in frames]
    stack = Image.new("RGB", (max(f.width for f in rgb), sum(f.height for f in rgb)))
    for i, frame in enumerate(rgb):
        stack.paste(frame, (0, i * frame.height))
    return stack.quantize(colors=255, method=Image.MEDIANCUT)


def assemble(frames: list[Image.Image], out: Path, *, delay_ms: int) -> None:
    """Quantize the sequence against one shared palette, then let ImageMagick build delta frames.

    ``-layers OptimizeFrame`` (not ``Optimize``) matters: ``Optimize`` re-quantizes
    the palette away, which is what we just spent a median cut avoiding.
    """
    frame_dir = WORK / out.stem
    if frame_dir.exists():
        for stale in frame_dir.glob("*.png"):
            stale.unlink()
    frame_dir.mkdir(parents=True, exist_ok=True)
    pal = global_palette(frames)
    for i, frame in enumerate(frames):
        frame.convert("RGB").quantize(palette=pal, dither=Image.FLOYDSTEINBERG).save(frame_dir / f"f{i:04d}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "magick", "-delay", str(delay_ms),
            *(str(p) for p in sorted(frame_dir.glob("*.png"))),
            "-loop", "0", "-layers", "OptimizeFrame", str(out),
        ],
        check=True,
    )
    print(f"{out.relative_to(ROOT)}: {len(frames)} frames, {out.stat().st_size / 1024:.0f} KB")


def main() -> None:
    rows = load_rows()
    for name, strip in rows.items():
        print(f"{name:<15} {len(strip)} frames")
    if not shutil_which("magick"):
        raise SystemExit("ImageMagick 'magick' not found on PATH")
    WORK.mkdir(parents=True, exist_ok=True)
    assemble(build_walk(rows), OUT / "styx-walk.gif", delay_ms=8)
    assemble(build_states(rows), OUT / "styx-states.gif", delay_ms=7)


def shutil_which(cmd: str) -> str | None:
    from shutil import which

    return which(cmd)


if __name__ == "__main__":
    sys.exit(main())
