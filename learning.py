"""Local question validation, quiz state, progression and scheduled review."""

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from random import expovariate
import re
import sqlite3
import unicodedata

from avatar import FIRST_LEVEL, OPERATORS, stage_for_level, valid_index
from model import XP, XP_GOAL
from missions import MISSIONS_BY_ID


WEIGHTS = {
    "networking_theory": 35, "ios_commands": 20, "ios_output": 15,
    "troubleshooting": 15, "subnetting": 15,
}
INTERVALS = (1, 3, 7, 14, 30)
KEYS = "ABCD"
MAX_SOURCE_BYTES = 2_000_000

PRACTICE, REVIEW, MISSION = 1, 2, 3
PRACTICE_LENGTH = 100

SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (name TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY, filename TEXT NOT NULL, imported TEXT NOT NULL,
    topic TEXT NOT NULL REFERENCES topics(name), kind TEXT NOT NULL,
    version INTEGER, subtopics TEXT NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY, source TEXT NOT NULL REFERENCES sources(id),
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    number INTEGER PRIMARY KEY, question TEXT NOT NULL REFERENCES questions(id),
    answered TEXT NOT NULL, selected TEXT NOT NULL, correct INTEGER NOT NULL,
    xp INTEGER NOT NULL, next_review TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
    question TEXT PRIMARY KEY REFERENCES questions(id), due TEXT NOT NULL,
    step INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS active (
    slot INTEGER PRIMARY KEY CHECK (slot BETWEEN 1 AND 3), number INTEGER NOT NULL,
    question TEXT NOT NULL REFERENCES questions(id), cursor INTEGER NOT NULL,
    selected TEXT NOT NULL
);
-- Legacy preview settings are retained for compatibility with older releases.
CREATE TABLE IF NOT EXISTS profile (
    slot INTEGER PRIMARY KEY CHECK (slot = 1), avatar INTEGER
);
CREATE TABLE IF NOT EXISTS operator_choice (
    slot INTEGER PRIMARY KEY CHECK (slot = 1), operator INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mission_runs (
    id INTEGER PRIMARY KEY, mission TEXT NOT NULL, questions TEXT NOT NULL,
    passing_score INTEGER NOT NULL, reward INTEGER NOT NULL,
    finished TEXT, bonus INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_mission ON mission_runs((1)) WHERE finished IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS one_mission_bonus ON mission_runs(mission) WHERE bonus > 0;
CREATE TABLE IF NOT EXISTS mission_answers (
    run INTEGER NOT NULL REFERENCES mission_runs(id), position INTEGER NOT NULL,
    attempt INTEGER NOT NULL UNIQUE REFERENCES attempts(number),
    PRIMARY KEY (run, position)
);
CREATE TABLE IF NOT EXISTS practice_round (
    slot INTEGER PRIMARY KEY CHECK (slot = 1), questions TEXT NOT NULL,
    position INTEGER NOT NULL, correct INTEGER NOT NULL, xp INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS practice_answers (
    attempt INTEGER PRIMARY KEY REFERENCES attempts(number)
);
CREATE TABLE IF NOT EXISTS attempt_order (
    sequence INTEGER PRIMARY KEY, attempt INTEGER NOT NULL UNIQUE REFERENCES attempts(number)
);
"""


class LearningError(ValueError):
    """An actionable local content or quiz error."""


def clean_text(value, label, limit, multiline=False):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise LearningError(f"{label}: expected nonempty text (maximum {limit} characters)")
    if any(unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
           and not (multiline and c in "\n\r\t") for c in value):
        raise LearningError(f"{label}: contains unsupported control characters")
    return value.strip()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LearningError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_pack(text):
    """Validate the pack format and return normalized questions in display order."""
    try:
        pack = json.loads(text, object_pairs_hook=unique_object)
    except (json.JSONDecodeError, RecursionError) as error:
        raise LearningError(f"Invalid JSON: {error}") from error
    if not isinstance(pack, dict) or type(pack.get("version")) is not int or pack["version"] < 1:
        raise LearningError("Pack: expected an object with a positive integer version")
    pack_id = clean_text(pack.get("pack_id"), "pack_id", 80)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", pack_id):
        raise LearningError("pack_id: use letters, digits, dots, underscores or hyphens")
    topic = clean_text(pack.get("topic"), "topic", 70)
    entries = pack.get("questions")
    if not isinstance(entries, list) or not entries:
        raise LearningError("questions: expected a nonempty list")
    questions = {}
    for index, item in enumerate(entries, 1):
        label = f"Question {index}"
        if not isinstance(item, dict):
            raise LearningError(f"{label}: expected an object")
        qid = clean_text(item.get("id"), f"{label} id", 100)
        if qid in questions:
            raise LearningError(f"{label}: duplicate question ID {qid}")
        label = f"{label} ({qid})"
        category, kind, difficulty = (item.get(k) for k in ("category", "type", "difficulty"))
        if not isinstance(category, str) or category not in WEIGHTS:
            raise LearningError(f"{label}: category must be one of {', '.join(WEIGHTS)}")
        if kind not in ("single_choice", "multiple_choice"):
            raise LearningError(f"{label}: invalid question type")
        if type(difficulty) is not int or not 1 <= difficulty <= 5:
            raise LearningError(f"{label}: difficulty must be an integer from 1 to 5")
        options = item.get("options")
        if not isinstance(options, dict) or not 2 <= len(options) <= 4 or set(options) != set(KEYS[:len(options)]):
            raise LearningError(f"{label}: use 2–4 consecutive alternatives starting at A")
        options = {key: clean_text(options[key], f"{label} option {key}", 1000) for key in sorted(options)}
        if len({" ".join(option.split()).casefold() for option in options.values()}) != len(options):
            raise LearningError(f"{label}: alternatives must be distinct")
        answers = item.get("correct_answers")
        if (not isinstance(answers, list) or not all(isinstance(key, str) and key in options for key in answers)
                or len(answers) != len(set(answers)) or not (
                    len(answers) == 1 if kind == "single_choice" else 2 <= len(answers) <= len(options))):
            raise LearningError(f"{label}: correct_answers must contain distinct valid keys matching {kind}")
        snippet = item.get("snippet")
        questions[qid] = {
            "id": qid, "topic": topic, "subtopic": clean_text(item.get("subtopic"), f"{label} subtopic", 100),
            "category": category, "difficulty": difficulty, "type": kind, "options": options,
            "correct_answers": sorted(answers),
            "question": clean_text(item.get("question"), f"{label} question", 4000, True),
            "explanation": clean_text(item.get("explanation"), f"{label} explanation", 6000, True),
            "snippet": clean_text(snippet, f"{label} snippet", 6000, True) if snippet is not None else "",
        }
        if "option_explanations" in item:
            reasons = item["option_explanations"]
            if not isinstance(reasons, dict) or reasons.keys() != options.keys():
                raise LearningError(f"{label}: option_explanations must cover exactly the available options")
            questions[qid]["option_explanations"] = {
                key: clean_text(reasons[key], f"{label} explanation for {key}", 1200, True)
                for key in options
            }
    return pack_id, pack["version"], topic, questions


class Learning:
    def __init__(self, path, weights=None, today=None):
        if weights is not None and not isinstance(weights, dict):
            raise LearningError("Category weights must be a JSON object")
        self.weights = dict(WEIGHTS if weights is None else weights)
        if set(self.weights) != set(WEIGHTS) or any(type(v) is not int or v <= 0 for v in self.weights.values()):
            raise LearningError("Category weights must be positive integers for all five categories")
        self.today = today or (lambda: datetime.now(timezone.utc).date())
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None)
        try:
            self.db.row_factory = sqlite3.Row
            self.db.execute("PRAGMA foreign_keys = ON")
            with self.transaction():
                version = self.db.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, 2):
                    raise LearningError("Learning database belongs to a newer application version")
                if version == 1:
                    self.db.execute("ALTER TABLE active RENAME TO previous_active")
                for statement in SCHEMA.split(";"):
                    if statement.strip():
                        self.db.execute(statement)
                if version == 1:
                    self.db.execute("INSERT INTO active SELECT * FROM previous_active")
                    self.db.execute("DROP TABLE previous_active")
                    self.db.execute("""
                        INSERT INTO attempt_order(attempt) SELECT number FROM attempts ORDER BY number
                    """)
                # The active slot identifies the latest answer even in older rounds.
                self.db.execute("""
                    INSERT OR IGNORE INTO practice_answers(attempt)
                    SELECT a.number FROM active a JOIN attempts h ON h.number = a.number
                    JOIN practice_round p ON p.slot = a.slot
                    WHERE a.slot = ?
                """, (PRACTICE,))
                self.db.execute("PRAGMA user_version = 2")
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def activate(self, topic):
        topic = clean_text(topic, "topic", 70)
        self.db.execute("INSERT OR IGNORE INTO topics VALUES (?)", (topic,))

    def ingest(self, path, topic=None, subtopic=None, *, keep_existing=False, feedback_only=False):
        path = Path(path)
        kind = path.suffix.lower()
        if kind not in (".json", ".md", ".txt"):
            raise LearningError("Import a .json question pack, .md note or .txt note")
        filename = clean_text(path.name, "source filename", 255)
        with path.open("rb") as source:
            raw = source.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise LearningError("Source exceeds the 2 MB import limit")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeError as error:
            raise LearningError("Source must be UTF-8 text") from error
        if kind == ".json":
            if topic is not None or subtopic is not None:
                raise LearningError("Question packs declare their own topic and subtopics")
            pack_id, version, topic, questions = parse_pack(text)
            identifier = f"pack:{pack_id}"
            subtopics = sorted({q["subtopic"] for q in questions.values()})
            note = None
        else:
            note = clean_text(text, "note", MAX_SOURCE_BYTES, True)
            headers = re.match(r"Topic: ([^\r\n]+)(?:\r?\nSubtopic: ([^\r\n]+))?", note, re.I)
            topic = clean_text(topic or (headers[1] if headers else None), "note topic (--topic or Topic: header)", 70)
            subtopic = subtopic or (headers[2] if headers else None)
            subtopics = [clean_text(subtopic, "note subtopic", 100)] if subtopic else []
            fingerprint = json.dumps([topic, subtopics, note]).encode()
            identifier = f"note:{sha256(fingerprint).hexdigest()}"
            version, questions = None, {}

        with self.transaction():
            if self.db.execute("SELECT 1 FROM sources WHERE id = ?", (identifier,)).fetchone():
                if keep_existing or feedback_only:
                    self._refresh_option_explanations(identifier, questions)
                    return identifier
                raise LearningError("Source already imported. Use a new pack ID for a different pack.")
            if feedback_only:
                return None
            for qid in questions:
                if self.db.execute("SELECT 1 FROM questions WHERE id = ?", (qid,)).fetchone():
                    raise LearningError(f"Question ID already exists: {qid}")
            self.activate(topic)
            self.db.execute("INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (identifier, filename, self.today().isoformat(), topic,
                             kind, version, json.dumps(subtopics), note))
            self.db.executemany("INSERT INTO questions VALUES (?, ?, ?)",
                                ((qid, identifier, json.dumps(q)) for qid, q in questions.items()))
        return identifier

    def _refresh_option_explanations(self, source, questions):
        """Add bundled feedback to existing questions without replacing their content."""
        for row in self.db.execute("SELECT id, data FROM questions WHERE source = ?", (source,)):
            incoming = questions.get(row["id"], {})
            reasons = incoming.get("option_explanations")
            if not reasons:
                continue
            existing = json.loads(row["data"])
            fields = ("question", "snippet", "options", "correct_answers")
            if any(existing.get(field) != incoming[field] for field in fields):
                continue
            if existing.get("option_explanations") != reasons:
                existing["option_explanations"] = reasons
                self.db.execute("UPDATE questions SET data = ? WHERE id = ?",
                                (json.dumps(existing), row["id"]))

    def sources(self):
        return self.db.execute("""
            SELECT s.*, (SELECT count(*) FROM questions q WHERE q.source = s.id) AS question_count
            FROM sources s ORDER BY imported DESC, filename, id
        """).fetchall()

    def session(self, slot=PRACTICE):
        row = self.db.execute("""
            SELECT a.*, q.data, h.correct, h.xp, h.next_review FROM active a
            JOIN questions q ON a.question=q.id LEFT JOIN attempts h ON a.number=h.number
            WHERE a.slot = ?
        """, (slot,)).fetchone()
        if row is None:
            return None
        return {**dict(row), "data": json.loads(row["data"]), "selected": json.loads(row["selected"])}

    def set_question(self, slot, qid):
        kind = self.db.execute("SELECT json_extract(data, '$.type') FROM questions WHERE id = ?",
                               (qid,)).fetchone()[0]
        number = self.db.execute("""
            SELECT coalesce(max(number), 0) + 1 FROM (
                SELECT number FROM attempts UNION ALL SELECT number FROM active
            )
        """).fetchone()[0]
        selected = '["A"]' if kind == "single_choice" else "[]"
        self.db.execute("INSERT OR REPLACE INTO active VALUES (?, ?, ?, 0, ?)",
                        (slot, number, qid, selected))
        return self.session(slot)

    def practice_round(self):
        row = self.db.execute("SELECT * FROM practice_round WHERE slot = 1").fetchone()
        if row:
            questions = json.loads(row["questions"])
            return {**dict(row), "questions": questions, "finished": row["position"] == len(questions)}
        return None

    def practice_topics(self):
        return self.db.execute("""
            SELECT s.topic, count(*) AS answered, sum(a.correct) AS correct
            FROM practice_answers p
            JOIN attempts a ON a.number = p.attempt
            JOIN questions q ON q.id = a.question
            JOIN sources s ON s.id = q.source
            GROUP BY s.topic ORDER BY s.topic COLLATE NOCASE, s.topic
        """).fetchall()

    def _start_practice(self, advance, new_round):
        current = self.session()
        round_ = self.practice_round()
        if round_ and round_["finished"] and not new_round:
            return None
        if round_ and not round_["finished"]:
            if not advance or current["correct"] is None:
                return current
            position = round_["position"] + 1
            self.db.execute("UPDATE practice_round SET position = ? WHERE slot = 1", (position,))
            if position == len(round_["questions"]):
                return None
            return self.set_question(PRACTICE, round_["questions"][position])

        # Retain an active question from saves that predate finite rounds.
        legacy = current if round_ is None else None
        candidates = self.db.execute("""
            SELECT id, json_extract(data, '$.category') AS category FROM questions ORDER BY id
        """).fetchall()
        if not candidates:
            return None
        if legacy:
            candidates = [row for row in candidates if row["id"] != legacy["question"]]
        counts = Counter(row["category"] for row in candidates)
        # An exponential sort draws a weighted sample without replacement.
        shuffled = sorted(candidates, key=lambda row: expovariate(
            self.weights[row["category"]] / counts[row["category"]]))
        questions = [legacy["question"]] if legacy else []
        questions.extend(row["id"] for row in shuffled[:PRACTICE_LENGTH - len(questions)])
        self.db.execute("DELETE FROM practice_answers")
        self.db.execute("INSERT OR REPLACE INTO practice_round VALUES (1, ?, 0, ?, ?)",
                        (json.dumps(questions), int(bool(legacy and legacy["correct"])),
                         (legacy["xp"] or 0) if legacy else 0))
        if legacy:
            if legacy["correct"] is not None:
                self.db.execute("INSERT INTO practice_answers VALUES (?)", (legacy["number"],))
            return legacy
        return self.set_question(PRACTICE, questions[0])

    def start(self, advance=False, *, review=False, new_round=False):
        with self.transaction():
            if not review:
                return self._start_practice(advance, new_round)
            session = self.session(REVIEW)
            if session and session["correct"] is None:
                due = self.db.execute("SELECT due FROM reviews WHERE question = ?", (session["question"],)).fetchone()
                if due is None or due[0] > self.today().isoformat():
                    self.db.execute("DELETE FROM active WHERE slot = ?", (REVIEW,))
                    session = None
            if session and (not advance or session["correct"] is None):
                return session
            target = self.select_review()
            return self.set_question(REVIEW, target["id"]) if target else None

    def select_review(self):
        today = self.today().isoformat()
        rows = self.db.execute("""
            SELECT q.data, r.due FROM reviews r JOIN questions q ON q.id=r.question
            WHERE r.due <= ?
        """, (today,)).fetchall()
        if not rows:
            return None
        candidates = [(json.loads(row["data"]), row["due"]) for row in rows]
        history = self.history()
        if history and len(candidates) > 1:
            candidates = [(q, due) for q, due in candidates if q["id"] != history[-1]["question"]]

        categories = {q["category"] for q, _ in candidates}
        weight_sum = sum(self.weights[key] for key in categories)
        counts = Counter(row["category"] for row in history if row["category"] in categories)
        opportunity = sum(counts.values()) + 1
        topic_count = Counter(row["topic"] for row in history)
        topic_correct = Counter(row["topic"] for row in history if row["correct"])
        misses = Counter(row["question"] for row in history if not row["correct"])
        seen = Counter(row["question"] for row in history)

        def priority(candidate):
            q, due = candidate
            category, topic, qid = q["category"], q["topic"], q["id"]
            deficit = self.weights[category] * opportunity - counts[category] * weight_sum
            accuracy = (topic_correct[topic] + 1) / (topic_count[topic] + 2)
            return (-deficit, accuracy, due or today, -misses[qid], seen[qid], q["difficulty"], qid)

        return min(candidates, key=priority)[0]

    def mission_available(self, mission):
        return all(self.db.execute("SELECT 1 FROM questions WHERE id = ?", (qid,)).fetchone()
                   for qid in mission.questions)

    def mission_run(self, mission_id=None):
        row = self.db.execute("""
            SELECT * FROM mission_runs WHERE ? IS NULL OR mission = ? ORDER BY id DESC LIMIT 1
        """, (mission_id, mission_id)).fetchone()
        if row is None:
            return None
        answers = self.db.execute("""
            SELECT a.correct, a.xp, q.data FROM mission_answers m
            JOIN attempts a ON a.number = m.attempt JOIN questions q ON q.id = a.question
            WHERE m.run = ? ORDER BY m.position
        """, (row["id"],)).fetchall()
        return {**dict(row), "questions": json.loads(row["questions"]), "answered": len(answers),
                "correct": sum(a["correct"] for a in answers),
                "xp": row["bonus"] + sum(a["xp"] for a in answers),
                "weak": tuple(dict.fromkeys(json.loads(a["data"])["subtopic"]
                                            for a in answers if not a["correct"]))}

    def start_mission(self, mission_id):
        mission = MISSIONS_BY_ID[mission_id]
        with self.transaction():
            current = self.mission_run()
            if current and not current["finished"]:
                raise LearningError("Finish the current operation before starting another.")
            if not self.mission_available(mission):
                raise LearningError("This operation requires its bundled question packs.")
            self.db.execute("""
                INSERT INTO mission_runs(mission, questions, passing_score, reward) VALUES (?, ?, ?, ?)
            """, (mission.id, json.dumps(mission.questions), mission.passing_score, mission.reward))
            return self.mission_question(mission.questions[0])

    def mission_question(self, qid):
        return self.set_question(MISSION, qid)

    def advance_mission(self):
        with self.transaction():
            run = self.mission_run()
            if not run or run["finished"]:
                return None
            session = self.session(MISSION)
            if session["correct"] is None:
                return session
            return self.mission_question(run["questions"][run["answered"]])

    def record_mission_answer(self, number):
        run = self.mission_run()
        self.db.execute("INSERT INTO mission_answers VALUES (?, ?, ?)",
                        (run["id"], run["answered"], number))
        run = self.mission_run()
        if run["answered"] == len(run["questions"]):
            rewarded = self.db.execute(
                "SELECT 1 FROM mission_runs WHERE mission = ? AND bonus > 0", (run["mission"],)
            ).fetchone()
            bonus = run["reward"] if run["correct"] >= run["passing_score"] and not rewarded else 0
            self.db.execute("UPDATE mission_runs SET finished = ?, bonus = ? WHERE id = ?",
                            (self.today().isoformat(), bonus, run["id"]))
            return bonus
        return 0

    def completed_missions(self):
        return self.db.execute("SELECT count(DISTINCT mission) FROM mission_runs WHERE bonus > 0").fetchone()[0]

    def earned_xp(self):
        return self.db.execute("""
            SELECT coalesce((SELECT sum(xp) FROM attempts), 0)
                 + coalesce((SELECT sum(bonus) FROM mission_runs), 0)
        """).fetchone()[0]

    def select(self, key, slot=PRACTICE):
        with self.transaction():
            session = self.session(slot)
            if not session or session["correct"] is not None:
                return
            q = session["data"]
            keys = list(q["options"])
            cursor = session["cursor"]
            selected = set(session["selected"])
            if key in ("UP", "DOWN"):
                cursor = (cursor + (-1 if key == "UP" else 1)) % len(keys)
            elif key in keys:
                cursor = keys.index(key)
            elif key != " ":
                return
            if q["type"] == "single_choice":
                selected = {keys[cursor]}
            elif key == " " or key in keys:
                selected.symmetric_difference_update({keys[cursor]})
            self.db.execute("UPDATE active SET cursor=?, selected=? WHERE slot=?",
                            (cursor, json.dumps(sorted(selected)), slot))

    def submit(self, slot=PRACTICE):
        with self.transaction():
            session = self.session(slot)
            if not session or session["correct"] is not None:
                return session
            if not session["selected"]:
                raise LearningError("Select at least one alternative before submitting")
            q = session["data"]
            correct = set(session["selected"]) == set(q["correct_answers"])
            awarded = self.db.execute("SELECT 1 FROM attempts WHERE question=? AND xp>0", (q["id"],)).fetchone()
            xp = 20 * q["difficulty"] if correct and not awarded else 0
            prior = self.db.execute("SELECT step FROM reviews WHERE question=?", (q["id"],)).fetchone()
            step = min((prior[0] if prior else -1) + 1, len(INTERVALS) - 1) if correct else -1
            today = self.today()
            due = today + timedelta(days=INTERVALS[max(0, step)])
            self.db.execute("INSERT INTO attempts VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (session["number"], q["id"], today.isoformat(), json.dumps(session["selected"]),
                             correct, xp, due.isoformat()))
            self.db.execute("INSERT OR REPLACE INTO reviews VALUES (?, ?, ?)", (q["id"], due.isoformat(), step))
            self.db.execute("INSERT INTO attempt_order(attempt) VALUES (?)", (session["number"],))
            if slot == MISSION:
                self.record_mission_answer(session["number"])
            elif slot == PRACTICE:
                self.db.execute("INSERT INTO practice_answers VALUES (?)", (session["number"],))
                self.db.execute("UPDATE practice_round SET correct = correct + ?, xp = xp + ? WHERE slot = 1",
                                (correct, xp))
            return self.session(slot)

    def history(self):
        return self.db.execute("""
            SELECT a.*, s.topic, json_extract(q.data, '$.category') AS category,
                json_extract(q.data, '$.difficulty') AS difficulty
            FROM attempts a JOIN questions q ON a.question=q.id
            JOIN sources s ON q.source=s.id JOIN attempt_order o ON a.number=o.attempt ORDER BY o.sequence
        """).fetchall()

    def summary(self):
        history = self.history()
        topics = {row[0]: [] for row in self.db.execute("SELECT name FROM topics ORDER BY name")}
        for row in history:
            topics[row["topic"]].append(row)
        result = {}
        for name, attempts in topics.items():
            correct = sum(row["correct"] for row in attempts)
            count = len(attempts)
            latest = {row["question"]: row["correct"] for row in attempts}
            mastered = sum(latest.values()) >= 3 and correct * 5 >= count * 4
            result[name] = (("Mastered" if mastered else "Practiced") if count else "Introduced", correct, count)
        streak = 0
        for row in reversed(history):
            if not row["correct"]:
                break
            streak += 1
        return {
            "topics": result, "answered": len(history), "correct": sum(row["correct"] for row in history),
            "xp": self.earned_xp(), "streak": streak, "recent": history[-3:][::-1],
        }

    @staticmethod
    def level(earned):
        return FIRST_LEVEL + (XP + earned) // XP_GOAL

    def operator(self):
        row = self.db.execute("SELECT operator FROM operator_choice WHERE slot = 1").fetchone()
        return row["operator"] if row and valid_index(row["operator"], OPERATORS) else 0

    def cycle_operator(self):
        with self.transaction():
            choice = (self.operator() + 1) % len(OPERATORS)
            self.db.execute("INSERT OR REPLACE INTO operator_choice VALUES (1, ?)", (choice,))

    def unlocked_stage(self, earned):
        return stage_for_level(self.level(earned))

    def reviews(self):
        return self.db.execute("""
            SELECT s.topic, r.due, count(*) AS pending FROM reviews r
            JOIN questions q ON r.question=q.id JOIN sources s ON q.source=s.id
            GROUP BY s.topic, r.due ORDER BY r.due, s.topic
        """).fetchall()
