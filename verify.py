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
from avatar import OPERATORS, STAGES, portrait_palette
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
        rendered = receive(b"\x1b[0m")
        clear = re.search(rb"\x1b\[38;2;[0-9;]+m\x1b\[48;2;[0-9;]+m\x1b\[2J", rendered)
        return rendered[clear.start():] if clear else rendered

    def dashboard():
        rendered = frame()
        assert (b"OPERATOR" in rendered or b"PREVIEW" in rendered) and b"XP 640/1,000" in rendered
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
        rendered = dashboard()
        check_bounds(rendered, rows, columns)
        return rendered

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
                assert b"STUDIED TOPICS" in frame()
                initial = press(b"x")
                assert b"EXERCISE 001 OF 3" in initial and "● C.".encode() in initial
                assert b"Correct:" not in initial
                with closing(Learning(db_path)) as engine:
                    plan = engine.practice_round()["questions"]
                    for index, qid in enumerate(plan, 1):
                        current = engine.session()
                        assert current["question"] == qid
                        q = current["data"]
                        if q["type"] == "multiple_choice":
                            for key in set(q["correct_answers"]) ^ set(current["selected"]):
                                press(key.encode())
                        else:
                            press(q["correct_answers"][0].encode())
                        result = press(b"\r")
                        assert b"CORRECT" in result and b"ANSWER REVIEW" in result
                        assert all(reason[:25].encode() in result for reason in q["option_explanations"].values())
                        result = press(b"n")
                        if index < len(plan):
                            assert f"EXERCISE {index + 1:03d} OF 3".encode() in result
                assert b"PRACTICE RESULTS" in result and b"3 correct" in result
                assert b"ACCURACY BY TOPIC" in result and b"100%   3/3   Network Fundamentals" in result
                assert b"PRACTICE RESULTS" in press(b"x")
                result = press(b"q")
                assert b"XP 700/1,000" in result and b"Mastered" in result
        else:
            initial = dashboard()
            if graphics_reply:
                def picture(rendered):
                    return re.search(rb'\x1bP.*?\x1b\\', rendered)[0]

                def check_operator_rail(rendered, profile_width):
                    image = picture(rendered)
                    raster = re.match(rb'\x1bP0;1q"1;1;(\d+);(\d+)', image)
                    pixel_width, pixel_height = map(int, raster.groups())
                    assert pixel_width == (profile_width - 3) * 7
                    before_image, after_image = rendered.split(image, 1)
                    image_origin = re.search(rb"\x1b\[(\d+);\d+H$", before_image)
                    start_row = int(image_origin[1])
                    rail = "▌".encode()
                    for row in range(start_row, start_row + (pixel_height + 16) // 17):
                        cursor = f"\x1b[{row};{profile_width + 1}H".encode()
                        assert re.search(re.escape(cursor) + rb'(?:\x1b\[[\d;]+m)+' + rail, after_image)

                check_operator_rail(initial, 43)
                caret_end = "▸\x1b[22m".encode()
                idle = receive(caret_end)
                next_idle = receive(caret_end)
                assert idle != next_idle
                assert b"CONSOLE RECOVERY" not in initial
                letters = re.findall(rb"\x1b\[8;(\d+)H(?:\x1b\[[\d;]+m)+([A-Z])", idle)
                assert [(col, letter) for col, letter in letters if 54 <= int(col) < 70][:4] == [(b"54", b"C"), (b"55", b"O"), (b"56", b"N"), (b"57", b"S")]
                for row, column in ((24, 48), (24, 95), (39, 4), (37, 60), (32, 4)):
                    assert f"\x1b[{row};{column}H".encode() in idle
                for update in (idle, next_idle):
                    assert not any(code in update for code in (b"\x1bP", b"\x1b[2J", b"XP"))

                update = receive(caret_end)
                assert b"\x1bP" not in update and b"\x1b[2J" not in update

                os.write(master, b"x")
                assert b"QUIZ MODE" in frame()
                assert not buffer and not select.select([master], [], [], 1.1)[0]
                os.write(master, b"\x1b")
                dashboard()

                images = {picture(initial)}
                assert b"1/4 Equipped" not in initial
                for stage in range(1, len(STAGES) + 1):
                    os.write(master, b"e")
                    for operator in OPERATORS:
                        rendered = dashboard()
                        assert b"PREVIEW" in rendered and operator.upper().encode() in rendered
                        state = "Unlocked" if stage == 1 else "Locked"
                        assert f"{stage}/4 {state}".encode() in rendered
                        images.add(picture(rendered))
                        if capture:
                            capture(f"{operator.lower()}-{stage}", rendered)
                        os.write(master, b"a")
                    dashboard()  # The second swap restores the preview operator.
                assert len(images) == len(STAGES) * len(OPERATORS)
                os.write(master, b"e")
                assert b"1/4 Equipped" in dashboard()
                os.write(master, b"a")
                assert b"RELAY" in dashboard()
                tty.tcsetwinsize(master, (24, 80))
                compact = dashboard()
                assert b"RELAY" in compact and picture(compact) not in images
                check_operator_rail(compact, 80 // 3)
            else:
                skin_color = portrait_palette(THEMES[1])[20]
                assert color(skin_color).encode() in initial
                assert b"\x1bP" not in initial
                check_bounds(initial, 45, 140)

            if mode == "text":
                assert b"A branch router rebooted" in resize(35, 110)
                resize(24, 80)
                os.write(master, b"\x1b[B\t\t\t")
                assert "▸ STUDIED TOPICS".encode() in dashboard()
                os.write(master, b"\x1b[A")
                assert "▸ NEXT REVIEW".encode() in dashboard()
                os.write(master, b"e")
                assert b"1/4 Unlocked" in dashboard()
                os.write(master, b"a")
                assert b"RELAY" in dashboard()
                os.write(master, b"s")
                assert b"THEME SETTINGS" in frame()
                for index, theme in enumerate(THEMES, 1):
                    os.write(master, str(index).encode())
                    rendered = frame()
                    assert color(theme.background, True).encode() in rendered
                    assert f"{index}  ●  {theme.name}".encode() in rendered
                    assert b"Theme saved" in rendered
                os.write(master, b"\x1b")
                assert b"1/4 Unlocked" in dashboard()
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
