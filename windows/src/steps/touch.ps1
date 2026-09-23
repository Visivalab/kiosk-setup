function Test-KioskTouchscreen {
    try {
        $touch = Get-CimInstance Win32_PnPEntity | Where-Object {
            $_.Name -match "touch.?screen|pantalla tactil|écran tactile"
        } | Select-Object -First 1
        if ($touch) {
            Write-KioskDone "touch screen detected. Windows manages its mapping for this display."
        } else {
            Write-KioskDone "no touch screen was detected. Nothing was changed."
        }
    } catch {
        Write-KioskDone "touch screen detection was unavailable. Windows will keep its current mapping."
    }
}
