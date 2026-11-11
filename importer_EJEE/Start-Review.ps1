$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$log = Join-Path $root 'runs\morin-chapter-01\logs'
New-Item -ItemType Directory -Force -Path $log | Out-Null
function Test-Port($port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try { $client.Connect('127.0.0.1', $port); return $true } catch { return $false } finally { $client.Dispose() }
}
if (-not (Test-Port 8011)) {
    Start-Process -FilePath (Join-Path $root '.venv\Scripts\python.exe') -WindowStyle Hidden -WorkingDirectory $root `
        -ArgumentList 'serve.py','--port','8011' `
        -RedirectStandardOutput (Join-Path $log 'api.out.log') -RedirectStandardError (Join-Path $log 'api.err.log')
}
if (-not (Test-Port 5183)) {
    $node = (Get-Command node.exe).Source
    $vite = Join-Path $root 'reference\PaperLab\frontend\node_modules\vite\bin\vite.js'
    $conf = Join-Path $root 'vite.review.config.mjs'
    Start-Process -FilePath $node -WindowStyle Hidden -WorkingDirectory (Join-Path $root 'reference\PaperLab\frontend') `
        -ArgumentList $vite,'--config',$conf `
        -RedirectStandardOutput (Join-Path $log 'web.out.log') -RedirectStandardError (Join-Path $log 'web.err.log')
}
Write-Output 'Review app: http://127.0.0.1:5183/archive'
