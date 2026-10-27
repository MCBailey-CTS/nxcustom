# The Python UFuncs' progress window (in place of the C# Ui\ProgressLogForm, 2026-10-23; was AutoDesignProgress.ps1).
# progress_window.ProgressWindow starts it with the run's own progress file (one per run, in %TEMP%) - Auto Design and
# Export Strip use it; it stays open after the run until closed, and deletes the file then. Keep this file
# ASCII-only: PowerShell 5.1 reads a BOM-less script as Windows-1252.
#
# Lines in the file:
#   #TITLE text   the window title (the current operation)
#   #LOG text     one of the UFunc's own lines
#   #DONE         the run is over: stop following
#   anything else a builder step (tsg_nx.progress): indented under its program, and the tail of the title
#
# -Position Center (the default) or BottomRight (the screen's working area corner - Export Strip, whose NX Yes/No
# questions come up mid-run in the middle of the screen, where this TopMost window would cover them).
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [string]$Title = 'Progress',
    [ValidateSet('Center', 'BottomRight')][string]$Position = 'Center'
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = $Title
$form.Size = New-Object System.Drawing.Size(600, 400)
if ($Position -eq 'BottomRight') {
    $area = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $form.StartPosition = 'Manual'
    $form.Location = New-Object System.Drawing.Point(($area.Right - $form.Width), ($area.Bottom - $form.Height))
} else {
    $form.StartPosition = 'CenterScreen'
}
$form.TopMost = $true

$box = New-Object System.Windows.Forms.TextBox
$box.Multiline = $true
$box.ReadOnly = $true
$box.ScrollBars = 'Both'
$box.WordWrap = $false
$box.Dock = 'Fill'
$box.Font = New-Object System.Drawing.Font([System.Drawing.FontFamily]::GenericMonospace, 9)
$form.Controls.Add($box)

$state = @{ Stream = $null; Reader = $null; Partial = ''; Operation = $Title; Done = $false; Waited = 0 }

function Add-Line([string]$text) {
    $box.AppendText($text + [Environment]::NewLine)
}

function Read-Progress {
    if ($state.Done) { return }
    if ($null -eq $state.Reader) {
        try {
            # Shared for writing (AutoDesign.py and the builders append while this reads) and deleting.
            $share = [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
            $state.Stream = New-Object System.IO.FileStream($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, $share)
            $state.Reader = New-Object System.IO.StreamReader($state.Stream, [System.Text.Encoding]::UTF8)
        } catch {
            $state.Waited++
            if ($state.Waited -eq 40) { Add-Line "(waiting for $Path)" }
            return
        }
    }
    $chunk = $state.Reader.ReadToEnd()
    if (-not $chunk) { return }
    $text = $state.Partial + $chunk
    $lines = $text -split "`n"
    # The last piece has no newline yet: keep it for the next tick.
    $state.Partial = $lines[-1]
    foreach ($raw in $lines[0..($lines.Count - 2)]) {
        $line = $raw.TrimEnd("`r")
        if ($line.StartsWith('#TITLE ')) {
            $state.Operation = $line.Substring(7)
            $form.Text = $state.Operation
        } elseif ($line.StartsWith('#LOG ')) {
            Add-Line $line.Substring(5)
        } elseif ($line -eq '#DONE') {
            $state.Done = $true
            $state.Reader.Dispose()
            $state.Reader = $null
            return
        } elseif ($line) {
            Add-Line ('    ' + $line)
            $form.Text = $state.Operation + ': ' + $line
        }
    }
}

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 250
$timer.Add_Tick({ Read-Progress })
$timer.Start()

$form.Add_FormClosed({
    $timer.Stop()
    if ($null -ne $state.Reader) { $state.Reader.Dispose() }
    try { Remove-Item -LiteralPath $Path -ErrorAction Stop } catch { }
})

[void]$form.ShowDialog()
