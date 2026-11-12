$ErrorActionPreference = 'Stop'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$script = Join-Path $PSScriptRoot 'importer.py'
function Run-Phase($phase) {
    & $python $script $phase
    if ($LASTEXITCODE -ne 0) { throw "Importer phase failed: $phase" }
}
Run-Phase 'inspect'
if (-not (Test-Path (Join-Path $PSScriptRoot 'runs\morin-chapter-01\manifest.json'))) { Run-Phase 'prepare' }
foreach ($phase in @('extract','figures','classify','pack','verify')) { Run-Phase $phase }
