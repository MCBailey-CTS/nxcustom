<#
.SYNOPSIS
    The bill of material's "Select Required Vendors" check list (the C# Static.BomShowCheckBoxDialog / CheckBoxDialog).

.DESCRIPTION
    BillOfMaterial.py writes the purchased materials found in the rows, and which of them the job's previous.txt had
    ticked, to a JSON file ({ "title": ..., "items": [...], "checked": [...] }) and runs this script, which shows them
    as a check list. OK writes the ticked items to stdout, one per line, and exits 0; closing the window exits 1
    (Python then stops the bill of material, as the C# did when the vendor dialog was cancelled).
    Kept ASCII-only: PowerShell 5.1 reads a BOM-less script as Windows-1252.
#>
param([Parameter(Mandatory = $true)][string]$Path)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$job = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
$checked = @($job.checked)

$form = New-Object System.Windows.Forms.Form
$form.Text = $job.title
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false
$form.TopMost = $true
$form.ClientSize = New-Object System.Drawing.Size(260, 330)

$list = New-Object System.Windows.Forms.CheckedListBox
$list.CheckOnClick = $true
$list.Location = New-Object System.Drawing.Point(10, 10)
$list.Size = New-Object System.Drawing.Size(240, 275)
foreach ($item in $job.items) {
    [void]$list.Items.Add($item, ($checked -contains $item))
}
$form.Controls.Add($list)

$ok = New-Object System.Windows.Forms.Button
$ok.Text = 'OK'
$ok.Location = New-Object System.Drawing.Point(94, 295)
$ok.Size = New-Object System.Drawing.Size(75, 25)
$ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
$form.Controls.Add($ok)
$form.AcceptButton = $ok

$form.Add_Shown({ $form.Activate() })

if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 1 }

foreach ($item in $list.CheckedItems) { Write-Output $item }
exit 0
