"""Avatar asset, rendering and preview regressions."""

from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import avatar
from learning import Learning
from missions import load_bundled
from model import THEMES
from ops import Dashboard


class AvatarTest(TestCase):
    def test_all_asset_mappings_and_fallback(self):
        for operator in range(len(avatar.OPERATORS)):
            sprites = avatar.PORTRAITS[operator]
            self.assertEqual(len(set(sprites)), len(avatar.STAGES))
            for stage, sprite in enumerate(sprites):
                self.assertEqual(avatar.load_portrait(avatar.asset_path(operator, stage)), sprite)
        baseline = avatar.PORTRAITS[1][0]
        with TemporaryDirectory() as directory, patch.object(avatar, "ASSETS", Path(directory)):
            asset = avatar.asset_path(1, 0)
            asset.write_text("\n".join("".join("0123456789abcdefghijklmnopqrstuvwxyz"[v] for v in row)
                                       for row in baseline))
            avatar.asset_path(1, 2).write_text("malformed\n")
            sprites = avatar.load_portraits()
            self.assertEqual(sprites[1], (baseline,) * 4)
            self.assertFalse(any(map(any, sprites[0][0])))

    def test_invalid_renderer_indices_and_theme_palette(self):
        self.assertEqual(avatar.portrait(-1, 1), avatar.portrait(0, 1))
        self.assertEqual(avatar.portrait(None, 99), avatar.portrait(0, 0))
        self.assertEqual(avatar.portrait("3"), avatar.portrait(0))
        for theme in THEMES:
            palette = avatar.portrait_palette(theme)
            self.assertEqual(palette[1:-2], tuple(avatar.ART_COLORS[1:]))
            self.assertEqual(palette[0], theme.panel)
        self.assertEqual(len(list(avatar.half_blocks(0, 16, 5))), 5)
        self.assertEqual(avatar.sixel(0, palette, (8, 17), 80, 90), "")

    def test_preview_and_themes_preserve_save(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "learning.sqlite"
            with closing(Learning(db)) as learning:
                learning.cycle_operator()
                with learning.transaction():
                    learning.db.execute("INSERT INTO profile VALUES (1, 99)")
                app = Dashboard(root / "theme", learning, root / "inbox")
                before = list(learning.db.iterdump())
                self.assertIn("1/4 Equipped", app.frame(140, 45))
                app.key("e")
                app.key("a")
                for _ in range(3):
                    app.key("e")
                app.key("s")
                for index in range(1, 6):
                    app.key(str(index))
                app.key("ESC")
                rendered = app.frame(140, 45, (8, 17))
                self.assertIn("4/4 Locked", rendered)
                self.assertIn("ROOK", rendered)
                app.key("ESC")
                rendered = app.frame(80, 24)
                self.assertIn("RELAY", rendered)
                self.assertNotIn("\x1bP", rendered)
                self.assertIn("▄", rendered)
                self.assertEqual(list(learning.db.iterdump()), before)
                with learning.transaction():
                    learning.db.execute("UPDATE operator_choice SET operator = -1")
                self.assertEqual(learning.operator(), 0)

    def test_equipped_stage_tracks_persisted_xp(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / "learning.sqlite"
            with closing(Learning(db)) as learning:
                load_bundled(learning)
                learning.cycle_operator()
                for _ in range(18):
                    if learning.earned_xp() >= 360:
                        break
                    session = learning.start(advance=True)
                    for key in session["data"]["correct_answers"]:
                        learning.select(key)
                    self.assertTrue(learning.submit()["correct"])
                self.assertGreaterEqual(learning.earned_xp(), 360)
                earned = learning.earned_xp()
            with closing(Learning(db)) as reopened:
                self.assertEqual(reopened.earned_xp(), earned)
                app = Dashboard(root / "theme", reopened, root / "inbox")
                self.assertIn("2/4 Equipped", app.frame(140, 45))
                self.assertIn("RELAY", app.frame(140, 45))
                app.key("e")
                self.assertIn("1/4 Unlocked", app.frame(140, 45))
                app.key("ESC")
                self.assertIn("2/4 Equipped", app.frame(140, 45))
