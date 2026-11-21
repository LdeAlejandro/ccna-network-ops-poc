"""Run with python3 ops.py in an interactive UTF-8 terminal."""

import argparse
from contextlib import closing
import json
import sqlite3
import textwrap
import unicodedata
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

from avatar import OPERATORS, STAGES, half_blocks, portrait_palette, sixel
from lettering import masthead
from learning import Learning, LearningError, MISSION, PRACTICE, REVIEW
from missions import MISSIONS, MISSIONS_BY_ID, load_bundled
from model import GEAR, THEMES, XP, XP_GOAL

ESC = "\x1b["
DEFAULT_CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
CONFIG = DEFAULT_CONFIG / "ccna-network-ops" / "theme"
DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "ccna-network-ops"


def cell_text(text):
    """Keep imported text inside the renderer's one-codepoint-per-cell layout."""
    return "".join(
        char if char in "\n\t" or (not unicodedata.category(char).startswith(("C", "M"))
                                      and unicodedata.east_asian_width(char) not in ("W", "F"))
        else "?" for char in text.replace("\r\n", "\n").replace("\r", "\n")
    )


@lru_cache(maxsize=256)
def color(hex_value, background=False):
    rgb = ";".join(str(int(hex_value[i:i + 2], 16)) for i in (0, 2, 4))
    return f"{ESC}{48 if background else 38};2;{rgb}m"


class Dashboard:
    def __init__(self, preference, learning, inbox):
        self.preference = preference
        self.learning = learning
        self.inbox = inbox
        self.mode = self.source = self.reveal = None
        self.scroll = self.feed_cursor = 0
        self.page_size = 1
        self.inbox_view = False
        self.mission_cursor = 0
        self.theme_index = 1
        try:
            name = preference.read_text().strip()
            self.theme_index = next(i for i, theme in enumerate(THEMES) if theme.name == name)
        except (OSError, UnicodeError, StopIteration):
            pass
        self.focus = self.offset = 0
        self.settings = False
        self.preview_stage = self.preview_operator = None
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
        if len(key) == 1 and key.isascii():
            key = key.lower()
        try:
            self.route_key(key)
        except (LearningError, OSError, sqlite3.Error) as error:
            self.notice = str(error)

    def route_key(self, key):
        if self.mode:
            self.mode_key(key)
        elif self.settings:
            if key in "12345" and len(key) == 1:
                self.choose(int(key) - 1)
            elif key in ("s", "ESC"):
                self.settings = False
        elif key == "s":
            self.settings = True
            self.notice = ""
        elif key == "x":
            self.open_quiz()
        elif key == "m" or (key == "ENTER" and self.focus == 1):
            self.open_missions()
        elif key == "r":
            self.open_quiz(REVIEW)
        elif key == "ENTER" and self.focus in (2, 3, 4):
            self.mode = "progress"
            self.notice = ""
            self.scroll = 0
            self.reveal = None
        elif key == "f":
            self.mode = "feed"
            self.source = None
            self.notice = ""
            self.scroll = self.feed_cursor = 0
            self.reveal = None
        elif key == "a":
            if self.preview_stage is None:
                self.learning.cycle_operator()
            else:
                self.preview_operator = (self.preview_operator + 1) % len(OPERATORS)
        elif key == "e":
            if self.preview_stage is None:
                self.preview_stage = 0
                self.preview_operator = self.learning.operator()
            elif self.preview_stage == len(STAGES) - 1:
                self.preview_stage = self.preview_operator = None
            else:
                self.preview_stage += 1
        elif key == "ESC":
            self.preview_stage = self.preview_operator = None
        elif key in ("DOWN", "TAB", "UP"):
            step = -1 if key == "UP" else 1
            self.focus = (self.focus + step) % 6
            self.offset = max(0, self.focus - 2)

    @property
    def quiz_slot(self):
        return {"quiz": PRACTICE, "review": REVIEW, "mission_quiz": MISSION}.get(self.mode)

    def show_mode(self, mode):
        self.mode = mode
        self.notice = ""
        self.scroll = 0
        self.reveal = None

    def open_quiz(self, slot=PRACTICE, *, new_round=False):
        self.show_mode("review" if slot == REVIEW else "quiz")
        session = self.learning.start(review=slot == REVIEW, new_round=new_round)
        if session and session["correct"] is not None:
            self.reveal = "feedback"
        elif slot == PRACTICE and not session and self.learning.practice_round():
            self.show_mode("practice_result")

    def open_missions(self):
        current = self.learning.mission_run()
        if current and not current["finished"]:
            self.mission_cursor = next(i for i, m in enumerate(MISSIONS) if m.id == current["mission"])
        self.show_mode("missions")
        self.reveal = self.mission_cursor

    def mission_key(self, key):
        mission = MISSIONS[self.mission_cursor]
        run = self.learning.mission_run()
        if self.mode == "missions":
            if key in ("UP", "DOWN", "TAB"):
                self.mission_cursor = (self.mission_cursor + (-1 if key == "UP" else 1)) % len(MISSIONS)
                self.reveal = self.mission_cursor
            elif key == "ENTER":
                self.show_mode("briefing")
            elif key == "h":
                previous = self.learning.mission_run(mission.id)
                if previous:
                    self.show_mode("mission_result")
                else:
                    self.notice = "No attempts for this operation yet."
        elif self.mode == "briefing" and key == "ENTER":
            if not run or run["finished"]:
                self.learning.start_mission(mission.id)
            elif run["mission"] != mission.id:
                self.notice = f"Resume {MISSIONS_BY_ID[run['mission']].name} first."
                return
            self.show_mode("mission_quiz")
            if self.learning.session(MISSION)["correct"] is not None:
                self.reveal = "feedback"
        elif self.mode == "mission_result" and key == "ENTER":
            self.show_mode(None)

    def feed_items(self):
        if not self.inbox_view:
            return self.learning.sources()
        return sorted(path for path in self.inbox.iterdir()
                      if path.is_file() and not path.is_symlink()
                      and path.suffix.lower() in (".json", ".md", ".txt"))

    def mode_key(self, key):
        if key in ("ESC", "q"):
            if self.mode == "feed" and self.source:
                self.source = None
                self.scroll = 0
            elif self.mode in ("briefing", "mission_result") and key == "ESC":
                self.show_mode("missions")
                self.reveal = self.mission_cursor
            else:
                self.show_mode(None)
            return
        if key in ("PAGEUP", "PAGEDOWN"):
            self.scroll = max(0, self.scroll + (-self.page_size if key == "PAGEUP" else self.page_size))
            self.reveal = None
            return
        if self.mode in ("missions", "briefing", "mission_result"):
            self.mission_key(key)
            return
        if self.mode == "practice_result":
            if key == "ENTER":
                self.open_quiz(new_round=True)
            elif key in ("UP", "DOWN"):
                self.scroll = max(0, self.scroll + (-1 if key == "UP" else 1))
            return
        if self.mode == "progress":
            return
        if self.mode == "feed":
            if self.source:
                return
            if key == "t":
                self.inbox_view = not self.inbox_view
                self.feed_cursor = self.scroll = 0
                self.notice = ""
                return
            items = self.feed_items()
            if not items:
                return
            if key in ("UP", "DOWN"):
                self.feed_cursor = (self.feed_cursor + (-1 if key == "UP" else 1)) % len(items)
                self.reveal = self.feed_cursor
            elif key == "ENTER":
                item = items[min(self.feed_cursor, len(items) - 1)]
                if self.inbox_view:
                    self.learning.ingest(item)
                    self.notice = f"Imported {item.name}"
                else:
                    self.source = item
                    self.scroll = 0
                    self.reveal = None
            return

        slot = self.quiz_slot
        if key == "n":
            session = self.learning.session(slot)
            if session is None or session["correct"] is not None:
                if slot == MISSION:
                    if not self.learning.advance_mission():
                        self.show_mode("mission_result")
                        return
                elif not self.learning.start(advance=True, review=slot == REVIEW):
                    if slot == PRACTICE and self.learning.practice_round():
                        self.show_mode("practice_result")
                    elif slot == REVIEW:
                        self.notice = "No more reviews due today."
                    return
                self.notice = ""
                self.scroll = 0
                self.reveal = None
        elif key == "ENTER":
            result = self.learning.submit(slot)
            if result and result["correct"] is not None:
                self.notice = ""
                self.reveal = "feedback"
        elif key in ("UP", "DOWN", " ", "a", "b", "c", "d"):
            session = self.learning.session(slot)
            if session and session["correct"] is not None and key in ("UP", "DOWN"):
                self.scroll = max(0, self.scroll + (-1 if key == "UP" else 1))
                return
            self.learning.select(key.upper(), slot)
            session = self.learning.session(slot)
            if session and session["correct"] is None:
                self.notice = ""
                self.reveal = session["cursor"]

    def learning_frame(self, put, panel, body, footer, cols, rows, theme):
        width = min(cols - 2, 112)
        x = (cols - width) // 2
        lines = []
        anchor = None

        def add(value="", ink=None, wrap=True, indent=""):
            value = cell_text(value)
            for line in value.expandtabs(4).split("\n"):
                chunks = (textwrap.wrap(line, width - 4, replace_whitespace=False,
                                        initial_indent=indent, subsequent_indent=indent)
                          if wrap else [line[i:i + width - 4] for i in range(0, len(line), width - 4)])
                lines.extend((piece, ink) for piece in chunks or [""])

        slot = self.quiz_slot
        if slot:
            title = {PRACTICE: "QUIZ MODE / PRACTICE", REVIEW: "REVIEW MODE", MISSION: "MISSION QUIZ"}[slot]
            session = self.learning.session(slot)
            run = self.learning.mission_run() if slot == MISSION else None
            practice = self.learning.practice_round() if slot == PRACTICE else None
            if run:
                mission = MISSIONS_BY_ID[run["mission"]]
                stage = run["answered"] + int(session["correct"] is None)
                title += (f" / {mission.id} / QUESTION {stage} OF {len(run['questions'])}" if cols >= 58
                          else f" / {mission.id} / {stage} OF {len(run['questions'])}")
                add(mission.name, theme.accent)
                add(f"Objective · {mission.objective}", theme.muted)
            if session:
                q = session["data"]
                submitted = session["correct"] is not None
                multiple = q["type"] == "multiple_choice"
                if practice:
                    number, total = practice["position"] + 1, len(practice["questions"])
                    title = (f"{title} / EXERCISE {number:03d} OF {total}" if cols >= 68
                             else f"PRACTICE / {number:03d} OF {total}")
                elif not run:
                    title += f"  /  EXERCISE {session['number']:03d}"
                add(f"{q['topic']} / {q['subtopic']}  |  Difficulty {q['difficulty']}/5", theme.secondary)
                if not submitted:
                    add("Select all that apply" if multiple else "Select one answer", theme.muted)
                add(q["question"], theme.text)
                if q["snippet"]:
                    add(q["snippet"], theme.secondary, wrap=False)
                reasons = q.get("option_explanations")
                displayed_options = () if submitted and reasons else q["options"].items()
                if displayed_options:
                    add()
                for index, (key, option) in enumerate(displayed_options):
                    selected = key in session["selected"]
                    correct = submitted and key in q["correct_answers"]
                    mark = "✓" if correct else "×" if submitted and selected else "●" if selected else "○"
                    pointer = "▸" if session["cursor"] == index else " "
                    if self.reveal == index:
                        anchor = len(lines)
                    add(f"{pointer} {mark} {key}. {option}", theme.accent if correct or selected else theme.text)
                if submitted:
                    add()
                    if self.reveal == "feedback":
                        self.scroll = len(lines)
                    verdict = "CORRECT" if session["correct"] else "INCORRECT"
                    add(f"{verdict}  |  +{session['xp']} XP  |  Review {session['next_review']}", theme.accent)
                    add(f"Correct: {', '.join(q['correct_answers'])}", theme.secondary)
                    if reasons:
                        add()
                        add("ANSWER REVIEW", theme.accent)
                        for index, (key, option) in enumerate(q["options"].items()):
                            if index:
                                add()
                            correct = key in q["correct_answers"]
                            state = "Correct" if correct else "Incorrect"
                            picked = " · Selected" if key in session["selected"] else ""
                            add(f"{key}. {state}{picked} — {option}", theme.secondary if correct else theme.text)
                            add(reasons[key], indent="  ")
                    else:
                        add(q["explanation"])
            else:
                submitted = False
                add("No reviews are due today." if slot == REVIEW else
                    "No questions available. Import a question pack in Feed.",
                    theme.secondary)
            last_exercise = practice and practice["position"] + 1 == len(practice["questions"])
            next_label = "Results" if last_exercise or (run and run["finished"]) else "Next"
            if not session:
                commands = (("Esc", "Back"),)
            elif submitted:
                commands = (("N", next_label), ("Esc", "Back"))
            else:
                commands = (("↑↓", "Move"), ("A–D", "Pick"), ("Enter", "Submit"), ("Esc", "Back"))
            if submitted:
                hint = "N opens results" if next_label == "Results" else ""
            elif session and multiple:
                hint = "Space toggles the highlighted option"
            else:
                hint = "Enter submits the highlighted answer" if session else ""
        elif self.mode == "practice_result":
            title = "PRACTICE RESULTS"
            round_ = self.learning.practice_round()
            total, correct = len(round_["questions"]), round_["correct"]
            add(f"{total} / {total} answered", theme.accent)
            add(f"{correct} correct  /  {total - correct} incorrect")
            add(f"Accuracy {100 * correct // total}%  /  +{round_['xp']} XP", theme.secondary)
            topics = self.learning.practice_topics()
            add()
            add("ACCURACY BY TOPIC", theme.accent)
            covered = sum(topic["answered"] for topic in topics)
            if covered < total:
                add(f"Topic breakdown covers {covered}/{total} answers from this round.", theme.muted)
            for topic in topics:
                correct, answered = topic["correct"], topic["answered"]
                add(f"{100 * correct // answered:3d}%   {correct}/{answered}   {topic['topic']}")
            commands = (("Enter", "New quiz"), ("Esc", "Back"))
            hint = ""
        elif self.mode in ("missions", "briefing", "mission_result"):
            mission = MISSIONS[self.mission_cursor]
            run = self.learning.mission_run(mission.id)
            if self.mode == "missions":
                title = "MISSION SELECT"
                for i, entry in enumerate(MISSIONS):
                    if self.reveal == i:
                        anchor = len(lines)
                    current = self.learning.mission_run(entry.id)
                    if current and current["finished"]:
                        status = "Completed" if current["correct"] >= current["passing_score"] else "Failed"
                    elif current:
                        status = f"{current['answered']}/{len(current['questions'])} answered"
                    else:
                        status = "Available" if self.learning.mission_available(entry) else "Requires bundled packs"
                    selected = i == self.mission_cursor
                    add(f"{'▸' if selected else ' '} {entry.id}  {entry.name}  /  {status}",
                        theme.accent if selected else theme.text)
                commands = (("↑↓", "Move"), ("Enter", "Briefing"), ("H", "Last run"), ("Esc", "Back"))
                hint = "Choose an operation"
            elif self.mode == "briefing":
                title = f"MISSION BRIEFING / {mission.id}"
                add(mission.name, theme.accent)
                add(mission.briefing)
                add(f"Objective · {mission.objective}", theme.secondary)
                add(f"Focus · {mission.focus}", theme.muted)
                add(f"{len(mission.questions)} questions  /  Difficulty {mission.difficulty}/5")
                add(f"Pass with {mission.passing_score} correct  /  First completion +{mission.reward} XP")
                if run and not run["finished"]:
                    add(f"Progress · {run['answered']}/{len(run['questions'])} answered", theme.accent)
                active = self.learning.mission_run()
                hint = ""
                if active and not active["finished"] and active["mission"] != mission.id:
                    hint = f"Resume {MISSIONS_BY_ID[active['mission']].name} first."
                elif not self.learning.mission_available(mission):
                    hint = "The bundled packs are required."
                commands = (("Esc", "Back"),)
                if not hint:
                    commands = (("Enter", "Resume" if run and not run["finished"] else "Start mission"),) + commands
            else:
                title = f"MISSION SUMMARY / {mission.id}"
                add(mission.name, theme.accent)
                total = len(run["questions"])
                correct = run["correct"]
                verdict = ("COMPLETED" if correct >= run["passing_score"] else "FAILED") if run["finished"] else "IN PROGRESS"
                add(f"{verdict}  /  {run['answered']}/{total} answered", theme.accent)
                accuracy = f"{100 * correct // run['answered']}%" if run["answered"] else "—"
                add(f"Accuracy {accuracy}  /  {correct} correct  /  +{run['xp']} XP")
                add(f"Mission bonus +{run['bonus']} XP", theme.secondary)
                if run["weak"]:
                    add("Review · " + ", ".join(run["weak"]))
                    add("Missed questions enter the review schedule.", theme.muted)
                commands = (("Enter", "Dashboard"), ("Esc", "Missions"))
                hint = ""
        elif self.mode == "progress":
            summary = self.learning.summary()
            commands = (("Pg↑↓", "Scroll"), ("Esc", "Back"))
            hint = "Local learning record"
            if self.focus == 2:
                title = "EXERCISE HISTORY"
                for attempt in reversed(self.learning.history()):
                    result = "Correct" if attempt["correct"] else "Incorrect"
                    add(f"#{attempt['number']:03d}  {attempt['answered']}  {result}  +{attempt['xp']} XP")
                    add(f"{attempt['topic']} / {attempt['question']}  |  Review {attempt['next_review']}", theme.muted)
                if not summary["answered"]:
                    add("No answers recorded.")
            elif self.focus == 3:
                title = "REVIEW SCHEDULE"
                reviews = self.learning.reviews()
                today = self.learning.today().isoformat()
                for row in reviews:
                    status = "Due now" if row["due"] <= today else row["due"]
                    add(f"{status}  |  {row['topic']}  ({row['pending']} questions)")
                if not reviews:
                    add("No scheduled reviews.")
            else:
                title = "TOPIC PERFORMANCE"
                for name, (state, correct, total) in summary["topics"].items():
                    score = f"  |  {correct}/{total} correct ({correct * 100 // total}%)" if total else ""
                    add(f"{name}  |  {state}{score}")
                if not summary["topics"]:
                    add("No topics introduced. Import material in Feed.")
        else:
            title = "FEED MODE / " + ("INBOX" if self.inbox_view else "LIBRARY")
            if self.source:
                source = self.source
                add(source["filename"], theme.accent)
                add(source["id"], theme.muted)
                add(f'{source["topic"]}  |  Imported {source["imported"]}', theme.secondary)
                add("Subtopics: " + (", ".join(json.loads(source["subtopics"])) or "None"))
                add(f'{source["question_count"]} validated questions')
                add()
                if source["note"]:
                    add(source["note"])
                commands = (("Pg↑↓", "Scroll"), ("Esc", "Back"))
            else:
                items = self.feed_items()
                if not items:
                    add("No files in the inbox." if self.inbox_view else "No sources imported yet.", theme.secondary)
                    add("Copy .json, .md or .txt files into the local study inbox, then use T.")
                    add(str(self.inbox), theme.muted)
                    add("Notes need a Topic: header. Notes never create quiz questions.")
                for i, item in enumerate(items):
                    selected = i == self.feed_cursor
                    if self.reveal == i:
                        anchor = len(lines)
                    label = item.name if self.inbox_view else f"{item['filename']}  /  {item['topic']}  /  {item['question_count']} questions"
                    add(("▸ " if selected else "  ") + label, theme.accent if selected else None)
                commands = (("↑↓", "Move"), ("T", "Switch"), ("Enter", "Import" if self.inbox_view else "Open"), ("Esc", "Back"))
            hint = "Local study sources"

        height = min(rows - 8, max(10, len(lines) + 5))
        visible = height - 5
        self.page_size = max(1, visible - 1)
        if anchor is not None:
            if anchor < self.scroll:
                self.scroll = anchor
            elif anchor >= self.scroll + visible:
                self.scroll = anchor - visible + 1
        self.reveal = None
        self.scroll = min(self.scroll, max(0, len(lines) - visible))
        panel(x, 6, width, height, title, active=True)
        for row, (text, ink) in enumerate(lines[self.scroll:self.scroll + visible], 7):
            body(x, row, width, text, ink)
        if len(lines) > visible:
            arrows = self.mode == "practice_result" or (slot and submitted)
            scroll_keys = "↑↓ / Pg↑↓" if arrows else "Pg↑/Pg↓"
            hint = f"{scroll_keys} scroll  |  {self.scroll + 1}–{self.scroll + visible} / {len(lines)}"
        body(x, height + 2, width, hint, theme.muted)
        body(x, height + 3, width, cell_text(self.notice), theme.accent)
        label = {PRACTICE: "Practice", REVIEW: "Review", MISSION: "Mission"}.get(slot)
        footer(commands, label or self.mode.replace("_", " ").capitalize())

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

        if self.mode:
            self.learning_frame(put, panel, body, footer, cols, rows, t)
            return "".join(frame)

        summary = self.learning.summary()
        earned = summary["xp"]
        level = self.learning.level(earned)
        unlocked_stage = self.learning.unlocked_stage(earned)
        preview = self.preview_stage is not None
        stage = self.preview_stage if preview else unlocked_stage
        operator = self.preview_operator if preview else self.learning.operator()
        operator_name = OPERATORS[operator].upper()
        xp = (XP + earned) % XP_GOAL
        topics = tuple(f"{cell_text(name)}: {state}" + (f"  {right}/{total}" if total else "")
                       for name, (state, right, total) in summary["topics"].items())
        answered = summary["answered"]
        correct = summary["correct"]
        accuracy = f"{correct * 100 // answered}%" if answered else "—"
        pending = self.learning.reviews()
        today = self.learning.today().isoformat()
        reviews = tuple(f"{'Due now' if row['due'] <= today else row['due']}  {cell_text(row['topic'])} ({row['pending']})"
                        for row in pending)
        latest = self.learning.mission_run()
        completed = self.learning.completed_missions()
        gear_unlocked = tuple(completed >= threshold for _, _, threshold in GEAR)
        mission = MISSIONS_BY_ID[latest["mission"]] if latest else MISSIONS[self.mission_cursor]
        if latest:
            status = ("Completed" if latest["correct"] >= latest["passing_score"] else "Failed"
                      ) if latest["finished"] else "In progress"
            status += f"  /  {latest['answered']}/{len(latest['questions'])} answered"
        else:
            status = "Ready to start" if self.learning.mission_available(mission) else "Bundled packs required"
        mission_lines = (f"{mission.id} / {mission.name}", mission.objective, status)
        panels = (
            ("CURRENT MISSION", mission_lines),
            ("RECENT PROGRESS", (f"Exercises {answered}   Accuracy {accuracy}",
                                 f"Correct {correct}   Incorrect {answered - correct}",
                                 f"Streak {summary['streak']}   +{earned:,} XP")),
            ("NEXT REVIEW", reviews or ("No reviews scheduled",)),
            ("STUDIED TOPICS", topics),
            ("GEAR", tuple(name if unlocked else f"{name} (Locked)"
                           for (name, _, _), unlocked in zip(GEAR, gear_unlocked))),
        )

        # Draw the study windows first. The portrait is independent of focus and panel paging.
        y0, end = 6, rows - 2
        left = 1
        profile_w = min(43, cols * 31 // 100) if not compact else cols // 3
        right = left + profile_w + 1
        right_w = cols - right - 1

        def study(index, x, y, width, height):
            title, lines = panels[index]
            panel(x, y, width, height, title, active=self.focus == index + 1)
            for i, line in enumerate(lines[:height - 2]):
                prefix = "▪ " if index in (1, 4) else ""
                body(x, y + i + 1, width, prefix + line,
                     t.accent if index == 0 and i == 0 else t.text)
                if index == 0 and i == 0:
                    put(x + 2, y + 1, line[:width - 4], t.accent, row_bg(y + 1), bold=True)

        if compact:
            count = min(5, (end - y0) // 5)
            first = min(self.offset, 5 - count)
            if self.focus:
                first = min(self.focus - 1, max(first, self.focus - count))
            for i in range(first, first + count):
                y = y0 + (i - first) * 5
                study(i, right, y, right_w, 5)
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
            panel(right, gear_y, right_w, gear_h, panels[4][0], active=self.focus == 5)
            if mission_h >= 9:
                panel(right, y0, right_w, mission_h, panels[0][0], active=self.focus == 1)
                detail_x = right + right_w - 30
                brief_w = detail_x - right
                put(right + 2, y0 + 1, f" {mission.id} ", t.background, t.accent, bold=True)
                put(right + 8, y0 + 1, mission.name, t.accent, row_bg(y0 + 1), bold=True)
                for i, line in enumerate(textwrap.wrap(mission.briefing, brief_w - 4)[:mission_h - 7], 3):
                    body(right, y0 + i, brief_w, line)
                body(right, y0 + mission_h - 3, brief_w, mission.objective, t.secondary)
                body(right, y0 + mission_h - 2, brief_w, status, t.accent)
                for i in range(1, mission_h - 1):
                    put(detail_x, y0 + i, "│", t.shadow, row_bg(y0 + i))
                body(detail_x, y0 + 1, 30, "MISSION DETAILS", t.secondary)
                body(detail_x, y0 + 3, 30, f"Difficulty {mission.difficulty}/5")
                body(detail_x, y0 + 4, 30, f"Questions  {len(mission.questions)}")
                body(detail_x, y0 + 5, 30, f"First pass +{mission.reward} XP")
                total = len(latest["questions"]) if latest else len(mission.questions)
                done = latest["answered"] if latest else 0
                body(detail_x, y0 + mission_h - 3, 30, f"Progress {done}/{total}", t.secondary)
                meter(detail_x + 2, y0 + mission_h - 2, total, done)
            else:
                study(0, right, y0, right_w, mission_h)
            study(1, right, mid_y, mid_w, mid_h)
            study(2, review_x, mid_y, review_w, mid_h)
            for i, attempt in enumerate(summary["recent"][:max(0, mid_h - 5)], 4):
                outcome = "Correct" if attempt["correct"] else "Incorrect"
                body(right, mid_y + i, mid_w,
                     f"#{attempt['number']:03d}  {outcome}  +{attempt['xp']} XP", t.muted)

            icons = (
                ("▀▄       ", "  ▀▀▀▄   ", "      ▀▄ "),
                (" ▄▄▄▄▄▄▄ ", "█▪▪▪▪▪▪▪█", " ▀▀▀▀▀▀▀ "),
                (" ▄▄▄▄▄▄▄ ", "█▁▃▁▆▂▅▁█", " ▀▀▀▀▀▀▀ "),
            )
            tile_w = (right_w - 4) // 3
            active = self.focus == 5
            for i, ((name, role, threshold), icon) in enumerate(zip(GEAR, icons)):
                unlocked = gear_unlocked[i]
                if not unlocked:
                    role = f"PASS {threshold} MISSION" + ("S" if threshold != 1 else "")
                ink = (t.accent if active else t.text) if unlocked else t.muted
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
                    put(label_x, gear_y + 3, name.upper(), ink, card_bg, bold=True)
                    put(label_x, gear_y + 5, role, t.muted, card_bg)
                else:
                    label = name.upper()
                    if not unlocked and gear_h == 7:
                        label = f"□ {label}"[:width - 2]
                    put(x + 1, gear_y + 5, label.center(width - 2), ink, card_bg, bold=True)
                    if gear_h == 8:
                        put(x + 1, gear_y + 6, role.center(width - 2), t.muted, card_bg)

        panel(left, y0, profile_w, profile_end - y0, "PREVIEW" if preview else "OPERATOR",
              active=self.focus == 0)
        portrait_y = y0 + 1
        portrait_rows = profile_end - portrait_y - 5
        portrait_columns = profile_w - 2
        palette = portrait_palette(t)
        image = sixel(stage, palette, pixels, portrait_columns, portrait_rows, operator) if pixels else ""
        if image:
            frame.extend((f"{ESC}{portrait_y + 1};{left + gutter + 2}H", image))
        else:
            for y, pairs in enumerate(half_blocks(stage, portrait_columns, portrait_rows, operator), portrait_y):
                x = left + 1 + (portrait_columns - len(pairs)) // 2
                for (top, bottom), cells in groupby(pairs):
                    length = sum(1 for _ in cells)
                    put(x, y, (" " if top == bottom else "▀") * length, palette[top], palette[bottom])
                    x += length

        stats_y = profile_end - 5
        if profile_w >= 25:
            put(left + 1, stats_y, f" ▸ {operator_name}".ljust(profile_w - 2), t.background, t.secondary, bold=True)
            put(left + profile_w - 11, stats_y, f" LEVEL {level:02d} ", t.background, t.accent, bold=True)
        else:
            put(left + 1, stats_y, f" {operator_name} / LV {level:02d}"[:profile_w - 2], t.background, t.secondary, bold=True)
        if preview:
            state = "Locked" if stage > unlocked_stage else "Unlocked"
            progress = f"{stage + 1}/{len(STAGES)} {state} · {STAGES[stage]}"
        else:
            progress = f"{stage + 1}/{len(STAGES)} Equipped · {STAGES[stage]}"
        body(left, stats_y + 1, profile_w, progress, t.secondary)
        body(left, stats_y + 2, profile_w, f"XP {xp:,}/{XP_GOAL:,}", t.text)
        segments = min(16, (profile_w - 3) // 2)
        meter(left + 2, stats_y + 3, segments, xp * segments // XP_GOAL)
        if profile_w >= 38:
            put(left + profile_w - 5, stats_y + 3, "▰▰", t.secondary, row_bg(stats_y + 3))
        if not compact and profile_w >= 34:
            put(left + profile_w - 6, stats_y + 2, f"{xp * 100 // XP_GOAL:>2}%", t.accent, t.panel)
        focus = ("Operator", "Mission", "Progress", "Review", "Topics", "Gear")[self.focus]
        if self.focus in (1, 2, 3, 4):
            focus += "  /  Enter details"
        commands = (("M", "Missions"), ("X", "Practice"), ("R", "Review"), ("F", "Feed"),
                    ("S", "Theme"), ("Q", "Quit"))
        if cols >= 110:
            commands += (("A", "Operator"), ("E", "Preview"), ("Tab/↑↓", "Panels"))
        elif cols >= 68:
            focus += "  /  A Swap  E Preview  Tab Panels"
        else:
            commands = (("M", "Missions"), ("X", "Practice"), ("R", "Review"), ("A", "Swap"), ("Q", "Quit"))
            focus += "  /  F Feed  E Preview  S Theme"
        if preview:
            focus = "E Next  A Preview operator  Esc Exit"
        footer(commands, focus)
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
            b"\x1b[Z": "UP", b"\t": "TAB", b"\x1b": "ESC",
            b"\r": "ENTER", b"\n": "ENTER", b"\x1b[5~": "PAGEUP", b"\x1b[6~": "PAGEDOWN"}
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
                if token == b"\x03" or (token.lower() == b"q" and not app.mode):
                    return
                app.key(keys.get(token, token.decode("ascii", errors="replace")))
            previous = None
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, saved)
        write(ESC + "0m" + ESC + "?25h" + ESC + "?1049l")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="CCNA Network Ops 1.0.0rc1")
    parser.add_argument("--avatar", choices=("text", "sixel"), default="sixel",
                        help="probe for Sixel by default, or force Unicode with text")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--feed", type=Path, metavar="FILE", help="import a local question pack or note")
    actions.add_argument("--activate", metavar="TOPIC", help="introduce a named topic without adding questions")
    parser.add_argument("--topic", help="topic for a Markdown or text note")
    parser.add_argument("--subtopic", help="optional subtopic for a note")
    parser.add_argument("--no-bundled", action="store_true", help="launch using only the study database")
    args = parser.parse_args()
    if (args.topic is not None or args.subtopic is not None) and args.feed is None:
        parser.error("--topic and --subtopic require --feed")
    if not (args.feed or args.activate or (sys.stdin.isatty() and sys.stdout.isatty())):
        parser.error("an interactive terminal is required")
    try:
        weights_file = CONFIG.with_name("category-weights.json")
        weights = json.loads(weights_file.read_text()) if weights_file.exists() else None
        with closing(Learning(DATA / "learning.sqlite3", weights)) as learning:
            if args.feed:
                learning.ingest(args.feed, args.topic, args.subtopic)
                print(f"Imported {cell_text(args.feed.name)}")
            elif args.activate:
                learning.activate(args.activate)
                print(f"Introduced {cell_text(args.activate)}")
            else:
                if not args.no_bundled:
                    load_bundled(learning)
                inbox = DATA / "inbox"
                inbox.mkdir(exist_ok=True)
                run(Dashboard(CONFIG, learning, inbox), args.avatar)
    except (LearningError, OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Study data: {cell_text(str(error))}\n")
