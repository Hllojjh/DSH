$rt = (Get-Date).AddMinutes(2).ToString('HH:mm')
schtasks /create /f /tn DSHWebRestart /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File D:\DS-harness\DSH-desktop\remote-restart.ps1" /sc once /st $rt | Out-Null
('restart scheduled at ' + $rt) | Out-File 'D:\DS-harness\DSH-desktop\logs\remote-schedule.log' -Encoding utf8