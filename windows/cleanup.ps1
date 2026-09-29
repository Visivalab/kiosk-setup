Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

. (Join-Path $PSScriptRoot "src\steps\rotation.ps1")

function Test-CleanupAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Clear-KioskAutologonSecret {
    if (-not ("KioskAutologonSecret" -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class KioskAutologonSecret {
    [StructLayout(LayoutKind.Sequential)]
    struct LSA_OBJECT_ATTRIBUTES {
        public int Length;
        public IntPtr RootDirectory;
        public IntPtr ObjectName;
        public uint Attributes;
        public IntPtr SecurityDescriptor;
        public IntPtr SecurityQualityOfService;
    }

    [StructLayout(LayoutKind.Sequential)]
    struct LSA_UNICODE_STRING {
        public ushort Length;
        public ushort MaximumLength;
        public IntPtr Buffer;
    }

    [DllImport("advapi32.dll")]
    static extern uint LsaOpenPolicy(IntPtr systemName, ref LSA_OBJECT_ATTRIBUTES attributes, uint access, out IntPtr handle);

    [DllImport("advapi32.dll")]
    static extern uint LsaStorePrivateData(IntPtr handle, ref LSA_UNICODE_STRING key, IntPtr value);

    [DllImport("advapi32.dll")]
    static extern uint LsaNtStatusToWinError(uint status);

    [DllImport("advapi32.dll")]
    static extern uint LsaClose(IntPtr handle);

    public static void ClearDefaultPassword() {
        const uint POLICY_CREATE_SECRET = 0x20;
        const uint STATUS_OBJECT_NAME_NOT_FOUND = 0xC0000034;
        var attributes = new LSA_OBJECT_ATTRIBUTES();
        attributes.Length = Marshal.SizeOf(typeof(LSA_OBJECT_ATTRIBUTES));
        IntPtr handle;
        uint status = LsaOpenPolicy(IntPtr.Zero, ref attributes, POLICY_CREATE_SECRET, out handle);
        if (status != 0)
            throw new Win32Exception((int)LsaNtStatusToWinError(status));

        IntPtr buffer = Marshal.StringToHGlobalUni("DefaultPassword");
        try {
            var key = new LSA_UNICODE_STRING();
            key.Buffer = buffer;
            key.Length = (ushort)("DefaultPassword".Length * 2);
            key.MaximumLength = (ushort)(("DefaultPassword".Length + 1) * 2);
            status = LsaStorePrivateData(handle, ref key, IntPtr.Zero);
            if (status != 0 && status != STATUS_OBJECT_NAME_NOT_FOUND)
                throw new Win32Exception((int)LsaNtStatusToWinError(status));
        } finally {
            Marshal.FreeHGlobal(buffer);
            LsaClose(handle);
        }
    }
}
'@
    }
    [KioskAutologonSecret]::ClearDefaultPassword()
}

function Stop-KioskProcesses {
    param([string[]] $Roots)
    $processes = @(Get-CimInstance Win32_Process | Where-Object {
        $command = [string] $_.CommandLine
        if (-not $command -or [int] $_.ProcessId -eq $PID) { return $false }
        foreach ($root in $Roots) {
            if ($command.IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -ge 0) { return $true }
        }
        $false
    })
    foreach ($process in $processes) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Write-Host "Done: stopped $($processes.Count) kiosk process(es)."
}

function Get-KioskCleanupPorts {
    param([string] $MachineRoot)

    $statePath = Join-Path $MachineRoot "kiosk-state.json"
    if (Test-Path $statePath) {
        try {
            $state = Get-Content -Raw $statePath | ConvertFrom-Json
            $ports = @(@($state.ports) | Where-Object { $_ } | ForEach-Object { [int] $_ })
            if ($ports.Count -gt 0) { return $ports }
        } catch {}
    }
    @(8080)
}

function Invoke-KioskCleanup {
    try {
        if ($env:OS -ne "Windows_NT") { throw "This cleanup only runs on Windows. Nothing was changed." }
        if (-not (Test-CleanupAdministrator)) { throw "Run Windows Terminal as Administrator. Nothing was changed." }

        $userRoot = Join-Path $env:LOCALAPPDATA "pi-kiosk"
        $machineRoot = Join-Path $env:ProgramData "pi-kiosk"
        $startup = Join-Path ([Environment]::GetFolderPath("Startup")) "pi-kiosk.cmd"

        Remove-Item $startup -Force -ErrorAction SilentlyContinue
        Write-Host "Done: removed kiosk startup."

        & schtasks.exe /End /TN "pi-kiosk-totem-status" 2>$null | Out-Null
        & schtasks.exe /Delete /F /TN "pi-kiosk-totem-status" 2>$null | Out-Null
        Write-Host "Done: removed the kiosk status task."

        Stop-KioskProcesses @($userRoot, $machineRoot)

        $winlogon = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
        Remove-ItemProperty -Path $winlogon -Name AutoAdminLogon, DefaultUserName, DefaultDomainName, DefaultPassword -ErrorAction SilentlyContinue
        Clear-KioskAutologonSecret
        Write-Host "Done: disabled Windows autologin and cleared its saved secret."

        $ports = Get-KioskCleanupPorts $machineRoot
        foreach ($port in $ports) {
            & netsh.exe http delete urlacl url=http://127.0.0.1:$port/ 2>$null | Out-Null
        }
        Write-Host "Done: removed the local web server reservation on port(s) $($ports -join ', ')."

        Remove-Item $userRoot -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item $machineRoot -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Done: removed downloaded kiosk files, runtime files, logs, and saved kiosk credentials."

        $displays = @(Get-KioskDisplays)
        foreach ($display in $displays) {
            Initialize-RotationApi
            [KioskDisplay]::Rotate($display.DeviceName, 0)
        }
        Write-Host "Done: restored normal rotation on $($displays.Count) active display(s)."
        Write-Host "Done: Windows kiosk cleanup completed. RustDesk, VLC, power settings, and remote registration were left unchanged."
        return 0
    } catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        return 1
    }
}

if ($MyInvocation.InvocationName -ne ".") {
    exit (Invoke-KioskCleanup)
}
