import io
import unittest

from pi_kiosk.choice import Choice
from pi_kiosk.terminal_ui import TerminalUI


class TerminalUITests(unittest.TestCase):
    def test_choose_prints_numbered_options_and_returns_id(self):
        stdin = io.StringIO("2\n")
        stdout = io.StringIO()
        ui = TerminalUI(stdin=stdin, stdout=stdout)

        picked = ui.choose(
            "Screen rotation",
            [
                Choice("none", "No rotation"),
                Choice("clockwise", "Rotate clockwise (90°)"),
                Choice("counterclockwise", "Rotate counterclockwise (90°)"),
            ],
        )

        self.assertEqual(picked, "clockwise")
        text = stdout.getvalue()
        self.assertIn("1) No rotation", text)
        self.assertIn("2) Rotate clockwise (90°)", text)
        self.assertIn("3) Rotate counterclockwise (90°)", text)

    def test_choose_rejects_out_of_range_then_accepts(self):
        stdin = io.StringIO("0\n9\nabc\n1\n")
        stdout = io.StringIO()
        ui = TerminalUI(stdin=stdin, stdout=stdout)

        picked = ui.choose(
            "Screen rotation",
            [
                Choice("none", "No rotation"),
                Choice("clockwise", "Rotate clockwise (90°)"),
            ],
        )

        self.assertEqual(picked, "none")
        self.assertGreaterEqual(stdout.getvalue().lower().count("invalid"), 1)

    def test_info_prints_the_completion_message(self):
        stdout = io.StringIO()
        TerminalUI(stdin=io.StringIO(), stdout=stdout).info("Done: example")
        self.assertIn("Done: example", stdout.getvalue())

    def test_prompt_reads_a_free_text_value(self):
        stdin = io.StringIO(
            "https://github.com/Visivalab/demo-app/releases/download/latest/demo-app-dist.zip\n"
        )
        stdout = io.StringIO()
        ui = TerminalUI(stdin=stdin, stdout=stdout)

        text = ui.prompt("Webapp ZIP URL")

        self.assertEqual(
            text,
            "https://github.com/Visivalab/demo-app/releases/download/latest/demo-app-dist.zip",
        )
        self.assertIn("Webapp ZIP URL: ", stdout.getvalue())

    def test_secret_reads_a_value(self):
        stdin = io.StringIO("secret-pass\n")
        stdout = io.StringIO()
        ui = TerminalUI(stdin=stdin, stdout=stdout)

        text = ui.secret("RustDesk password")

        self.assertEqual(text, "secret-pass")
        self.assertIn("RustDesk password: ", stdout.getvalue())

    def test_progress_prints_a_loading_line(self):
        stdout = io.StringIO()
        TerminalUI(stdin=io.StringIO(), stdout=stdout).progress("Downloading webapp ZIP")
        self.assertIn("[....] Downloading webapp ZIP", stdout.getvalue())

    def test_confirm_accepts_default_yes_on_empty_input(self):
        stdin = io.StringIO("\n")
        stdout = io.StringIO()
        accepted = TerminalUI(stdin=stdin, stdout=stdout).confirm("Open the app now?")
        self.assertTrue(accepted)
        self.assertIn("Open the app now? [Y/n]: ", stdout.getvalue())

    def test_confirm_accepts_no(self):
        stdin = io.StringIO("n\n")
        stdout = io.StringIO()
        accepted = TerminalUI(stdin=stdin, stdout=stdout).confirm("Open the app now?")
        self.assertFalse(accepted)
