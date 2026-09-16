param(
    [Parameter(Mandatory=$true)][string]$InputPptx,
    [Parameter(Mandatory=$true)][string]$OutputDir
)
$ErrorActionPreference = 'Stop'
$source = (Resolve-Path -LiteralPath $InputPptx).Path
$destination = [IO.Path]::GetFullPath($OutputDir)
if (Test-Path -LiteralPath $destination) { throw 'OutputDir must be new to prevent stale exports' }
New-Item -ItemType Directory -Path $destination | Out-Null
$presentation = $null
$application = $null
$report = @{ source = $source; sha256 = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLower(); automated_open_export_passed = $false; visual_review = 'not tested' }
try {
    $application = New-Object -ComObject PowerPoint.Application
    $report.office_version = $application.Version
    $presentation = $application.Presentations.Open($source, -1, 0, 0)
    $report.slide_count = $presentation.Slides.Count
    $presentation.Export($destination, 'PNG', 1600, 900)
    $pages = @(Get-ChildItem -LiteralPath $destination -Filter '*.PNG')
    $report.exported_pages = $pages.Count
    $report.automated_open_export_passed = $pages.Count -eq $presentation.Slides.Count
} catch {
    $report.error = $_.Exception.Message
} finally {
    if ($presentation) { $presentation.Close(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentation) }
    if ($application) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($application) }
    $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $destination 'powerpoint-smoke.json') -Encoding utf8
}
if (-not $report.automated_open_export_passed) { exit 2 }
