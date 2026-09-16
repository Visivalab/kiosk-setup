# pi-kiosk-setup

Interactive first-boot wizard for Raspberry Pi OS (Bookworm / Trixie, labwc).

The repo must be **public**. Then, on the Pi:

    curl -fsSL https://raw.githubusercontent.com/Visivalab/pi-kiosk/master/kiosk.sh | sudo bash

That downloads only `kiosk.sh`. The script then fetches the rest of the tree
and gives the wizard access to `/dev/tty` so the rotation prompt still works.

Or copy this folder to a Pi / clone it there, then:

    sudo ./kiosk.sh

To run the standalone totem registration flow later from a checkout:

    PYTHONPATH=src python3 -m pi_kiosk register-totem

Or directly from GitHub on the Pi:

    curl -fsSL https://raw.githubusercontent.com/Visivalab/pi-kiosk/master/kiosk.sh | sudo bash -s -- register-totem

It asks these interactive questions:

1. Screen rotation
2. RustDesk unattended password
3. What kind of kiosk to deploy
4. S3 ZIP path for a webapp kiosk (for example
   `screen_1_de/screen_1_de-dist.zip`), or Dropbox link for a video kiosk
5. Whether to register the totem now
6. If you choose registration: totem name and optional description/location
7. What to do next: launch now, reboot, or do nothing

Then it applies the rest and prints what it did after each step.

If a Wayland desktop session is available, rotation is also applied live and
saved for future graphical logins.

This is not an image builder. Flash stock Raspberry Pi OS Desktop 64-bit
with Imager, boot normally, run the command.

## What v1 does

1. Screen rotation selector:
   - No rotation
   - Rotate clockwise (90°)
   - Rotate counterclockwise (90°)
2. Disable screen blanking / sleep
3. Desktop autologin (no password prompt on boot)
4. RustDesk installation and unattended-access setup:
   - installs the latest official RustDesk `.deb`
   - sets the unattended-access password you provide
   - prints the generated RustDesk ID
5. Webapp kiosk deployment from the ZIP at
   `https://visivalab-totems-releases.s3.eu-west-3.amazonaws.com/` plus the
   path you enter:
   - downloads the webapp ZIP
   - deploys the extracted static app files
   - serves the static app locally with `python3 -m http.server`
   - launches Chromium in kiosk mode on graphical login
   - installs a labwc cursor-hide keybind and, when `wtype` and `swayidle`
     are available, re-hides the mouse cursor after idle

The account password is not deleted. It is still used for sudo.

## Standalone totem registration

The installer does not register anything remotely. Use the separate command when
you want to register the device in your dashboard/backend:

    PYTHONPATH=src python3 -m pi_kiosk register-totem

If you are not inside a checkout on the Pi, use the pipeable form instead:

    curl -fsSL https://raw.githubusercontent.com/Visivalab/pi-kiosk/master/kiosk.sh | sudo bash -s -- register-totem

That command:

- detects the machine name from the system hostname
- asks for the totem type when it cannot reuse the current wizard selection
- asks for the totem name
- asks for the totem description (optional)
- asks for the totem location (optional)
- reuses the RustDesk ID and unattended password already configured on the Pi, when available
- sends a `POST` to your configured registration endpoint
- installs an hourly systemd timer that reports raw runtime facts to the backend

The hourly reporter sends:

- `totem_type`: `webapp` or `video`
- `machineName`: the current system hostname at the moment the heartbeat is sent
- `kiosk_running`: `true` when `labwc` is running for the desktop user
- `webapp_running`: `true` when `127.0.0.1:8080` is answering

Configure the endpoint and token in [src/pi_kiosk/totem_registration.py](/mnt/c/Users/Nitropc/orca/pi-kiosk/src/pi_kiosk/totem_registration.py)
or override them with:

- `PI_KIOSK_REGISTER_TOTEM_URL`
- `PI_KIOSK_REGISTER_TOTEM_TOKEN`

The hourly status reporter reuses `PI_KIOSK_REGISTER_TOTEM_TOKEN`. Its status
URL is inferred from `PI_KIOSK_REGISTER_TOTEM_URL` by replacing the final
`register-totem` path segment with `totem-status`.

## What it will not do

- It refuses to run on a non-Raspberry Pi. Safe to invoke by mistake.
- It refuses to run without sudo.
- It does not build frontend code on the Pi with npm/node.
- It does not authenticate downloads from private object storage.
- It does not configure a custom RustDesk server.
- It does not disable touch input devices; it only maps touch when needed.

## Layout

- `src/pi_kiosk/app.py` — wizard loop. Add a step here, not by forking the CLI.
- `src/pi_kiosk/steps/` — one module per concern (rotation, touch, nosleep, autologin, RustDesk, webapp kiosk).
- `src/pi_kiosk/host.py` — system port. Tests use an in-memory fake.
- `src/pi_kiosk/linux.py` — the only code that touches a real machine.

Re-running is safe: tagged blocks in `~/.config/labwc/autostart` are replaced,
not duplicated.

## Tests

    make test

Tests never talk to raspi-config or write labwc files on the machine that
runs them.
