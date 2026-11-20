"""Run with python3 ops.py in an interactive UTF-8 terminal."""

import argparse
from functools import lru_cache
from itertools import groupby
import os
from pathlib import Path
import re
import select
import sys
import termios
from time import monotonic
import tty

from avatar import half_blocks, portrait_palette, sixel
from lettering import masthead
from model import MISSION_DETAILS, PANELS, THEMES, XP, XP_GOAL

ESC = "\x1b["
DEFAULT_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
CONFIG = DEFAULT_CONFIG / "ccna-network-ops" / "theme"


@lru_cache(maxsize=256)
def color(hex_value, background=False):
    rgb = ";".join(str(int(hex_value[i:i + 2], 16)) for i in (0, 2, 4))
    return f"{ESC}{48 if background else 38};2;{rgb}m"


class Dashboard:
    def __init__(self, preference):
        self.preference = preference
        self.theme_index = 1
        try:
            name = preference.read_text().strip()
            self.theme_index = next(i for i, theme in enumerate(THEMES) if theme.name == name)
        except (OSError, UnicodeError, StopIteration):
            pass
        self.stage = self.focus = self.offset = 0
        self.settings = False
        self.notice = ""

    def choose(self, index):
        self.theme_index = index
        try:
            self.preference.parent.mkdir(parents=True, exist_ok=True)
            self.preference.write_text(THEMES[index].name + "\n")
            self.notice = "Theme saved"
        except OSError:
            self.notice = "Theme applied for this session"

    def key(self, key):
        if self.settings:
            if key in "12345" and len(key) == 1:
                self.choose(int(key) - 1)
            elif key in ("s", "ESC"):
                self.settings = False
        elif key == "s":
            self.settings = True
            self.notice = ""
        elif key == "e":
            self.stage = 1 - self.stage
        elif key in ("DOWN", "TAB", "UP"):
            step = -1 if key == "UP" else 1
            self.focus = (self.focus + step) % 6
            self.offset = max(0, self.focus - 2)

    def frame(self, cols, rows, pixels=None):
        t = THEMES[self.theme_index]
        gutter = max(0, (cols - 148) // 2)
        cols -= 2 * gutter
        scan = "".join(
            f"{(17 * int(t.panel[i:i+2], 16) + int(t.shadow[i:i+2], 16)) // 18:02x}"
            for i in (0, 2, 4)
        )
        frame = [color(t.text), color(t.background, True), ESC + "2J"]

        def put(x, y, value, fg=None, bg=None, bold=False):
            if 0 <= y < rows and 0 <= x < cols:
                frame.extend((f"{ESC}{y + 1};{x + gutter + 1}H", color(fg or t.text),
                              color(bg or t.background, True), ESC + "1m" if bold else "",
                              value[:cols - x], ESC + "22m" if bold else ""))

        if cols < 50 or rows < 18:
            put(0, 0, "Resize to at least 50 × 18. Q quit", t.accent)
            return "".join(frame)

        def row_bg(y):
            return scan if y % 2 == 0 else t.panel

        def panel(x, y, width, height, title, active=False):
            edge = t.accent if active else t.border
            cap = " ─ □ × " if width >= 26 else " × "
            label = (" ▸ " if active else " » ") + title
            title_bar = label[:width - len(cap) - 2].ljust(width - len(cap) - 1) + cap + " "
            green = t.name == "Cyber Emerald"
            put(x, y, title_bar, edge if green else t.background, t.panel if green else edge, bold=True)
            if width >= 25:
                put(x, y, "▟", edge)
                put(x + width - 1, y, "▙", edge)
            rail = edge if active or t.name in ("Cyber Emerald", "Neon Rose") else t.secondary
            for dy in range(1, height - 1):
                put(x, y + dy, "▐", rail, t.panel)
                put(x + 1, y + dy, " " * (width - 2), t.text, row_bg(y + dy))
                put(x + width - 1, y + dy, "▌", rail, t.panel)
            put(x, y + height - 1, "▜" + "▀" * (width - 2) + "▛", rail)
            if width >= 27:
                put(x + width - 10, y + height - 1, "▀▀", t.secondary)
                put(x + width - 8, y + height - 1, "▀", t.shadow)

        def body(x, y, width, value, ink=None):
            put(x + 2, y, value[:width - 4], ink, row_bg(y))

        def meter(x, y, count, filled):
            for i in range(count):
                put(x + i * 2, y, " ", bg=t.accent if i < filled else t.shadow)

        def strip(y):
            motif = "▰▰▰╸" + "▂" * (cols - 10) + "╺▰▰▰"
            put(1, y, motif, t.shadow, t.panel)

        def footer(items, selection=None):
            status_y = rows - 1
            command_y = status_y - int(selection is not None)
            put(1, status_y, " " * (cols - 2), t.text, t.panel)
            put(1, command_y, " " * (cols - 2), t.text, t.shadow)
            if selection:
                put(2, status_y, f"▸ {selection.upper()}", t.accent, t.panel, bold=True)
                if cols >= 76:
                    name = f" {t.name} "
                    put(cols - len(name) - 2, status_y, name, t.text, t.panel)

            x = 2
            contents = sum(len(key) + len(label) + 4 for key, label in items)
            gap = max(0, min(8, (cols - contents - 4) // len(items)))
            for i, (key, label) in enumerate(items):
                chosen = i == 0
                foreground = t.background if chosen else t.text
                background = t.accent if chosen else t.panel
                command = f"[{key}] {label} "
                put(x, command_y, command, foreground, background, bold=True)
                x += len(command) + gap
            frame.append(ESC + "0m")

        compact = cols < 100 or rows < 32
        title = "CCNA NETWORK OPS"
        if cols >= 76:
            rows_of_type = tuple(masthead(title, wide=cols >= 130))
            wordmark_x = (cols - len(rows_of_type[0])) // 2
            green = t.name == "Cyber Emerald"
            if not green:
                put(wordmark_x - 1, 0, "▄" * (len(rows_of_type[0]) + 2), t.border)
            for row, line in enumerate(rows_of_type, 1):
                wing = min(wordmark_x - 1, 10 - 2 * row)
                bevel = "▓▒░" if not green else "▰╱╱"
                if wordmark_x - wing >= 5:
                    put(wordmark_x - wing - 3, row, bevel[::-1], t.shadow)
                    put(wordmark_x + len(line) + wing, row, bevel, t.shadow)
                ink, paper = (t.border, t.background) if green else (t.background, t.border)
                put(wordmark_x - wing, row, " " * wing + line + " " * wing, ink, paper)
            if cols >= 120:
                left_mark = ("╱╱ ▄▄▄▄▄▄▄▄▄▄", "╱ ▄█▪▪▪▪▪▪▪▪█▄", "  ═▀▀▀▀▀▀▀▀▀▀═")
                right_mark = ("    ▄█▄   ╲╲", " ▄━━━┻━━━▄ ╲", " ▣   ▣   ▣")
                for row, (switch, topology) in enumerate(zip(left_mark, right_mark), 1):
                    put(3, row, switch, t.secondary)
                    put(cols - 15, row, topology, t.secondary)
            strip(4)
            subtitle = " ▪  T E R M I N A L   R P G   /   C C N A   S T U D Y  ▪ "
            put((cols - len(subtitle)) // 2, 4, subtitle, t.text, t.shadow, bold=True)
        else:
            put(1, 1, " " + title.ljust(cols - 3), t.background, t.border)
            strip(4)

        if self.settings:
            width = min(52, cols - 2)
            panel(1, 6, width, 10, "THEME SETTINGS")
            for i, theme in enumerate(THEMES):
                active = i == self.theme_index
                label = f"{i + 1}  {'●' if active else '○'}  {theme.name}"
                put(3, 7 + i, label.ljust(width - 14),
                    t.background if active else t.text, t.accent if active else t.panel)
                for j, ink in enumerate((theme.shadow, theme.border, theme.secondary, theme.accent)):
                    put(width - 9 + 2 * j, 7 + i, "  ", bg=ink)
            body(1, 13, width, self.notice, t.secondary)
            footer((("1–5", "Select theme"), ("Esc", "Back"), ("Q", "Quit")))
            return "".join(frame)

        # Draw the study windows first. The portrait is independent of focus and panel paging.
        y0, end = 6, rows - 2
        left = 1
        profile_w = min(43, cols * 31 // 100) if not compact else cols // 3
        right = left + profile_w + 1
        right_w = cols - right - 1

        def study(index, x, y, width, height):
            title, lines = PANELS[index]
            panel(x, y, width, height, title, active=self.focus == index + 1)
            for i, line in enumerate(lines[:height - 2]):
                prefix = "☑ " if index == 3 else "▪ " if index in (1, 4) else ""
                body(x, y + i + 1, width, prefix + line,
                     t.accent if index == 0 and i == 0 else t.text)
                if index == 0 and i == 0:
                    put(x + 2, y + 1, line[:width - 4], t.accent, row_bg(y + 1), bold=True)
                if index == 3:
                    row = y + i + 1
                    put(x + 2, row, "☑", t.accent, row_bg(row))
                    if width >= 33:
                        put(x + width - 11, row, " STUDIED ", t.background, t.secondary, bold=True)
            if index == 3 and height >= 6:
                body(x, y + height - 2, width, f"{len(lines):02d} TOPICS STUDIED", t.muted)

        if compact:
            count = min(5, (end - y0) // 5)
            first = min(self.offset, 5 - count)
            if self.focus:
                first = min(self.focus - 1, max(first, self.focus - count))
            for i in range(first, first + count):
                y = y0 + (i - first) * 5
                study(i, right, y, right_w, 5)
                if i == 1 and right_w >= 24:
                    done, total = map(int, PANELS[1][1][0].rsplit("  ", 1)[1].split("/"))
                    meter(right + 2, y + 3, total, done)
            last = y0 + count * 5
            if last < end:
                body(right, last, right_w, f"{first + 1}–{first + count} / 5   ↑↓", t.muted)
            profile_end = end
        else:
            topics_y = end - 6
            profile_end = topics_y - 1
            study(3, left, topics_y, profile_w, 6)
            mid_w = (right_w - 1) // 2
            review_x = right + mid_w + 1
            review_w = right_w - mid_w - 1
            gear_h = 8 if rows >= 39 else 7
            gear_y = end - gear_h - (2 if rows >= 39 else 0)
            # Give the short activity panels less height and separate the right-hand groups.
            mid_h = 9 if rows >= 39 else 7
            gear_gap = 2 if rows >= 35 else 1
            mission_gap = 2 if rows >= 39 else 1
            mid_y = gear_y - mid_h - gear_gap
            mission_h = mid_y - y0 - mission_gap
            panel(right, y0, right_w, mission_h, PANELS[0][0], active=self.focus == 1)
            panel(right, mid_y, mid_w, mid_h, PANELS[1][0], active=self.focus == 2)
            panel(review_x, mid_y, review_w, mid_h, PANELS[2][0], active=self.focus == 3)
            panel(right, gear_y, right_w, gear_h, PANELS[4][0], active=self.focus == 5)

            mission_title, description, objectives = PANELS[0][1]
            code, title_text = mission_title.split(" / ", 1)
            headline_y = y0 + 1
            put(right + 2, headline_y, f" {code} ", t.background, t.accent)
            divider_x = right + right_w - 34
            briefing_w = divider_x - right
            put(right + 8, headline_y, f" {title_text.upper()} ".ljust(briefing_w - 10),
                t.accent, t.shadow, bold=True)
            body(right, headline_y + 1, briefing_w, description)
            for dy in range(1, mission_h - 1):
                put(divider_x, y0 + dy, "│", t.shadow, scan)

            checklist = (
                ("Review VLAN fundamentals", True),
                ("Identify the switch uplinks", True),
                ("Set the uplink to trunk mode", False),
                ("Verify the trunk link", False),
            )
            full_brief = mission_h >= 10
            if full_brief:
                checklist_y = headline_y + (2 if mission_h == 10 else 3)
                body(right, checklist_y, briefing_w, "OBJECTIVE CHECKLIST", t.secondary)
                for i, (label, done) in enumerate(checklist):
                    row = checklist_y + 1 + i
                    put(right + 2, row, "☑" if done else "□", t.accent if done else t.secondary, row_bg(row))
                    body(right + 2, row, briefing_w - 2, label, t.muted if done else t.text)
            else:
                body(right, headline_y + 3, briefing_w, objectives, t.secondary)
                body(right, headline_y + 4, briefing_w, "☑ ☑ □ □", t.accent)

            map_rows = (
                "         ┏━↕━┓",
                "     ┌━━━┻━━━┻━━━┐",
                "  ┏━━┻━━┓     ┏━━┻━━┓",
                "  ┗▪▪▪▪▪┛     ┗▪▪▪▪▪┛",
                "    SW1         SW2",
            )
            stats_x = divider_x + 2
            if mission_h >= 14:
                put(stats_x, y0 + 1, "  MISSION DETAILS  ", t.background, t.secondary, bold=True)
                for dy, (label, value) in enumerate(MISSION_DETAILS, 2):
                    put(stats_x, y0 + dy, label, t.muted, row_bg(y0 + dy))
                    put(stats_x + 13, y0 + dy, value, t.accent, row_bg(y0 + dy), bold=True)
                map_y = y0 + 7
                put(stats_x, map_y - 1, "802.1Q TOPOLOGY ━━━━━━━━━━━━━", t.secondary, row_bg(map_y - 1))
            elif mission_h >= 10:
                mission_type, difficulty, reward, focus = (value for _, value in MISSION_DETAILS)
                put(stats_x, y0 + 2, f" {mission_type} ", t.background, t.secondary, bold=True)
                put(stats_x + 17, y0 + 2, f" DIFF {difficulty.replace(' ', '')}",
                    t.accent, row_bg(y0 + 2), bold=True)
                put(stats_x, y0 + 3, focus, t.secondary, row_bg(y0 + 3))
                put(stats_x + 18, y0 + 3, reward, t.accent, row_bg(y0 + 3), bold=True)
                map_y = y0 + 4
                map_rows = (
                    "         ┌─↕─┐",
                    "     ┌━━━┻━━━┻━━━┐",
                    "  ▣ SW1         SW2 ▣",
                )
            else:
                map_y = y0 + 1
            for i, line in enumerate(map_rows):
                put(stats_x + 3, map_y + i, line, t.accent if i == 1 else t.secondary, row_bg(map_y + i))
            if full_brief:
                completed = sum(done for _, done in checklist)
                if mission_h >= 14:
                    status_y = min(y0 + mission_h - 3, checklist_y + 6)
                    body(right, status_y, briefing_w, f"OBJECTIVES  {completed:02d}/{len(checklist):02d}  COMPLETE", t.secondary)
                    meter(right + 2, status_y + 1, 14, 14 * completed // len(checklist))
                else:
                    status_y = min(y0 + mission_h - 2, map_y + 5)
                    put(stats_x, status_y, f" OBJECTIVES  {completed:02d}/{len(checklist):02d} ", t.text, t.shadow, bold=True)

            drill_label, drill_score = PANELS[1][1][0].rsplit("  ", 1)
            done, total = map(int, drill_score.split("/"))
            basic_label, basic_status = PANELS[1][1][1].rsplit("  ", 1)
            progress_y = mid_y + 1
            put(right + 2, progress_y, f"▸ {drill_label.upper()}", t.text, row_bg(progress_y), bold=True)
            put(right + mid_w - 10, progress_y, f" {done} / {total} ", t.background, t.accent, bold=True)
            meter(right + 4, progress_y + 1, total, done)
            body(right + 2, progress_y + 2, mid_w - 2, f"{total - done} DRILLS REMAIN", t.muted)
            completion_y = mid_y + min(mid_h - 2, 6)
            put(right + 2, completion_y, f"☑ {basic_label.upper()}", t.text, row_bg(completion_y), bold=True)
            put(right + mid_w - 11, completion_y, f" {basic_status.upper()} ", t.background, t.secondary, bold=True)

            review_entries = tuple(line.split(maxsplit=1) for line in PANELS[2][1])
            put(review_x + 2, mid_y + 1, "REVIEW QUEUE", t.secondary, row_bg(mid_y + 1), bold=True)
            put(review_x + review_w - 12, mid_y + 1, f" {len(review_entries):02d} TOPICS ",
                t.background, t.secondary, bold=True)
            for i, (when, topic) in enumerate(review_entries):
                row = mid_y + 2 + i * (3 if mid_h >= 9 else 2)
                put(review_x + 2, row, when.upper().center(10), t.background,
                    t.accent if i == 0 else t.secondary, bold=True)
                put(review_x + 13, row, topic[:review_w - 15], t.text, row_bg(row), bold=True)

            icons = (
                ("▀▄       ", "  ▀▀▀▄   ", "      ▀▄ "),
                (" ▄▄▄▄▄▄▄ ", "█▪▪▪▪▪▪▪█", " ▀▀▀▀▀▀▀ "),
                (" ▄▄▄▄▄▄▄ ", "█▁▃▁▆▂▅▁█", " ▀▀▀▀▀▀▀ "),
            )
            tile_w = (right_w - 4) // 3
            active = self.focus == 5
            equipment_roles = ("SERIAL ACCESS", "LAYER 2", "FRAME INSPECTION")
            for i, (name, icon, role) in enumerate(zip(PANELS[4][1], icons, equipment_roles)):
                x = right + 2 + i * tile_w
                width = tile_w - 1
                border = t.accent if active else t.secondary
                card_bg = scan if i % 2 == 0 else t.panel
                put(x, gear_y + 1, "▟" + "▄" * (width - 2) + "▙", border, card_bg)
                for dy in range(2, gear_h - 1):
                    put(x, gear_y + dy, "▌" + " " * (width - 2) + "▐", border, card_bg)
                side_by_side = width >= 29
                icon_x = x + 1 if side_by_side else x + (width - len(icon[0])) // 2
                for dy, line in enumerate(icon, 2):
                    put(icon_x, gear_y + dy, line, t.secondary, card_bg)
                if side_by_side:
                    label_x = x + 12
                    put(label_x, gear_y + 3, name.upper(), t.accent if active else t.text, card_bg, bold=True)
                    put(label_x, gear_y + 5, role, t.muted, card_bg)
                else:
                    put(x + 1, gear_y + 5, name.upper().center(width - 2), t.accent if active else t.text, card_bg, bold=True)
                    if gear_h == 8:
                        put(x + 1, gear_y + 6, role.center(width - 2), t.muted, card_bg)

        panel(left, y0, profile_w, profile_end - y0, "OPERATOR", active=self.focus == 0)
        portrait_y = y0 + 1
        portrait_rows = profile_end - portrait_y - 5
        portrait_columns = profile_w - 2
        palette = portrait_palette(t)
        image = sixel(self.stage, palette, pixels, portrait_columns, portrait_rows) if pixels else ""
        if image:
            frame.extend((f"{ESC}{portrait_y + 1};{left + gutter + 2}H", image))
        else:
            for y, pairs in enumerate(half_blocks(self.stage, portrait_columns, portrait_rows), portrait_y):
                x = left + 1 + (portrait_columns - len(pairs)) // 2
                for (top, bottom), cells in groupby(pairs):
                    length = sum(1 for _ in cells)
                    put(x, y, (" " if top == bottom else "▀") * length, palette[top], palette[bottom])
                    x += length

        stats_y = profile_end - 5
        if profile_w >= 25:
            put(left + 1, stats_y, " ▸ ROOK".ljust(profile_w - 2), t.background, t.secondary, bold=True)
            put(left + profile_w - 11, stats_y, " LEVEL 07 ", t.background, t.accent, bold=True)
        else:
            put(left + 1, stats_y, " ROOK / LV 07"[:profile_w - 2], t.background, t.secondary, bold=True)
        body(left, stats_y + 1, profile_w, f"Evolution {self.stage + 1} / 2", t.secondary)
        body(left, stats_y + 2, profile_w, f"XP {XP:,}/{XP_GOAL:,}", t.text)
        segments = min(16, (profile_w - 3) // 2)
        meter(left + 2, stats_y + 3, segments, XP * segments // XP_GOAL)
        if profile_w >= 38:
            put(left + profile_w - 5, stats_y + 3, "▰▰", t.secondary, row_bg(stats_y + 3))
        if not compact and profile_w >= 34:
            put(left + profile_w - 6, stats_y + 2, f"{XP * 100 // XP_GOAL:>2}%", t.accent, t.panel)
        focus = ("Operator", "Mission", "Progress", "Review", "Topics", "Gear")[self.focus]
        panel_key = "Tab/↑↓" if cols >= 56 else "Tab"
        footer(((panel_key, "Panels"), ("E", "Avatar"), ("S", "Settings"), ("Q", "Quit")), focus)
        return "".join(frame)


def probe(fd, write):
    """Probe before the first frame. Require Sixel DA and known cell dimensions."""
    write(ESC + "c" + ESC + "16t")
    reply = b""
    deadline = monotonic() + 0.2
    while len(reply) < 1024 and select.select([fd], [], [], max(0, deadline - monotonic()))[0]:
        chunk = os.read(fd, 256)
        if not chunk:
            break
        reply += chunk
        da = re.search(rb"\x1b\[\?([0-9;]+)c", reply)
        cell = re.search(rb"\x1b\[6;(\d+);(\d+)t", reply)
        if da and cell:
            if b"4" in da[1].split(b";"):
                width, height = int(cell[2]), int(cell[1])
                if 1 <= width <= 128 and 1 <= height <= 256:
                    return width, height
            break
    return None


def run(app, avatar_mode):
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)

    def write(value):
        sys.stdout.write(value)
        sys.stdout.flush()

    keys = {b"\x1b[A": "UP", b"\x1b[B": "DOWN", b"\x1bOA": "UP", b"\x1bOB": "DOWN",
            b"\x1b[Z": "UP", b"\t": "TAB", b"\x1b": "ESC"}
    try:
        tty.setraw(fd)
        write(ESC + "?1049h" + ESC + "?25l")
        pixels = probe(fd, write) if avatar_mode == "sixel" else None
        previous = None
        pending = b""
        while True:
            size = os.get_terminal_size(fd)
            if size != previous:
                write(app.frame(*size, pixels))
                previous = size
            if not select.select([fd], [], [], 0.1)[0]:
                continue
            data = os.read(fd, 256)
            if not data:
                break
            pending += data
            while pending:
                if pending.startswith(b"\x1b["):
                    match = re.match(rb"\x1b\[[0-?]*[ -/]*[@-~]", pending)
                    if not match:
                        break
                    token = match[0]
                elif pending.startswith(b"\x1bO"):
                    if len(pending) < 3:
                        break
                    token = pending[:3]
                elif pending == b"\x1b" and select.select([fd], [], [], 0.03)[0]:
                    break
                else:
                    token = pending[:1]
                pending = pending[len(token):]
                if token in (b"q", b"\x03"):
                    return
                app.key(keys.get(token, token.decode("ascii", errors="replace")))
            previous = None
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, saved)
        write(ESC + "0m" + ESC + "?25h" + ESC + "?1049l")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--avatar", choices=("text", "sixel"), default="sixel",
                        help="probe for Sixel by default, or force Unicode with text")
    args = parser.parse_args()
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        parser.error("an interactive terminal is required")
    run(Dashboard(CONFIG), args.avatar)
