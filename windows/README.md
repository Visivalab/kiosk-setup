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

Accept the Windows administrator prompt. The visual wizard keeps passwords masked and encrypts them while handing setup work to the background process.

## Remove the kiosk configuration

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

RustDesk and VLC are installed with `winget` when missing. Webapps are served only on `http://127.0.0.1:8080`.

Nothing is applied until every answer validates, so a bad link on the second screen cannot leave the first one half-configured.

## Audio

The PC has one set of speakers, so only one screen plays sound and the rest run with `--no-audio`.

With a single display there is nothing to choose: the only video (or the webapp) plays its own sound through whatever output is available when it plays. With several displays the wizard asks which video carries the audio, and which output to send it to — either the default output or a specific active playback device.

Which video actually has an audio track is only knowable once the files are downloaded, which happens after the form is filled. So the answer is a preference, and setup corrects it against the files: if only one video turns out to carry audio, that one is used; if none does, every screen plays muted. Either way the summary says what was decided.

A chosen output device is re-checked at playback. If it is gone — unplugged, disabled — the player falls back to the system default rather than playing to nothing.

## Several displays

One entry in the Startup folder runs `bin\kiosk-start.ps1`, which starts every screen. Each player is bound to its screen by Windows device name, resolved at login rather than baked in as pixel coordinates, so re-rotating or re-arranging the monitors later does not send a video to the wrong screen.

Two or more videos start together: VLC is launched paused on every screen and released over its local control interface once all of them are ready. If any player fails to answer within 30 seconds, the orchestrator restarts them all without the pause rather than leaving a screen frozen.

Videos loop independently. Different durations drift apart over time by design; only the start is synchronised.

The Windows password prompt accepts an empty value only for a local account that has no password. Enter the account password—not a Windows Hello PIN—when a password exists. Passwordless local accounts use Windows' native `AutoAdminLogon`; other accounts use the temporary official Sysinternals Autologon utility.

## Layout

- `kiosk-gui.cmd` launches the portable visual wizard and requests administrator access.
- `kiosk-gui.ps1` renders the native Windows UI and runs setup in the background.
- `kiosk.ps1` loads the original console wizard and exits with its result.
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
