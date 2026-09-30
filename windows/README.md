# Windows kiosk config

The portable visual wizard runs the complete setup using Windows' built-in controls. It needs no installation or extra runtime.

Everything that belongs to the PC — autologin, sleep, RustDesk, registration — is asked once. Rotation and kiosk content are asked once per display. With a single display the wizard offers a webapp or a video kiosk; **with several displays it offers video only**, one looping video per screen, and every screen may use a different rotation.

## Run directly from GitHub

Open Windows Terminal **as Administrator**, then run:

```powershell
$url = 'https://raw.githubusercontent.com/Visivalab/pi-kiosk/master/windows/setup.ps1'
Invoke-RestMethod -Uri $url | Invoke-Expression
```

The bootstrap downloads one repository archive so the wizard, its steps, runtime scripts, and shared configuration always use the same revision.

## Run as a portable app

Download and extract the repository ZIP, then double-click:

```text
windows\kiosk-gui.cmd
```

Accept the Windows administrator prompt. The visual wizard pre-fills previous display links, rotations, audio choice and other non-secret answers by physical monitor identity. Older multi-display setups saved only Windows `DISPLAY` numbers, which can change after a reboot: on the first run after upgrading, review each physical screen and re-enter its video link rather than trusting the old numbering. Subsequent runs can reuse the saved monitor identities. The last GUI answers are kept in `%LOCALAPPDATA%\pi-kiosk\gui-settings.json` and removed by cleanup. Passwords are never saved in that file: enter the RustDesk password (and the Windows account password, if applicable) again. Passwords remain masked and are encrypted while handed to the background process.

## Remove the kiosk configuration

The visual wizard has a **Remove kiosk setup** button next to Configure kiosk. It asks for confirmation, then runs the same cleanup as the commands below and reports progress in the same box.

Or, from a terminal:

Open Windows Terminal **as Administrator**, then run:

```powershell
$url = 'https://raw.githubusercontent.com/Visivalab/pi-kiosk/master/windows/cleanup-setup.ps1'
Invoke-RestMethod -Uri $url | Invoke-Expression
```

Cleanup removes kiosk startup and status reporting, disables autologin, deletes files owned by `pi-kiosk`, removes every local HTTP reservation it recorded, and restores all active displays to 0° rotation. It leaves installed applications, power settings, and the remote registration record unchanged.

## Run a local checkout

From the repository root, double-click `windows\kiosk-gui.cmd`, or run the original console wizard in an Administrator terminal:

```bat
windows\kiosk.cmd
```

To clean up a locally configured PC:

```bat
windows\cleanup.cmd
```

The wizard configures:

1. Rotation, per display, applied to every screen in a single display-layout commit
2. Disabled display blanking and sleep
3. Windows autologin through native AutoAdminLogon for a passwordless local account, or Microsoft Sysinternals Autologon when the account has a password
4. RustDesk unattended access
5. A webapp kiosk in Microsoft Edge (single display only) or a looping video kiosk in VLC on each display
6. Which screen plays the sound and through which output
7. Optional totem registration and five-minute status reporting, both reporting every screen
8. Launch now, reboot, or do nothing

RustDesk and VLC are installed with `winget` when missing. Setup installs the RustDesk Windows service if needed, sets it to start automatically, and checks that it is running before configuring unattended access. If `winget` cannot install RustDesk, check **Skip RustDesk (no remote access)** in the visual wizard to proceed without it: the password fields are disabled, the totem can still be registered without RustDesk credentials, and the choice is remembered. This does not skip VLC or the video download. Cleanup leaves any installed RustDesk service unchanged. Webapps are served only on `http://127.0.0.1:8080`.

Nothing is applied until every answer validates, so a bad link on the second screen cannot leave the first one half-configured.

## Register a totem later

Registration is also available on its own, without configuring the kiosk again. The visual wizard has a **Register totem** button: fill in the Registration group and select it. From a terminal:

```bat
windows\kiosk.cmd register-totem
```

If a video download or other kiosk content installation fails during setup, the wizard still attempts the selected totem registration, but reports setup as failed and does not write a new kiosk startup entry or claim the incomplete setup is working. Registration can still fail independently if the server is unreachable.

Either way it reuses what `kiosk-state.json` already knows about this PC — every screen, its type, and which one carries the audio — so the record matches the running setup. On a PC that was never configured it falls back to the detected displays and asks for the totem type. The saved RustDesk ID and password are reused when they exist, and the five-minute status reporter is installed as usual. Nothing about the kiosk setup itself is touched.

## Audio

The PC has one set of speakers, so only one screen plays sound and the rest run with `--no-audio`.

With a single display there is nothing to choose: the only video (or the webapp) plays its own sound through whatever output is available when it plays. With several displays the wizard asks which video carries the audio, and which output to send it to — either the default output or a specific active playback device.

Which video actually has an audio track is only knowable once the files are downloaded, which happens after the form is filled. So the answer is a preference, and setup corrects it against the files: if only one video turns out to carry audio, that one is used; if none does, every screen plays muted. Either way the summary says what was decided.

A chosen output device is re-checked at playback. If it is gone — unplugged, disabled — the player falls back to the system default rather than playing to nothing.

## Several displays

One entry in the Startup folder runs `bin\kiosk-start.ps1`, which starts every screen. Each player is bound to its physical monitor interface ID, resolved against the current Windows display names at login rather than relying on `DISPLAY1`/`DISPLAY2`. If a configured monitor is absent or cannot be identified uniquely, startup logs an error instead of deliberately assigning its video to another screen. An existing installation needs to be configured again once to save these monitor IDs.

VLC starts each video without pausing and repeats that file independently. The players launch in quick succession but are not frame-synchronised; different durations drift apart over time. In the video source field you can enter a Dropbox link **or choose a local video using Browse...** (one button per display). You can also type an absolute path, for example `D:\videos\screen1.mp4` on a USB drive. Setup checks that the file is nonempty and copies it into `%LOCALAPPDATA%\pi-kiosk\video\display-1\current\`; after setup finishes, the USB drive can be removed. For additional displays, use the matching `display-2`, etc. Do not place files directly in the `current` folder: the wizard manages that folder and records the chosen filename in its state. Re-runs reuse an existing nonempty video when the saved display, device and source match; a changed source or missing managed file triggers a new download or copy. Keep the original local file accessible when running setup again.

The Windows password prompt accepts an empty value only for a local account that has no password. Enter the account password—not a Windows Hello PIN—when a password exists. Passwordless local accounts use Windows' native `AutoAdminLogon`; other accounts use the temporary official Sysinternals Autologon utility. The RustDesk password must be entered twice, with an exact match, in both the visual and console wizards.

## Layout

- `kiosk-gui.cmd` launches the portable visual wizard and requests administrator access.
- `kiosk-gui.ps1` renders the native Windows UI and runs setup in the background.
- `kiosk.ps1` loads the original console wizard and exits with its result. It takes one optional command, `register-totem`.
- `cleanup.ps1` removes the persistent Windows kiosk configuration owned by this project.
- `src/app.ps1` builds the setup plan and applies it in one ordered pass.
- `src/plan.ps1` defines the plan and the single validation used by both the console and the visual wizard.
- `src/steps/` contains one file per configuration concern.
- `src/steps/startup.ps1` generates the startup orchestrator that runs every screen.
- `src/steps/audio.ps1` lists playback devices, detects audio tracks, and picks the screen that carries the sound.
- `runtime/` contains the scripts copied to the configured PC.
- `setup.ps1` is the remote GitHub bootstrap.

Run the dependency-free PowerShell checks on Windows with:

```bat
powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows\tests\run.ps1
```
