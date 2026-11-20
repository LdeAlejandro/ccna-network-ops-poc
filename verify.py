"""Exercise the real entry point using a Linux pseudoterminal."""

import errno
import os
from pathlib import Path
import pty
import re
import select
import subprocess
import sys
import tempfile
from time import monotonic
import tty

from model import THEMES
from avatar import portrait_palette
from ops import Dashboard, color


def verify(mode, root, graphics_reply=False):
    master, slave = pty.openpty()
    tty.tcsetwinsize(slave, (45, 140))
    child = subprocess.Popen(
        [sys.executable, "ops.py", "--avatar", mode],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env={**os.environ, "XDG_CONFIG_HOME": str(root)},
    )
    os.close(slave)
    buffer = b""

    def receive(marker):
        nonlocal buffer
        deadline = monotonic() + 3
        while marker not in buffer and select.select([master], [], [], max(0, deadline - monotonic()))[0]:
            try:
                data = os.read(master, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                break
            if not data or monotonic() > deadline:
                break
            buffer += data
        assert marker in buffer, (marker, buffer[-500:])
        end = buffer.index(marker) + len(marker)
        frame, buffer = buffer[:end], buffer[end:]
        return frame

    def frame():
        return receive(b"\x1b[0m")

    def dashboard():
        rendered = frame()
        assert b"OPERATOR" in rendered and b"XP 640/1,000" in rendered
        for label in ("Panels", "Avatar", "Settings", "Quit"):
            assert label.encode() in rendered
        return rendered

    def check_bounds(rendered, rows, columns):
        assert f"\x1b[{rows};2H".encode() in rendered
        placements = re.split(rb"\x1b\[(\d+);(\d+)H", rendered)[1:]
        for row, col, content in zip(placements[::3], placements[1::3], placements[2::3]):
            text = re.sub(rb"\x1b\[[0-9;]*m", b"", content).decode()
            assert 1 <= int(row) <= rows and 1 <= int(col) <= columns
            assert int(col) - 1 + len(text) <= columns

    def resize(rows, columns):
        tty.tcsetwinsize(master, (rows, columns))
        check_bounds(dashboard(), rows, columns)

    try:
        if mode == "sixel":
            receive(b"\x1b[16t")
            if graphics_reply:
                os.write(master, b"\x1b[?62;1;4c\x1b[6;17;7t")

        initial = dashboard()
        if graphics_reply:
            first_image = re.search(rb'\x1bP.*?\x1b\\', initial)[0]
            os.write(master, b"e")
            evolved = dashboard()
            assert b"Evolution 2 / 2" in evolved
            second_image = re.search(rb'\x1bP.*?\x1b\\', evolved)[0]
            assert first_image != second_image
        else:
            skin_color = portrait_palette(THEMES[1])[20]
            assert color(skin_color).encode() in initial
            assert b"\x1bP" not in initial
            check_bounds(initial, 45, 140)

        if mode == "text":
            resize(35, 110)
            resize(24, 80)
            os.write(master, b"\x1b[B\t\t\t")
            assert "▸ STUDIED TOPICS".encode() in dashboard()
            os.write(master, b"\x1b[A")
            assert "▸ NEXT REVIEW".encode() in dashboard()
            os.write(master, b"e")
            assert b"Evolution 2 / 2" in dashboard()
            os.write(master, b"s")
            assert b"THEME SETTINGS" in frame()
            for index, theme in enumerate(THEMES, 1):
                os.write(master, str(index).encode())
                rendered = frame()
                assert color(theme.background, True).encode() in rendered
                assert f"{index}  ●  {theme.name}".encode() in rendered
                assert b"Theme saved" in rendered
            os.write(master, b"\x1b")
            assert b"Evolution 2 / 2" in dashboard()
            assert (root / "ccna-network-ops" / "theme").read_text().strip() == THEMES[-1].name
        os.write(master, b"q")
        receive(b"\x1b[?1049l")
        assert child.wait(timeout=3) == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        verify("sixel", root)
        verify("sixel", root, graphics_reply=True)
        verify("text", root)
        assert Dashboard(root / "ccna-network-ops" / "theme").theme_index == 4
    print("PASS: 140×45 → 110×35 → 80×24, navigation, five themes, persistence, XP, avatar evolution and Sixel fallback")
