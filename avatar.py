"""Indexed operator artwork rendered as Sixel or theme-colored Unicode half blocks."""

from functools import lru_cache
from itertools import groupby
from pathlib import Path


ASSETS = Path(__file__).with_name("assets")
PORTRAITS = tuple(
    tuple(tuple(int(pixel, 36) for pixel in row) for row in (ASSETS / name).read_text().splitlines())
    for name in ("rook.pixels", "rook-uplink.pixels")
)


ART_COLORS = (ASSETS / "rook.palette").read_text().splitlines()


def portrait_palette(theme):
    """Tint the matte. Keep skin, hair, and low-contrast artwork colors authored."""
    scanline = "".join(
        f"{(3 * int(theme.panel[i:i + 2], 16) + int(theme.shadow[i:i + 2], 16)) // 4:02x}"
        for i in (0, 2, 4)
    )
    return (theme.panel, *ART_COLORS[1:], theme.shadow, scanline)


def half_blocks(stage, max_columns, rows):
    """Yield centered color pairs with a roughly square physical sampling grid."""
    sprite = PORTRAITS[stage]
    if rows <= 12:
        # Spend the smallest viewports on the face and headset.
        sprite = tuple(row[8:-8] for row in sprite[:90])
    height, width = len(sprite), len(sprite[0])
    columns = min(max_columns, round(rows * 2.4 * width / height))
    art_rows = max(1, min(rows, round(columns * height / (2.4 * width))))
    pad = (rows - art_rows) // 2
    for _ in range(pad):
        yield ((0, 0),) * columns
    for y in range(art_rows):
        upper = sprite[(4 * y + 1) * height // (4 * art_rows)]
        lower = sprite[(4 * y + 3) * height // (4 * art_rows)]
        yield tuple(
            (upper[x], lower[x])
            for i in range(columns)
            for x in ((2 * i + 1) * width // (2 * columns),)
        )


@lru_cache(maxsize=12)
def sixel(stage, palette, cell, columns, rows):
    """Center nearest-neighbor art on a cell-aligned matte."""
    sprite = PORTRAITS[stage]
    source_h, source_w = len(sprite), len(sprite[0])
    width = columns * cell[0]
    height = rows * cell[1] // 6 * 6
    if not height or width * height > 400_000:
        return ""

    # Keep the art large even where a whole-number scale would leave a wide matte.
    scale = min((width - 2) / source_w, height / source_h)
    art_w = max(1, int(source_w * scale))
    art_h = max(1, int(source_h * scale))
    left = (width - art_w) // 2
    top = (height - art_h) // 2
    blank = bytes(width)
    stripe = bytes([len(palette) - 1]) * width
    raster = [stripe if y % 8 == 0 else blank for y in range(height)]
    # A crescent and stippled skyline sit behind the transparent artwork.
    radius = min(width, height) // 7
    for y in range(height):
        background = bytearray(raster[y])
        for x in range(width):
            inside = (x - radius) ** 2 + (y - radius) ** 2 < radius ** 2
            cutout = (x - radius - radius // 3) ** 2 + (y - radius + radius // 4) ** 2 < radius ** 2
            skyline = y > 3 * height // 5 and (x + 2 * y) % 13 == 0
            if inside and not cutout:
                background[x] = len(palette) - 1 if (x + y) % 3 == 0 else len(palette) - 2
            elif skyline:
                background[x] = len(palette) - 1
        raster[y] = bytes(background)
    x_samples = [x * source_w // art_w for x in range(art_w)]
    for y in range(art_h):
        source = sprite[y * source_h // art_h]
        backdrop = raster[top + y]
        art = bytes(source[x] or backdrop[left + i] for i, x in enumerate(x_samples))
        raster[top + y] = backdrop[:left] + art + backdrop[left + art_w:]

    output = [f'\x1bP0;1q"1;1;{width};{height}']
    for index, color in enumerate(palette):
        rgb = [round(int(color[i:i + 2], 16) * 100 / 255) for i in (0, 2, 4)]
        output.append(f"#{index};2;" + ";".join(map(str, rgb)))

    for y in range(0, height, 6):
        stripes = [bytearray(width) for _ in palette]
        for bit, scanline in enumerate(raster[y:y + 6]):
            for x, index in enumerate(scanline):
                stripes[index][x] |= 1 << bit
        for index, stripe in enumerate(stripes):
            if not any(stripe):
                continue
            output.append(f"#{index}")
            for value, run in groupby(stripe.rstrip(b"\0")):
                count = sum(1 for _ in run)
                glyph = chr(value + 63)
                output.append(f"!{count}{glyph}" if count > 3 else glyph * count)
            output.append("$")
        if y + 6 < height:
            output.append("-")
    output.append("\x1b\\")
    return "".join(output)
