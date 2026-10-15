# Run by the "title color" folder-open task in tasks.json.
# Cyan title bar when this repo is opened as U:\nxcustom (the live tree), green anywhere else.

$settingsPath = Join-Path $PSScriptRoot 'settings.json'
$root = (Split-Path $PSScriptRoot -Parent).TrimEnd('\')

if ($root -ieq 'U:\nxcustom') {
    $colors = [ordered]@{
        'titleBar.activeBackground'   = '#00bcd4'
        'titleBar.activeForeground'   = '#000000'
        'titleBar.inactiveBackground' = '#00838f'
        'titleBar.inactiveForeground' = '#e0f7fa'
    }
} else {
    $colors = [ordered]@{
        'titleBar.activeBackground'   = '#2e7d32'
        'titleBar.activeForeground'   = '#ffffff'
        'titleBar.inactiveBackground' = '#1b5e20'
        'titleBar.inactiveForeground' = '#c8e6c9'
    }
}

# Keep any other settings; only workbench.colorCustomizations is replaced.
$settings = [pscustomobject]@{}
if (Test-Path $settingsPath) {
    try {
        $settings = Get-Content $settingsPath -Raw | ConvertFrom-Json -ErrorAction Stop
    } catch {
        Write-Warning "settings.json is not plain JSON (comments?); leaving it alone."
        exit 0
    }
}
$settings | Add-Member -NotePropertyName 'workbench.colorCustomizations' -NotePropertyValue ([pscustomobject]$colors) -Force

$json = $settings | ConvertTo-Json -Depth 10
$current = if (Test-Path $settingsPath) { (Get-Content $settingsPath -Raw).Trim() } else { '' }
if ($current -ne $json.Trim()) {
    [IO.File]::WriteAllText($settingsPath, $json + "`r`n", (New-Object Text.UTF8Encoding $false))
}
