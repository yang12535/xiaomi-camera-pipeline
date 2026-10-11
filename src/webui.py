#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web 管理界面模块（v1.3.0）

零第三方依赖，仅使用 Python 标准库（http.server / sqlite3 / json），
为流水线提供一个可视化管理仪表盘：

- 展示 merge/compress/upload 各阶段已处理数量与断点续传记录数
- 在线编辑各配置段（性能/压缩/合并/上传/调度/日志，白名单见 EDITABLE_SCHEMA），
  直接改内存中的 config dict 就地生效，同时原子写入数据目录
  runtime_overrides.yaml，容器重启后自动恢复；由环境变量钉死的键拒绝修改（409），
  WebDAV 凭据与目录路径不开放编辑；machine 字段提供 CPU 信息供前端渲染核心网格
- 触发"立即运行"（set 主循环的 trigger_event，立即唤醒一轮处理）
- 查看 pipeline.log 日志尾部

入口：start_webui(config, trigger_event)
  config        load_config() 返回的完整配置 dict
  trigger_event threading.Event，主循环用它 wait(timeout=interval) 睡眠
返回：运行中的 ThreadingHTTPServer 对象；启动失败时返回 None（绝不让
WebUI 的异常影响主程序）。
"""

import os
import re
import json
import sqlite3
import logging
import threading
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

WEBUI_VERSION = 'v1.3.0'

# performance 段默认值（config 中缺少该段或字段时使用）
DEFAULT_PERFORMANCE = {
    'parallel': 1,      # 并行处理数，1-32
    'cores': 0,         # 限定使用的核数，0 = 不限制，0-128
    'core_list': '',    # 绑核列表，如 "0-3" 或 "0,2,4"，空 = 不指定
    'bind': False,      # 是否启用绑核
}

# 可通过 WebUI 编辑的配置白名单：段 -> 键 -> 校验规格
# 规格形式：('int', 下限, 上限) / ('bool',) / ('str',) / ('enum', 候选值) /
#           ('resolution',) = 'original' 或 宽x高 / ('core_list',) = 核心列表表达式
# webdav_*/各 *_dir/webui 段一律不可编辑：凭据不进无鉴权 API，目录与容器挂载绑定
EDITABLE_SCHEMA = {
    'performance': {
        'parallel': ('int', 1, 32),
        'cores': ('int', 0, 128),
        'core_list': ('core_list',),
        'bind': ('bool',),
    },
    'compress': {
        'crf': ('int', 0, 51),
        'preset': ('enum', ('ultrafast', 'superfast', 'veryfast', 'faster', 'fast',
                            'medium', 'slow', 'slower', 'veryslow')),
        'resolution': ('resolution',),
        'threads': ('int', 1, 32),
        'delete_source': ('bool',),
    },
    'merge': {
        'delete_source': ('bool',),
    },
    'upload': {
        'enabled': ('bool',),
        'rate_limit': ('str',),
        'delete_after_upload': ('bool',),
        'resume': ('bool',),
        'max_retries': ('int', 1, 10),
        'retry_delay': ('int', 5, 600),
    },
    'schedule': {
        'interval': ('int', 60, 86400),
        'run_once': ('bool',),
    },
    'logging': {
        'level': ('enum', ('DEBUG', 'INFO', 'WARNING', 'ERROR')),
    },
}

# 旧版 POST /api/config 兼容：body 顶层直接带这四个键时视为 {'performance': {...}}
LEGACY_PERFORMANCE_KEYS = ('parallel', 'cores', 'core_list', 'bind')

# 读取日志尾部时最多向前回溯的字节数（日志文件由 RotatingFileHandler 管理，单文件 <=10MB）
LOG_TAIL_WINDOW = 256 * 1024

# core_list 表达式校验复用 affinity 模块；该模块不可用时跳过格式校验
try:
    from src.affinity import parse_core_list
except ImportError:
    try:
        from affinity import parse_core_list  # 兼容以 src 为工作目录的运行方式
    except ImportError:
        parse_core_list = None

# 运行时覆盖配置的持久化/重载复用 config 模块；不可用时跳过持久化
try:
    from src.config import (
        RUNTIME_OVERRIDES as _RUNTIME_OVERRIDES,
        ENV_PINNED,
        save_runtime_overrides,
        delete_runtime_overrides,
        load_config,
    )
except ImportError:
    try:
        from config import (
            RUNTIME_OVERRIDES as _RUNTIME_OVERRIDES,
            ENV_PINNED,
            save_runtime_overrides,
            delete_runtime_overrides,
            load_config,
        )
    except ImportError:
        _RUNTIME_OVERRIDES = None
        ENV_PINNED = set()
        save_runtime_overrides = None
        delete_runtime_overrides = None
        load_config = None


# ========== 内嵌仪表盘页面 ==========

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>小米摄像头视频流水线</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
         background: #f5f6f8; color: #333; }
  .container { max-width: 1080px; margin: 0 auto; padding: 20px 16px 40px; }
  header { display: flex; align-items: center; justify-content: space-between;
           flex-wrap: wrap; gap: 10px; margin-bottom: 20px; }
  h1 { font-size: 20px; font-weight: 600; }
  .version { display: inline-block; margin-left: 8px; padding: 2px 8px;
             font-size: 12px; color: #fff; background: #4a90d9; border-radius: 10px;
             vertical-align: middle; }
  .time { font-size: 12px; color: #999; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
           gap: 12px; margin-bottom: 20px; }
  .card { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
          padding: 14px 16px; }
  .card .label { font-size: 13px; color: #888; margin-bottom: 6px; }
  .card .value { font-size: 26px; font-weight: 600; color: #2c3e50; }
  section { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
            padding: 16px; margin-bottom: 20px; }
  h2 { font-size: 15px; font-weight: 600; margin-bottom: 12px; color: #2c3e50; }
  .form-row { display: flex; flex-wrap: wrap; gap: 18px; align-items: center;
              font-size: 14px; margin-bottom: 14px; }
  .form-row label { display: flex; align-items: center; gap: 6px; }
  .form-row input[type=number] { width: 72px; padding: 4px 6px; font-size: 14px;
                                 border: 1px solid #d0d5dd; border-radius: 4px; }
  .form-row .chk input { width: 15px; height: 15px; }
  .core-head { display: flex; justify-content: space-between; align-items: center;
               flex-wrap: wrap; gap: 8px; font-size: 13px; color: #666; margin-bottom: 8px; }
  .core-btns button { padding: 2px 10px; font-size: 12px; color: #4a90d9;
                      background: #eef2f7; border: 1px solid #d5e0ee; margin-left: 6px; }
  .core-btns button:hover { background: #dfe9f5; }
  #core-grid { display: grid; grid-template-columns: repeat(8, 1fr); gap: 6px;
               max-width: 560px; }
  .core-cell { text-align: center; padding: 6px 0; font-size: 12px; color: #666;
               font-family: Consolas, monospace; background: #f0f2f5;
               border: 1px solid #e0e3e8; border-radius: 4px; cursor: pointer;
               user-select: none; }
  .core-cell.on { background: #4a90d9; border-color: #4a90d9; color: #fff; }
  .core-info { margin: 8px 0 14px; font-size: 12px; color: #888; }
  .core-info code { padding: 1px 6px; background: #f0f2f5; border-radius: 4px;
                    font-family: Consolas, monospace; }
  #save-msg { margin-left: 10px; font-size: 13px; }
  #save-msg.ok { color: #4a8f4a; }
  #save-msg.err { color: #c04545; }
  .hint { margin-top: 10px; font-size: 12px; color: #aaa; }
  fieldset { border: 1px solid #e5e7eb; border-radius: 6px; padding: 10px 14px 12px;
             margin: 0 0 12px; }
  legend { font-size: 13px; color: #888; padding: 0 6px; }
  .form-row input[type=text], .form-row select { padding: 4px 6px; font-size: 14px;
             border: 1px solid #d0d5dd; border-radius: 4px; background: #fff; }
  .form-row input:disabled, .form-row select:disabled { background: #eee; color: #999;
             cursor: not-allowed; }
  .pinned-note { font-size: 11px; color: #bbb; margin-left: 4px; }
  .core-warn { font-size: 12px; color: #c04545; margin-left: 8px; }
  .schedule { margin-top: 10px; font-size: 13px; color: #888; }
  button { padding: 8px 20px; font-size: 14px; color: #fff; background: #4a90d9;
           border: none; border-radius: 6px; cursor: pointer; }
  button:hover { background: #3a7bc0; }
  button:disabled { background: #a9c6e4; cursor: default; }
  button.secondary { padding: 8px 16px; margin-left: 8px; color: #4a90d9;
                     background: #eef2f7; border: 1px solid #d5e0ee; }
  button.secondary:hover { background: #dfe9f5; }
  button.secondary:disabled { color: #a9c6e4; background: #f5f7fa; }
  #run-msg { margin-left: 10px; font-size: 13px; color: #4a8f4a; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #eee; }
  th { color: #999; font-weight: normal; }
  td.path { word-break: break-all; }
  .stage { display: inline-block; padding: 1px 8px; border-radius: 8px;
           font-size: 12px; background: #eef2f7; color: #4a90d9; }
  .empty { font-size: 13px; color: #aaa; padding: 8px 0; }
  pre#log { background: #1e1e1e; color: #d4d4d4; font-family: Consolas, "Courier New", monospace;
            font-size: 12px; line-height: 1.5; padding: 12px; border-radius: 6px;
            max-height: 420px; overflow: auto; white-space: pre-wrap; word-break: break-all; }
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>小米摄像头视频流水线<span class="version">v1.3.0</span></h1>
    <span class="time" id="time">--</span>
  </header>

  <div class="cards">
    <div class="card"><div class="label">已合并 (merge)</div><div class="value" id="c-merge">-</div></div>
    <div class="card"><div class="label">已压缩 (compress)</div><div class="value" id="c-compress">-</div></div>
    <div class="card"><div class="label">已上传 (upload)</div><div class="value" id="c-upload">-</div></div>
    <div class="card"><div class="label">断点续传记录</div><div class="value" id="c-pending">-</div></div>
  </div>

  <section>
    <h2>性能配置（点击保存后生效）</h2>
    <div class="form-row">
      <label>并行数 <input type="number" id="f-parallel" min="1" max="32" oninput="onTaskParamsChange()"></label>
      <label>每任务核心数 <input type="number" id="f-cores-per" min="1" oninput="onTaskParamsChange()"></label>
      <label class="chk"><input type="checkbox" id="f-bind" onchange="renderCoreGrid()"> 启用绑核</label>
    </div>
    <div class="core-head">
      <span>绑核列表（核心选择）</span>
      <span class="core-btns">
        <button type="button" onclick="coreSelectAll()">全选</button><button type="button" onclick="coreSelectNone()">清空</button><button type="button" onclick="coreSelectInvert()">反选</button>
      </span>
    </div>
    <div id="core-grid"></div>
    <div class="core-info">表达式 <code id="core-expr">（空）</code> · <span id="core-count"></span><span id="core-warn"></span></div>
    <button id="save-btn" onclick="saveConfig()">保存</button><button id="reset-btn" class="secondary" onclick="resetConfig()">恢复文件配置</button><span id="save-msg"></span>
    <div class="hint">每个压缩任务使用 每任务核心数 个线程（-threads）；启用绑核后任务将钉死在所选核心上。</div>
    <div class="hint">保存后立即生效并写入数据目录 runtime_overrides.yaml，重启容器后依然有效；环境变量优先级更高。</div>
    <div class="schedule" id="schedule">--</div>
  </section>

  <section>
    <h2>流水线配置</h2>
    <div class="hint" style="margin:0 0 12px">此处配置保存后立即生效并持久化到数据卷；WebDAV 凭据、目录路径请编辑 config.yaml</div>
    <fieldset>
      <legend>压缩 compress</legend>
      <div class="form-row">
        <label>CRF <input type="number" id="c-crf" min="0" max="51"></label>
        <label>预设 <select id="c-preset">
          <option>ultrafast</option><option>superfast</option><option>veryfast</option>
          <option>faster</option><option>fast</option><option>medium</option>
          <option>slow</option><option>slower</option><option>veryslow</option>
        </select></label>
        <label>分辨率 <input type="text" id="c-resolution" placeholder="original 或 宽x高" style="width:130px"></label>
        <label class="chk"><input type="checkbox" id="c-delete-source"> 压缩后删除源文件</label>
      </div>
    </fieldset>
    <fieldset>
      <legend>合并 merge</legend>
      <div class="form-row">
        <label class="chk"><input type="checkbox" id="m-delete-source"> 合并后删除源文件</label>
      </div>
    </fieldset>
    <fieldset>
      <legend>上传 upload</legend>
      <div class="form-row">
        <label class="chk"><input type="checkbox" id="u-enabled"> 启用上传</label>
        <label>限速 <input type="text" id="u-rate-limit" placeholder="如 1M，0 不限" style="width:90px"></label>
        <label class="chk"><input type="checkbox" id="u-delete-after-upload"> 上传后删除</label>
        <label class="chk"><input type="checkbox" id="u-resume"> 断点续传</label>
        <label>最大重试 <input type="number" id="u-max-retries" min="1" max="10"></label>
        <label>重试间隔(秒) <input type="number" id="u-retry-delay" min="5" max="600"></label>
      </div>
    </fieldset>
    <fieldset>
      <legend>调度 schedule</legend>
      <div class="form-row">
        <label>轮询间隔(秒) <input type="number" id="s-interval" min="60" max="86400"></label>
        <label class="chk"><input type="checkbox" id="s-run-once"> 单次运行</label>
      </div>
    </fieldset>
    <fieldset>
      <legend>日志 logging</legend>
      <div class="form-row">
        <label>级别 <select id="l-level">
          <option>DEBUG</option><option>INFO</option><option>WARNING</option><option>ERROR</option>
        </select></label>
      </div>
    </fieldset>
    <button id="save-pipe-btn" onclick="savePipelineConfig()">保存配置</button><span id="pipe-msg"></span>
  </section>

  <section>
    <h2>手动触发</h2>
    <button id="run-btn" onclick="runNow()">立即运行</button><span id="run-msg"></span>
  </section>

  <section>
    <h2>最近 20 条处理记录</h2>
    <table>
      <thead><tr><th>文件路径</th><th>阶段</th><th>时间</th></tr></thead>
      <tbody id="recent"></tbody>
    </table>
    <div class="empty" id="recent-empty" style="display:none">暂无处理记录</div>
  </section>

  <section>
    <h2>日志尾部（最近 50 行）</h2>
    <pre id="log">加载中…</pre>
  </section>
</div>

<script>
async function refreshStatus() {
  try {
    const d = await (await fetch('/api/status')).json();
    document.getElementById('c-merge').textContent = d.stage_counts.merge;
    document.getElementById('c-compress').textContent = d.stage_counts.compress;
    document.getElementById('c-upload').textContent = d.stage_counts.upload;
    document.getElementById('c-pending').textContent = d.pending_uploads;
    document.getElementById('schedule').textContent =
      '轮询间隔 ' + d.schedule.interval + ' 秒' + (d.schedule.run_once ? ' · 单次运行模式' : '');
    document.getElementById('time').textContent = '更新时间 ' + d.time;

    const tbody = document.getElementById('recent');
    tbody.innerHTML = '';
    const rows = d.recent || [];
    document.getElementById('recent-empty').style.display = rows.length ? 'none' : 'block';
    for (const r of rows) {
      const tr = document.createElement('tr');
      const tdPath = document.createElement('td');
      tdPath.className = 'path';
      tdPath.textContent = r.path;
      const tdStage = document.createElement('td');
      const span = document.createElement('span');
      span.className = 'stage';
      span.textContent = r.stage;
      tdStage.appendChild(span);
      const tdTime = document.createElement('td');
      tdTime.textContent = r.timestamp;
      tr.appendChild(tdPath); tr.appendChild(tdStage); tr.appendChild(tdTime);
      tbody.appendChild(tr);
    }
  } catch (e) { /* 服务暂不可达时保持旧数据 */ }
}

async function refreshLogs() {
  try {
    const d = await (await fetch('/api/logs?lines=50')).json();
    document.getElementById('log').textContent =
      d.lines.length ? d.lines.join('\n') : '（日志文件不存在或为空）';
  } catch (e) { /* 忽略 */ }
}

/* ---------- 性能配置表单 ---------- */
let MACHINE = { logical_cpus: 0, available_cpus: 0, allowed_cores: [] };
let selectedCores = new Set();
let PINNED = [];            // 被环境变量钉死的 '段.键' 列表
let coreListPinned = false; // performance.core_list 被钉死时禁用核心网格

/* '段.键' -> 输入框 id（性能卡片的派生框与网格单独处理） */
const PIPE_FIELD_MAP = {
  'compress.crf': 'c-crf', 'compress.preset': 'c-preset',
  'compress.resolution': 'c-resolution',
  'compress.delete_source': 'c-delete-source',
  'merge.delete_source': 'm-delete-source',
  'upload.enabled': 'u-enabled', 'upload.rate_limit': 'u-rate-limit',
  'upload.delete_after_upload': 'u-delete-after-upload', 'upload.resume': 'u-resume',
  'upload.max_retries': 'u-max-retries', 'upload.retry_delay': 'u-retry-delay',
  'schedule.interval': 's-interval', 'schedule.run_once': 's-run-once',
  'logging.level': 'l-level',
  'performance.parallel': 'f-parallel', 'performance.cores': 'f-cores-per',
  'performance.bind': 'f-bind',
};

function setField(id, value) {
  const el = document.getElementById(id);
  if (el.type === 'checkbox') el.checked = !!value;
  else el.value = value == null ? '' : value;
}

/* 钉死的键：禁用输入框 + 灰色 + 小字提示 */
function setPinnedState(key, id) {
  const el = document.getElementById(id);
  const isPinned = PINNED.includes(key);
  el.disabled = isPinned;
  let note = document.getElementById(id + '-pinned');
  if (isPinned && !note) {
    note = document.createElement('span');
    note.id = id + '-pinned';
    note.className = 'pinned-note';
    note.textContent = '由环境变量固定';
    el.parentNode.appendChild(note);
  } else if (!isPinned && note) {
    note.remove();
  }
}

function applyPinned() {
  for (const [key, id] of Object.entries(PIPE_FIELD_MAP)) setPinnedState(key, id);
  coreListPinned = PINNED.includes('performance.core_list');
  renderCoreGrid();
}

/* 解析 core_list 表达式（如 "0-3,6"）为核心编号集合，与后端 parse_core_list 对应 */
function parseCoreExpr(expr) {
  const set = new Set();
  for (const part of String(expr || '').split(',')) {
    const p = part.trim();
    if (!p) continue;
    const m = p.match(/^(\d+)-(\d+)$/);
    if (m) {
      for (let i = parseInt(m[1]); i <= parseInt(m[2]); i++) set.add(i);
    } else if (/^\d+$/.test(p)) {
      set.add(parseInt(p));
    }
  }
  return set;
}

/* 把选中核心序列化为表达式，连续区间压缩成 起-止 形式（如 [0,1,2,3,6] -> "0-3,6"） */
function serializeCores(set) {
  const arr = [...set].sort((a, b) => a - b);
  const parts = [];
  let i = 0;
  while (i < arr.length) {
    let j = i;
    while (j + 1 < arr.length && arr[j + 1] === arr[j] + 1) j++;
    parts.push(i === j ? String(arr[i]) : arr[i] + '-' + arr[j]);
    i = j + 1;
  }
  return parts.join(',');
}

/* N = 并行数 × 每任务核心数：既是每个 ffmpeg 的 -threads 数，也是绑核模式需选的核心总数 */
function currentN() {
  const parallel = parseInt(document.getElementById('f-parallel').value) || 1;
  const perTask = parseInt(document.getElementById('f-cores-per').value) || 1;
  return Math.max(1, parallel * perTask);
}

/* 已选集合超出 N 时自动裁剪到 N 个（保留编号最小的） */
function trimSelectionToN() {
  const n = currentN();
  if (selectedCores.size > n) {
    selectedCores = new Set([...selectedCores].sort((a, b) => a - b).slice(0, n));
  }
}

/* 并行数/每任务核心数变化：重算 N、裁剪选择、刷新网格 */
function onTaskParamsChange() {
  trimSelectionToN();
  renderCoreGrid();
}

/* 统计文本旁的红色提示，2 秒后消失 */
let coreWarnTimer = null;
function showCoreWarn(text) {
  const el = document.getElementById('core-warn');
  el.textContent = text;
  if (coreWarnTimer) clearTimeout(coreWarnTimer);
  coreWarnTimer = setTimeout(() => { el.textContent = ''; }, 2000);
}

/* 网格仅在启用绑核且 core_list 未被环境变量钉死时可点选 */
function coreGridDisabled() {
  return coreListPinned || !document.getElementById('f-bind').checked;
}

function renderCoreGrid() {
  const grid = document.getElementById('core-grid');
  const disabled = coreGridDisabled();
  grid.innerHTML = '';
  grid.style.opacity = disabled ? 0.55 : 1;
  document.querySelectorAll('.core-btns button').forEach(b => { b.disabled = disabled; });
  // 遍历真实可用核心编号（cpuset 感知，可能非连续/非 0 起始）
  for (const core of MACHINE.allowed_cores) {
    const cell = document.createElement('div');
    cell.className = 'core-cell' + (selectedCores.has(core) ? ' on' : '');
    cell.textContent = core;
    if (!disabled) {
      cell.onclick = () => {
        if (selectedCores.has(core)) {
          selectedCores.delete(core);
        } else if (selectedCores.size >= currentN()) {
          // 已达 N 个：不允许再多选，闪一行红色提示（点已选中的框仍可取消）
          showCoreWarn('最多选 ' + currentN() + ' 个核心');
          return;
        } else {
          selectedCores.add(core);
        }
        renderCoreGrid();
      };
    }
    grid.appendChild(cell);
  }
  updateCoreInfo();
}

function updateCoreInfo() {
  const bind = document.getElementById('f-bind').checked;
  const n = selectedCores.size;
  document.getElementById('core-expr').textContent = serializeCores(selectedCores) || '（空）';
  const el = document.getElementById('core-count');
  if (bind) {
    el.textContent = '需选 ' + currentN() + ' 核（并行×每任务核心数），已选 ' + n + ' 核';
  } else {
    const perTask = parseInt(document.getElementById('f-cores-per').value) || 1;
    el.textContent = '未启用绑核：每个任务 ' + perTask + ' 线程，由系统自由调度';
  }
}

function coreSelectAll() {
  // 取可用核心数组的前 N 个元素（真实编号，不超过数组长度）
  selectedCores = new Set(MACHINE.allowed_cores.slice(0, currentN()));
  renderCoreGrid();
}
function coreSelectNone() { selectedCores.clear(); renderCoreGrid(); }
function coreSelectInvert() {
  for (const core of MACHINE.allowed_cores) {
    if (selectedCores.has(core)) selectedCores.delete(core); else selectedCores.add(core);
  }
  trimSelectionToN();  // 反选后若超过 N 自动裁剪到 N
  renderCoreGrid();
}

/* 拉取当前配置并填充表单（页面加载时与保存成功后调用） */
async function loadConfig() {
  try {
    const d = await (await fetch('/api/config')).json();
    MACHINE = d.machine;
    if (!Array.isArray(MACHINE.allowed_cores)) MACHINE.allowed_cores = [];
    PINNED = d.pinned || [];
    const s = d.sections;
    const p = s.performance;
    document.getElementById('f-parallel').value = p.parallel;
    const cInput = document.getElementById('f-cores-per');
    cInput.max = MACHINE.allowed_cores.length;
    // 每任务核心数初值：已限核数时按 cores/parallel 折算，否则按可用核心均分
    cInput.value = p.cores > 0
      ? Math.max(1, Math.round(p.cores / p.parallel))
      : Math.max(1, Math.floor(MACHINE.allowed_cores.length / p.parallel));
    document.getElementById('f-bind').checked = p.bind;
    selectedCores = parseCoreExpr(p.core_list);
    // 流水线配置卡片
    setField('c-crf', s.compress.crf);
    setField('c-preset', s.compress.preset);
    setField('c-resolution', s.compress.resolution);
    setField('c-delete-source', s.compress.delete_source);
    setField('m-delete-source', s.merge.delete_source);
    setField('u-enabled', s.upload.enabled);
    setField('u-rate-limit', s.upload.rate_limit);
    setField('u-delete-after-upload', s.upload.delete_after_upload);
    setField('u-resume', s.upload.resume);
    setField('u-max-retries', s.upload.max_retries);
    setField('u-retry-delay', s.upload.retry_delay);
    setField('s-interval', s.schedule.interval);
    setField('s-run-once', s.schedule.run_once);
    setField('l-level', s.logging.level);
    applyPinned();  // 内部会 renderCoreGrid()
  } catch (e) { /* 服务暂不可达时保持现状 */ }
}

async function saveConfig() {
  const btn = document.getElementById('save-btn');
  const msg = document.getElementById('save-msg');
  const parallel = parseInt(document.getElementById('f-parallel').value);
  const perTask = parseInt(document.getElementById('f-cores-per').value);
  const bind = document.getElementById('f-bind').checked;
  if (!(parallel >= 1 && parallel <= 32) || !(perTask >= 1)) {
    msg.className = 'err';
    msg.textContent = '请填写合法的数字';
    return;
  }
  const n = parallel * perTask;  // N = 并行数 × 每任务核心数（ffmpeg 线程总量）
  if (bind && selectedCores.size !== n) {
    // 绑核模式必须恰好选 N 个核心，多选少选都不给保存
    msg.className = 'err';
    msg.textContent = '绑核模式需选择恰好 ' + n + ' 个核心（当前已选 ' + selectedCores.size + '）';
    return;
  }
  btn.disabled = true;
  msg.className = '';
  msg.textContent = '';
  // 被环境变量钉死的键不提交（提交了也会被后端 409 整单拒绝）
  const body = {};
  if (!PINNED.includes('performance.parallel')) body.parallel = parallel;
  if (!PINNED.includes('performance.cores')) body.cores = n;  // cores 恒为 N（并行数×每任务核心数）
  if (!PINNED.includes('performance.core_list')) body.core_list = bind ? serializeCores(selectedCores) : '';
  if (!PINNED.includes('performance.bind')) body.bind = bind;
  if (Object.keys(body).length === 0) {
    btn.disabled = false;
    msg.className = 'err';
    msg.textContent = '所有配置项均由环境变量固定，无可保存项';
    return;
  }
  try {
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ performance: body })
    });
    const d = await r.json();
    if (r.ok && d.persisted === false) {
      // 已生效但覆盖文件写入失败，明确提示重启后会丢失
      msg.className = 'err';
      msg.textContent = '已生效，但写入覆盖文件失败: ' + (d.persist_error || '未知原因');
      await loadConfig();
    } else if (r.ok) {
      msg.className = 'ok';
      msg.textContent = '已保存并生效';
      await loadConfig();
    } else {
      msg.className = 'err';
      msg.textContent = d.error || ('保存失败 (' + r.status + ')');
    }
  } catch (e) {
    msg.className = 'err';
    msg.textContent = '请求失败';
  }
  btn.disabled = false;
  setTimeout(() => { msg.textContent = ''; msg.className = ''; }, 6000);
}

/* 收集"流水线配置"卡片并整体保存；被环境变量钉死的键不提交 */
async function savePipelineConfig() {
  const btn = document.getElementById('save-pipe-btn');
  const msg = document.getElementById('pipe-msg');
  const num = id => parseInt(document.getElementById(id).value);
  const chk = id => document.getElementById(id).checked;
  const txt = id => document.getElementById(id).value.trim();
  const sel = id => document.getElementById(id).value;
  const body = { compress: {}, merge: {}, upload: {}, schedule: {}, logging: {} };
  const put = (sec, key, value) => {
    if (!PINNED.includes(sec + '.' + key)) body[sec][key] = value;
  };
  put('compress', 'crf', num('c-crf'));
  put('compress', 'preset', sel('c-preset'));
  put('compress', 'resolution', txt('c-resolution'));
  put('compress', 'delete_source', chk('c-delete-source'));
  put('merge', 'delete_source', chk('m-delete-source'));
  put('upload', 'enabled', chk('u-enabled'));
  put('upload', 'rate_limit', txt('u-rate-limit'));
  put('upload', 'delete_after_upload', chk('u-delete-after-upload'));
  put('upload', 'resume', chk('u-resume'));
  put('upload', 'max_retries', num('u-max-retries'));
  put('upload', 'retry_delay', num('u-retry-delay'));
  put('schedule', 'interval', num('s-interval'));
  put('schedule', 'run_once', chk('s-run-once'));
  put('logging', 'level', sel('l-level'));
  for (const sec of Object.keys(body)) {
    if (Object.keys(body[sec]).length === 0) delete body[sec];
  }
  if (Object.keys(body).length === 0) {
    msg.className = 'err';
    msg.textContent = '所有配置项均由环境变量固定，无可保存项';
    return;
  }
  btn.disabled = true;
  msg.className = '';
  msg.textContent = '';
  try {
    const r = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const d = await r.json();
    if (r.ok && d.persisted === false) {
      // 已生效但覆盖文件写入失败，明确提示重启后会丢失
      msg.className = 'err';
      msg.textContent = '已生效，但写入覆盖文件失败: ' + (d.persist_error || '未知原因') + '（重启后丢失）';
      await loadConfig();
    } else if (r.ok) {
      msg.className = 'ok';
      msg.textContent = '已保存并生效';
      await loadConfig();
    } else {
      // 400（校验失败）与 409（环境变量钉死）都直接展示后端 error 全文
      msg.className = 'err';
      msg.textContent = d.error || ('保存失败 (' + r.status + ')');
    }
  } catch (e) {
    msg.className = 'err';
    msg.textContent = '请求失败';
  }
  btn.disabled = false;
  setTimeout(() => { msg.textContent = ''; msg.className = ''; }, 8000);
}

/* 删除 WebUI 覆盖配置，恢复 config.yaml/环境变量的设置 */
async function resetConfig() {
  if (!confirm('删除 WebUI 覆盖配置并恢复 config.yaml/环境变量的设置？')) return;
  const btn = document.getElementById('reset-btn');
  const msg = document.getElementById('save-msg');
  btn.disabled = true;
  msg.className = '';
  msg.textContent = '';
  try {
    const r = await fetch('/api/config/reset', { method: 'POST' });
    const d = await r.json();
    if (r.ok) {
      msg.className = 'ok';
      msg.textContent = '已恢复文件配置';
      await loadConfig();
    } else {
      msg.className = 'err';
      msg.textContent = d.error || ('恢复失败 (' + r.status + ')');
    }
  } catch (e) {
    msg.className = 'err';
    msg.textContent = '请求失败';
  }
  btn.disabled = false;
  setTimeout(() => { msg.textContent = ''; msg.className = ''; }, 6000);
}

async function runNow() {
  const btn = document.getElementById('run-btn');
  const msg = document.getElementById('run-msg');
  btn.disabled = true;
  msg.textContent = '';
  try {
    const r = await fetch('/api/run', { method: 'POST' });
    const d = await r.json();
    msg.textContent = d.ok ? '已触发，正在唤醒处理循环' : '触发失败';
  } catch (e) {
    msg.textContent = '请求失败';
  }
  setTimeout(() => { btn.disabled = false; }, 3000);
  setTimeout(() => { msg.textContent = ''; }, 6000);
}

refreshStatus();
refreshLogs();
loadConfig();
setInterval(refreshStatus, 10000);
setInterval(refreshLogs, 10000);
</script>
</body>
</html>
"""


# ========== 数据查询（全部为只读操作，任何异常都返回空数据） ==========

def _state_db_path():
    """状态数据库路径（每次请求实时读取环境变量，便于容器内调整）"""
    return os.getenv('STATE_DB', '/app/data/pipeline.db')


def _log_file_path():
    """流水线日志文件路径"""
    return os.path.join(os.getenv('LOG_DIR', '/logs'), 'pipeline.log')


def _query_status_db():
    """查询状态数据库：各阶段计数、断点续传记录数、最近 20 条处理记录

    DB 文件不存在、表不存在或查询出错时均返回空数据，不影响页面展示。
    """
    result = {
        'stage_counts': {'merge': 0, 'compress': 0, 'upload': 0},
        'pending_uploads': 0,
        'recent': [],
    }
    db_path = _state_db_path()
    if not os.path.exists(db_path):
        return result
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            # 各阶段已处理数量
            try:
                for stage, count in conn.execute(
                        'SELECT stage, COUNT(*) FROM processed GROUP BY stage'):
                    result['stage_counts'][stage] = count
            except sqlite3.Error:
                pass
            # 断点续传（上传中断）记录数
            try:
                row = conn.execute('SELECT COUNT(*) FROM upload_progress').fetchone()
                result['pending_uploads'] = row[0] if row else 0
            except sqlite3.Error:
                pass
            # 最近 20 条处理记录
            try:
                rows = conn.execute(
                    'SELECT path, stage, timestamp FROM processed '
                    'ORDER BY timestamp DESC LIMIT 20').fetchall()
                result['recent'] = [
                    {'path': r[0], 'stage': r[1], 'timestamp': r[2]} for r in rows
                ]
            except sqlite3.Error:
                pass
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as e:
        logging.warning(f"[WebUI] 查询状态数据库失败: {e}")
    return result


def _read_log_tail(n):
    """读取日志文件末尾 n 行，文件不存在或读取失败时返回空列表"""
    log_file = _log_file_path()
    if not os.path.exists(log_file):
        return []
    try:
        with open(log_file, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            # 只回溯固定窗口，避免日志文件过大时全量读入内存
            f.seek(max(0, size - LOG_TAIL_WINDOW))
            data = f.read().decode('utf-8', errors='replace')
        return data.splitlines()[-n:]
    except OSError as e:
        logging.warning(f"[WebUI] 读取日志文件失败: {e}")
        return []


def _get_performance(config):
    """读取 performance 段实时值（缺省时补默认值）"""
    perf = config.get('performance')
    if not isinstance(perf, dict):
        perf = {}
    return {
        'parallel': perf.get('parallel', DEFAULT_PERFORMANCE['parallel']),
        'cores': perf.get('cores', DEFAULT_PERFORMANCE['cores']),
        'core_list': perf.get('core_list', DEFAULT_PERFORMANCE['core_list']),
        'bind': perf.get('bind', DEFAULT_PERFORMANCE['bind']),
    }


def _get_editable_sections(config):
    """按 EDITABLE_SCHEMA 白名单读取各段当前值（upload 段绝不回传 webdav_*）"""
    sections = {}
    for section, schema in EDITABLE_SCHEMA.items():
        sec = config.get(section)
        if not isinstance(sec, dict):
            sec = {}
        if section == 'performance':
            sections[section] = _get_performance(config)
        else:
            sections[section] = {key: sec.get(key) for key in schema}
    return sections


def _get_webui(config):
    """读取 webui 段实时值（缺省时补默认值）"""
    webui = config.get('webui')
    if not isinstance(webui, dict):
        webui = {}
    return {
        'host': webui.get('host', '0.0.0.0'),
        'port': webui.get('port', 8080),
    }


def _get_machine():
    """机器 CPU 信息，供前端渲染核心选择网格

    logical_cpus   系统逻辑核心总数（os.cpu_count()）
    allowed_cores  当前进程可用核心编号列表（sched_getaffinity，容器 cpuset 感知，
                   可能是非连续/非 0 起始的集合如 [8..15]）；
                   平台不支持或调用失败时回落为 list(range(os.cpu_count() or 1))
    available_cpus 可用核心数，即 len(allowed_cores)
    """
    logical = os.cpu_count() or 0
    allowed = list(range(os.cpu_count() or 1))
    if hasattr(os, 'sched_getaffinity'):
        try:
            allowed = sorted(os.sched_getaffinity(0))
        except OSError:
            pass
    return {
        'logical_cpus': logical,
        'available_cpus': len(allowed),
        'allowed_cores': allowed,
    }


def _get_overrides_file():
    """运行时覆盖文件路径：文件存在时返回路径字符串，不存在返回 None

    路径取 src.config.RUNTIME_OVERRIDES；该模块不可用时按
    dirname(STATE_DB) + 'runtime_overrides.yaml' 推导。
    """
    if _RUNTIME_OVERRIDES:
        path = _RUNTIME_OVERRIDES
    else:
        path = os.path.join(os.path.dirname(_state_db_path()), 'runtime_overrides.yaml')
    return path if os.path.exists(path) else None


def _build_status(config):
    """构造 /api/status 响应数据"""
    db = _query_status_db()
    schedule = config.get('schedule')
    if not isinstance(schedule, dict):
        schedule = {}
    return {
        'stage_counts': db['stage_counts'],
        'pending_uploads': db['pending_uploads'],
        'performance': _get_performance(config),
        'schedule': {
            'interval': schedule.get('interval', 3600),
            'run_once': schedule.get('run_once', False),
        },
        'time': datetime.now().isoformat(),
        'recent': db['recent'],
        'machine': _get_machine(),
    }


def _validate_value(name, spec, value):
    """按规格校验单个配置值，非法时抛出 ValueError（name 形如 '段.键'）"""
    kind = spec[0]
    if kind == 'int':
        lo, hi = spec[1], spec[2]
        # 注意 bool 是 int 的子类，必须先排除
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f'{name} 必须是整数')
        if not lo <= value <= hi:
            raise ValueError(f'{name} 必须在 {lo}-{hi} 之间')
        return value
    if kind == 'bool':
        if not isinstance(value, bool):
            raise ValueError(f'{name} 必须是布尔值')
        return value
    if kind == 'enum':
        if value not in spec[1]:
            raise ValueError(f'{name} 必须是以下值之一: {", ".join(spec[1])}')
        return value
    if kind == 'str':
        if not isinstance(value, str):
            raise ValueError(f'{name} 必须是字符串')
        return value
    if kind == 'resolution':
        if not isinstance(value, str) or not (
                value == 'original' or re.match(r'^\d{3,4}x\d{3,4}$', value)):
            raise ValueError(f"{name} 必须是 'original' 或 宽x高 格式（如 1920x1080）")
        return value
    if kind == 'core_list':
        if not isinstance(value, str):
            raise ValueError(f'{name} 必须是字符串')
        # 空串 = 自动分配，无需校验；affinity 模块不可用时跳过格式校验
        if value.strip() and parse_core_list is not None:
            try:
                parse_core_list(value)
            except ValueError as e:
                raise ValueError(f'{name} 格式非法: {e}')
        return value
    raise ValueError(f'{name} 的校验规格未知: {kind}')


def _validate_sections_update(data):
    """按 EDITABLE_SCHEMA 校验 {"段名": {键: 值}} 请求体，返回净化后的更新 dict

    未知段/键、类型错误、越界、非法枚举/格式都抛出 ValueError —— 任何一键
    非法整个请求拒绝，不部分生效。空段跳过（前端会过滤掉被环境变量钉死的键）。
    """
    if not isinstance(data, dict) or not data:
        raise ValueError('请求体必须是非空 JSON 对象')
    update = {}
    for section, values in data.items():
        if section not in EDITABLE_SCHEMA:
            raise ValueError(f'不支持的配置段: {section}')
        if not isinstance(values, dict):
            raise ValueError(f'配置段 {section} 必须是对象')
        if not values:
            continue
        schema = EDITABLE_SCHEMA[section]
        cleaned = {}
        for key, value in values.items():
            if key not in schema:
                raise ValueError(f'不支持的配置项: {section}.{key}')
            cleaned[key] = _validate_value(f'{section}.{key}', schema[key], value)
        update[section] = cleaned
    if not update:
        raise ValueError('没有可更新的配置项')
    return update


# ========== HTTP 服务 ==========

class _WebUIServer(ThreadingHTTPServer):
    """携带流水线上下文的 HTTP 服务"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, handler_class, config, trigger_event):
        # 共享给所有请求线程的上下文；config 与主程序共用同一个 dict，
        # POST /api/config 就地修改后主程序下一轮循环即可读到新值
        self.config = config
        self.trigger_event = trigger_event
        self.config_lock = threading.Lock()
        super().__init__(server_address, handler_class)


class _WebUIHandler(BaseHTTPRequestHandler):
    """WebUI 请求处理器"""

    server_version = 'PipelineWebUI/1.3.0'

    def log_message(self, format, *args):
        """访问日志走 logging，避免直接写 stderr"""
        logging.debug(f"[WebUI] {self.address_string()} {format % args}")

    # ---------- 响应辅助 ----------

    def _send_json(self, obj, status=200):
        """发送 JSON 响应（UTF-8，中文不转义）"""
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html):
        """发送 HTML 页面"""
        body = html.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------- 路由 ----------

    def do_GET(self):
        """处理 GET 请求"""
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == '/':
                self._send_html(INDEX_HTML)
            elif path == '/api/status':
                self._send_json(_build_status(self.server.config))
            elif path == '/api/logs':
                qs = parse_qs(parsed.query)
                try:
                    n = int(qs.get('lines', ['50'])[0])
                except (ValueError, TypeError):
                    n = 50
                n = max(1, min(n, 500))  # 默认 50，上限 500
                self._send_json({'lines': _read_log_tail(n)})
            elif path == '/api/config':
                self._send_json({
                    'sections': _get_editable_sections(self.server.config),
                    'pinned': sorted(ENV_PINNED),
                    'machine': _get_machine(),
                    'overrides_file': _get_overrides_file(),
                })
            else:
                self._send_json({'error': '未找到'}, 404)
        except Exception as e:
            logging.warning(f"[WebUI] 处理 GET {self.path} 异常: {e}")
            try:
                self._send_json({'error': '服务器内部错误'}, 500)
            except Exception:
                pass

    def do_POST(self):
        """处理 POST 请求"""
        try:
            path = urlparse(self.path).path
            if path == '/api/run':
                # 唤醒主循环，立即执行一轮处理
                self.server.trigger_event.set()
                logging.info("[WebUI] 收到立即运行请求，已触发处理循环")
                self._send_json({'ok': True})
            elif path == '/api/config':
                self._handle_config_update()
            elif path == '/api/config/reset':
                self._handle_config_reset()
            else:
                self._send_json({'error': '未找到'}, 404)
        except Exception as e:
            logging.warning(f"[WebUI] 处理 POST {self.path} 异常: {e}")
            try:
                self._send_json({'error': '服务器内部错误'}, 500)
            except Exception:
                pass

    # ---------- 配置更新 ----------

    def _handle_config_update(self):
        """POST /api/config：在线更新配置（就地生效 + 写入覆盖文件）

        body 为 {"段名": {键: 值, ...}, ...}，可多段一次提交；兼容旧格式：
        顶层直接带 parallel/cores/core_list/bind 时视为 {'performance': {...}}。
        任何一键非法整单 400；被环境变量钉死的键整单 409。
        """
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except (ValueError, TypeError):
            length = 0
        raw = self.rfile.read(length) if length > 0 else b''
        if not raw:
            self._send_json({'error': '请求体为空，需要 JSON 对象'}, 400)
            return
        try:
            data = json.loads(raw.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            self._send_json({'error': '请求体不是合法 JSON'}, 400)
            return
        # 旧版前端兼容：顶层直接带 performance 四键且无段名键时包一层
        if isinstance(data, dict) \
                and any(k in LEGACY_PERFORMANCE_KEYS for k in data) \
                and not any(k in EDITABLE_SCHEMA for k in data):
            data = {'performance': dict(data)}
        try:
            update = _validate_sections_update(data)
        except ValueError as e:
            self._send_json({'error': str(e)}, 400)
            return
        # 被环境变量钉死的键：整单拒绝（改了也会被 env 覆盖回去）
        pinned = sorted(
            f'{section}.{key}'
            for section, values in update.items()
            for key in values
            if f'{section}.{key}' in ENV_PINNED
        )
        if pinned:
            self._send_json({
                'error': f"键 {', '.join(pinned)} 由环境变量固定，"
                         f"需在 compose 中移除对应环境变量后才能在此修改",
                'pinned': pinned,
            }, 409)
            return
        with self.server.config_lock:
            for section, values in update.items():
                sec = self.server.config.get(section)
                if not isinstance(sec, dict):
                    sec = {}
                    self.server.config[section] = sec
                sec.update(values)
            sections = _get_editable_sections(self.server.config)
            # 持久化被编辑段的当前完整值（save 函数会保留文件里其他段）
            patch = {sec: dict(self.server.config[sec]) for sec in update}
        logging.info(f"[WebUI] 配置已更新: {update}")

        persisted = True
        persist_error = None
        if save_runtime_overrides is not None:
            try:
                save_runtime_overrides(patch)
            except Exception as e:
                persisted = False
                persist_error = str(e)
                logging.warning(f"[WebUI] 覆盖配置写入失败: {e}")
        else:
            persisted = False
            persist_error = 'config 模块不可用，未持久化'
        resp = {'sections': {sec: sections[sec] for sec in update},
                'persisted': persisted}
        if 'performance' in resp['sections']:
            resp['performance'] = resp['sections']['performance']
        if persist_error:
            resp['persist_error'] = persist_error
        # 唤醒主循环：立即跑一轮并按新配置（如 interval）重新睡眠
        self.server.trigger_event.set()
        self._send_json(resp)

    def _handle_config_reset(self):
        """POST /api/config/reset：删除覆盖文件并就地重载文件/环境变量配置"""
        if load_config is None:
            self._send_json({'error': 'config 模块不可用，无法重载配置'}, 503)
            return
        if delete_runtime_overrides is not None:
            try:
                if delete_runtime_overrides():
                    logging.info("[WebUI] 已删除运行时覆盖配置")
            except Exception as e:
                logging.warning(f"[WebUI] 删除覆盖文件失败: {e}")
        try:
            fresh = load_config()
        except Exception as e:
            logging.warning(f"[WebUI] 重载配置失败: {e}")
            self._send_json({'error': f'重载配置失败: {e}'}, 500)
            return
        with self.server.config_lock:
            # 必须保持同一个 dict 对象：主循环与 WebUI 共享引用
            self.server.config.clear()
            self.server.config.update(fresh)
            new_perf = _get_performance(self.server.config)
        logging.info("[WebUI] 配置已恢复为文件/环境变量设置")
        # 唤醒主循环：立即按恢复后的配置跑一轮
        self.server.trigger_event.set()
        self._send_json({'ok': True, 'performance': new_perf})


# ========== 对外入口 ==========

def start_webui(config, trigger_event):
    """启动 Web 管理界面

    config        load_config() 返回的完整配置 dict（就地修改 performance 段即生效）
    trigger_event threading.Event，set 后唤醒主循环立即执行一轮处理

    启动成功返回 server 对象；bind 失败等任何异常都只记录 warning 并返回 None，
    绝不让 WebUI 影响主程序运行。
    """
    webui = _get_webui(config)
    host = webui['host']
    try:
        port = int(webui['port'])
    except (ValueError, TypeError):
        logging.warning(f"[WebUI] 端口配置无效: {webui['port']!r}，WebUI 未启动")
        return None
    try:
        server = _WebUIServer((host, port), _WebUIHandler, config, trigger_event)
    except Exception as e:
        logging.warning(f"[WebUI] 启动失败({host}:{port}): {e}")
        return None
    thread = threading.Thread(
        target=server.serve_forever, name='webui-http', daemon=True)
    thread.start()
    logging.info(f"[WebUI] 管理界面已启动: http://{host}:{port}")
    return server
