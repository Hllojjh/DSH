#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DSH Desktop Launcher — DeepSeek Harness 桌面启动器
====================================================
一个零依赖（纯标准库）的 Windows 桌面小应用，用于：
  * 一键启动 / 停止本机 DSH（DeepSeek Harness）Web UI（默认 http://127.0.0.1:3080）
  * 实时查看 dsh 进程日志
  * 一键在浏览器中打开 DSH Web UI
  * 配置 DeepSeek API Key（写入 ~/.dsh/.credentials.yaml，启动时注入环境变量）

运行方式：
  python dsh_launcher.py            # 正常启动 GUI
  python dsh_launcher.py --smoke    # 冒烟测试：打开窗口 2 秒后自动关闭
  python dsh_launcher.py --selftest # 命令行自检（不打开窗口）
"""

from __future__ import annotations

import glob
import json
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

# 可选依赖：系统托盘。未安装时优雅降级（关闭窗口 = 退出程序）。
try:
    import pystray
    from PIL import Image, ImageDraw
    TRAY_AVAILABLE = True
except ImportError:
    pystray = None
    TRAY_AVAILABLE = False

APP_NAME = "DSH Desktop Launcher"
# 打包成 exe 时 __file__ 指向临时解压目录，必须用可执行文件所在目录，
# 这样 config.json / logs 会落在 exe 旁边，源码运行时则是脚本所在目录。
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
CONFIG_FILE = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "logs" / "dsh-web.log"
DSH_HOME = Path(os.environ.get("DSH_HOME", str(Path.home() / ".dsh")))
CRED_FILE = DSH_HOME / ".credentials.yaml"
DEFAULT_PORT = 3080
POLL_MS = 600          # 状态轮询间隔
LOG_POLL_MS = 100      # 日志队列消费间隔
MAX_LOG_LINES = 3000   # GUI 日志区最大行数

# 应用图标（托盘 + 任务栏）：
# - 打包成 exe 时：优先从 PyInstaller 内置资源目录（sys._MEIPASS）读取
# - 源码运行时：应用目录下的 Picture/deepseek.icon
# - 其次回退到工作区 picture/deepseek.icon，最后回退到内置绘制图标。
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _bundle_dir = Path(sys._MEIPASS)
    ICON_CANDIDATES = [
        _bundle_dir / "Picture" / "deepseek.icon",
        APP_DIR / "Picture" / "deepseek.icon",
        APP_DIR / "picture" / "deepseek.icon",
        APP_DIR.parent / "picture" / "deepseek.icon",
    ]
else:
    ICON_CANDIDATES = [
        APP_DIR / "Picture" / "deepseek.icon",
        APP_DIR / "picture" / "deepseek.icon",
        APP_DIR.parent / "picture" / "deepseek.icon",
    ]

DEFAULT_CONFIG = {
    "port": DEFAULT_PORT,
    "auto_open_browser": True,
    "launch_cmd": None,  # 探测到的 dsh 启动命令，None 表示自动探测
    "auto_tray_on_start": True,  # 启动后自动隐藏到系统托盘
    "close_to_tray": True,       # 点击窗口关闭按钮时最小化到托盘而非退出
    "autostart_launch_dsh": True,  # 开机自启动（--silent）时自动启动 DSH 服务
}

# 开机自启动：写入 HKCU 注册表 Run 键（仅当前用户，无需管理员权限）
AUTOSTART_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "DSHDesktopLauncher"


# --------------------------------------------------------------------------
# 配置与凭据
# --------------------------------------------------------------------------

def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_FILE.exists():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            for k in cfg:
                if k in data:
                    cfg[k] = data[k]
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def read_api_key() -> str:
    """从 ~/.dsh/.credentials.yaml 读取 DEEPSEEK_API_KEY（明文）。"""
    try:
        if not CRED_FILE.exists():
            return ""
        for line in CRED_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("DEEPSEEK_API_KEY"):
                val = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                return val
    except Exception:
        pass
    return ""


def write_api_key(key: str) -> None:
    """写入/更新 ~/.dsh/.credentials.yaml 的 DEEPSEEK_API_KEY 行，保留其余内容。"""
    key = key.strip()
    CRED_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = CRED_FILE.read_text(encoding="utf-8").splitlines() if CRED_FILE.exists() else []
    idx = next((i for i, l in enumerate(lines) if l.strip().startswith("DEEPSEEK_API_KEY")), None)
    new_line = f"DEEPSEEK_API_KEY: {key}"
    if idx is not None:
        lines[idx] = new_line
    else:
        lines.append(new_line)
    CRED_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------
# 开机自启动（HKCU 注册表 Run 键，--silent 静默模式）
# --------------------------------------------------------------------------

def autostart_command() -> str:
    """生成写入注册表 Run 键的静默启动命令行。

    打包成 exe 时指向 exe 本身；源码运行时指向 pythonw.exe + 本脚本，
    保证无控制台窗口闪现。
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --silent'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)  # 兜底：无 pythonw 时退回 python.exe
    return f'"{pythonw}" "{Path(__file__).resolve()}" --silent'


def autostart_enabled() -> bool:
    """检测当前用户 Run 键中是否已注册本启动器。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY) as key:
            value, _ = winreg.QueryValueEx(key, AUTOSTART_NAME)
        return "dsh" in value.lower() and "--silent" in value.lower()
    except OSError:
        return False


def set_autostart(enable: bool) -> bool:
    """启用 / 禁用开机自启动。返回是否成功。"""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_REG_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enable:
                winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, AUTOSTART_NAME)
                except FileNotFoundError:
                    pass  # 本来就没有，视为成功
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# 应用图标（托盘 + 任务栏）
# --------------------------------------------------------------------------

def load_app_icon_image(scale: int = 2):
    """加载 deepseek 图标（.icon 文件实际是 PNG 内容）。

    返回 PIL Image（RGBA），背景近白色已转为透明；找不到或解码失败返回 None。
    scale: 源图放大倍数（默认 2 倍，40x29 → 80x58，保证高 DPI 下清晰）。
    """
    if not TRAY_AVAILABLE:
        return None
    for cand in ICON_CANDIDATES:
        if not cand.exists():
            continue
        try:
            img = Image.open(cand).convert("RGBA")
            _make_white_transparent(img)
            if scale != 1:
                img = img.resize(
                    (img.width * scale, img.height * scale),
                    Image.LANCZOS,
                )
            return img
        except Exception:
            continue
    return None


def _make_white_transparent(img):
    """把近白色背景 (≈249,250,251) 的像素转为透明，保留图标主体（DeepSeek 蓝）。"""
    w, h = img.size
    px = img.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if r >= 235 and g >= 235 and b >= 235:
                px[x, y] = (r, g, b, 0)


# 托盘画布尺寸：Windows 托盘 API（LR_DEFAULTSIZE，通常取 32x32）对超大单帧
# ICO 兼容性差——128x128 画布会导致图标缩到系统尺寸后几乎不可见。
# 64x64 是经过验证的安全尺寸，源图放大 2 倍后缩入画布，清晰度足够。
TRAY_ICON_SIZE = 64


def make_tray_icon_image():
    """生成托盘图标：deepseek 图标（放大 2 倍后缩入 64 画布），回退内置图标。"""
    img = load_app_icon_image(scale=2)
    if img is not None:
        # 缩放到画布内（保持比例、居中、透明底），主体占满画布
        size = TRAY_ICON_SIZE
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        img.thumbnail((size - 6, size - 6), Image.LANCZOS)
        canvas.paste(img, ((size - img.width) // 2, (size - img.height) // 2), img)
        return canvas
    return _builtin_tray_icon()


def _builtin_tray_icon():
    """内置兜底图标：深蓝圆角方块 + 白色圆环。"""
    size = TRAY_ICON_SIZE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([2, 2, size - 3, size - 3], radius=14, fill=(30, 60, 120, 255))
    d.ellipse([size // 2 - 12, size // 2 - 12, size // 2 + 12, size // 2 + 12], fill=(255, 255, 255, 255))
    d.ellipse([size // 2 - 6, size // 2 - 6, size // 2 + 6, size // 2 + 6], fill=(30, 60, 120, 255))
    return img

def resolve_dsh_cmd() -> str:
    """探测 dsh 可执行文件。优先复用 npx 缓存中已安装的 dsh（离线可用），
    其次全局 dsh，最后退回 npx -y（可能联网检查）。"""
    # 1) npx 缓存：%LOCALAPPDATA%\npm-cache\_npx\<hash>\node_modules\.bin\dsh.cmd
    try:
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        if local.exists():
            candidates = glob.glob(str(local / "npm-cache" / "_npx" / "*" / "node_modules" / ".bin" / "dsh.cmd"))
            if candidates:
                best = max(candidates, key=os.path.getmtime)
                return best
    except Exception:
        pass
    # 2) 全局 PATH
    p = shutil.which("dsh")
    if p:
        return p
    # 3) 退回 npx
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if npx:
        return f"{npx} -y @deepseek-ai/dsh"
    raise RuntimeError("未找到 dsh / npx，请先安装 Node.js（https://nodejs.org）")


# --------------------------------------------------------------------------
# 端口 / 进程检测
# --------------------------------------------------------------------------

def profile_fixed_port() -> int | None:
    """读取 ~/.dsh/profiles/web/cordis.patch.yml 中 webserver 固定端口。

    dsh 的 profile 补丁层优先级高于命令行 --port：若用户在 profile 里给
    webserver 固定了端口（例如 Radmin VPN 远程访问 3080），启动器传 --port
    不会生效。返回固定端口；未固定返回 None。
    """
    patch = DSH_HOME / "profiles" / "web" / "cordis.patch.yml"
    try:
        if not patch.exists():
            return None
        text = patch.read_text(encoding="utf-8")
        # 在 "id: webserver" 段落后找 port: <数字>
        idx = text.find("id: webserver")
        if idx == -1:
            return None
        segment = text[idx:idx + 600]
        for line in segment.splitlines():
            m = line.strip()
            if m.startswith("port:"):
                val = m.split(":", 1)[1].strip()
                if val.isdigit():
                    return int(val)
    except Exception:
        pass
    return None


def port_in_use(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def listening_pid(port: int):
    """返回监听端口的 PID（仅本机），找不到返回 None。"""
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == "TCP" and parts[3] == "LISTENING":
                local = parts[1]
                # local 形如 127.0.0.1:3080 或 [::1]:3080
                if local.endswith(f":{port}") or local.endswith(f"]:{port}"):
                    try:
                        return int(parts[4])
                    except ValueError:
                        return None
    except Exception:
        pass
    return None


# --------------------------------------------------------------------------
# 核心：dsh 进程管理
# --------------------------------------------------------------------------

class DshProcess:
    """管理一个由本启动器拉起的 dsh 子进程（含输出读取线程）。"""

    CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.out_queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, cmd: list[str], env: dict, cwd: str) -> bool:
        self.stop()
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(LOG_FILE, "ab", buffering=0)  # 供读取线程回写
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            cwd=cwd,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=self.CREATE_NEW_PROCESS_GROUP | self.CREATE_NO_WINDOW,
        )
        self._thread = threading.Thread(
            target=self._reader, args=(self.proc, log_fh), daemon=True, name="dsh-log-reader"
        )
        self._thread.start()
        return True

    def _reader(self, proc: subprocess.Popen, log_fh):
        """逐行读取子进程输出：写入日志文件 + 放入队列供 GUI 消费。"""
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                raw = line.rstrip("\r\n")
                try:
                    log_fh.write((raw + "\n").encode("utf-8", errors="replace"))
                except Exception:
                    pass
                self.out_queue.put(raw)
        except Exception:
            pass
        finally:
            try:
                log_fh.close()
            except Exception:
                pass

    def stop(self, timeout: float = 8.0) -> bool:
        """停止自己启动的进程树（taskkill /T）。返回是否确认停止。"""
        if self.proc is None:
            return True
        pid = self.proc.pid
        if self.proc.poll() is None:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, timeout=timeout,
                    creationflags=self.CREATE_NO_WINDOW,
                )
            except Exception:
                pass
        # 等进程真正退出
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                break
            time.sleep(0.15)
        exited = self.proc.poll() is not None
        self.proc = None
        return exited


# --------------------------------------------------------------------------
# 系统托盘（pystray 可选）
# --------------------------------------------------------------------------

class TrayController:
    """系统托盘控制器。pystray 不可用时所有方法安全空转（返回 False / 无操作）。

    托盘线程与 tkinter 主线程隔离：所有回调通过 app.after(0, ...) 调度回主线程，
    避免跨线程操作 tkinter 控件。
    """

    def __init__(self, app: "LauncherApp"):
        self.app = app
        self._icon = None
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        return TRAY_AVAILABLE and self._icon is not None

    def _make_image(self):
        """托盘图标：优先 deepseek 图标（Picture/deepseek.icon），回退内置绘制图标。"""
        return make_tray_icon_image()

    def start(self) -> bool:
        """创建托盘图标并在后台线程运行消息循环。返回是否成功。"""
        if not TRAY_AVAILABLE:
            return False
        try:
            menu = pystray.Menu(
                pystray.MenuItem("显示主窗口", self._cb_show, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("启动 DSH", self._cb_start),
                pystray.MenuItem("停止 DSH", self._cb_stop),
                pystray.MenuItem("重启 DSH", self._cb_restart),
                pystray.MenuItem("打开 Web UI", self._cb_open),
                pystray.MenuItem("关闭外部占用实例", self._cb_kill_external),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("重启程序", self._cb_restart_program),
                pystray.MenuItem("退出", self._cb_quit),
            )
            self._icon = pystray.Icon(
                "dsh-desktop-launcher",
                self._make_image(),
                f"{APP_NAME} — DeepSeek Harness",
                menu,
            )
            self._thread = threading.Thread(target=self._icon.run, daemon=True, name="tray-icon")
            self._thread.start()
            return True
        except Exception as e:
            self._icon = None
            self.app._post_status(f"托盘启动失败（不影响使用）: {e}")
            return False

    def stop(self):
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None

    def notify(self, title: str, message: str):
        if self.available:
            try:
                self._icon.notify(message, title)
            except Exception:
                pass

    # ---- 托盘菜单回调（托盘线程 → 调度回主线程）----

    def _cb_show(self, icon, item):
        self.app.after(0, self.app._show_window)

    def _cb_start(self, icon, item):
        self.app.after(0, self.app._on_start)

    def _cb_stop(self, icon, item):
        self.app.after(0, self.app._on_stop)

    def _cb_restart(self, icon, item):
        self.app.after(0, self.app._on_restart)

    def _cb_open(self, icon, item):
        self.app.after(0, self.app._on_open)

    def _cb_kill_external(self, icon, item):
        self.app.after(0, self.app._on_kill_external)

    def _cb_restart_program(self, icon, item):
        self.app.after(0, self.app._on_restart_program)

    def _cb_quit(self, icon, item):
        self.app.after(0, self.app._on_tray_quit)


# --------------------------------------------------------------------------
# GUI
# --------------------------------------------------------------------------

class LauncherApp(tk.Tk):
    def __init__(self):
        # 静默模式（--silent）或"启动后自动隐藏到托盘"开启时，窗口从创建起就隐藏，
        # 必须在任何 title/geometry/UI 构建之前 withdraw，彻底杜绝窗口闪现。
        self._silent_mode = "--silent" in sys.argv
        if self._silent_mode:
            super().__init__()
            self.withdraw()
            self.update_idletasks()  # 立即生效，确保不渲染任何帧
        else:
            super().__init__()
        self.title(f"{APP_NAME} — DeepSeek Harness")
        self.geometry("920x620")
        self.minsize(720, 480)
        self.cfg = load_config()
        self.dsh = DshProcess()
        self.tray = TrayController(self)
        self.external_pid: int | None = None   # 端口被占用但不是我们启动的进程 PID
        self._starting = False
        self._profile_port = profile_fixed_port()
        # 线程安全：工作线程不能直接操作 tkinter，回调经此队列由主线程执行
        self._ui_cb_queue: queue.Queue = queue.Queue()
        # 状态轮询事件：任意线程 set() 即可触发一次端口检测（检测在后台线程执行）
        self._status_event = threading.Event()

        self._set_window_icon()
        self._build_ui()
        self._apply_config_to_ui()
        self._start_status_loop()
        self.after(200, self._refresh_status)

    def _call_main(self, fn, *args):
        """线程安全：把回调交给主线程执行（tkinter 只能在主线程操作）。"""
        self._ui_cb_queue.put((fn, args))

    def _drain_ui_cb(self):
        """主线程轮询执行工作线程提交的回调（必须由主线程调用）。"""
        self.after(LOG_POLL_MS, self._drain_ui_cb)
        try:
            while True:
                fn, args = self._ui_cb_queue.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    pass
        except queue.Empty:
            pass

    # ---------- 状态检测（后台线程，避免阻塞主线程） ----------

    def _start_status_loop(self):
        """后台线程：定期检测端口/PID 状态。

        端口检测包含 socket 连接与 netstat 子进程调用（可能阻塞数百毫秒），
        必须在后台线程执行；结果通过 _call_main 送回主线程更新 UI。
        """

        def loop():
            while True:
                self._status_event.wait(timeout=POLL_MS / 1000.0)
                self._status_event.clear()
                try:
                    port = self.effective_port()
                    in_use = port_in_use(port)
                    pid = listening_pid(port) if in_use else None
                    alive = self.dsh.alive
                    starting = self._starting
                    self._call_main(self._apply_status, port, in_use, pid, alive, starting)
                except Exception:
                    pass

        threading.Thread(target=loop, daemon=True, name="status-loop").start()

    def _apply_status(self, port: int, in_use: bool, pid, alive: bool, starting: bool):
        """主线程执行：根据后台检测结果更新 UI。"""
        if starting:
            return
        if alive:
            self._set_state("running")
            self.status_dot.config(fg="#34a853")
            self.status_label.config(text="运行中（本启动器托管）")
            self.pid_label.config(text=f"PID {self.dsh.proc.pid}")
            self.port_label.config(text=f"端口 {port}")
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
            self.btn_restart.config(state="normal")
            self.btn_kill_ext.config(state="disabled")
            self.btn_open.config(state="normal")
            return

        if in_use:
            self.external_pid = pid
            self._set_state("external")
            self.status_dot.config(fg="#fbbc04")
            self.status_label.config(text="端口已被外部 DSH 实例占用")
            self.pid_label.config(text=f"PID {pid}" if pid else "")
            self.port_label.config(text=f"端口 {port}")
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="disabled")
            self.btn_restart.config(state="disabled")
            self.btn_kill_ext.config(state="normal" if pid else "disabled")
            self.btn_open.config(state="normal")
            return

        self.external_pid = None
        self._set_state("stopped")
        self.status_dot.config(fg="#ea4335")
        self.status_label.config(text="已停止")
        self.pid_label.config(text="")
        self.port_label.config(text=f"端口 {port}")
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_restart.config(state="disabled")
        self.btn_kill_ext.config(state="disabled")
        self.btn_open.config(state="disabled")

    def _set_state(self, state: str):
        self._state = state

    def effective_port(self) -> int:
        """实际生效端口：profile 固定端口优先（dsh 补丁层覆盖命令行 --port）。"""
        return self._profile_port or int(self.cfg.get("port", DEFAULT_PORT))

    # ---------- 任务栏图标 ----------

    def _set_window_icon(self):
        """设置任务栏 / 窗口图标（deepseek 图标，放大 2 倍后缩到 32x32 更清晰），失败时静默跳过。"""
        if not TRAY_AVAILABLE:
            return
        try:
            img = load_app_icon_image(scale=2)
            if img is None:
                return
            # 缩放为适合窗口的 32x32，转 PNG 字节给 tk.PhotoImage
            import io
            icon32 = img.copy()
            icon32.thumbnail((32, 32), Image.LANCZOS)
            buf = io.BytesIO()
            icon32.save(buf, format="PNG")
            self._window_icon = tk.PhotoImage(data=buf.getvalue())
            self.iconphoto(True, self._window_icon)
        except Exception:
            pass  # 图标失败不影响使用

    # ---------- UI 构建 ----------

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except Exception:
            pass

        pad = {"padx": 10, "pady": 6}

        # 顶部状态条（打开 Web UI 按钮也放在这一行，最右端）
        top = ttk.Frame(self, padding=(10, 8, 10, 4))
        top.pack(fill="x")
        self.status_dot = tk.Label(top, text="●", font=("Segoe UI", 14), fg="#9aa0a6")
        self.status_dot.pack(side="left")
        self.status_label = ttk.Label(top, text="正在检测状态…", font=("Segoe UI", 11, "bold"))
        self.status_label.pack(side="left", padx=(6, 0))
        self.port_label = ttk.Label(top, text=f"端口 {self.cfg['port']}")
        self.port_label.pack(side="left", padx=(14, 0))
        self.btn_open = ttk.Button(top, text="🌐 打开 Web UI", command=self._on_open, width=15, state="disabled")
        self.btn_open.pack(side="right")
        self.pid_label = ttk.Label(top, text="", foreground="#666")
        self.pid_label.pack(side="right", padx=(0, 10))

        # 按钮区（左右两列，每列两行）
        btns = ttk.Frame(self, padding=(10, 4))
        btns.pack(fill="x")

        # 左列：DSH 服务操作（第 1 行：启动/停止；第 2 行：重启/解除占用）
        left_col = ttk.Frame(btns)
        left_col.pack(side="left")
        left_row1 = ttk.Frame(left_col)
        left_row1.pack(anchor="w", pady=(0, 4))
        self.btn_start = ttk.Button(left_row1, text="▶ 启动 DSH", command=self._on_start, width=13)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(left_row1, text="■ 停止 DSH", command=self._on_stop, width=13, state="disabled")
        self.btn_stop.pack(side="left", padx=(6, 0))
        left_row2 = ttk.Frame(left_col)
        left_row2.pack(anchor="w")
        self.btn_restart = ttk.Button(left_row2, text="↻ 重启 DSH", command=self._on_restart, width=13, state="disabled")
        self.btn_restart.pack(side="left")
        self.btn_kill_ext = ttk.Button(left_row2, text="⛔ 解除占用", command=self._on_kill_external, width=13, state="disabled")
        self.btn_kill_ext.pack(side="left", padx=(6, 0))

        # 右列：程序操作（第 1 行：关闭/重启程序；第 2 行：设置/刷新）
        right_col = ttk.Frame(btns)
        right_col.pack(side="right")
        right_row1 = ttk.Frame(right_col)
        right_row1.pack(anchor="e", pady=(0, 4))
        self.btn_quit = ttk.Button(right_row1, text="⏻ 关闭程序", command=self._on_tray_quit, width=13)
        self.btn_quit.pack(side="left")
        self.btn_restart_prog = ttk.Button(right_row1, text="⟳ 重启程序", command=self._on_restart_program, width=13)
        self.btn_restart_prog.pack(side="left", padx=(6, 0))
        right_row2 = ttk.Frame(right_col)
        right_row2.pack(anchor="e")
        self.btn_settings = ttk.Button(right_row2, text="⚙ 设置", command=self._on_settings, width=13)
        self.btn_settings.pack(side="left")
        self.btn_refresh = ttk.Button(right_row2, text="🔄 刷新", command=self._refresh_status, width=13)
        self.btn_refresh.pack(side="left", padx=(6, 0))

        # 日志区
        log_frame = ttk.LabelFrame(self, text=" 运行日志 （logs/dsh-web.log） ", padding=(6, 6))
        log_frame.pack(fill="both", expand=True, padx=10, pady=(4, 6))
        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap="word", state="disabled", font=("Consolas", 9),
            background="#1e1e1e", foreground="#d4d4d4", insertbackground="#d4d4d4",
        )
        self.log_text.pack(fill="both", expand=True)

        # 底部状态栏
        statusbar = ttk.Frame(self, padding=(10, 2))
        statusbar.pack(fill="x", side="bottom")
        self.foot_label = ttk.Label(statusbar, text="就绪", foreground="#666", anchor="w")
        self.foot_label.pack(side="left", fill="x", expand=True)
        self.dsh_path_label = ttk.Label(statusbar, text="", foreground="#888", anchor="e")
        self.dsh_path_label.pack(side="right")

    def _apply_config_to_ui(self):
        try:
            self.dsh_path_label.config(text=f"dsh: {resolve_dsh_cmd()}")
        except Exception as e:
            self.dsh_path_label.config(text=f"dsh: 未找到（{e}）")
        # 若 profile 固定了端口，提示用户设置里的端口不会生效
        if self._profile_port and self._profile_port != int(self.cfg.get("port", DEFAULT_PORT)):
            self._post_status(
                f"提示：profile（cordis.patch.yml）将 webserver 固定为端口 {self._profile_port}，"
                f"设置里的端口 {self.cfg.get('port')} 不会生效，实际使用 {self._profile_port}"
            )

    # ---------- 状态刷新 ----------

    def _refresh_status(self):
        """轻量触发：让后台状态检测线程立即执行一次检测（不做任何阻塞 I/O）。

        真正的端口/PID 检测在 _start_status_loop 的后台线程中完成，
        结果经 _apply_status 更新 UI——主线程永远不做 netstat/socket 阻塞调用。
        """
        self._status_event.set()

    def _set_state(self, state: str):
        self._state = state

    # ---------- 动作 ----------

    def _on_start(self, silent: bool = False):
        """启动 DSH。silent=True（静默模式）时端口被占不弹窗，仅记入日志。"""
        port = self.effective_port()
        if port_in_use(port):
            if silent:
                self._post_status(f"自启动：端口 {port} 已被占用（可能已有 DSH 在运行），跳过启动")
            else:
                messagebox.showwarning(APP_NAME, f"端口 {port} 已被占用，无法启动。\n请先停止现有 DSH 实例或更换端口。")
            return
        self._starting = True
        self._set_state("starting")
        self.status_dot.config(fg="#4285f4")
        self.status_label.config(text="正在启动…")
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        threading.Thread(target=self._start_worker, args=(port,), daemon=True, name="dsh-start").start()

    def _silent_autostart(self):
        """静默模式（--silent）下的自动启动：不弹窗，按配置决定是否拉起 DSH。

        启动后在后台等待端口就绪，用托盘通知告知用户结果（成功/已运行/失败），
        避免"以为自启动失败"。
        """
        if not self.cfg.get("autostart_launch_dsh", True):
            self._post_status("自启动：已按配置跳过自动启动 DSH")
            return
        port = self.effective_port()
        if port_in_use(port):
            self._post_status(f"自启动：端口 {port} 已被占用（DSH 可能已在运行），跳过启动")
            self.tray.notify(APP_NAME, "DSH 已在运行，无需重复启动（端口已被占用）")
            return
        self._post_status("自启动：正在后台启动 DSH 服务…")
        self._on_start(silent=True)

        def watch_result():
            deadline = time.time() + 20
            while time.time() < deadline:
                if port_in_use(port):
                    self._call_main(self.tray.notify, APP_NAME, "DSH 服务已自动启动（端口就绪）")
                    return
                time.sleep(0.5)
            # 超时未就绪：多半是 npx 首次拉取慢或启动报错，通知用户查看日志
            self._post_status("自启动：DSH 未在 20 秒内就绪，请双击托盘图标查看日志")
            self._call_main(self.tray.notify, APP_NAME, "DSH 自动启动未就绪，双击托盘图标查看日志")

        threading.Thread(target=watch_result, daemon=True, name="autostart-watch").start()

    def _start_worker(self, port: int):
        try:
            dsh_cmd = self.cfg.get("launch_cmd") or resolve_dsh_cmd()
            # 兼容 npx fallback 形式（含空格参数）与直接路径形式
            cmd = dsh_cmd.split() if " " in dsh_cmd else [dsh_cmd]
            cmd = cmd + ["web", "--port", str(port)]
            env = os.environ.copy()
            key = read_api_key()
            if key:
                env["DEEPSEEK_API_KEY"] = key
            ok = self.dsh.start(cmd, env, str(Path.home()))
            self._post_status(f"启动命令: {' '.join(cmd)}" + (f"（已注入 API Key）" if key else ""))
            if not ok:
                self._post_status("启动失败：子进程未能创建")
        except Exception as e:
            self._post_status(f"启动失败: {e}")
        finally:
            self._starting = False
            self._call_main(self._refresh_status)

    def _on_stop(self):
        if self._state == "external":
            messagebox.showinfo(
                APP_NAME,
                f"当前 DSH 实例不是由本启动器启动的（PID {self.external_pid}）。\n"
                "请使用“⛔ 关闭占用”按钮强制结束它，\n"
                "或手动执行：\n"
                f"  taskkill /PID {self.external_pid} /T /F",
            )
            return
        if not self.dsh.alive:
            return
        self.btn_stop.config(state="disabled")
        self.btn_restart.config(state="disabled")
        self._set_state("stopping")
        self.status_label.config(text="正在停止…")
        threading.Thread(target=self._stop_worker, daemon=True, name="dsh-stop").start()

    def _stop_worker(self):
        exited = self.dsh.stop()
        self._post_status("DSH 已停止" if exited else "停止超时，进程可能仍在运行（请检查任务管理器）")
        self._call_main(self._refresh_status)

    def _on_kill_external(self):
        """关闭占用端口的外部实例（非本启动器托管的进程）。"""
        if self._state != "external" or not self.external_pid:
            return
        pid = self.external_pid
        port = self.effective_port()
        # 二次确认：杀外部进程有风险，明确告知
        if not messagebox.askyesno(
            APP_NAME,
            f"端口 {port} 被外部进程（PID {pid}）占用。\n\n"
            "点击“是”将强制结束该进程及其子进程树：\n"
            f"  taskkill /PID {pid} /T /F\n\n"
            "⚠️ 该进程不是由本启动器启动的（例如 remote-restart.ps1 拉起的 node 服务），\n"
            "强制结束可能导致正在进行的任务中断。确定要继续吗？",
        ):
            return
        self.btn_kill_ext.config(state="disabled")
        self.status_label.config(text="正在关闭外部实例…")
        threading.Thread(target=self._kill_external_worker, args=(pid,), daemon=True, name="kill-external").start()

    def _kill_external_worker(self, pid: int):
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._post_status(f"已强制结束外部实例 PID {pid}")
        except Exception as e:
            self._post_status(f"关闭外部实例失败: {e}")
        self._call_main(self._refresh_status)

    def _on_restart(self):
        self._on_stop()
        # 等待停止完成且端口释放后重新启动
        port = self.effective_port()
        def wait_and_start():
            deadline = time.time() + 12
            while time.time() < deadline:
                if not self.dsh.alive and not port_in_use(port):
                    break
                time.sleep(0.2)
            self._call_main(self._on_start)
        threading.Thread(target=wait_and_start, daemon=True, name="dsh-restart").start()

    def _restart_command(self) -> list[str]:
        """生成重启本程序用的命令行（保持当前参数，如 --silent）。"""
        keep = [a for a in sys.argv[1:] if a not in ("--smoke", "--selftest")]
        if getattr(sys, "frozen", False):
            return [sys.executable, *keep]
        # 源码运行：优先用 pythonw（无控制台窗口），与开机自启动一致
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        exe = pythonw if pythonw.exists() else Path(sys.executable)
        return [str(exe), str(Path(__file__).resolve()), *keep]

    def _on_restart_program(self):
        """重启启动器本身：按需停止 DSH，然后以相同参数重新拉起本程序。"""
        restart_cmd = self._restart_command()
        if self.dsh.alive:
            if not messagebox.askyesno(
                APP_NAME,
                "DSH 正在运行，重启程序前要停止它吗？\n"
                "（选择“否”将让 DSH 继续在后台运行，重启后由外部实例接管）",
            ):
                # 不停止 DSH，直接重启（DSH 继续后台运行）
                self.tray.stop()
                _release_single_instance()  # 必须先释放互斥体，否则新实例立即退出
                self.destroy()
                subprocess.Popen(
                    restart_cmd,
                    cwd=str(APP_DIR),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return
            self.btn_stop.config(state="disabled")
            self.status_label.config(text="正在停止…")
            self.update_idletasks()
            self.dsh.stop()
        self.tray.stop()
        _release_single_instance()  # 必须先释放互斥体，否则新实例立即退出
        self.destroy()
        subprocess.Popen(
            restart_cmd,
            cwd=str(APP_DIR),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _on_open(self):
        port = self.effective_port()
        webbrowser.open(f"http://127.0.0.1:{port}")

    def _on_settings(self):
        SettingsDialog(self)

    # ---------- 日志 ----------

    def _post_status(self, msg: str):
        """追加一条状态消息到日志区。线程安全（放入队列）。"""
        self.dsh.out_queue.put(f"[launcher] {time.strftime('%H:%M:%S')} {msg}")

    def _drain_log(self):
        self.after(LOG_POLL_MS, self._drain_log)
        try:
            while True:
                line = self.dsh.out_queue.get_nowait()
                self._append_log(line)
        except queue.Empty:
            pass

    def _append_log(self, line: str):
        self.log_text.config(state="normal")
        self.log_text.insert("end", line + "\n")
        # 限制行数
        line_count = int(self.log_text.index("end-1c").split(".")[0])
        if line_count > MAX_LOG_LINES:
            self.log_text.delete("1.0", f"{line_count - MAX_LOG_LINES}.0")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    # ---------- 窗口显示 / 托盘 ----------

    def _show_window(self):
        """从托盘恢复主窗口。"""
        self.deiconify()
        self.lift()
        self.focus_force()

    def _hide_to_tray(self):
        """隐藏主窗口到系统托盘。"""
        if not self.tray.available:
            return
        self.withdraw()
        self.tray.notify(APP_NAME, "已最小化到系统托盘，双击图标恢复窗口")

    def _on_close(self):
        """窗口关闭按钮（X）：若启用"关闭到托盘"且托盘可用，则隐藏而非退出。"""
        if self.tray.available and self.cfg.get("close_to_tray", True):
            self._hide_to_tray()
            return
        self._quit_all()

    def _on_tray_quit(self):
        """托盘菜单"退出"：先询问 DSH 是否停止，再真正退出。"""
        self._quit_all()

    def _quit_all(self):
        """真正退出：按需停止 DSH、停止托盘、销毁窗口。"""
        if self.dsh.alive:
            if not messagebox.askyesno(APP_NAME, "DSH 正在运行，退出前要停止它吗？\n（选择“否”将让 DSH 继续在后台运行）"):
                self.tray.stop()
                self.destroy()
                return
            self.btn_stop.config(state="disabled")
            self.status_label.config(text="正在停止…")
            self.update_idletasks()
            self.dsh.stop()
        self.tray.stop()
        self.destroy()


# --------------------------------------------------------------------------
# 设置对话框
# --------------------------------------------------------------------------

class SettingsDialog(tk.Toplevel):
    def __init__(self, app: LauncherApp):
        super().__init__(app)
        self.app = app
        self.title("设置 — API Key / 端口")
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)

        # API Key
        ttk.Label(frame, text="DeepSeek API Key (sk-...)").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.key_var = tk.StringVar(value=read_api_key())
        self.key_entry = ttk.Entry(frame, textvariable=self.key_var, width=46, show="•")
        self.key_entry.grid(row=1, column=0, sticky="we", pady=(0, 2))
        self.show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="显示密钥", variable=self.show_key, command=self._toggle_key).grid(
            row=2, column=0, sticky="w")
        ttk.Label(
            frame, text="保存到 ~/.dsh/.credentials.yaml，下次启动 DSH 时自动注入。",
            foreground="#888",
        ).grid(row=3, column=0, sticky="w", pady=(2, 8))

        # 端口
        ttk.Label(frame, text="Web UI 端口").grid(row=4, column=0, sticky="w", pady=(6, 4))
        self.port_var = tk.IntVar(value=int(app.cfg.get("port", DEFAULT_PORT)))
        port_spin = ttk.Spinbox(frame, from_=1024, to=65535, textvariable=self.port_var, width=10)
        port_spin.grid(row=5, column=0, sticky="w", pady=(0, 8))
        if app._profile_port:
            fixed_hint = (f"注意：profile（cordis.patch.yml）已将 webserver 固定为端口 "
                          f"{app._profile_port}，此处修改不会生效，实际始终使用 {app._profile_port}。")
        else:
            fixed_hint = None
        if fixed_hint:
            ttk.Label(frame, text=fixed_hint, foreground="#b26a00", wraplength=420).grid(
                row=5, column=1, sticky="w", padx=(10, 0))

        # 自动打开浏览器
        self.auto_open = tk.BooleanVar(value=bool(app.cfg.get("auto_open_browser", True)))
        ttk.Checkbutton(frame, text="启动完成后自动在浏览器打开 Web UI", variable=self.auto_open).grid(
            row=6, column=0, sticky="w", pady=(0, 8))

        # 托盘行为
        self.auto_tray = tk.BooleanVar(value=bool(app.cfg.get("auto_tray_on_start", True)))
        ttk.Checkbutton(frame, text="程序启动后自动隐藏到系统托盘", variable=self.auto_tray).grid(
            row=7, column=0, sticky="w", pady=(0, 4))
        self.close_to_tray = tk.BooleanVar(value=bool(app.cfg.get("close_to_tray", True)))
        ttk.Checkbutton(frame, text="点击窗口关闭按钮（X）时最小化到托盘而非退出", variable=self.close_to_tray).grid(
            row=8, column=0, sticky="w", pady=(0, 4))
        tray_hint = ("（需要 pystray + Pillow；未安装时自动回退为普通窗口行为）"
                     if not TRAY_AVAILABLE else "（托盘图标双击可恢复主窗口）")
        ttk.Label(frame, text=tray_hint, foreground="#888").grid(
            row=9, column=0, sticky="w", pady=(2, 8))

        # 开机自启动
        self.autostart_var = tk.BooleanVar(value=autostart_enabled())
        ttk.Checkbutton(
            frame, text="开机自启动（静默启动到系统托盘，不显示窗口）",
            variable=self.autostart_var, command=self._on_autostart_toggle,
        ).grid(row=10, column=0, sticky="w", pady=(4, 4))
        self.autostart_dsh_var = tk.BooleanVar(value=bool(app.cfg.get("autostart_launch_dsh", True)))
        ttk.Checkbutton(
            frame, text="自启动时自动启动 DSH 服务", variable=self.autostart_dsh_var,
        ).grid(row=11, column=0, sticky="w", pady=(0, 4))
        autostart_hint = (f"注册表位置：HKCU\\{AUTOSTART_REG_KEY}\\{AUTOSTART_NAME}\n"
                          f"命令行：{autostart_command()}")
        ttk.Label(frame, text=autostart_hint, foreground="#888", justify="left").grid(
            row=12, column=0, sticky="w", pady=(2, 8))

        # 底部按钮
        btns = ttk.Frame(frame)
        btns.grid(row=13, column=0, sticky="e", pady=(8, 0))
        ttk.Button(btns, text="保存", command=self._save).pack(side="left")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="left", padx=(8, 0))

        self.bind("<Return>", lambda e: self._save())
        self.bind("<Escape>", lambda e: self.destroy())

    def _toggle_key(self):
        self.key_entry.config(show="" if self.show_key.get() else "•")

    def _on_autostart_toggle(self):
        """勾选/取消"开机自启动"时立即写入/删除注册表，无需点保存。"""
        enable = self.autostart_var.get()
        if not TRAY_AVAILABLE and enable:
            messagebox.showwarning(
                "设置", "系统托盘不可用（未安装 pystray/Pillow），静默启动无法隐藏窗口，\n"
                "已自动取消开机自启动。请先执行：python -m pip install pystray pillow",
                parent=self,
            )
            self.autostart_var.set(False)
            return
        if set_autostart(enable):
            self.app._post_status(f"开机自启动已{'开启' if enable else '关闭'}")
        else:
            messagebox.showerror("设置", "写入注册表失败，请以管理员身份运行或检查系统权限。", parent=self)
            self.autostart_var.set(not enable)

    def _save(self):
        key = self.key_var.get().strip()
        if key and not key.startswith("sk-"):
            messagebox.showwarning("设置", "API Key 通常以 sk- 开头，请检查是否填写正确。", parent=self)
            return
        if key:
            write_api_key(key)
        else:
            messagebox.showwarning("设置", "API Key 为空：已跳过写入。\n（如需清除旧密钥，请手动编辑 ~/.dsh/.credentials.yaml）", parent=self)
        try:
            port = int(self.port_var.get())
            if not (1024 <= port <= 65535):
                raise ValueError
        except ValueError:
            messagebox.showwarning("设置", "端口必须是 1024–65535 之间的数字。", parent=self)
            return
        self.app.cfg["port"] = port
        self.app.cfg["auto_open_browser"] = bool(self.auto_open.get())
        self.app.cfg["auto_tray_on_start"] = bool(self.auto_tray.get())
        self.app.cfg["close_to_tray"] = bool(self.close_to_tray.get())
        self.app.cfg["autostart_launch_dsh"] = bool(self.autostart_dsh_var.get())
        save_config(self.app.cfg)
        self.app.port_label.config(text=f"端口 {port}")
        self.app._post_status(
            f"设置已保存：端口 {port}，自动打开浏览器 {'开' if self.app.cfg['auto_open_browser'] else '关'}，"
            f"启动隐藏托盘 {'开' if self.app.cfg['auto_tray_on_start'] else '关'}，"
            f"关闭最小化托盘 {'开' if self.app.cfg['close_to_tray'] else '关'}，"
            f"自启动自动拉 DSH {'开' if self.app.cfg['autostart_launch_dsh'] else '关'}"
            + ("，已写入 API Key" if key else "")
        )
        self.app._refresh_status()
        self.destroy()


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------

SINGLE_INSTANCE_MUTEX = "Local\\DSHDesktopLauncherMutex"
_single_instance_handle = None


def _ensure_single_instance() -> bool:
    """单实例保护：通过 Windows 命名互斥体检测是否已有实例在运行。

    返回 True = 本进程是唯一实例（应继续启动）；
    返回 False = 已有实例在运行（调用方应退出，避免出现多个托盘图标）。
    非 Windows 平台或无权限时放行（返回 True）。
    """
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateMutexW(None, False, SINGLE_INSTANCE_MUTEX)
        if not handle:
            return True  # 无法创建互斥体，放行
        last_err = ctypes.get_last_error()
        if last_err == 183:  # ERROR_ALREADY_EXISTS：已有实例
            kernel32.CloseHandle(handle)
            return False
        # 保存句柄防止被 GC；进程退出时 OS 自动释放
        global _single_instance_handle
        _single_instance_handle = handle
        return True
    except Exception:
        return True


def _release_single_instance():
    """主动释放单实例互斥体。

    重启程序时必须先释放再拉起新进程，否则新进程会因"已有实例"立即退出。
    """
    global _single_instance_handle
    if _single_instance_handle is not None:
        try:
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle(_single_instance_handle)
        except Exception:
            pass
        _single_instance_handle = None

def selftest():
    """命令行自检：验证环境与核心逻辑（不打开窗口）。"""
    ok = True
    print(f"[selftest] Python {sys.version.split()[0]}")
    print(f"[selftest] DSH_HOME = {DSH_HOME}")
    print(f"[selftest] credentials = {CRED_FILE}（存在: {CRED_FILE.exists()}）")
    print(f"[selftest] 系统托盘: {'pystray ' + getattr(pystray, '__version__', '?') + ' + Pillow 可用' if TRAY_AVAILABLE else '不可用（未安装 pystray/Pillow，关闭窗口=退出）'}")
    try:
        cmd = resolve_dsh_cmd()
        print(f"[selftest] dsh 命令: {cmd}")
    except Exception as e:
        print(f"[selftest] dsh 命令: 失败 -> {e}")
        ok = False
    key = read_api_key()
    print(f"[selftest] API Key: {'已配置 (' + (key[:6] + '…' if len(key) > 6 else '') + ')' if key else '未配置'}")
    icon = load_app_icon_image()
    if icon is not None:
        found = next((str(c) for c in ICON_CANDIDATES if c.exists()), "未知路径")
        print(f"[selftest] 应用图标: 已加载 ({icon.size[0]}x{icon.size[1]}, 来自 {found})")
    else:
        print(f"[selftest] 应用图标: 未找到，使用内置图标")
    print(f"[selftest] 开机自启动: {'已开启 (静默模式)' if autostart_enabled() else '未开启'}")
    print(f"[selftest] 自启动命令行: {autostart_command()}")
    fixed = profile_fixed_port()
    print(f"[selftest] profile 固定端口: {fixed if fixed else '无（使用启动器设置）'}")
    for port in (fixed or int(DEFAULT_CONFIG["port"]),):
        in_use = port_in_use(port)
        pid = listening_pid(port) if in_use else None
        print(f"[selftest] 端口 {port}: {'占用中 (PID ' + str(pid) + ')' if in_use else '空闲'}")
    print(f"[selftest] {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    smoke = "--smoke" in sys.argv
    silent = "--silent" in sys.argv
    # 单实例保护：已有实例时直接退出（避免多个托盘图标）。
    # --smoke 测试模式跳过，避免测试环境残留实例导致误判。
    if not smoke and not _ensure_single_instance():
        print("DSH Desktop Launcher 已在运行，本次启动退出。")
        return 0
    app = LauncherApp()  # 静默/自动隐藏时窗口已在 __init__ 中 withdraw（无闪现）
    app._drain_log()
    app._drain_ui_cb()  # 主线程轮询执行工作线程提交的 tkinter 回调
    if smoke:
        app.after(2000, app.destroy)
    else:
        tray_ok = app.tray.start()
        # 需要"不显示窗口"的情况：--silent，或开启"启动后自动隐藏到托盘"
        want_hidden = silent or app.cfg.get("auto_tray_on_start", True)
        if want_hidden:
            if tray_ok:
                # 窗口自创建起即隐藏（无闪现），直接进托盘并自动启动 DSH 服务
                app._post_status("已静默启动，进入系统托盘")
                app.after(800, app._silent_autostart)
            else:
                # 托盘不可用：静默无意义，恢复窗口并提示
                app.deiconify()
                app._post_status("警告：系统托盘不可用，启动退化为普通窗口模式")
        else:
            app.deiconify()  # 用户关闭了"自动隐藏"，正常显示窗口
    app.protocol("WM_DELETE_WINDOW", app._on_close)
    app.mainloop()
    if not smoke:
        app.tray.stop()


if __name__ == "__main__":
    main()
