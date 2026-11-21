"""Indexed operator artwork rendered as Sixel or theme-colored Unicode half blocks."""

from functools import lru_cache
from itertools import groupby
from pathlib import Path


ASSETS = Path(__file__).with_name("assets")
OPERATORS = ("Rook", "Relay")
FIRST_LEVEL = 7
STAGE_SPECS = (
    ("Field", FIRST_LEVEL, ""),
    ("Uplink", FIRST_LEVEL + 1, "-uplink"),
    ("Vanguard", FIRST_LEVEL + 2, "-vanguard"),
    ("Sentinel", FIRST_LEVEL + 3, "-sentinel"),
)
STAGES = tuple(name for name, _, _ in STAGE_SPECS)
ART_COLORS = (ASSETS / "rook.palette").read_text().splitlines()
WIDTH, HEIGHT = 104, 106


def stage_for_level(level):
    return max((index for index, (_, minimum, _) in enumerate(STAGE_SPECS)
                if level >= minimum), default=0)


def valid_index(value, options):
    return type(value) is int and 0 <= value < len(options)


def asset_path(operator, stage):
    return ASSETS / f"{OPERATORS[operator].lower()}{STAGE_SPECS[stage][2]}.pixels"


def load_portrait(path):
    try:
        rows = path.read_text().splitlines()
        if len(rows) == HEIGHT and all(len(row) == WIDTH for row in rows):
            sprite = tuple(tuple(int(pixel, 36) for pixel in row) for row in rows)
            if all(max(row) < len(ART_COLORS) for row in sprite) and any(map(any, sprite)):
                return sprite
    except (OSError, ValueError):
        pass
    return None


def load_portraits():
    sprites = tuple(tuple(load_portrait(asset_path(operator, stage)) for stage in range(len(STAGES)))
                    for operator in range(len(OPERATORS)))
    # Keep the selected identity if its stage file is missing. If its base is
    # also missing, use its first surviving stage or leave the matte empty.
    blank = ((0,) * WIDTH,) * HEIGHT
    return tuple(tuple(sprite or next((item for item in stages if item), blank)
                       for sprite in stages) for stages in sprites)


PORTRAITS = load_portraits()


def portrait(stage, operator=0):
    operator = operator if valid_index(operator, OPERATORS) else 0
    stage = stage if valid_index(stage, STAGES) else 0
    sprite = PORTRAITS[operator][stage]
    # Align the eye lines without moving features within either portrait.
    padding = ((0,) * WIDTH,) * 4
    return padding + sprite if operator == 1 else sprite + padding


def portrait_palette(theme):
    """Tint the matte. Keep skin, hair, and low-contrast artwork colors authored."""
    scanline = "".join(
        f"{(3 * int(theme.panel[i:i + 2], 16) + int(theme.shadow[i:i + 2], 16)) // 4:02x}"
        for i in (0, 2, 4)
    )
    return (theme.panel, *ART_COLORS[1:], theme.shadow, scanline)


def half_blocks(stage, max_columns, rows, operator=0):
    """Yield centered color pairs with a roughly square physical sampling grid."""
    if max_columns <= 0 or rows <= 0:
        return
    sprite = portrait(stage, operator)
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
    for _ in range(rows - art_rows - pad):
        yield ((0, 0),) * columns


@lru_cache(maxsize=12)
def sixel(stage, palette, cell, columns, rows, operator=0):
    """Center nearest-neighbor art on a cell-aligned matte."""
    sprite = portrait(stage, operator)
    source_h, source_w = len(sprite), len(sprite[0])
    width = columns * cell[0]
    height = rows * cell[1] // 6 * 6
    if width < 3 or height <= 0 or width * height > 400_000:
        return ""

    scale = min((width - 2) / source_w, height / source_h)
    integer_scale = int(scale)
    if integer_scale and integer_scale >= 0.85 * scale:
        scale = integer_scale
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
