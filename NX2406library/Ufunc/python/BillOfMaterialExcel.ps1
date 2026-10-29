<#
.SYNOPSIS
    Fills the bill of material workbooks BillOfMaterial.py has already copied from their templates.

.DESCRIPTION
    Python in NX has no Excel library, so BillOfMaterial.py gathers every cell, writes them to a JSON file and runs
    this script, which drives Excel through COM the way the C# Bom (ExcelApplication / NXExcelData) did. Excel stays
    hidden; each workbook is saved and closed. The JSON:

        { "workbooks": [ { "path": "...xlsx", "sheets": [ {
              "name": null | "fasteners",   # null = the workbook's active sheet
              "format": true,               # NXExcelData.WriteData: every column centered, Verdana 10
              "used_range": false,          # true: row / column count from the sheet's UsedRange (ExcelApplication.SetCell)
              "cells": [ [row, column, value], ... ],
              "green": [ [row, column], ... ] } ] } ] }

    Exit code 0 when every workbook was written, 1 otherwise (the error is on stdout for the listing window).
    Kept ASCII-only: PowerShell 5.1 reads a BOM-less script as Windows-1252.
#>
param([Parameter(Mandatory = $true)][string]$Path)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$job = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json

$xlCenter = -4108
# RGB(0, 255, 0) as Excel's BGR integer - System.Drawing.Color.FromArgb(0, 255, 0) in the C#.
$green = 65280

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
$failed = $false

try {
    foreach ($book in $job.workbooks) {
        $workbook = $null
        try {
            $workbook = $excel.Workbooks.Open($book.path)

            foreach ($sheet in $book.sheets) {
                if ($sheet.name) {
                    $worksheet = $workbook.Worksheets.Item($sheet.name)
                } else {
                    $worksheet = $workbook.ActiveSheet
                }

                if ($sheet.format) {
                    $worksheet.Columns.HorizontalAlignment = $xlCenter
                    $worksheet.Columns.Font.Name = 'verdana'
                    $worksheet.Columns.Font.Size = 10
                }

                if ($sheet.used_range) {
                    $origin = $worksheet.UsedRange
                } else {
                    $origin = $worksheet
                }

                foreach ($cell in $sheet.cells) {
                    # Not "... .Value2 = $value": PowerShell caches the COM setter by the first value's type, so a
                    # sheet of strings followed by a number fails ("Unable to cast Int32 to String").
                    $range = $origin.Cells.Item([int]$cell[0], [int]$cell[1])
                    [void]$range.GetType().InvokeMember('Value2', [Reflection.BindingFlags]::SetProperty, $null, $range, @($cell[2]))
                }

                foreach ($cell in $sheet.green) {
                    $origin.Cells.Item([int]$cell[0], [int]$cell[1]).Interior.Color = $green
                }

                Write-Output ("{0} [{1}]: {2} cells" -f $book.path, $worksheet.Name, @($sheet.cells).Count)
            }

            $workbook.Save()
        } catch {
            $failed = $true
            Write-Output ("{0}: {1} (line {2})" -f $book.path, $_.Exception.Message, $_.InvocationInfo.ScriptLineNumber)
        } finally {
            if ($workbook -ne $null) {
                $workbook.Close($false)
                [void][Runtime.InteropServices.Marshal]::ReleaseComObject($workbook)
            }
        }
    }
} finally {
    $excel.Quit()
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

if ($failed) { exit 1 }
exit 0
