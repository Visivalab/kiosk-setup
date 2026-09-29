# Windows kiosk config

The Windows wizard currently runs the complete single-display setup. When more than one active display is detected it lists them and exits without changing the PC; per-display setup is the next milestone.

## Run directly from GitHub

Open Windows Terminal **as Administrator**, then run:

```powershell
$url = 'https://raw.githubusercontent.com/Visivalab/pi-kiosk/master/windows/setup.ps1'
Invoke-RestMethod -Uri $url | Invoke-Expression
```

The bootstrap downloads one repository archive so the wizard, its steps, runtime scripts, and shared configuration always use the same revision.

## Remove the kiosk configuration

Open Windows Terminal **as Administrator**, then run:

```powershell
$url = 'https://raw.githubusercontent.com/Visivalab/pi-kiosk/master/windows/cleanup-setup.ps1'
Invoke-RestMethod -Uri $url | Invoke-Expression
```

Cleanup removes kiosk startup and status reporting, disables autologin, deletes files owned by `pi-kiosk`, removes the local HTTP reservation, and restores all active displays to 0° rotation. It leaves installed applications, power settings, and the remote registration record unchanged.

## Run a local checkout

From the repository root in an Administrator terminal:

```bat
windows\kiosk.cmd
```

To clean up a locally configured PC:

```bat
windows\cleanup.cmd
```

For a single active display the wizard configures:

1. Rotation
2. Disabled display blanking and sleep
3. Windows autologin through native AutoAdminLogon for a passwordless local account, or Microsoft Sysinternals Autologon when the account has a password
4. RustDesk unattended access
5. A webapp kiosk in Microsoft Edge or a looping video kiosk in VLC
6. Optional totem registration and five-minute status reporting
7. Launch now, reboot, or do nothing

RustDesk and VLC are installed with `winget` when missing. Webapps are served only on `http://127.0.0.1:8080` and start from the current user's Startup folder.

The Windows password prompt accepts an empty value only for a local account that has no password. Enter the account password—not a Windows Hello PIN—when a password exists. Passwordless local accounts use Windows' native `AutoAdminLogon`; other accounts use the temporary official Sysinternals Autologon utility.

## Layout

- `kiosk.ps1` loads the wizard and exits with its result.
- `cleanup.ps1` removes the persistent Windows kiosk configuration owned by this project.
- `src/app.ps1` defines the ordered wizard flow.
- `src/steps/` contains one file per configuration concern.
- `runtime/` contains the scripts copied to the configured PC.
- `setup.ps1` is the remote GitHub bootstrap.

Run the dependency-free PowerShell checks on Windows with:

```bat
powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows\tests\run.ps1
```
