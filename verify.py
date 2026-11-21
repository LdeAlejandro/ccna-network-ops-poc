"""Exercise the real entry point using a Linux pseudoterminal."""

from contextlib import closing
import errno
import os
from pathlib import Path
import pty
import re
import select
import shutil
import subprocess
import sys
import tempfile
from time import monotonic
import tty

from learning import Learning, MISSION, REVIEW
from missions import MISSIONS
from model import THEMES
from avatar import portrait_palette
from ops import color


def verify(mode, root, graphics_reply=False, study=None, capture=None):
    release = study in ("mission", "mission-resume")
    data_home = root / ("release" if release else "study" if study else f"data-{mode}-{graphics_reply}")
    db_path = data_home / "ccna-network-ops" / "learning.sqlite3"
    if study == "import":
        inbox = data_home / "ccna-network-ops" / "inbox"
        inbox.mkdir(parents=True)
        shutil.copyfile("content/network-fundamentals.json", inbox / "fundamentals.json")
    master, slave = pty.openpty()
    tty.tcsetwinsize(slave, (45, 140))
    child = subprocess.Popen(
        [sys.executable, "ops.py", "--avatar", mode] + ([] if release else ["--no-bundled"]),
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env={**os.environ, "XDG_CONFIG_HOME": str(root),
             "XDG_DATA_HOME": str(data_home)},
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
        for label in ("Missions", "Practice", "Review", "Feed", "Theme", "Quit"):
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

        if release:
            def press(key):
                os.write(master, key)
                return frame()

            if study == "mission":
                initial = dashboard()
                if capture:
                    capture("dashboard", initial)
                assert b"No reviews are due today" in press(b"r")
                press(b"\x1b")
                assert b"QUIZ MODE / PRACTICE" in press(b"x")
                press(b"b")
                press(b"\x1b")
                assert b"MISSION SELECT" in press(b"m")
                briefing = press(b"\r")
                assert b"MISSION BRIEFING / M01" in briefing and b"First completion +60 XP" in briefing
                if capture:
                    capture("mission-briefing", briefing)
                quiz = press(b"\r")
                assert b"QUESTION 1 OF 5" in quiz and b"Correct:" not in quiz
                if capture:
                    capture("mission-quiz", quiz)
                for rows, cols in ((35, 110), (24, 80), (18, 50)):
                    tty.tcsetwinsize(master, (rows, cols))
                    check_bounds(frame(), rows, cols)
                os.write(master, b"d")
                receive("● D.".encode())
                frame()
                press(b"\x1b")
            else:
                dashboard()
                assert b"MISSION SELECT" in press(b"m")
                assert b"Resume" in press(b"\r")
                assert "● D.".encode() in press(b"\r")
                with closing(Learning(db_path)) as engine:
                    for index, qid in enumerate(MISSIONS[0].questions, 1):
                        session = engine.session(MISSION)
                        assert session["question"] == qid
                        for key in session["data"]["correct_answers"]:
                            press(key.lower().encode())
                        assert b"CORRECT" in press(b"\r")
                        result = press(b"n")
                        if index < len(MISSIONS[0].questions):
                            assert f"QUESTION {index + 1} OF 5".encode() in result
                assert b"MISSION SUMMARY" in result and b"Accuracy 100%" in result and b"Mission bonus +60 XP" in result
                if capture:
                    capture("mission-summary", result)
                assert b"CONSOLE RECOVERY" in press(b"\r")
                assert "● B.".encode() in press(b"x")
                press(b"\x1b")
                with closing(Learning(db_path)) as engine:
                    engine.db.execute("UPDATE reviews SET due = ?", (engine.today().isoformat(),))
                assert b"REVIEW MODE" in press(b"r")
                with closing(Learning(db_path)) as engine:
                    review = engine.session(REVIEW)
                    assert review and review["question"] in MISSIONS[0].questions
                for key in review["data"]["correct_answers"]:
                    press(key.lower().encode())
                assert b"CORRECT" in press(b"\r")
                with closing(Learning(db_path)) as engine:
                    assert engine.session(REVIEW)["next_review"] > engine.today().isoformat()
                press(b"\x1b")
        elif study:
            def press(key):
                os.write(master, key)
                return frame()

            if study == "import":
                dashboard()
                assert b"FEED MODE / LIBRARY" in press(b"f")
                assert b"fundamentals.json" in press(b"t")
                assert b"Imported fundamentals.json" in press(b"\r")
                assert b"Introduced" in press(b"\x1b")
                initial = press(b"x")
                assert b"EXERCISE 001" in initial
                assert b"Correct:" not in initial
                for rows, cols in ((35, 110), (24, 80)):
                    tty.tcsetwinsize(master, (rows, cols))
                    check_bounds(frame(), rows, cols)
                assert b"EXERCISE 001" in press(b"c")
                assert b"OPERATOR" in press(b"\x1b")
            else:
                assert b"Introduced" in frame()
                initial = press(b"x")
                assert b"EXERCISE 001" in initial and "● C.".encode() in initial
                assert b"Correct:" not in initial
                result = press(b"\r")
                assert b"CORRECT" in result and b"Correct: C" in result and b"+20 XP" in result
                assert b"EXERCISE 002" in press(b"n")
                assert b"Select at least one" in press(b"\r")
                assert b"EXERCISE 002" in press(b" ")
                press(b"c")
                assert b"Correct: A, C" in press(b"\r")
                result = press(b"q")
                assert b"XP 680/1,000" in result and b"Practiced" in result
        else:
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
        verify("text", root, study="import")
        verify("text", root, study="resume")
        verify("text", root, study="mission")
        verify("text", root, study="mission-resume")
    print("PASS: 140×45 → 110×35 → 80×24 → 50×18, navigation, five themes, persistence, XP, avatar evolution, Sixel fallback and persistent practice, mission briefing and results, and due review flow")
