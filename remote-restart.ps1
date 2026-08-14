# DSH Remote Access - one-shot restart: stop old dsh web, start new one (0.0.0.0), verify.
$ErrorActionPreference = 'SilentlyContinue'
$log = 'D:\DS-harness\DSH-desktop\logs\remote-restart.log'
$lines = @()

Start-Sleep -Seconds 15   # grace: let the running chat deliver its final message

# inject the API key like the desktop launcher does
$cred = 'C:\Users\Admin\.dsh\.credentials.yaml'
if (Test-Path $cred) {
    $line = Get-Content $cred | Where-Object { $_ -match '^DEEPSEEK_API_KEY' } | Select-Object -First 1
    if ($line) {
        $val = ($line -split ':', 2)[1].Trim().Trim('"').Trim("'")
        if ($val) { $env:DEEPSEEK_API_KEY = $val }
    }
}

$listener = Get-NetTCPConnection -LocalPort 3080 -State Listen | Select-Object -First 1
if ($listener) {
    $lines += ('stopping old pid ' + $listener.OwningProcess)
    Stop-Process -Id $listener.OwningProcess -Force
    Start-Sleep -Seconds 4
} else {
    $lines += 'no old listener on 3080'
}

$node = 'C:\Program Files\nodejs\node.exe'
$bin  = 'C:\Users\Admin\AppData\Local\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\lib\bin.js'
$null = Start-Process -FilePath $node -ArgumentList @($bin, 'web', '--port', '3080') -WindowStyle Hidden -WorkingDirectory 'C:\Users\Admin'
$lines += 'started: dsh web --port 3080 (binds 0.0.0.0 via profile patch)'

Start-Sleep -Seconds 20
$okLocal = Test-NetConnection -ComputerName 127.0.0.1 -Port 3080 -InformationLevel Quiet
$okVpn   = Test-NetConnection -ComputerName 26.159.224.5 -Port 3080 -InformationLevel Quiet
$lines += ('port3080 loopback: ' + $okLocal + '; radmin-ip: ' + $okVpn)

# cleanup: these were one-shot tasks; remove them so they never re-run
schtasks /delete /tn DSHFirewall3080 /f | Out-Null
schtasks /delete /tn DSHWebRestart /f | Out-Null
$lines += 'scheduled tasks cleaned up'

$lines | Out-File -FilePath $log -Encoding utf8