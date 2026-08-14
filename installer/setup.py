#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH Desktop Launcher — 安装引导程序（setup.exe）
=================================================
双击运行：把启动器安装到 %LOCALAPPDATA%\Programs\DSH Desktop Launcher，
创建开始菜单/桌面快捷方式，注册卸载信息。无需管理员权限。

打包：pyinstaller --onefile --windowed --name "DSH-Setup" --icon ../Picture/deepseek.ico \
      --add-data "../dist/DSH-Launcher.exe;." \
      --add-data "../Picture/deepseek.ico;Picture" \
      --add-data "../Picture/deepseek.icon;Picture" \
      --add-data "../README.md;." setup.py
"""

import os
import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

APP_NAME = "DSH Desktop Launcher"
EXE_NAME = "DSH-Launcher.exe"
ICON_NAME = "deepseek.ico"


def resource_path(rel):
    """PyInstaller 打包后从 _MEIPASS 读取内置资源；源码运行时多路径回退。"""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return str(Path(sys._MEIPASS) / rel)
    here = Path(__file__).resolve().parent
    parent = here.parent
    candidates = [
        here / rel,
        parent / rel,
        parent / "dist" / rel,
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return str(candidates[0])


class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"安装 {APP_NAME}")
        self.resizable(False, False)
        self._install_dir = Path(os.environ["LOCALAPPDATA"]) / "Programs" / APP_NAME
        self._build_ui()
        self._set_icon()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _set_icon(self):
        try:
            ico = resource_path(f"Picture/{ICON_NAME}")
            if os.path.exists(ico):
                self.iconbitmap(ico)
        except Exception:
            pass

    def _build_ui(self):
        pad = {"padx": 20, "pady": 8}
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="DSH Desktop Launcher", font=("Segoe UI", 14, "bold")).pack(**pad)
        ttk.Label(frame, text="DeepSeek Harness 桌面启动器\n（托盘 / 静默启动 / 开机自启 / 日志）").pack(**pad)
        ttk.Label(
            frame,
            text=f"将安装到:\n{self._install_dir}\n\n"
                 "• 创建开始菜单与桌面快捷方式\n"
                 "• 可在“设置 → 应用”中卸载\n"
                 "• 无需管理员权限",
            justify="left",
        ).pack(**pad)

        btns = ttk.Frame(frame)
        btns.pack(**pad)
        self.btn_install = ttk.Button(btns, text="安装", command=self._do_install, width=14)
        self.btn_install.pack(side="left")
        self.btn_cancel = ttk.Button(btns, text="取消", command=self._on_cancel, width=14)
        self.btn_cancel.pack(side="left", padx=(10, 0))

        self.status_var = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.status_var, foreground="#666").pack()

    def _on_cancel(self):
        self.destroy()

    def _do_install(self):
        self.btn_install.config(state="disabled")
        self.btn_cancel.config(state="disabled")
        self.status_var.set("正在安装…")
        self.update_idletasks()
        try:
            self._install()
        except Exception as e:
            self.status_var.set("")
            messagebox.showerror("安装失败", str(e), parent=self)
            self.btn_install.config(state="normal")
            self.btn_cancel.config(state="normal")
            return
        messagebox.showinfo(APP_NAME, "安装完成！\n点击开始菜单或桌面的“DSH Desktop Launcher”启动。", parent=self)
        self.destroy()

    def _install(self):
        # 1) 创建目录并复制文件
        self._install_dir.mkdir(parents=True, exist_ok=True)
        pic_dir = self._install_dir / "Picture"
        pic_dir.mkdir(exist_ok=True)

        for src, dst in [
            (resource_path(EXE_NAME), self._install_dir / EXE_NAME),
            (resource_path(f"Picture/{ICON_NAME}"), pic_dir / ICON_NAME),
            (resource_path("Picture/deepseek.icon"), pic_dir / "deepseek.icon"),
            (resource_path("README.md"), self._install_dir / "README.md"),
        ]:
            if os.path.exists(src):
                shutil.copy2(src, dst)

        # 2) 快捷方式
        import win32com.client  # pywin32
        shell = win32com.client.Dispatch("WScript.Shell")
        exe_path = str(self._install_dir / EXE_NAME)
        ico_path = str(pic_dir / ICON_NAME)

        start_menu = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        desktop = Path.home() / "Desktop"

        # 开始菜单（静默）
        sm = shell.CreateShortCut(str(start_menu / f"{APP_NAME}.lnk"))
        sm.Targetpath = exe_path
        sm.Arguments = "--silent"
        sm.WorkingDirectory = str(self._install_dir)
        sm.IconLocation = f"{ico_path},0"
        sm.Description = "DeepSeek Harness 桌面启动器"
        sm.save()

        # 桌面（普通）
        ds = shell.CreateShortCut(str(desktop / f"{APP_NAME}.lnk"))
        ds.Targetpath = exe_path
        ds.WorkingDirectory = str(self._install_dir)
        ds.IconLocation = f"{ico_path},0"
        ds.Description = "DeepSeek Harness 桌面启动器"
        ds.save()

        # 3) 卸载信息
        import winreg
        unreg = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\DSHDesktopLauncher"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, unreg) as k:
            winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
            winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, "1.0.0")
            winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, "Kiayxd")
            winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, str(self._install_dir))
            winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, ico_path)
            uninst = f'powershell.exe -ExecutionPolicy Bypass -File "{self._install_dir / "uninstall.ps1"}"'
            winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ, uninst)

        # 4) 卸载脚本
        uninstall_ps1 = f'''$ErrorActionPreference = 'SilentlyContinue'
$AppName = '{APP_NAME}'
$InstallDir = Join-Path $env:LOCALAPPDATA 'Programs\\{APP_NAME}'
Get-Process -Name 'DSH-Launcher' -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item (Join-Path $env:APPDATA "Microsoft\\Windows\\Start Menu\\Programs\\$AppName.lnk") -Force
Remove-Item (Join-Path ([Environment]::GetFolderPath('Desktop')) "$AppName.lnk") -Force
Remove-Item "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\DSHDesktopLauncher" -Recurse -Force
Start-Sleep -Seconds 1
Remove-Item $InstallDir -Recurse -Force
Write-Host "$AppName 已卸载"
'''
        (self._install_dir / "uninstall.ps1").write_text(uninstall_ps1, encoding="utf-8-sig")


def main():
    app = InstallerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
