import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
KIOSK_SH = REPO / "kiosk.sh"


def find_bash() -> str | None:
    git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if git_bash.is_file():
        return str(git_bash)
    which = shutil.which("bash")
    if which and "system32" not in which.lower():
        return which
    return None


def to_bash_path(path: Path | str) -> str:
    text = str(Path(path))
    if len(text) >= 2 and text[1] == ":":
        return "/" + text[0].lower() + text[2:].replace("\\", "/")
    return text.replace("\\", "/")


def _chmod_exec(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


class KioskShTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bash = find_bash()
        if cls.bash is None:
            raise unittest.SkipTest("bash is required to test kiosk.sh")

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.out = self.root / "out.txt"
        self.tarball = self.root / "kiosk-config.tar.gz"
        self._write_archive(self.tarball)
        self._write_fake_python()
        self._write_fake_sudo()
        self._chmod_bin()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_archive(self, dest: Path) -> None:
        tree = self.root / "archive-tree" / "kiosk-config-master" / "pi" / "src" / "pi_kiosk"
        tree.mkdir(parents=True)
        (tree / "__init__.py").write_text("", encoding="utf-8")
        with tarfile.open(dest, "w:gz") as bundle:
            bundle.add(
                tree.parents[2],
                arcname="kiosk-config-master",
            )

    def _write_fake_python(self) -> None:
        script = self.bin / "python3"
        script.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "printf '%s\\n' \"${PYTHONPATH-}\" > \"$KIOSK_TEST_OUT\"",
                    "if [[ -t 0 ]]; then echo tty >> \"$KIOSK_TEST_OUT\"; else echo notty >> \"$KIOSK_TEST_OUT\"; fi",
                    "exit 0",
                    "",
                ]
            ),
            encoding="utf-8",
            newline="\n",
        )
        _chmod_exec(script)

    def _write_fake_sudo(self) -> None:
        script = self.bin / "sudo"
        script.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "while [[ $# -gt 0 && \"$1\" == *=* ]]; do",
                    "  export \"$1\"",
                    "  shift",
                    "done",
                    "exec \"$@\"",
                    "",
                ]
            ),
            encoding="utf-8",
            newline="\n",
        )
        _chmod_exec(script)

    def _write_fake_curl(self, *, record: Path, payload: Path | None) -> None:
        script = self.bin / "curl"
        if payload is None:
            body = [
                "#!/usr/bin/env bash",
                f"printf 'called\\n' >> \"{to_bash_path(record)}\"",
                "exit 1",
                "",
            ]
        else:
            body = [
                "#!/usr/bin/env bash",
                f"printf 'called\\n' >> \"{to_bash_path(record)}\"",
                "out=\"\"",
                "while [[ $# -gt 0 ]]; do",
                "  case \"$1\" in",
                "    -o) out=\"$2\"; shift 2 ;;",
                "    -*) shift ;;",
                "    *) shift ;;",
                "  esac",
                "done",
                f"if [[ -n \"$out\" ]]; then cp \"{to_bash_path(payload)}\" \"$out\"; else cat \"{to_bash_path(payload)}\"; fi",
                "exit 0",
                "",
            ]
        script.write_text("\n".join(body), encoding="utf-8", newline="\n")
        _chmod_exec(script)
        self._chmod_bin()

    def _chmod_bin(self) -> None:
        subprocess.run(
            [self.bash, "-c", f"chmod +x {to_bash_path(self.bin)}/*"],
            check=False,
            capture_output=True,
        )

    def _env(self) -> dict[str, str]:
        bash_bin = to_bash_path(self.bin)
        env = {
            "PATH": f"{bash_bin}:/usr/bin:/bin:/mingw64/bin",
            "HOME": to_bash_path(self.root),
            "TMPDIR": to_bash_path(self.root),
            "KIOSK_TEST_OUT": to_bash_path(self.out),
            "PI_KIOSK_ARCHIVE_URL": to_bash_path(self.tarball),
        }
        if os.name == "nt":
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
            env["WINDIR"] = os.environ.get("WINDIR", r"C:\Windows")
        return env

    def _run_file(self, script: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.bash, "--noprofile", "--norc", to_bash_path(script)],
            cwd=str(self.root),
            env=self._env(),
            text=True,
            capture_output=True,
            timeout=30,
        )

    def _run_piped(self) -> subprocess.CompletedProcess[str]:
        script = KIOSK_SH.read_bytes().replace(b"\r\n", b"\n")
        return subprocess.run(
            [self.bash, "--noprofile", "--norc", "-s"],
            input=script.decode("utf-8"),
            cwd=str(self.root),
            env=self._env(),
            text=True,
            capture_output=True,
            timeout=30,
        )

    def test_checkout_run_uses_local_src_and_does_not_download(self):
        curl_log = self.root / "curl.log"
        self._write_fake_curl(record=curl_log, payload=None)

        result = self._run_file(KIOSK_SH)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(curl_log.exists(), "checkout run must not call curl")
        pythonpath = self.out.read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(
            pythonpath.replace("\\", "/").endswith("/src"),
            pythonpath,
        )
        self.assertTrue(
            (Path(pythonpath) / "pi_kiosk").is_dir()
            or Path(to_windows_path(pythonpath)).joinpath("pi_kiosk").is_dir(),
            pythonpath,
        )

    def test_piped_run_downloads_archive_then_runs_module(self):
        curl_log = self.root / "curl.log"
        self._write_fake_curl(record=curl_log, payload=None)

        result = self._run_piped()

        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        self.assertFalse(
            curl_log.exists(),
            "local archive path should be copied, not fetched with curl",
        )
        pythonpath = self.out.read_text(encoding="utf-8").splitlines()[0]
        self.assertIn("kiosk-config-master", pythonpath.replace("\\", "/"))
        self.assertTrue(pythonpath.replace("\\", "/").endswith("/src"), pythonpath)

    def test_script_body_is_wrapped_so_stdin_can_be_the_terminal(self):
        text = KIOSK_SH.read_text(encoding="utf-8")
        self.assertIn("main()", text)
        self.assertNotRegex(text, r"exec\s+</dev/tty")
        self.assertRegex(text, r"</dev/tty")
        self.assertRegex(text.strip().splitlines()[-1], r'^main\s+"\$@"\s*$')


def to_windows_path(bash_path: str) -> str:
    if bash_path.startswith("/") and len(bash_path) > 2 and bash_path[2] == "/":
        return bash_path[1].upper() + ":" + bash_path[2:].replace("/", "\\")
    return bash_path
