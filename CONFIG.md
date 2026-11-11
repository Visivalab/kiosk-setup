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

No. It runs on a Raspberry Pi with Raspberry Pi OS, or on an Ubuntu/Debian
desktop PC whose display manager is GDM or LightDM. Servers without a display
manager, WSL and containers are refused, and it always needs root. Launch it
with `sudo` from the desktop user's account.

### What is different on an Ubuntu/Debian desktop?

Raspberry Pi OS already runs labwc. On a desktop PC the autologin step first
installs `labwc`, `wlr-randr`, `xwayland`, `libinput-tools` and
`xdg-desktop-portal-wlr` (and `wlopm` if the distribution has it), then logs the
user straight into labwc:

| Display manager | Files changed |
| --- | --- |
| GDM | `AutomaticLoginEnable=True` and `AutomaticLogin=<user>` in `/etc/gdm3/custom.conf` (`daemon.conf` on Debian); `Session=labwc` in `/var/lib/AccountsService/users/<user>` |
| LightDM | `/etc/lightdm/lightdm.conf.d/60-pi-kiosk.conf` |

Instead of `raspi-config nonint do_blanking 1`, it masks `sleep.target`,
`suspend.target`, `hibernate.target` and `hybrid-sleep.target`. All the labwc
files described below are the same, and apply after rebooting into labwc.
`cleanup` reverses the autologin and session choice and unmasks the targets.

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
| deployed video (one screen) | `<home>/.local/share/pi-kiosk/video/current/` |
| deployed videos (several screens) | `<home>/.local/share/pi-kiosk/video/<output>/current/` |
| video player pids (several screens) | `<home>/.local/state/pi-kiosk/display-<output>.pid` |
| saved kiosk setup (no passwords) | `/etc/pi-kiosk/kiosk-state.json` |
| visual wizard answers (no passwords) | `<home>/.config/pi-kiosk/gui-settings.json` |
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
# Retried while a screen is still off; see CONFIG.md, screen rotation.
pi_kiosk_tries=0
until wlr-randr --output HDMI-A-1 --transform 270 >/dev/null 2>&1; do
  pi_kiosk_tries=$((pi_kiosk_tries + 1))
  if [ "$pi_kiosk_tries" -ge 60 ]; then
    break
  fi
  sleep 0.5
done
# pi-kiosk-setup:rotation-end
```

The output name and transform in the real file depend on the detected display
and the answer selected in the wizard. The loop around the command is
explained in "What if a screen is still off when the Pi starts?".

### Which rotation values are used?

| Wizard selection | `wlr-randr` transform |
| --- | --- |
| No rotation | `normal` |
| Rotate clockwise | `270` |
| Rotate counterclockwise | `90` |
| Rotate 180 (upside down) | `180` |

These transform values follow the output coordinate convention used by
`wlr-randr`.

### How does the installer choose the display output?

It runs `wlr-randr` inside the desktop Wayland session and lists every enabled
output. With one screen it uses that output; if none can be detected, it falls
back to `HDMI-A-1`.

### What happens with two screens?

Rotation is asked once per screen and written as one command (inside the same
retry loop) that also places the screens side by side, for example:

```text
wlr-randr --output HDMI-A-1 --transform 270 --pos 0,0 --output HDMI-A-2 --transform normal --pos 1080,0
```

On a Raspberry Pi the output names follow the physical HDMI ports
(`HDMI-A-1` is HDMI0, next to the power input), so they do not swap after a
reboot.

### What if a screen is still off when the Pi starts?

`wlr-randr` refuses the whole command when one of the screens it names is
missing, so a TV or projector that gives a signal after the desktop is up
(typical when everything shares one power switch) used to leave every screen
unrotated, and both videos on the screen that was on. The block therefore
retries the command every half second for up to 30 seconds. labwc runs
autostart with `sh` from top to bottom and the kiosk line comes after this
block, so the videos also wait until every screen is there.

If a screen is still missing after 30 seconds, each screen that is on gets its
own rotation (two screens add one `wlr-randr --output <name> --transform
<value>` line per screen before the `break`) and the kiosk starts anyway.

This covers the start only. A screen that is unplugged or loses its signal
while the kiosk runs comes back without its rotation, and its video can stay
on the other screen, until the next login or reboot.

### When does rotation take effect?

The installer attempts to apply it immediately in the active Wayland session.
The block in labwc autostart applies it again on every future graphical login.

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

With one screen, no calibration matrix is needed and no mapping block is added.

### What happens with two screens?

The wizard asks which screen has the touchscreen. Touch is then always mapped
to that output, even without rotation, so a touch does not spread across both
screens. The calibration matrix follows that screen's rotation.

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

### Can RustDesk be skipped?

Yes. Answer no to "Install RustDesk for remote access?" (or check **Skip
RustDesk** in the visual wizard). Nothing is installed, and a registration made
in that run sends empty RustDesk credentials. The password is typed twice when
RustDesk is installed.

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

### Will the kiosk restart automatically if Chromium or VLC exits?

Chromium: no. labwc starts the launcher once per graphical login. If the
foreground kiosk process exits, it is not supervised or restarted by systemd.
Logging in again or rebooting starts it again.

VLC: only after a crash. The video launcher starts a VLC again two seconds
after it ends with an error, on its own screen and with the same sound
setting; with two screens the other one keeps playing. A VLC closed by a
person (Ctrl+Q, Alt+F4) ends without an error and stays closed, so the desktop
can still be reached with a keyboard. A VLC that hangs without ending is not
detected.

## Step 7A: webapp kiosk

### Which webapp ZIP paths are accepted?

The wizard asks for an S3 ZIP path, such as
`screen_1_de/screen_1_de-dist.zip`. It adds the fixed base URL
`https://visivalab-totems-releases.s3.eu-west-3.amazonaws.com/` before
downloading. Enter a folder path ending in a `.zip` filename, not a full URL.

The Pi does not receive AWS credentials, so the S3 object must be downloadable
using an unauthenticated HTTPS request.

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

### Which video sources are accepted?

Dropbox shared file URLs over HTTPS (the `dl` query parameter is rewritten to
`dl=1` to request a direct download), or an absolute local path such as
`/media/pi/USB/screen1.mp4`.

A local file that is already on the same disk as the deployment folder (for
example `~/Videos/promo.mp4`) is hard-linked into it: no copy, no extra space,
and the kiosk keeps playing even if the original name is deleted. Its owner and
permissions are left untouched, because a hard link shares them with the
original.

A file on another disk (a USB stick) is copied, so the stick can be removed
after setup. Before copying, the wizard checks free space and keeps a 64 MB
margin. If the new video only fits once the previous one is gone, the previous
video is removed first; if it cannot fit at all, setup stops before copying and
the running kiosk keeps its current video.

### How do two screens play video?

Each screen gets its own video, downloaded into
`<home>/.local/share/pi-kiosk/video/<output>/current/`. The single
`video-kiosk.sh` launcher starts one VLC per screen, fullscreen on that screen
(see "How does each video find its screen?"), and waits for all of them. Only the screen chosen
for audio plays sound; the others use `--no-audio`. The sound goes to the
speakers of that same screen (on a Pi, `HDMI-A-1` is the audio card
`vc4-hdmi-0` and `HDMI-A-2` is `vc4-hdmi-1`), so a projector without speakers
never takes it. Choose another output only for separate speakers. The
launcher also makes that output the system default, so the sound cannot drift
to the other screen. If the output is still not present after the launcher's
audio wait (see below), VLC uses the default output, and the wizard's final
summary shows a `WARNING - sound` line when it cannot see the speakers at
setup time. The players start together but are not frame-synchronised.

Webapp kiosks remain single-screen, as on Windows.

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

With VLC, the same player that plays the files smoothly when opened by hand on
the Pi, and the one the Windows kiosk uses. mpv was used before, but on a Pi 5
with two screens it stuttered, and Raspberry Pi supports VLC, not mpv
([forum](https://forums.raspberrypi.com/viewtopic.php?t=393942)). Raspberry Pi
builds VLC to use the HEVC hardware decoder without extra copies.

The launcher runs the full `vlc` with its Qt window, not `cvlc`, whose own
Wayland output crashes on a Pi 5. The options are in `VLC_ARGS`:

```text
--no-one-instance --fullscreen --repeat --no-video-title-show --no-osd
--no-qt-fs-controller --mouse-hide-timeout=0 --no-mouse-events
--no-qt-privacy-ask --qt-continue=0 --no-qt-video-autoresize
```

Fullscreen, looping, no title, controls or cursor over the video.
`--no-mouse-events` keeps a double tap on a touchscreen from leaving
fullscreen; the keyboard stays available. The last two skip VLC's first-run
privacy question and its "continue where you left off?" prompt;
`--no-qt-video-autoresize` keeps VLC from resizing its window when the video
starts (see "How does each video find its screen?"). VLC refuses to
start on an unknown option, so all of these exist in VLC 3.0 on any Linux
build.

### What happens when the video reaches its end?

VLC plays it again (`--repeat`): it lets the last frames play out, ends the
playback and opens the same file again. This is not frame-exact, so expect a
short hold at the loop. Where that matters, end the video on a still or a
fade: the hold is then invisible.

With two screens each VLC loops on its own, so the two videos drift apart a
little at every loop and the difference adds up over a day. `--input-repeat`
(a jump back to the start without reopening the file) was considered and
dropped: it does not keep the screens in step either.

### How do I check the loop without waiting for the whole video?

Close the running videos (Ctrl+Q on each) and start the launcher with a
loop length in seconds:

```bash
PI_KIOSK_LOOP_SECONDS=15 bash ~/.config/pi-kiosk/video-kiosk.sh
```

Each VLC then gets `--stop-time=15`. VLC treats the stop time as the end of
the file, so it loops the first 15 seconds through the same code as the real
loop, on the real screens, with the rotation and the sound. Left running for
an hour that is 240 loops: several days of an exhibition for a ten-minute
video. Watch that the picture and the sound come back at every loop on both
screens. A normal start (login, reboot) plays the whole video.

### How does each video find its screen?

labwc puts it there. Each VLC is started with its own X11 window name
(`RESOURCE_NAME=pi-kiosk-HDMI-A-2`), and the wizard writes one window rule per
screen in `<home>/.config/labwc/rc.xml`, between the
`pi-kiosk-setup:video-screens` markers:

```xml
<windowRule identifier="pi-kiosk-HDMI-A-2">
  <action name="MoveToOutput" output="HDMI-A-2" />
</windowRule>
```

labwc applies the rule when the window first appears, and VLC only asks for
fullscreen, so the video fills the screen labwc chose. A VLC started again
after a crash keeps its name and goes back to the same screen.

Before 0.3.1 VLC chose the screen itself (`--qt-fullscreen-screennumber`, as
on Windows). On a Pi 4 with two screens that failed two boots in five: the
second screen's video came up on the first screen, or shifted over it. VLC's
choice is an X11 move followed by a fullscreen request. labwc applies the move
late when the window is also changing size, and not at all before the window
is shown; the fullscreen then lands on the screen under the pointer. That
explains the video on the wrong screen. The shifted video is not explained:
labwc on its own only puts a fullscreen window exactly on a screen, so the
position must have come from VLC, but the exact sequence was not found.
`--no-qt-video-autoresize` is there so that VLC sends labwc no position at
all: a resize sent right after labwc moved the window would carry the old one.

labwc tells XWayland windows apart by that name from version 0.8.1 on
(`labwc --version`). With an older labwc the launcher keeps VLC's own choice
and the wizard's final report says so with a `WARNING - screens` line. The
number is then counted the way Qt sees XWayland's screens, in `xrandr` order,
primary first, and falls back to the order the wizard detected.

The wizard's "launch now" runs the launcher with `WAYLAND_DISPLAY` only. When
`DISPLAY` is empty, the launcher takes XWayland's display from its socket in
`/tmp/.X11-unix`.

The rule has not been tried on a real Pi yet. If a video comes up on the wrong
screen, send the output of `labwc --version` and of
`xprop WM_CLASS` (then click the video): the first name must be
`pi-kiosk-<screen>`.

### Why can the video take a few seconds to start after boot?

At boot, labwc runs the launcher before PipeWire has found the HDMI audio
outputs. VLC opens its audio output only once, so a player started that early
stays silent until the next login, even though it worked when launched from
the wizard. Before starting a player with sound, the launcher runs
`<home>/.config/pi-kiosk/audio-route.py` (Python stdlib, written by the
wizard). It reads the outputs with `pw-dump`, which ships with PipeWire, or
with `pactl` when `pw-dump` is missing, and waits at most 20 seconds for the
output: the speakers of the screen that plays the sound, or the output chosen
in the wizard. When found, it makes it the default with `wpctl set-default`
and the VLC with sound gets `PULSE_SINK=<name>`. After 20 seconds the videos start
anyway, so a screen without speakers still plays. When every screen is muted
there is no wait.

Each start rewrites `<home>/.local/state/pi-kiosk/audio.log`: the outputs it
saw (with their `vc4-hdmi-N` card) and where the sound went, or `NOT FOUND`.
Read it first when a Pi has no sound.

### Does the video use hardware decoding?

Yes. VLC uses the hardware decoder on its own when the file allows it. On a Pi
that means HEVC (H.265): a Pi 5 has no H.264 decoder at all, and a Pi 4
decodes only one 1080p stream. For smooth playback on a Pi, encode the videos
as HEVC at the screen's resolution (1080p for a 1080p screen), for example:

```bash
ffmpeg -i input.mp4 -vf "scale=1920:1080:force_original_aspect_ratio=decrease" \
  -c:v libx265 -preset medium -crf 23 -tag:v hvc1 -c:a aac -b:a 160k output.mp4
```

### Does `pi-kiosk` install VLC?

Raspberry Pi OS Desktop ships VLC. If the wizard cannot find `vlc`, it
installs the package with `apt-get` before generating the launcher.

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

The resolved status endpoint and token are persisted for the status reporter in:

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
- Every 5 minutes after its previous activation.
- After a missed scheduled run when the machine comes back, because the timer is
  persistent.

### What status information is sent?

The reporter sends:

- `totem_id`: the hostname captured at registration time.
- `totem_type`: `webapp` or `video`.
- `machineName`: the hostname at the time of the status check.
- `checkedAt`: the current UTC timestamp.
- `kiosk_running`: with several screens, whether at least one video player is
  alive (from the pid files); with one screen, whether a `labwc` process is
  running for the desktop user.
- `webapp_running`: whether TCP port `127.0.0.1:8080` accepts a connection.
- `screenCount` and `screens`: each screen's number, type and its own
  `kiosk_running` / `webapp_running`.

For a video kiosk, `webapp_running` is normally false because no HTTP server is
started.

### Is there an additional startup heartbeat for webapps?

Yes. After its local server becomes ready, the webapp launcher runs the same
status reporter in the background. It retries up to 12 times with five seconds
between attempts. This is independent of the 5-minute systemd timer.

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
sudo env PYTHONPATH=pi/src python3 -m pi_kiosk register-totem
```

Or using the pipeable installer command:

```bash
curl -fsSL https://raw.githubusercontent.com/Visivalab/kiosk-setup/master/kiosk.sh \
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
again with the same ZIP path to deploy the new build.

### Does the Pi retain the original ZIP URL?

The URL assembled from the fixed S3 base and entered path appears in the
completion report, but no dedicated persistent “current source URL”
configuration file is installed. The deployed static files remain in the
`current` directory.

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

Yes: `sudo ./kiosk.sh cleanup`, or **Remove kiosk setup** in the visual wizard.
It stops the kiosk players, browser and local server, removes the tagged labwc
blocks, the status timer and service, the pi-kiosk files under the desktop
user's home, `/etc/pi-kiosk` and `/usr/local/lib/pi-kiosk`, disables desktop
autologin (`raspi-config` B3) and restores normal rotation on every screen.
RustDesk, VLC, the blanking setting and the remote registration record are left
unchanged.
