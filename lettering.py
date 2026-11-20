"""Four-pixel display lettering for the dashboard masthead."""

GLYPHS = {
    "A": (6, 9, 15, 9, 9),
    "C": (7, 8, 8, 8, 7),
    "E": (15, 8, 14, 8, 15),
    "K": (9, 10, 12, 10, 9),
    "N": (9, 13, 11, 9, 9),
    "O": (6, 9, 9, 9, 6),
    "P": (14, 9, 14, 8, 8),
    "R": (14, 9, 14, 10, 9),
    "S": (7, 8, 6, 1, 14),
    "T": (15, 6, 6, 6, 6),
    "W": (9, 9, 9, 15, 6),
}


def masthead(label, wide=False):
    for row in (0, 2, 4):
        letters = []
        for letter in label:
            if letter == " ":
                letters.append(" ")
                continue
            glyph = GLYPHS[letter]
            top, bottom = glyph[row], glyph[row + 1] if row < 4 else 0
            letters.append("".join(
                " ▄▀█"[bool(bottom & bit) + 2 * bool(top & bit)]
                for bit in ((8, 4, 4, 2, 1) if wide else (8, 4, 2, 1))
            ))
        yield " ".join(letters)
