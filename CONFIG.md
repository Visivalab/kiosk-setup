# Raspberry Pi post-install configuration FAQ

This document describes the state left on a Raspberry Pi after `pi-kiosk` has
finished. It follows the wizard steps in the order in which they are applied.

## Conventions and installation scope

### What does `<desktop-user>` mean in this document?

It is the Linux user that owns and runs the graphical desktop. If the setup is
started with `sudo`, `pi-kiosk` obtains this user from `SUDO_USER`. A typical
value is `pi`, so `<home>` would normally mean `/home/pi`.

The installer deliberately writes labwc and kiosk files under that user's home,
not under `/root`.

### Does the installer run on any Linux machine?

No. It refuses to make changes unless the machine looks like a Raspberry Pi and
the process is running as root. It should be launched with `sudo` from the
desktop user's account.

### Is the installer itself permanently installed?

Not necessarily. When using the `curl | sudo bash` command, `kiosk.sh` downloads
the repository into a temporary directory, runs the Python wizard, and removes
that temporary directory afterward. The configuration files, deployed media,
packages, and systemd units described below remain on the Pi.

When running from a cloned or copied checkout, that checkout remains wherever
it was placed.

### Is it safe to run the wizard again?

The configuration blocks written by `pi-kiosk` are tagged and replaced instead
of duplicated. Webapp and video deployments use a staging directory and replace
their respective `current` directory after a successful download and prepare
step.

A rerun may download packages and deployment files again. It does not remove
unrelated lines from existing labwc configuration files.

### What are the main persistent locations?

| Purpose | Location |
| --- | --- |
| labwc startup commands | `<home>/.config/labwc/autostart` |
| labwc touch and cursor configuration | `<home>/.config/labwc/rc.xml` |
| webapp launcher | `<home>/.config/pi-kiosk/webapp-kiosk.sh` |
| deployed webapp | `<home>/.local/share/pi-kiosk/webapp/current/` |
| webapp server log | `<home>/.local/state/pi-kiosk/webapp-server.log` |
| webapp startup heartbeat log | `<home>/.local/state/pi-kiosk/webapp-heartbeat.log` |
| video launcher | `<home>/.config/pi-kiosk/video-kiosk.sh` |
| deployed video | `<home>/.local/share/pi-kiosk/video/current/` |
| saved RustDesk password | `/etc/pi-kiosk/rustdesk.json` |
| totem status reporter | `/usr/local/lib/pi-kiosk/totem-status.py` |
| totem status configuration | `/etc/pi-kiosk/totem-status.json` |
| totem status systemd service | `/etc/systemd/system/pi-kiosk-totem-status.service` |
| totem status systemd timer | `/etc/systemd/system/pi-kiosk-totem-status.timer` |

## Step 1: screen rotation

### Where is screen rotation configured?

The persistent rotation command is stored in:

```text
<home>/.config/labwc/autostart
```

It is enclosed by these markers:

```text
# pi-kiosk-setup:rotation-begin
wlr-randr --output HDMI-A-1 --transform 270
# pi-kiosk-setup:rotation-end
```

The output name and transform in the real file depend on the detected display
and the answer selected in the wizard.

### Which rotation values are used?

| Wizard selection | `wlr-randr` transform |
| --- | --- |
| No rotation | `normal` |
| Rotate clockwise | `270` |
| Rotate counterclockwise | `90` |

These transform values follow the output coordinate convention used by
`wlr-randr`.

### How does the installer choose the display output?

It runs `wlr-randr` inside the desktop Wayland session and uses the first output
reported. If the output cannot be detected, it falls back to `HDMI-A-1`.

### When does rotation take effect?

The installer attempts to apply it immediately in the active Wayland session.
The command in labwc autostart applies it again on every future graphical login.

## Step 2: touchscreen mapping

### Where is touchscreen rotation configured?

When a touchscreen is detected and the screen is rotated, `pi-kiosk` writes a
tagged XML block to:

```text
<home>/.config/labwc/rc.xml
```

The block is enclosed by:

```xml
<!-- pi-kiosk-setup:touch-begin -->
...
<!-- pi-kiosk-setup:touch-end -->
```

It maps touch input to the selected output and adds the appropriate libinput
calibration matrix.

### How is a touchscreen detected?

The installer runs `libinput list-devices` and looks for a device whose
capabilities include touch.

### What happens when there is no touchscreen?

No touch configuration is written.

### What happens when the display is not rotated?

The touchscreen is detected, but no calibration matrix is needed and no mapping
block is added.

### Does the installer switch the Pi to X11?

No. Rotation and touch configuration remain on Wayland and labwc.

## Step 3: screen blanking and sleep

### How is screen blanking disabled?

The installer invokes Raspberry Pi OS configuration non-interactively:

```bash
raspi-config nonint do_blanking 1
```

It also adds a Wayland guard to labwc autostart:

```text
# pi-kiosk-setup:nosleep-begin
wlopm --on '*' >/dev/null 2>&1 || true
# pi-kiosk-setup:nosleep-end
```

The autostart file is:

```text
<home>/.config/labwc/autostart
```

### Why are both `raspi-config` and `wlopm` used?

`raspi-config` disables the Raspberry Pi OS blanking setting. The `wlopm`
command additionally asks all Wayland outputs to be on when labwc starts.

### When does this take effect?

The Raspberry Pi OS setting is applied during setup. The labwc guard runs at
each graphical login and is expected to be fully effective after reboot.

## Step 4: desktop autologin

### How is desktop autologin enabled?

The installer runs:

```bash
raspi-config nonint do_boot_behaviour B4
```

`B4` is Raspberry Pi OS desktop autologin. `pi-kiosk` delegates the underlying
system configuration to `raspi-config` rather than editing a display-manager
file itself.

### Does autologin remove the account password?

No. The desktop starts without prompting for it, but the account password still
exists and continues to be used for SSH and `sudo`.

### Which user is logged in automatically?

The Raspberry Pi desktop user from which setup was invoked with `sudo`.

## Step 5: RustDesk unattended access

### How is RustDesk installed?

The installer queries the latest official RustDesk GitHub release, selects the
`.deb` matching the Pi's Debian architecture, downloads it to a temporary
directory, and installs it with `apt-get install -fy`.

The downloaded `.deb` is temporary; the installed package remains managed by
the operating system package manager.

### What unattended-access settings are applied?

The RustDesk CLI is used to set and verify:

```text
approve-mode=password
verification-method=use-permanent-password
```

The supplied permanent password is then configured, and the `rustdesk` systemd
service is restarted.

### Where is the RustDesk password saved by `pi-kiosk`?

It is saved as JSON at:

```text
/etc/pi-kiosk/rustdesk.json
```

The file mode is `0600`, so only root can read or modify it. This copy is used
when registering the totem with the backend. RustDesk may also maintain its own
application configuration separately.

Do not publish or attach this file to support tickets.

### How can I see the RustDesk ID?

Run:

```bash
rustdesk --get-id
```

The wizard also prints the ID after configuration.

### How can I inspect the RustDesk service?

Run:

```bash
systemctl status rustdesk
```

## Step 6: kiosk selection and shared autostart

### Where is automatic kiosk startup configured?

Both webapp and video kiosks use one shared tagged block in:

```text
<home>/.config/labwc/autostart
```

The block looks like:

```text
# pi-kiosk-setup:kiosk-begin
bash <home>/.config/pi-kiosk/webapp-kiosk.sh
# pi-kiosk-setup:kiosk-end
```

For a video kiosk, the command points to `video-kiosk.sh` instead.

This is a labwc graphical-session autostart, not a systemd service. It runs after
the desktop user is automatically logged in.

### What happens when switching between webapp and video mode?

The shared kiosk block is replaced so only the selected launcher runs at the
next graphical login. Previously downloaded webapp or video files and the
unused launcher may remain on disk, but they are no longer referenced by
autostart.

### Will the kiosk restart automatically if Chromium or mpv exits?

No. labwc starts the launcher once per graphical login. If the foreground kiosk
process exits, it is not supervised or restarted by systemd. Logging in again or
rebooting starts it again.

## Step 7A: webapp kiosk

### Which webapp URLs are accepted?

The wizard accepts public HTTPS URLs whose path ends in `.zip`, including Amazon
S3 and CloudFront URLs. Existing public GitHub Release ZIP URLs remain
compatible.

The Pi does not receive AWS credentials. An S3 or CloudFront object therefore
has to be downloadable using an unauthenticated HTTPS request.

### Does the Pi build the webapp?

No. The ZIP must already contain the compiled static application. Node.js, npm,
and frontend build tools are not used on the Pi.

### What structure must the ZIP have?

`index.html` must be at the ZIP root:

```text
index.html
assets/
```

A single wrapping directory is also accepted. Metadata entries such as
`__MACOSX` and `.DS_Store` are ignored when resolving that directory.

For safety, ZIP entries containing absolute paths, parent traversal (`..`), or
symbolic links are rejected.

### Where are the webapp files deployed?

The active files are stored in:

```text
<home>/.local/share/pi-kiosk/webapp/current/
```

During deployment, files are prepared under:

```text
<home>/.local/share/pi-kiosk/webapp/next/
```

The previous `current` directory is replaced after the new download has been
successfully extracted and staged. Temporary download and extraction files are
removed automatically.

### Where is Chromium autorun configured?

There are two parts:

1. `<home>/.config/labwc/autostart` runs the webapp launcher.
2. `<home>/.config/pi-kiosk/webapp-kiosk.sh` starts the server and Chromium.

The launcher contains the detected `chromium-browser` or `chromium` executable
and starts it with:

```text
--kiosk --incognito --noerrdialogs --disable-infobars
```

### Does `pi-kiosk` install Chromium?

No. Chromium must already be available on Raspberry Pi OS. Setup stops with an
error if neither `chromium-browser` nor `chromium` can be found.

### Where is kiosk mode configured?

Chromium kiosk mode is configured directly in the generated launcher through
the `--kiosk` argument. The labwc autostart entry controls when that launcher is
run.

### How is the webapp served?

The launcher changes into the deployed `current` directory and starts the
Python standard-library server:

```bash
python3 -m http.server 8080 --bind 127.0.0.1
```

No nginx, Apache, Node.js server, or webapp systemd service is installed.

### What is the IP and URL of the local server?

The server listens on the loopback address only:

```text
IP:   127.0.0.1
Port: 8080
URL:  http://127.0.0.1:8080
```

It is accessible from the same Pi but not directly from other machines on the
LAN. `127.0.0.1` always means “this machine”; it is not the Pi's LAN address.

### Does the local server support SPA route fallback?

No. `python3 -m http.server` serves files as they exist on disk and does not
rewrite unknown routes to `index.html`. A single-page application should use
hash routing or otherwise avoid requiring server-side fallback for direct URLs.

### Where are the webapp logs?

Server stdout and stderr are written to:

```text
<home>/.local/state/pi-kiosk/webapp-server.log
```

Inspect them with:

```bash
tail -f <home>/.local/state/pi-kiosk/webapp-server.log
```

This log is replaced whenever the launcher starts.

Startup heartbeat output is appended to:

```text
<home>/.local/state/pi-kiosk/webapp-heartbeat.log
```

Inspect it with:

```bash
tail -f <home>/.local/state/pi-kiosk/webapp-heartbeat.log
```

### How is the mouse cursor hidden?

The installer writes an `Alt+Super+H` labwc key binding to:

```text
<home>/.config/labwc/rc.xml
```

The XML is enclosed by:

```xml
<!-- pi-kiosk-setup:cursor-hide-begin -->
...
<!-- pi-kiosk-setup:cursor-hide-end -->
```

The launcher uses `wtype` to trigger that binding after startup. When both
`wtype` and `swayidle` are available, it triggers it again after five seconds of
idle time. Missing `wtype` or `swayidle` packages are installed with `apt-get`.

### What happens when Chromium closes?

The launcher exits and cleans up the local HTTP server and cursor-idle process.
They start again on the next graphical login or reboot.

### How can I verify the server locally?

Run on the Pi:

```bash
curl -I http://127.0.0.1:8080
```

To inspect the relevant processes:

```bash
ps aux | grep -E 'chromium|http.server'
```

## Step 7B: video kiosk

### Which video URLs are accepted?

The wizard currently accepts Dropbox shared file URLs over HTTPS. It rewrites
the `dl` query parameter to `dl=1` to request a direct download.

### Where is the video stored?

The active video is stored under:

```text
<home>/.local/share/pi-kiosk/video/current/
```

The actual filename is taken from Dropbox's `Content-Disposition` response when
available. Otherwise, it is derived from the URL.

### Where is the video launcher?

```text
<home>/.config/pi-kiosk/video-kiosk.sh
```

The common kiosk block in `<home>/.config/labwc/autostart` runs this script on
graphical login.

### How is the video played?

The launcher starts `mpv` with fullscreen, infinite looping, hidden controls,
and automatic cursor hiding:

```text
--fs --loop-file=inf --no-osc --no-osd-bar --cursor-autohide=always
```

Touch-to-mouse emulation is disabled with:

```text
--input-touch-emulate-mouse=no
```

Keyboard and mouse input are otherwise left available.

### Does `pi-kiosk` install mpv?

Yes, if it cannot find `mpv`, it installs the package with `apt-get` before
generating the launcher.

### Is there a dedicated video log?

No dedicated video log file is configured by `pi-kiosk`.

## Step 8: optional totem registration

### What identifies the totem?

At registration time, the current system hostname is used as `totem_id` and
`machineName`. The contents of `/etc/machine-id`, when available, are also sent
as `machineId`.

The registration additionally sends the selected project type, display name,
optional description and location, registration time, and available RustDesk
ID and password.

### Where are the registration endpoint and token configured?

They can be overridden for the installer process with:

```text
PI_KIOSK_REGISTER_TOTEM_URL
PI_KIOSK_REGISTER_TOTEM_TOKEN
```

The resolved status endpoint and token are persisted for the hourly reporter in:

```text
/etc/pi-kiosk/totem-status.json
```

This file contains a bearer token and should be treated as sensitive. Do not
publish it or include it unredacted in logs or support requests.

### How is the status endpoint determined?

The final path segment of the registration URL is replaced with
`totem-status`. Query parameters and fragments are removed.

For example:

```text
https://example.test/api/register-totem
```

becomes:

```text
https://example.test/api/totem-status
```

### What files does the status reporter install?

```text
/usr/local/lib/pi-kiosk/totem-status.py
/etc/pi-kiosk/totem-status.json
/etc/systemd/system/pi-kiosk-totem-status.service
/etc/systemd/system/pi-kiosk-totem-status.timer
```

The Python script is executable and uses only the Python standard library.

### How often is status reported?

Registration starts the service once immediately. The enabled systemd timer
then runs it:

- Five minutes after boot.
- Every hour after its previous activation.
- After a missed scheduled run when the machine comes back, because the timer is
  persistent.

### What status information is sent?

The reporter sends:

- `totem_id`: the hostname captured at registration time.
- `totem_type`: `webapp` or `video`.
- `machineName`: the hostname at the time of the status check.
- `checkedAt`: the current UTC timestamp.
- `kiosk_running`: whether a `labwc` process is running for the desktop user.
- `webapp_running`: whether TCP port `127.0.0.1:8080` accepts a connection.

For a video kiosk, `webapp_running` is normally false because no HTTP server is
started.

### Is there an additional startup heartbeat for webapps?

Yes. After its local server becomes ready, the webapp launcher runs the same
status reporter in the background. It retries up to 12 times with five seconds
between attempts. This is independent of the hourly systemd timer.

### How can I inspect the status timer and service?

```bash
systemctl status pi-kiosk-totem-status.timer
systemctl status pi-kiosk-totem-status.service
systemctl list-timers pi-kiosk-totem-status.timer
journalctl -u pi-kiosk-totem-status.service -n 50 --no-pager
```

### Can registration be run separately later?

Yes, from a checkout:

```bash
sudo env PYTHONPATH=src python3 -m pi_kiosk register-totem
```

Or using the pipeable installer command:

```bash
curl -fsSL https://raw.githubusercontent.com/Visivalab/pi-kiosk/master/kiosk.sh \
  | sudo bash -s -- register-totem
```

## Step 9: final startup action

### What does “Simulate autorun” do for a webapp?

It asks labwc to reload its configuration, waits briefly, and starts the webapp
launcher in the existing desktop session. This is intended for testing. Cursor
hiding may behave more reliably after a complete graphical login.

### What does “Close” do for a webapp?

It starts the generated launcher in `server-only` mode. The local server remains
available at `http://127.0.0.1:8080`, but Chromium is not opened.

### What do the equivalent video actions do?

- **Launch video now** starts the generated video launcher for testing.
- **Reboot** performs the normal production startup path.
- **Do nothing** leaves the configured autostart ready for the next graphical
  login.

### Why is reboot the recommended production path?

A reboot exercises the complete intended chain:

```text
boot → desktop autologin → labwc autostart → kiosk launcher → application
```

It also ensures that display, touch, blanking, and session configuration are all
loaded from their persistent locations.

## Maintenance and troubleshooting

### How can I see every block managed by `pi-kiosk`?

```bash
grep -R "pi-kiosk-setup:" \
  <home>/.config/labwc/autostart \
  <home>/.config/labwc/rc.xml
```

Managed blocks use `pi-kiosk-setup:<name>-begin` and
`pi-kiosk-setup:<name>-end` markers.

### Which files should I inspect first when kiosk startup fails?

For a webapp kiosk:

```text
<home>/.config/labwc/autostart
<home>/.config/pi-kiosk/webapp-kiosk.sh
<home>/.local/state/pi-kiosk/webapp-server.log
<home>/.local/state/pi-kiosk/webapp-heartbeat.log
```

For a video kiosk:

```text
<home>/.config/labwc/autostart
<home>/.config/pi-kiosk/video-kiosk.sh
<home>/.local/share/pi-kiosk/video/current/
```

### Does changing the S3 object update an already configured Pi automatically?

No. The Pi downloads the ZIP while the wizard is running. Replacing the object
at the same S3 URL does not push the new files to existing Pis. Run the wizard
again with that URL to deploy the new build.

### Does the Pi retain the original ZIP URL?

The URL is used during the wizard and appears in its completion report, but no
dedicated persistent “current source URL” configuration file is installed. The
deployed static files remain in the `current` directory.

### Does a webapp need internet access after deployment?

The static files are served locally, so loading those files does not require the
S3 object after installation. The application itself may still require internet
access if its frontend calls remote APIs or loads remote assets. RustDesk and
totem status reporting also require network access.

### Are configuration changes made under `/root`?

Desktop configuration, launchers, deployed media, and user logs are written
under the desktop user's home. Only machine-wide secrets, reporter files,
systemd units, and installed packages use system locations under `/etc`,
`/usr/local`, or the package manager.

### Is there an automatic uninstall command?

No. `pi-kiosk` currently configures and updates the Pi but does not provide an
uninstall command. Removal should account for the tagged labwc blocks, deployed
files, launchers, RustDesk package and credentials, and optional status-reporter
service and timer described above.
