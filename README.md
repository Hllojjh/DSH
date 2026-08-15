# DSH Desktop Launcher

基于 **Python + tkinter** 的 DeepSeek Harness（DSH）桌面启动器 —— 核心零第三方依赖（纯标准库，
系统托盘为可选的 `pystray` + `Pillow`），用于在本机一键启动 / 停止 DSH Web UI、实时查看日志、
配置 DeepSeek API Key。

## 🚀 部署方式（四种任选）

### 方式一：安装程序（setup.exe，推荐普通用户）

```
installer/dist/DSH-Setup.exe
```

- **大小**：约 43 MB（GUI 安装向导，含启动器 exe + 图标）
- **特点**：
  - 双击运行 → 点"安装"→ 自动安装到 `%LOCALAPPDATA%\Programs\DSH Desktop Launcher`
  - 自动创建**开始菜单**（静默启动）与**桌面**（普通启动）快捷方式
  - 可在 **设置 → 应用** 中正常卸载（含卸载脚本）
  - **无需管理员权限**
- 安装后从开始菜单/桌面快捷方式启动即可

### 方式二：一键下载 exe（便携版，无需任何环境）

```
dist/DSH-Launcher.exe
```

- **大小**：约 30 MB（单文件，PyInstaller 打包，含 Python 运行时与全部依赖）
- **用法**：双击运行 → 静默进入系统托盘 → 自动启动 DSH 服务 → 托盘气泡提示结果
- **兼容**：Windows 10/11 x64
- 下载后在任意文件夹运行即可（`config.json` / `logs/` 会生成在 exe 旁边）

### 方式三：npm / npx（需要 Node.js ≥16，推荐开发环境）

```bash
# 克隆仓库后本地运行
git clone https://github.com/Hllojjh/DSH.git
cd DSH

npm start            # 启动（优先 exe，缺 exe 时自动用 python）
npm run silent       # 静默启动到托盘
npm run selftest     # 环境自检
```

发布到 npm registry 后（`npm publish`），可一行命令直接运行：

```bash
npx dsh-desktop-launcher          # 启动
npx dsh-desktop-launcher --silent # 静默启动
```

> bin 脚本（`bin/dsh-launcher.js`）自动选择：存在 `dist/DSH-Launcher.exe` 就用 exe（无需 Python）；
> 否则回退 `pythonw dsh_launcher.py`（需 Python 3.10+）。

### 方式三：从源码运行（需 Python 3.10+ + Node.js）

```bash
python dsh_launcher.py            # 启动
python dsh_launcher.py --silent   # 静默
python dsh_launcher.py --selftest # 自检
```

> 若想从源码运行或自行打包，见下文"从源码运行"与"打包成独立 exe"。

## 功能

| 功能 | 说明 |
|---|---|
| ▶ 启动 DSH | 调用 `dsh web --port <端口>`（默认 3080）在后台启动 DSH Web UI |
| 🧩 以源码启动 | 可在 ⚙ 设置中开启：直接用 `node` 运行 dsh 源码 `bin.js`，跳过 npx/.cmd 层，启动更快 |
| ■ 停止 DSH | 只停止**由本启动器托管**的进程树（`taskkill /T`），绝不误杀外部实例 |
| ⛔ 关闭占用 | 端口被外部实例占用（黄色状态）时可用：二次确认后强制结束该外部进程及其子进程树 |
| ↻ 重启 DSH | 停止 DSH 后自动重新启动 |
| ⟳ 重启程序 | 重启启动器本身（保持 --silent 等参数；DSH 运行中先询问是否停止） |
| ⏻ 关闭程序 | 彻底退出启动器（先询问是否停止运行中的 DSH） |
| 🌐 打开 Web UI | 在浏览器打开 `http://127.0.0.1:<端口>` |
| ⚙ 设置 | 填写 API Key（写入 `~/.dsh/.credentials.yaml`）、修改端口、自动打开浏览器、托盘行为开关 |
| 📋 实时日志 | 运行日志实时显示，并落盘到 `logs/dsh-web.log` |
| 🔔 系统托盘 | 启动后自动隐藏到托盘；点窗口关闭按钮（X）最小化到托盘而非退出；托盘双击恢复窗口 |
| 🚀 开机自启动 | 注册到 HKCU 注册表 Run 键，开机静默启动到托盘（不显示窗口），可自动拉起 DSH 服务 |
| 🖼️ 自定义图标 | 托盘与任务栏窗口图标使用 `Picture/deepseek.icon`（DeepSeek 图标，白底自动透明化） |
| 🔒 单实例保护 | Windows 命名互斥体保证只有一个实例在运行（始终只有一个托盘图标）；重复启动自动退出 |

## 启动方式说明（dsh.cmd vs 源码启动）

启动 DSH 服务有两种方式，可在 **⚙ 设置 → "以源码方式启动 DSH"** 中切换：

| 方式 | 命令 | 特点 |
|---|---|---|
| **默认（dsh.cmd）** | `dsh web --port <端口>`（经 `.bin\dsh.cmd` 批处理） | 兼容性好，与官方一致 |
| **以源码启动** | `node <dsh 安装路径>\lib\bin.js web --port <端口>` | 跳过 .cmd/npx 解析层，**启动更快**；适合开发/调试 |

开启后日志区会显示 `（源码方式: node bin.js）` 标记。若源码入口缺失（未安装过 dsh），
启动器会自动回退到 dsh.cmd 方式并提示。

## 单实例保护（为什么托盘只有一个图标）

- 启动器通过 Windows 命名互斥体（`Local\DSHDesktopLauncherMutex`）检测是否已有实例在运行。
- 若已有一个实例（无论来自开机自启动、`run.bat` 双击还是命令行），**新启动的实例立即退出**，
  不会产生第二个托盘图标——这是你之前看到"托盘出现多个图标后消失"的根因（多个实例并存，
  各自创建图标，实例退出时图标逐个消失）。
- 因此无论启动多少次，始终只有一个托盘图标、一个主窗口。
- 若希望"双击 run.bat 时把已最小化到托盘的窗口唤出来"，请用托盘图标的双击/菜单；单实例保护
  只阻止重复实例，不自动弹出已有窗口。

## 重启 / 关闭

- **↻ 重启 DSH**：仅重启 DSH 服务（停止 → 等待端口释放 → 自动启动），启动器本身不受影响。
- **⟳ 重启程序**：重启启动器本身。若 DSH 正在运行，会先询问"是否停止"——选"是"则停止后重启；
  选"否"则 DSH 继续在后台运行（重启后由外部实例接管）。重启会保持当前启动参数
  （例如从自启动 `--silent` 进入的，重启后仍是静默模式）。
- **⏻ 关闭程序**：彻底退出。DSH 正在运行时会询问是否停止；若选"否"，DSH 继续在后台运行，
  之后可通过托盘重新打开启动器管理它。
- 上述操作在主窗口按钮区和托盘右键菜单中均有入口。

## 端口说明（重要）

- DSH 的端口优先级：**profile 补丁（`~/.dsh/profiles/web/cordis.patch.yml`）> 命令行 `--port`**。
- 如果你的 profile 里给 `webserver` 固定了端口（例如为 Radmin VPN 远程访问固定 `3080`），
  启动器设置里的端口修改**不会生效**——程序会自动检测并始终使用 profile 固定端口，
  并在设置界面给出橙色提示。
- 默认无 profile 固定端口时，使用启动器设置里的端口（默认 3080）。

## 启动方式

| 方式 | 说明 |
|---|---|
| **开始菜单** | 点击 **开始菜单 → "DeepSeek Harness"**（已配置为静默启动，DeepSeek 图标） |
| **双击 run.bat** | 直接运行 `DSH-desktop\run.bat`（无窗口，静默进托盘） |
| **命令行** | `python dsh_launcher.py --silent`（静默） / `python dsh_launcher.py`（显示窗口） |

> 开始菜单快捷方式 `C:\Users\...\Start Menu\Programs\DeepSeek Harness.lnk` 指向
> `pythonw.exe dsh_launcher.py --silent`（**静默启动**：无窗口闪现、无控制台），图标为
> `Picture\deepseek.ico`。若之前存在指向 `~/.dsh/start-dsh.cmd` 的旧快捷方式，请手动删除。

### 静默启动的行为

- **无窗口闪现**：`--silent` 时窗口在 `Tk()` 构造后、任何 UI 构建之前即 `withdraw()`，
  从创建起就不渲染，彻底杜绝闪现。
- **自动拉起 DSH**：静默启动会按设置自动启动 DSH 服务（"自启动时自动启动 DSH 服务"默认开），
  启动结果通过托盘气泡通知（已启动 / 已在运行 / 未就绪请查看日志）。
- **恢复窗口**：双击托盘图标或托盘菜单"显示主窗口"。

## 图标（托盘 + 任务栏）

- 托盘图标和任务栏窗口图标使用 **`Picture/deepseek.icon`**（PNG 内容）。
- 程序会把图标的近白色背景自动转为透明，并将源图 **放大 2 倍**（LANCZOS 高质量插值），
  再缩入 **64×64 托盘画布**（主体占满画布）和 32×32 窗口图标，托盘显示清晰可见。
- 开始菜单快捷方式图标使用同源生成的 **`Picture/deepseek.ico`**（多尺寸 16–128）。
- 若这些文件缺失，自动回退为内置的深蓝圆形图标，不影响任何功能。
- 想换图标：直接替换 `Picture/deepseek.icon`（PNG 或 ICO 内容均可）后重启启动器。

## 开机自启动（静默启动）

在 **⚙ 设置** 中勾选 **"开机自启动（静默启动到系统托盘，不显示窗口）"** 即立即生效
（写入注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\DSHDesktopLauncher`，仅当前用户，无需管理员权限）。

- **静默启动**：Windows 登录后自动在后台启动启动器，**从创建起就不显示窗口**（无窗口闪现），直接进入系统托盘。
- **自动拉起 DSH**：勾选下方 **"自启动时自动启动 DSH 服务"**（默认开启），开机后 DSH Web UI
  也会自动启动，直接浏览器访问即可。若端口已被占用（例如 DSH 已在运行），会自动跳过，不弹窗打扰。
  启动结果会通过托盘气泡通知（已启动 / 已在运行 / 未就绪请查看日志），不会"悄悄失败"。
- **取消自启动**：取消勾选并保存即可（删除注册表项）。
- 自启动依赖系统托盘（未安装 pystray/Pillow 时勾选会被拒绝并提示安装命令）。
- 手动以静默方式启动一次：`python dsh_launcher.py --silent`（等价于开机自启动的行为）。

## 系统托盘（默认开启）

- **启动后自动隐藏**：程序启动约 1.2 秒后主窗口自动隐藏到系统托盘（可在 ⚙ 设置中关闭），
  首次隐藏会弹出气泡通知。
- **关闭窗口不退出**：点击窗口右上角 X 只是隐藏到托盘，程序与 DSH 服务继续在后台运行；
  真正退出请使用**托盘菜单 → 退出**（会先询问是否停止正在运行的 DSH）。
- **托盘菜单**：显示主窗口 / 启动 DSH / 停止 DSH / 打开 Web UI / 退出。
- **托盘图标**：双击图标恢复主窗口。
- 托盘依赖 `pystray` + `Pillow`（首次运行前执行一次下面的安装命令）。
  若未安装，程序自动回退为普通窗口行为（关闭窗口 = 询问后退出），不影响其他功能。

```bat
python -m pip install pystray pillow
```

## 环境要求

- Windows 10/11
- Python 3.10+（开发机已验证 3.14.3，自带 tkinter）
- Node.js（dsh 依赖；启动器会自动定位 npx 缓存中的 `dsh`，离线可用）

## 使用方法

### 方式一：双击运行

```
双击 run.bat
```

### 方式二：命令行

```bat
python dsh_launcher.py            :: 正常启动
python dsh_launcher.py --silent   :: 静默启动（不显示窗口，直接进托盘）
python dsh_launcher.py --smoke    :: 冒烟测试（窗口 2 秒后自动关闭）
python dsh_launcher.py --selftest :: 命令行自检（不打开窗口）
```

## 首次使用

1. 打开启动器，点击 **⚙ 设置**
2. 粘贴你新启用的 DeepSeek API Key（`sk-...`），点保存 —— 密钥会写入
   `C:\Users\<你>\.dsh\.credentials.yaml` 的 `DEEPSEEK_API_KEY` 字段
   （只更新该行，不影响文件里其他内容）
3. 点击 **▶ 启动 DSH**，等待状态变为"运行中"（绿色 ●）
4. 点击 **🌐 打开 Web UI** 进入 DSH 控制台

> 提示：启动时若检测到已配置的 API Key，会注入到 DSH 子进程的环境变量
> （`DEEPSEEK_API_KEY`），DSH 的凭据优先级为：环境变量 > `.env` > `.credentials.yaml`。

## 安全行为（重要）

- 启动器**只停止自己启动的** DSH 进程（■ 停止按钮）。
- 若端口被**外部实例**占用（例如 `remote-restart.ps1` 用 node 拉起的 DSH、或手动启动的服务），
  状态栏显示黄色 ● 并给出外部 PID，同时 **"⛔ 关闭占用"按钮变为可用**：
  点击后**二次确认**（告知将执行 `taskkill /PID <pid> /T /F`），确认后强制结束该外部进程及其子进程树，
  端口随即释放，可正常启动。托盘菜单中也有"关闭外部占用实例"项。
- ⚠️ 关闭外部实例会**中断该进程正在进行的任务**（例如远程访问会话），请确认后再操作。
- API Key 明文保存在 `~/.dsh/.credentials.yaml`（与 dsh 官方凭据位置一致），请勿共享该文件。

## 🔒 安全声明（本仓库不含敏感信息）

本仓库（源码 + exe）**不包含任何密钥或敏感数据**，已逐项核实：

- ✅ 源码/脚本中**无 API Key 值**（`DEEPSEEK_API_KEY` 仅出现在读取逻辑中，密钥运行时从
  `~/.dsh/.credentials.yaml` 读取，该文件不入库）
- ✅ `exe` 二进制内扫描**无 sk- 密钥**、无本机用户名/路径痕迹
- ✅ git 历史所有提交**无密钥**
- ✅ `.gitignore` 排除 `config.json`、`logs/`、`.credentials.yaml`、`.env`、`__pycache__` 等
- ✅ 你的 `OpenClow.pem`（SSH 私钥）、会话记录 zip 等敏感文件**在仓库目录之外**，不会提交
- ⚠️ 提示：`remote-*.ps1` 含本机路径（如 `C:\Users\Admin\...`），是环境相关脚本，
  克隆到其他机器需按需调整路径；不包含任何密码/令牌。

## 目录结构

```
DSH-desktop/
├── dsh_launcher.py     # 主程序（单文件；托盘为可选依赖）
├── run.bat             # 一键启动脚本（无控制台窗口）
├── README.md           # 本文档
├── Picture/
│   └── deepseek.icon   # 托盘与任务栏图标（DeepSeek 图标）
├── config.json         # 启动器配置（运行时自动生成，含托盘开关）
└── logs/
    └── dsh-web.log     # DSH 运行日志（运行时自动生成）
```

## 🔔 托盘图标自愈（explorer 崩溃防护）

Windows 的托盘（通知区域）由 `explorer.exe` 管理。若 explorer 崩溃/重启
（可从事件查看器 `Application` → `Application Error` 看到 `Explorer.EXE` 崩溃记录），
**所有程序的托盘图标会先消失、再重新注册**，期间可能看到图标"忽多忽少"——这是 Windows 行为，
不是本程序的问题。

本启动器内置**图标自愈监控**：每 5 秒检查托盘图标线程，若因 explorer 重启等原因丢失，
自动重建图标并写入日志。若仍频繁出现图标异常，建议排查 explorer 崩溃诱因
（第三方 shell 扩展、显卡驱动等）。

## （可选）打包成独立 exe

如果希望不装 Python 也能运行，可用 PyInstaller 打成单个 exe：

```bat
pip install pyinstaller
pyinstaller --onefile --windowed --name DSH-Launcher dsh_launcher.py
:: 产物在 dist\DSH-Launcher.exe，双击即可运行
```

注意：打包后 `config.json` 与 `logs/` 会生成在 exe 所在目录旁（`sys.argv[0]` 所在位置），
因此建议把 exe 放在独立的文件夹中运行。

## 故障排查

| 现象 | 处理 |
|---|---|
| 点击启动后很快回到"已停止" | 打开日志区查看报错；大概率是 `npx` 首次拉取较慢或端口被占 |
| 提示端口被占用 | 先停止现有实例；若 profile 已固定端口（设置里会提示），请按该端口处理 |
| 找不到 dsh | 确认已安装 Node.js；启动器会自动定位 `%LOCALAPPDATA%\npm-cache\_npx\...` 下的 dsh |
| 停止后端口仍监听 | 该实例非本启动器启动，按黄色状态提示的 PID 手动 `taskkill /T /F` |
| 启动后窗口不见了 | 正常——默认自动隐藏到托盘，双击托盘图标恢复；或在 ⚙ 设置关闭"启动后自动隐藏" |
| 点 X 后程序没退出 | 正常——默认"关闭最小化到托盘"，托盘菜单 → 退出才是真正退出 |
| 没有托盘图标 | 未安装 pystray/Pillow，执行 `python -m pip install pystray pillow` 后重启 |
| 开机不自启 | 在 ⚙ 设置勾选"开机自启动"（写入注册表 Run 键）；如仍失败，检查是否被杀毒软件拦截 |
| 开机后 DSH 没自动启动 | 检查设置中"自启动时自动启动 DSH 服务"是否开启；若端口被占则自动跳过（属正常） |
| 改了端口却不生效 | profile（cordis.patch.yml）固定了 webserver 端口，启动器会自动跟随并提示；需改端口请编辑该文件 |
| 托盘出现多个图标后消失 | 旧版本多实例并存所致；新版已加单实例保护，只会有一个托盘图标。若仍有多个，说明存在旧版本进程，重启电脑或手动结束多余 pythonw 进程 |
