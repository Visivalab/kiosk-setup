# Windows kiosk config

The Windows terminal entry point currently detects and lists every active display. It is read-only; per-display kiosk configuration is the next step.

From Command Prompt or PowerShell on Windows 10/11:

```bat
windows\kiosk.cmd
```

Example output:

```text
Detected displays

1) \\.\DISPLAY1 - 1920x1080 at (0,0) - Primary
2) \\.\DISPLAY2 - 1920x1080 at (1920,0)

Detected 2 active display(s).
```

The primary display is listed first. Other displays are ordered by their position in the Windows virtual desktop.

Run the dependency-free display tests on Windows with:

```bat
powershell.exe -NoProfile -ExecutionPolicy Bypass -File windows\tests\run.ps1
```
