"""Build Relay's four indexed sprites from the generated Rook-style render."""

from pathlib import Path

from PIL import Image

from avatar import ART_COLORS, HEIGHT, WIDTH, asset_path


SOURCE = Path(__file__).with_name("source") / "relay-rook-style.png"
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
ALPHA_CUTOFF = 180


def indexed_base():
    with Image.open(SOURCE) as source:
        mask = source.getchannel("A").point(lambda alpha: 255 if alpha >= ALPHA_CUTOFF else 0)
        art = source.crop(mask.getbbox()).resize((96, 98), Image.Resampling.NEAREST)
    palette = [tuple(bytes.fromhex(color)) for color in ART_COLORS]
    rows = [["0"] * WIDTH for _ in range(HEIGHT)]
    for y in range(art.height):
        for x in range(art.width):
            red, green, blue, alpha = art.getpixel((x, y))
            if alpha >= ALPHA_CUTOFF:
                rgb = (red, green, blue)
                color = min(range(1, len(palette)),
                            key=lambda i: sum((a - b) ** 2 for a, b in zip(rgb, palette[i])))
                rows[y][x + 4] = DIGITS[color]
    return rows


def fit_uniform(base, stage):
    """Fit the shared operator jacket around Relay's own collar and zipper."""
    rows = [row.copy() for row in base]
    reference = asset_path(0, stage).read_text().splitlines()
    # Relay is placed four rows lower by the renderer. Align the shared
    # shoulder pieces in display coordinates, including on the Field sprite.
    for y in range(77, HEIGHT - 4):
        jacket = reference[y + 4]
        rows[y][:34] = jacket[:34]
        rows[y][74:] = jacket[74:]
    rows[98][34:74] = rows[97][34:74]
    return rows


def upgrade(rows, stage):
    rows[43][35:38] = list("dcd")
    rows[44][35:38] = list("pqc" if stage == 1 else "qqp")
    if stage >= 2:
        rows[45][35:38] = list("occ")
        rank = "pqq1pqq" if stage == 2 else "jkl1jkl1jkl"
        edge = len(rank) + 2
        x, y = 55, 76
        rows[y][x:x + edge] = list("c" * edge)
        rows[y + 1][x:x + edge] = list("1" + rank + "1")
        rows[y + 2][x:x + edge] = list("1" + rank + "1")
        rows[y + 3][x:x + edge] = list("1" * edge)


def main():
    base = indexed_base()
    for stage in range(4):
        rows = fit_uniform(base, stage)
        if stage:
            upgrade(rows, stage)
        asset_path(1, stage).write_text("".join("".join(row) + "\n" for row in rows))


if __name__ == "__main__":
    main()
