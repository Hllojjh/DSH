# DSH Desktop Launcher - 安装脚本
# 用法: powershell -ExecutionPolicy Bypass -File install.ps1 [-Silent]
# 安装到当前用户目录（无需管理员权限）

param(
    [switch]$Silent
)

$ErrorActionPreference = 'Stop'
$AppName = 'DSH Desktop Launcher'
$InstallDir = Join-Path $env:LOCALAPPDATA 'Programs\DSH Desktop Launcher'
$ExeName = 'DSH-Launcher.exe'
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path
# exe 可能在 installer 同级目录（源码构建）或 dist 目录（打包产物）
$ParentDir = Split-Path -Parent $SourceDir
$ExeCandidates = @(
    (Join-Path $SourceDir $ExeName),
    (Join-Path $ParentDir "dist\$ExeName"),
    (Join-Path $ParentDir $ExeName)
)
$ExePath = $ExeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $ExePath) {
    throw "未找到 $ExeName，请先构建 exe（dist\DSH-Launcher.exe）"
}

function Log($msg) {
    if (-not $Silent) { Write-Host $msg }
}

# ---------- 1. 复制文件 ----------
Log "==> 安装到 $InstallDir"
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $InstallDir 'Picture') -Force | Out-Null

# 复制 exe 与图标（图标可能在 installer 同级或上级 Picture 目录）
Copy-Item $ExePath (Join-Path $InstallDir $ExeName) -Force
$iconSrc = @(
    (Join-Path $SourceDir 'Picture\deepseek.icon'),
    (Join-Path $ParentDir 'Picture\deepseek.icon')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iconSrc) { Copy-Item $iconSrc (Join-Path $InstallDir 'Picture\deepseek.icon') -Force }
$icoSrc = @(
    (Join-Path $SourceDir 'Picture\deepseek.ico'),
    (Join-Path $ParentDir 'Picture\deepseek.ico')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($icoSrc) { Copy-Item $icoSrc (Join-Path $InstallDir 'Picture\deepseek.ico') -Force }

# 复制 README
$readmeSrc = @(
    (Join-Path $SourceDir 'README.md'),
    (Join-Path $ParentDir 'README.md')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($readmeSrc) { Copy-Item $readmeSrc (Join-Path $InstallDir 'README.md') -Force }

# ---------- 2. 快捷方式 ----------
$WshShell = New-Object -ComObject WScript.Shell
$StartMenuDir = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
$DesktopDir = [Environment]::GetFolderPath('Desktop')

# 开始菜单
$smLnk = Join-Path $StartMenuDir "$AppName.lnk"
$sc = $WshShell.CreateShortcut($smLnk)
$sc.TargetPath = Join-Path $InstallDir $ExeName
$sc.Arguments = '--silent'
$sc.WorkingDirectory = $InstallDir
$sc.IconLocation = (Join-Path $InstallDir 'Picture\deepseek.ico') + ',0'
$sc.Description = 'DeepSeek Harness 桌面启动器'
$sc.Save()
Log "==> 开始菜单快捷方式: $smLnk"

# 桌面快捷方式（可选，默认创建）
$deskLnk = Join-Path $DesktopDir "$AppName.lnk"
$sc2 = $WshShell.CreateShortcut($deskLnk)
$sc2.TargetPath = Join-Path $InstallDir $ExeName
$sc2.Arguments = ''
$sc2.WorkingDirectory = $InstallDir
$sc2.IconLocation = (Join-Path $InstallDir 'Picture\deepseek.ico') + ',0'
$sc2.Description = 'DeepSeek Harness 桌面启动器'
$sc2.Save()
Log "==> 桌面快捷方式: $deskLnk"

# ---------- 3. 卸载信息（注册表） ----------
$unreg = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DSHDesktopLauncher"
New-Item -Path $unreg -Force | Out-Null
New-ItemProperty -Path $unreg -Name 'DisplayName' -Value $AppName -PropertyType String -Force | Out-Null
New-ItemProperty -Path $unreg -Name 'DisplayVersion' -Value '1.0.0' -PropertyType String -Force | Out-Null
New-ItemProperty -Path $unreg -Name 'Publisher' -Value 'Kiayxd' -PropertyType String -Force | Out-Null
New-ItemProperty -Path $unreg -Name 'InstallLocation' -Value $InstallDir -PropertyType String -Force | Out-Null
New-ItemProperty -Path $unreg -Name 'DisplayIcon' -Value (Join-Path $InstallDir 'Picture\deepseek.ico') -PropertyType String -Force | Out-Null
New-ItemProperty -Path $unreg -Name 'UninstallString' -Value "powershell.exe -ExecutionPolicy Bypass -File `"$InstallDir\uninstall.ps1`"" -PropertyType String -Force | Out-Null
Log "==> 卸载信息已注册"

# ---------- 4. 复制卸载脚本 ----------
$uninstallScript = @'
$ErrorActionPreference = 'SilentlyContinue'
$AppName = 'DSH Desktop Launcher'
$InstallDir = Join-Path $env:LOCALAPPDATA 'Programs\DSH Desktop Launcher'

# 停止运行中的实例
Get-Process -Name 'DSH-Launcher' -ErrorAction SilentlyContinue | Stop-Process -Force

# 删除快捷方式
Remove-Item (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$AppName.lnk") -Force
Remove-Item (Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk") -Force

# 删除注册表卸载信息
Remove-Item "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\DSHDesktopLauncher" -Recurse -Force

# 删除安装目录
Start-Sleep -Seconds 1
Remove-Item $InstallDir -Recurse -Force
Write-Host "DSH Desktop Launcher 已卸载"
'@
$uninstallScript | Out-File (Join-Path $InstallDir 'uninstall.ps1') -Encoding utf8
Log "==> 卸载脚本已生成"

if (-not $Silent) {
    Write-Host ""
    Write-Host "安装完成！"
    Write-Host "  启动: 开始菜单或桌面点击 'DSH Desktop Launcher'"
    Write-Host "  卸载: 设置 -> 应用 -> 卸载 或运行 $InstallDir\uninstall.ps1"
}
