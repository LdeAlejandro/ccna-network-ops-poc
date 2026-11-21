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


def upgrade(base, stage):
    rows = [row.copy() for row in base]
    # Build the shoulder plates along the baseline jacket's magenta piping.
    for x in range(WIDTH):
        stripe = [y for y in range(82, HEIGHT) if base[y][x] == "8"]
        if not stripe:
            continue
        top, bottom = stripe[0], stripe[-1]
        for y in range(top - 1, min(bottom + 2, HEIGHT)):
            if base[y][x] != "0":
                rows[y][x] = "c" if y < bottom else "a"
        if len(stripe) >= 3:
            rows[top][x] = "d"
            if stage == 1 and (17 <= x <= 26 or 81 <= x <= 88):
                rows[top + 1][x] = "p"
            elif stage >= 2:
                rows[top + 1][x] = "q" if stage == 2 else "l"
                if bottom > top + 2:
                    rows[bottom - 1][x] = "o"

    rows[44][35:38] = list("ppc" if stage == 1 else "qqp")
    if stage >= 2:
        rows[45][35:38] = list("occ")
        rank = "pqq1pqq" if stage == 2 else "jkl1jkl1jkl"
        edge = len(rank) + 2
        x, y = 55, 76
        rows[y][x:x + edge] = list("c" * edge)
        rows[y + 1][x:x + edge] = list("1" + rank + "1")
        rows[y + 2][x:x + edge] = list("1" + rank + "1")
        rows[y + 3][x:x + edge] = list("1" * edge)
    return rows


def main():
    base = indexed_base()
    for stage in range(4):
        rows = upgrade(base, stage) if stage else base
        asset_path(1, stage).write_text("".join("".join(row) + "\n" for row in rows))


if __name__ == "__main__":
    main()
