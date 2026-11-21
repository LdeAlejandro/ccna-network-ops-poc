"""Regression coverage for the persistent multiple-choice engine."""

from contextlib import closing
from datetime import date, timedelta
import copy
from ipaddress import ip_interface, ip_network
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from learning import Learning, LearningError, MISSION, REVIEW, SCHEMA, parse_pack
from missions import MISSIONS, load_bundled

CONTENT = Path(__file__).with_name("content")


class EngineTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.today = date(2026, 1, 1)
        self.path = self.root / "learning.sqlite3"
        self.engine = Learning(self.path, today=lambda: self.today)
        self.addCleanup(self.engine.close)

    def import_sample(self, pack):
        return self.engine.ingest(CONTENT / f"{pack}.json")

    def test_schema_and_subnetting_answers(self):
        for path in CONTENT.glob("*.json"):
            parse_pack(path.read_text())
        _, _, _, questions = parse_pack((CONTENT / "ipv4-subnetting.json").read_text())
        boundary = questions["subnet-001"]
        self.assertEqual(boundary["options"][boundary["correct_answers"][0]],
                         str(ip_interface("192.0.2.77/27").network))
        sizing = questions["subnet-002"]
        longest = max(int(option[1:]) for option in sizing["options"].values()
                      if ip_network(f"192.0.2.0{option}").num_addresses - 2 >= 50)
        self.assertEqual(sizing["options"][sizing["correct_answers"][0]], f"/{longest}")

    def test_schema_rejections_and_atomic_collisions(self):
        pack = json.loads((CONTENT / "ios-basics.json").read_text())
        for key, bad_value in (
            ("category", ["ios_commands"]), ("difficulty", True), ("correct_answers", ["Z"]),
            ("explanation", ""), ("question", "\x1b[2J"), ("type", "multiple_choice"),
            ("options", {"A": "show ip route", "B": "SHOW IP ROUTE"}),
        ):
            modified = copy.deepcopy(pack)
            modified["questions"][0][key] = bad_value
            with self.subTest(key=key), self.assertRaises(LearningError):
                parse_pack(json.dumps(modified))
        duplicate = copy.deepcopy(pack)
        duplicate["questions"].append(duplicate["questions"][0])
        with self.assertRaisesRegex(LearningError, "duplicate question ID"):
            parse_pack(json.dumps(duplicate))
        self.import_sample("ios-basics")
        with self.assertRaisesRegex(LearningError, "already imported"):
            self.import_sample("ios-basics")
        pack.update(pack_id="different", topic="Collision topic")
        path = self.root / "collision.json"
        path.write_text(json.dumps(pack))
        with self.assertRaisesRegex(LearningError, "already exists"):
            self.engine.ingest(path)
        self.assertNotIn("Collision topic", self.engine.summary()["topics"])
        self.assertEqual(len(self.engine.sources()), 1)

    def test_notes_do_not_generate_questions_or_reset_session(self):
        note = self.root / "review.md"
        note.write_text("Topic: Ethernet\nSubtopic: MAC learning\n\nA switch learns from source addresses.")
        self.engine.ingest(note)
        self.assertIsNone(self.engine.start())
        self.assertEqual(self.engine.summary()["topics"]["Ethernet"], ("Introduced", 0, 0))
        self.import_sample("ios-basics")
        session = self.engine.start()
        self.engine.select("B")
        txt = self.root / "manual.txt"
        txt.write_text("Static routes")
        with self.assertRaises(LearningError):
            self.engine.ingest(txt)
        self.engine.ingest(txt, topic="Routing")
        with closing(Learning(self.path)) as reopened:
            self.assertEqual(reopened.start()["number"], session["number"])
            self.assertEqual(reopened.session()["selected"], ["B"])
            self.assertEqual(reopened.sources()[0]["question_count"] in (0, 3), True)

    def test_submission_review_and_xp_are_persistent_and_idempotent(self):
        self.import_sample("vlan-troubleshooting")
        self.engine.start()
        wrong = self.engine.submit()
        self.assertFalse(wrong["correct"])
        self.assertEqual(wrong["next_review"], "2026-01-02")
        self.assertEqual(self.engine.submit()["number"], 1)
        self.assertIsNone(self.engine.start(advance=True))
        self.today += timedelta(days=1)
        self.assertEqual(self.engine.start(advance=True)["number"], 2)
        self.engine.select("B")
        correct = self.engine.submit()
        self.assertTrue(correct["correct"])
        self.assertEqual(correct["xp"], 40)
        self.assertEqual(correct["next_review"], "2026-01-03")
        self.today += timedelta(days=1)
        self.engine.start(advance=True)
        self.engine.select("B")
        repeated = self.engine.submit()
        self.assertEqual(repeated["xp"], 0)
        self.assertEqual(repeated["next_review"], "2026-01-06")
        with closing(Learning(self.path)) as reopened:
            self.assertEqual(reopened.summary()["xp"], 40)
            self.assertEqual(reopened.summary()["streak"], 2)
            self.assertEqual(reopened.summary()["topics"]["VLANs"], ("Practiced", 2, 3))
            self.assertEqual(len(reopened.history()), 3)

    def test_multiple_choice_exact_match_and_mastery(self):
        self.import_sample("network-fundamentals")
        for i in range(3):
            current = self.engine.start(advance=True)
            question = current["data"]
            if question["type"] == "multiple_choice":
                with self.assertRaisesRegex(LearningError, "at least one"):
                    self.engine.submit()
                self.engine.select(" ")
                self.engine.select("DOWN")
                self.engine.select("DOWN")
                self.engine.select(" ")
            else:
                self.engine.select(question["correct_answers"][0])
            self.assertEqual(self.engine.submit()["number"], i + 1)
        self.assertEqual(self.engine.summary()["topics"]["Network Fundamentals"], ("Mastered", 3, 3))
        self.today += timedelta(days=1)
        while (question := self.engine.start(advance=True)["data"])["type"] != "multiple_choice":
            self.engine.select(question["correct_answers"][0])
            self.engine.submit()
        for answer in ("A", "B", "C"):
            self.engine.select(answer)
        self.assertFalse(self.engine.submit()["correct"])

    def test_weighting_redistributes_and_uses_due_questions(self):
        for path in CONTENT.glob("*.json"):
            self.engine.ingest(path)
        self.assertEqual(self.engine.start()["data"]["category"], "networking_theory")
        self.engine.submit()
        self.assertEqual(self.engine.start(advance=True)["data"]["category"], "ios_commands")
        self.engine.submit()
        self.today += timedelta(days=1)
        self.assertEqual(self.engine.start(advance=True)["data"]["id"], "fund-001")

    def test_upgrade_preserves_legacy_progress_and_pending_selection(self):
        legacy = self.root / "legacy.sqlite3"
        sample = CONTENT / "vlan-troubleshooting.json"
        pack_id, version, topic, questions = parse_pack(sample.read_text())
        qid, question = next(iter(questions.items()))
        with closing(sqlite3.connect(legacy)) as db, db:
            schema = SCHEMA.split("CREATE TABLE IF NOT EXISTS mission_runs")[0]
            db.executescript(schema.replace("slot BETWEEN 1 AND 3", "slot = 1"))
            db.execute("PRAGMA user_version = 1")
            source = f"pack:{pack_id}"
            db.execute("INSERT INTO topics VALUES (?)", (topic,))
            db.execute("INSERT INTO sources VALUES (?, ?, ?, ?, 'json', ?, '[]', NULL)",
                       (source, sample.name, "2026-01-01", topic, version))
            db.execute("INSERT INTO questions VALUES (?, ?, ?)", (qid, source, json.dumps(question)))
            db.execute("INSERT INTO attempts VALUES (1, ?, '2026-01-01', ?, 1, 40, '2026-01-02')",
                       (qid, json.dumps(["B"])))
            db.execute("INSERT INTO reviews VALUES (?, '2026-01-02', 0)", (qid,))
            db.execute("INSERT INTO active VALUES (1, 2, ?, 2, ?)", (qid, json.dumps(["C"])))
            db.execute("INSERT INTO profile VALUES (1, 1)")
        with closing(Learning(legacy, today=lambda: self.today)) as upgraded:
            self.assertEqual(upgraded.start()["selected"], ["C"])
            self.assertEqual(upgraded.history()[0]["number"], 1)
            self.assertEqual(upgraded.summary()["xp"], 40)
            self.assertEqual(upgraded.avatar_stage(40), 1)
            self.assertEqual(upgraded.reviews()[0]["due"], "2026-01-02")
            self.assertIsNone(upgraded.start(review=True))
            self.today += timedelta(days=1)
            self.assertEqual(upgraded.start(review=True)["number"], 3)
            self.assertEqual(upgraded.session()["number"], 2)

    def test_mission_failure_retry_and_one_time_bonus(self):
        load_bundled(self.engine)
        load_bundled(self.engine)
        self.assertEqual(sum(s["question_count"] for s in self.engine.sources()), 261)
        self.assertTrue(all(self.engine.mission_available(m) for m in MISSIONS))
        self.assertIsNone(self.engine.start(review=True))
        practice = self.engine.start()
        self.engine.select("D")
        mission = MISSIONS[0]
        for expected_pass, expected_bonus in ((False, 0), (True, mission.reward), (True, 0)):
            session = self.engine.start_mission(mission.id)
            with self.assertRaisesRegex(LearningError, "Finish the current operation"):
                self.engine.start_mission(MISSIONS[1].id)
            for index, qid in enumerate(mission.questions):
                self.assertEqual(session["question"], qid)
                q = session["data"]
                keys = q["correct_answers"] if expected_pass else [next(k for k in q["options"]
                                                                       if k not in q["correct_answers"])]
                for key in keys:
                    self.engine.select(key, MISSION)
                attempt = self.engine.submit(MISSION)
                self.assertEqual(self.engine.submit(MISSION)["number"], attempt["number"])
                run = self.engine.mission_run(mission.id)
                self.assertEqual(run["answered"], index + 1)
                session = self.engine.advance_mission()
            self.assertIsNone(session)
            self.assertEqual(run["correct"] >= run["passing_score"], expected_pass)
            self.assertEqual(run["bonus"], expected_bonus)
            self.assertEqual(len(run["weak"]), 0 if expected_pass else len(mission.questions))
        self.assertEqual(self.engine.completed_missions(), 1)
        self.assertEqual(self.engine.session()["number"], practice["number"])
        self.assertEqual(self.engine.session()["selected"], ["D"])
        self.today += timedelta(days=3)
        session = self.engine.start(review=True)
        self.assertIn(session["question"], mission.questions)
        self.assertEqual(self.engine.session(REVIEW)["number"], session["number"])

    def test_level_threshold_and_manual_avatar_persistence(self):
        self.assertEqual(self.engine.level(359), 7)
        self.assertEqual(self.engine.level(360), 8)
        self.assertEqual(self.engine.avatar_stage(360), 1)
        self.engine.toggle_avatar(0)
        with closing(Learning(self.path)) as reopened:
            self.assertEqual(reopened.avatar_stage(0), 1)


if __name__ == "__main__":
    unittest.main()
