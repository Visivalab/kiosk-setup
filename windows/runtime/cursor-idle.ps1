param([int] $Seconds = 5)

Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class CursorIdle {
  [StructLayout(LayoutKind.Sequential)] public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
  [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO value);
  [DllImport("user32.dll")] public static extern IntPtr SetCursor(IntPtr cursor);
  public static int IdleSeconds() { var x = new LASTINPUTINFO(); x.cbSize=(uint)Marshal.SizeOf(x); GetLastInputInfo(ref x); return (Environment.TickCount-(int)x.dwTime)/1000; }
}
"@

while ($true) {
    if ([CursorIdle]::IdleSeconds() -ge $Seconds) {
        [void] [CursorIdle]::SetCursor([IntPtr]::Zero)
    }
    Start-Sleep -Milliseconds 250
}
