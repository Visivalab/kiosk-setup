# kiosk-setup

Configuration tools for kiosk machines.

The Pi subproject is an interactive first-boot wizard for Raspberry Pi OS (Bookworm / Trixie, labwc). The Windows subproject provides a portable visual wizard for the equivalent setup, on one display or several: PC-wide settings are asked once, rotation and content once per screen. Several displays run one looping video each, started together; webapp kiosks remain single-display.

On Windows, either extract the repository ZIP and double-click `windows\kiosk-gui.cmd`, or open PowerShell as Administrator and run:

```powershell
$url = 'https://raw.githubusercontent.com/Visivalab/pi-kiosk/master/windows/setup.ps1'
Invoke-RestMethod -Uri $url | Invoke-Expression
```

To register a totem on Windows later, without configuring the kiosk again, use the **Register totem** button in the wizard or run `windows\kiosk.cmd register-totem`.

The repo must be **public**. On the Pi there are two ways to run the wizard,
with the same options: a **visual wizard** (like the Windows one) and the
**terminal wizard**.

### Visual wizard on the Pi

Open a terminal on the Pi desktop and run:

    curl -fsSL https://raw.githubusercontent.com/Visivalab/kiosk-setup/master/kiosk.sh | sudo bash -s -- gui

Or, from a checkout: `sudo ./kiosk.sh gui`.

A window opens with the same groups and buttons as the Windows wizard:
**Configure kiosk**, **Remove kiosk setup** and **Register totem**. Progress
appears in the window and in the terminal. The window runs as the desktop
user; the privileged work runs in the root process that opened it. If Tk is
missing, `python3-tk` is installed first. The last answers (never passwords)
are kept in `~/.config/pi-kiosk/gui-settings.json` and pre-fill the next run.

To preview the window on any computer with Tk, without a Pi:
`python3 pi/src/pi_kiosk/gui.py --demo --displays 2`.

### Terminal wizard on the Pi

    curl -fsSL https://raw.githubusercontent.com/Visivalab/kiosk-setup/master/kiosk.sh | sudo bash

That downloads only `kiosk.sh`. The script then fetches the rest of the tree
and gives the wizard access to `/dev/tty` so the prompts still work.

Or copy this folder to a Pi / clone it there, then:

    sudo ./kiosk.sh

To run the standalone totem registration flow later from a checkout:

    sudo env PYTHONPATH=pi/src python3 -m pi_kiosk register-totem

Or directly from GitHub on the Pi:

    curl -fsSL https://raw.githubusercontent.com/Visivalab/kiosk-setup/master/kiosk.sh | sudo bash -s -- register-totem

To undo the kiosk configuration (same as **Remove kiosk setup**):

    curl -fsSL https://raw.githubusercontent.com/Visivalab/kiosk-setup/master/kiosk.sh | sudo bash -s -- cleanup

The terminal wizard asks every question first and only then changes the Pi,
so a bad link on the second screen cannot leave the first one half-configured:

1. Screen rotation, once per connected screen
2. Which screen has the touchscreen (only with several screens and a touchscreen)
3. Whether to install RustDesk, and its unattended password (typed twice)
4. With one screen: webapp or video, then the S3 ZIP path (for example
   `screen_1_de/screen_1_de-dist.zip`) or the video source.
   With several screens: one video per screen, which screen plays the sound,
   and through which audio output.
   A video source is a Dropbox link or an absolute local path, for example
   `/media/pi/USB/screen1.mp4`. A file already on the Pi's disk is hard-linked
   (no copy, no extra space); a file on a USB stick is copied, so the stick can
   be removed afterwards.
5. Whether to register the totem now, then its name and optional description/location

Then it applies everything, prints what it did after each step and a summary,
and finally asks what to do next: launch now, reboot, or do nothing.

If a Wayland desktop session is available, rotation is also applied live and
saved for future graphical logins.

This is not an image builder. Flash stock Raspberry Pi OS Desktop 64-bit
with Imager, boot normally, run the command.

### Ubuntu / Debian desktop PCs

The same Pi wizard (terminal or visual) also configures a normal Ubuntu or
Debian desktop PC that logs in with GDM (Ubuntu's default) or LightDM. Run the
same commands from a terminal on that PC's desktop.

On those PCs it additionally:

- installs `labwc`, `wlr-randr`, `xwayland`, `libinput-tools` and
  `xdg-desktop-portal-wlr` (plus `wlopm` when available) with apt;
- makes labwc the autologin session: `AutomaticLogin` in
  `/etc/gdm3/custom.conf` plus `Session=labwc` in
  `/var/lib/AccountsService/users/<user>`, or a LightDM drop-in at
  `/etc/lightdm/lightdm.conf.d/60-pi-kiosk.conf`;
- masks the systemd sleep, suspend and hibernate targets instead of using
  `raspi-config`;
- installs Chromium when a webapp needs it and it is missing (a snap on Ubuntu).

Everything else (rotation, touch, kiosk autostart, cursor hide) is the same
labwc setup as on the Pi, so it takes effect after the reboot into the labwc
session. Screens are detected from the kernel when the current session is
GNOME. Servers without a display manager, WSL and containers are refused.
`cleanup` turns autologin off, restores the default GNOME/LightDM session and
unmasks sleep; labwc stays installed.

Known limits: GDM must allow Wayland (remove `WaylandEnable=false`, often set
for NVIDIA cards; the wizard warns about it). RustDesk on a wlroots Wayland
session relies on `xdg-desktop-portal-wlr` for screen sharing.

## What the Pi wizard does

1. Screen rotation per screen (no rotation, clockwise 90°, counterclockwise 90°, 180°).
   With several screens they are placed side by side in one `wlr-randr` call.
2. Touchscreen mapping to its screen, with the matching calibration
3. Disable screen blanking / sleep
4. Desktop autologin (no password prompt on boot)
5. RustDesk installation and unattended-access setup (optional):
   - installs the latest official RustDesk `.deb`
   - sets the unattended-access password you provide
   - prints the generated RustDesk ID
6. Webapp kiosk (one screen only) from the ZIP at
   `https://visivalab-totems-releases.s3.eu-west-3.amazonaws.com/` plus the
   path you enter:
   - downloads the webapp ZIP
   - deploys the extracted static app files
   - serves the static app locally with `python3 -m http.server`
   - launches Chromium in kiosk mode on graphical login
   - installs a labwc cursor-hide keybind and, when `wtype` and `swayidle`
     are available, re-hides the mouse cursor after idle
7. Or a looping video kiosk in mpv. With several screens each screen plays its
   own video, pinned to its output with `--fs-screen-name`. Only one screen
   plays sound; the others run with `--no-audio`. A chosen audio output that
   has disappeared falls back to the default output.
8. Saves the setup (never passwords) to `/etc/pi-kiosk/kiosk-state.json`, so
   `register-totem` and the visual wizard can reuse it.

The account password is not deleted. It is still used for sudo.

## Standalone totem registration

Registration is also available on its own, without configuring the kiosk
again (the **Register totem** button in the visual wizard does the same):

    PYTHONPATH=pi/src python3 -m pi_kiosk register-totem

If you are not inside a checkout on the Pi, use the pipeable form instead:

    curl -fsSL https://raw.githubusercontent.com/Visivalab/kiosk-setup/master/kiosk.sh | sudo bash -s -- register-totem

That command:

- detects the machine name from the system hostname
- reuses the saved kiosk setup (type and every screen) when the Pi was configured;
  otherwise asks for the totem type and reports the detected screens
- asks for the totem name
- asks for the totem description (optional)
- asks for the totem location (optional)
- reuses the RustDesk ID and unattended password already configured on the Pi, when available
- sends a `POST` to your configured registration endpoint
- installs a 5-minute systemd timer that reports raw runtime facts to the backend

The status reporter sends:

- `totem_type`: `webapp` or `video`
- `machineName`: the current system hostname at the moment the heartbeat is sent
- `kiosk_running`: `true` when the kiosk is running. With several screens this
  means at least one video player is alive; with one screen it means `labwc`
  is running for the desktop user
- `webapp_running`: `true` when `127.0.0.1:8080` is answering
- `screenCount` and `screens`: one entry per screen with its own `kiosk_running`,
  the same shape the Windows totems send

Configure the endpoint and token in [shared/kiosk.json](shared/kiosk.json) or override them with:

- `PI_KIOSK_REGISTER_TOTEM_URL`
- `PI_KIOSK_REGISTER_TOTEM_TOKEN`

The status reporter reuses `PI_KIOSK_REGISTER_TOTEM_TOKEN`. Its status
URL is inferred from `PI_KIOSK_REGISTER_TOTEM_URL` by replacing the final
`register-totem` path segment with `totem-status`.

## What it will not do

- It refuses to run on anything but a Raspberry Pi or an Ubuntu/Debian desktop
  with GDM or LightDM (servers, WSL and containers are refused). Safe to invoke by mistake.
- It refuses to run without sudo.
- It does not build frontend code on the Pi with npm/node.
- It does not authenticate downloads from private object storage.
- It does not configure a custom RustDesk server.
- It does not disable touch input devices; it only maps touch when needed.
- It does not frame-synchronise videos on different screens; they start
  together and loop independently.

## Layout

- `kiosk.sh` — root pipeable entry point; currently runs the Pi subproject.
  Commands: none (terminal wizard), `gui`, `register-totem`, `cleanup`.
- `pi/src/pi_kiosk/app.py` — Pi wizard loop: ask everything, then apply. Add a step here, not by forking the CLI.
- `pi/src/pi_kiosk/steps/` — one Pi module per concern (rotation, touch, nosleep, autologin, RustDesk, webapp/video kiosk, saved state).
- `pi/src/pi_kiosk/gui.py` — the visual wizard window (Tk, runs as the desktop user).
- `pi/src/pi_kiosk/gui_launcher.py`, `gui_session.py`, `gui_model.py` — root side of the visual wizard: opens the window, validates the form and applies it through the same steps.
- `pi/src/pi_kiosk/cleanup.py` — removes the kiosk configuration.
- `pi/src/pi_kiosk/host.py` — Pi system port. Tests use an in-memory fake.
- `pi/src/pi_kiosk/linux.py` — the only Pi code that touches a real machine.
- `windows/kiosk-gui.cmd` — portable visual Windows launcher.
- `windows/setup.ps1` — remote Windows bootstrap that downloads one repository archive and opens the visual wizard.
- `windows/kiosk.ps1` — thin Windows entry point; steps live under `windows/src/steps/`.
- `shared/kiosk.json` — service URLs and release settings shared by Pi and Windows.

Re-running is safe: tagged blocks in `~/.config/labwc/autostart` are replaced,
not duplicated.

## Tests

    make test

Tests never talk to raspi-config or write labwc files on the machine that
runs them.
