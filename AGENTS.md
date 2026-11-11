# AGENTS.md — pi-kiosk-setup

Guidance for coding agents working in this repository.

## Scope and working copy

- Canonical checkout: `/home/gerard/projects/pi-kiosk-setup`
- Public GitHub remote: `https://github.com/Visivalab/kiosk-setup` (must be public for the curl one-liner). Do not push unless asked.
- This tool is meant to run on **other** Raspberry Pis, never on the VPS that hosts this checkout.
- Do not run `sudo ./kiosk.sh` or `python3 -m pi_kiosk` against a real host unless the user explicitly wants a live Pi configured. Tests use an in-memory fake.

## What this project does

Interactive first-boot wizard for Raspberry Pi OS Desktop (Bookworm / Trixie, labwc).

The Pi side mirrors the Windows wizard: rotation and content per screen
(several screens = one looping video each), touch mapping, no blanking,
autologin (`raspi-config` B4), optional RustDesk, webapp or video kiosk, saved
state, optional totem registration, then a final action. It runs as a terminal
wizard (`sudo ./kiosk.sh`) or a Tk visual wizard (`sudo ./kiosk.sh gui`), plus
`register-totem` and `cleanup` commands.

The terminal wizard asks every question first, then applies. The visual wizard
builds the same step answers in `gui_model.form_to_answers` and calls
`Wizard.apply_answers`. Keep both paths on the same steps.

Autologin does not delete the account password. SSH and sudo still use it.

## Repository map

```text
kiosk.sh                       root pipeable entry point; runs the Pi subproject
setup.sh                       thin wrapper around kiosk.sh
pi/src/pi_kiosk/app.py         Pi wizard loop: ask → apply → report
pi/src/pi_kiosk/steps/         one Pi module per concern
pi/src/pi_kiosk/host.py        Pi Host protocol
pi/src/pi_kiosk/linux.py       only Pi code that touches a real machine
pi/src/pi_kiosk/terminal_ui.py numbered selector + Done: lines
pi/src/pi_kiosk/files.py       idempotent tagged-block edits
pi/src/pi_kiosk/kiosk_state.py /etc/pi-kiosk/kiosk-state.json (no passwords)
pi/src/pi_kiosk/cleanup.py     undo the kiosk configuration
pi/src/pi_kiosk/machine.py     platform detection (raspberry-pi / linux-desktop)
pi/src/pi_kiosk/desktop_session.py Ubuntu/Debian: labwc install + GDM/LightDM autologin
pi/src/pi_kiosk/gui.py         Tk window; runs as the desktop user, stdlib only,
                               no pi_kiosk imports (the launcher copies it alone)
pi/src/pi_kiosk/gui_launcher.py root side: opens the window, pipes JSON requests
pi/src/pi_kiosk/gui_session.py  runs configure/register/cleanup, streams progress
pi/src/pi_kiosk/gui_model.py    form -> step answers; all validation before apply
windows/                       future Windows subproject placeholder
tests/                         unittest, FakeHost / FakeUI
```

## Development rules

- Python 3 stdlib only. No pip, venv, or extra packages.
- TDD: failing test first for new behavior. `make test` must stay green.
- Add features as a new class in `pi/src/pi_kiosk/steps/` with `id`, `title`, `choices`, `ask()`, `apply()`. Register it in `default_steps()`.
- Do not put raspi-config or filesystem calls in the wizard. Steps talk to `Host`.
- Re-runs must be idempotent. User-facing files use `# pi-kiosk-setup:<name>-begin/end` blocks.
- Rotation names: `none` (0), `clockwise` (90), `counterclockwise` (270), `upside-down` (180).
- Stay on Wayland/labwc. Do not switch the Pi back to X11.
- Do not commit, deploy, or configure a live Pi unless the user asks.
- **Bump the version on every commit** that touches the Pi side: `__version__`
  in `pi/src/pi_kiosk/__init__.py`. Patch (`0.2.0` → `0.2.1`) for fixes, minor
  (`0.2.1` → `0.3.0`) for new features. Testers read it from the visual
  wizard's window title, the first line of the terminal wizard, or
  `sudo ./kiosk.sh --version`, so it tells which build a Pi was set up with.
- `kiosk.sh` may be piped (`curl … | sudo bash`). Keep the body in `main()` so the script is fully read before stdin is reattached to `/dev/tty`. If `pi/src/pi_kiosk` is missing, it downloads the public GitHub archive.

## Safety

- Refuse unsupported machines (`host.platform()` is None, see `machine.py`).
  Supported: Raspberry Pi OS, and Ubuntu/Debian desktops with GDM or LightDM.
  Servers (no display manager), WSL and containers must stay refused.
- `raspi-config` is Pi-only. On `linux-desktop`, autologin/no-sleep go through
  `desktop_session.py`.
- Refuse non-root.
- `LinuxHost` must write labwc files to the desktop user home (`SUDO_USER`), not `/root`.
- A live run on this VPS must exit 2 and change nothing.

## Verification

From the repository root:

```bash
make test
```

That is `python3 -m unittest discover -s tests -v`. Tests must never call real `raspi-config` or write `~/.config/labwc` on the machine that runs them.

After a behavior change, run `make test` and report the real result. Optional extra check: `PYTHONPATH=pi/src python3 -m pi_kiosk` on a non-Pi must print the refusal and exit 2.
