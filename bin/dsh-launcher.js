#!/usr/bin/env node
/**
 * DSH Desktop Launcher — npm 命令行入口
 * =======================================
 * 优先启动打包好的 Windows exe（无需 Python），
 * 找不到 exe 时回退到 pythonw/python 运行 dsh_launcher.py。
 *
 * 用法：
 *   npm start                    # 启动（exe 或 python）
 *   npm run silent               # 静默启动到托盘
 *   node bin/dsh-launcher.js --smoke   # 冒烟测试
 */
'use strict';

const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const EXE = path.join(ROOT, 'dist', 'DSH-Launcher.exe');
const SCRIPT = path.join(ROOT, 'dsh_launcher.py');

function findPython() {
  // 依次尝试 pythonw.exe / pythonw / python.exe / python
  const candidates = [
    process.env.PYTHONW,
    process.env.PYTHON,
    'pythonw.exe',
    'pythonw',
    'python.exe',
    'python',
  ];
  for (const c of candidates) {
    if (!c) continue;
    if (c.includes(path.sep) || c.includes('/')) {
      if (fs.existsSync(c)) return c;
      continue;
    }
    const r = spawnSync(c, ['--version'], { stdio: 'ignore' });
    if (r.status === 0) return c;
  }
  return null;
}

function main() {
  const args = process.argv.slice(2);

  // 1) 优先 exe（自带运行时，最省事）
  if (fs.existsSync(EXE)) {
    console.log(`[dsh-launcher] 使用 exe: ${EXE}`);
    const child = spawn(EXE, args, {
      stdio: 'ignore',
      detached: true,
      windowsHide: true,
    });
    child.unref();
    return;
  }

  // 2) 回退 python
  const py = findPython();
  if (!py) {
    console.error('[dsh-launcher] 未找到可执行文件：缺少 dist/DSH-Launcher.exe，且未安装 Python。');
    console.error('  请先构建 exe（见 README）或安装 Python 3.10+。');
    process.exit(1);
  }
  console.log(`[dsh-launcher] 使用 python: ${py} ${SCRIPT}`);
  const child = spawn(py, [SCRIPT, ...args], {
    stdio: 'ignore',
    detached: true,
    windowsHide: true,
  });
  child.unref();
}

main();
