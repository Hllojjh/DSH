$ErrorActionPreference = 'Continue'
$log = 'D:\DS-harness\DSH-desktop\logs\remote-firewall.log'
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
('elevated: ' + $isAdmin + ' at ' + (Get-Date -Format o)) | Out-File $log -Encoding utf8
$rule = Get-NetFirewallRule -DisplayName 'DSH Web 3080 (Radmin remote)' -ErrorAction SilentlyContinue
if ($rule) {
    'firewall rule already present' | Out-File $log -Encoding utf8 -Append
    exit
}
try {
    New-NetFirewallRule -DisplayName 'DSH Web 3080 (Radmin remote)' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 3080 -InterfaceAlias 'Radmin VPN','WLAN' -RemoteAddress LocalSubnet -Profile Any -ErrorAction Stop | Out-Null
    'firewall rule created OK' | Out-File $log -Encoding utf8 -Append
} catch {
    ('firewall rule FAILED: ' + $_.Exception.Message) | Out-File $log -Encoding utf8 -Append
}