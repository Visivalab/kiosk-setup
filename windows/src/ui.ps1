function Read-KioskChoice {
    param([string] $Prompt, [string[]] $Options)

    while ($true) {
        Write-Host $Prompt
        for ($index = 0; $index -lt $Options.Count; $index++) {
            Write-Host ("{0}) {1}" -f ($index + 1), $Options[$index])
        }
        $raw = Read-Host ("Choose [1-{0}]" -f $Options.Count)
        $number = 0
        if ([int]::TryParse($raw, [ref] $number) -and $number -ge 1 -and $number -le $Options.Count) {
            return $number - 1
        }
        Write-Host "WARN: Invalid choice. Enter a number from the list." -ForegroundColor Yellow
    }
}

function Read-KioskRequired {
    param([string] $Prompt)
    while ($true) {
        $value = (Read-Host $Prompt).Trim()
        if ($value) { return $value }
        Write-Host "WARN: $Prompt cannot be empty." -ForegroundColor Yellow
    }
}

function Read-KioskSecret {
    param([string] $Prompt)
    while ($true) {
        $secure = Read-Host $Prompt -AsSecureString
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $value = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
        if ($value) { return $value }
        Write-Host "WARN: $Prompt cannot be empty." -ForegroundColor Yellow
    }
}

function Read-KioskConfirmation {
    param([string] $Prompt, [bool] $Default = $true)
    $suffix = if ($Default) { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        $answer = (Read-Host "$Prompt $suffix").Trim().ToLowerInvariant()
        if (-not $answer) { return $Default }
        if ($answer -in @("y", "yes")) { return $true }
        if ($answer -in @("n", "no")) { return $false }
        Write-Host "WARN: Enter y or n." -ForegroundColor Yellow
    }
}

function Write-KioskProgress { param([string] $Message) Write-Host "[....] $Message" }

function Write-KioskDone {
    param([string] $Message)
    $report = "Done: $Message"
    $script:Reports.Add($report)
    Write-Host $report
}
