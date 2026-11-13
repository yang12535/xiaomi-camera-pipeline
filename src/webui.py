#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Web 管理界面模块（v1.3.0）

零第三方依赖，仅使用 Python 标准库（http.server / sqlite3 / json），
为流水线提供一个可视化管理仪表盘：

- 展示 merge/compress/upload 各阶段已处理数量与断点续传记录数
- 展示运行时阶段、最近一轮成果与下一次空闲检查时间（runtime 可选）
- 在线编辑各配置段（性能/压缩/合并/上传/调度/日志，白名单见 EDITABLE_SCHEMA），
  直接改内存中的 config dict 就地生效，同时原子写入数据目录
  runtime_overrides.yaml，容器重启后自动恢复；由环境变量钉死的键拒绝修改（409），
  WebDAV 凭据与目录路径不开放编辑；machine 字段提供 CPU 信息供前端渲染核心网格
- 触发"立即运行"（set 主循环的 trigger_event，立即唤醒一轮处理）
- 查看 pipeline.log 日志尾部

页面与静态资源拆分在 src/webui_static/（index.html / style.css / app.js），
由本模块按白名单路由提供，不引入框架、npm 或构建链；HTML 中的 {{VERSION}}
在响应时替换为 WEBUI_VERSION。

入口：start_webui(config, trigger_event, runtime=None)
  config        load_config() 返回的完整配置 dict
  trigger_event threading.Event，主循环用它 wait(timeout=interval) 睡眠
  runtime       可选，提供 snapshot() 的运行状态对象（src.runtime.RuntimeState）；
                None 或读取失败时 /api/status 返回空默认值，页面优雅降级
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

# 静态资源目录与白名单路由：URL -> (文件名, Content-Type, Cache-Control)
WEBUI_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'webui_static')
STATIC_ROUTES = {
    '/': ('index.html', 'text/html; charset=utf-8', 'no-store'),
    '/index.html': ('index.html', 'text/html; charset=utf-8', 'no-store'),
    '/assets/style.css': ('style.css', 'text/css; charset=utf-8', 'no-cache'),
    '/assets/app.js': ('app.js', 'text/javascript; charset=utf-8', 'no-cache'),
}

# 页面 CSP：所有脚本/样式都走同源静态文件，页面内没有内联脚本或样式
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)

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
        'settle_minutes': ('int', 0, 10080),
        'max_dirs_per_run': ('int', 1, 100),
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

# 运行时快照允许的阶段值；未知值降级为 unknown
RUNTIME_PHASES = frozenset({
    'starting', 'merging', 'compressing', 'uploading',
    'backlog', 'waiting', 'stopped',
})

# 静态资源按 (mtime, size) 缓存，修改文件后无需重启即可生效
_STATIC_CACHE = {}

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


# ========== 静态资源 ==========

def _read_static_asset(name):
    """读取 webui_static 下的固定文件，按 mtime/size 缓存；缺失时返回 None

    name 只来自 STATIC_ROUTES 白名单，不接受外部输入。
    """
    path = os.path.join(WEBUI_STATIC_DIR, name)
    try:
        stat = os.stat(path)
    except OSError:
        return None
    cached = _STATIC_CACHE.get(name)
    if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
        return cached[2]
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError as e:
        logging.warning(f"[WebUI] 读取静态资源失败({name}): {e}")
        return None
    _STATIC_CACHE[name] = (stat.st_mtime, stat.st_size, data)
    return data


def _render_index_html():
    """读取并渲染 index.html：替换 {{VERSION}} 令牌；文件缺失返回 None"""
    data = _read_static_asset('index.html')
    if data is None:
        return None
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError as e:
        logging.warning(f"[WebUI] index.html 不是合法 UTF-8: {e}")
        return None
    return text.replace('{{VERSION}}', WEBUI_VERSION).encode('utf-8')


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


# ========== 运行时状态 ==========

def _as_iso(value):
    """datetime/字符串统一为 ISO 字符串；None 保持 None"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone().isoformat()
    if isinstance(value, str):
        return value
    return str(value)


def _safe_count(value):
    """计数值只接受非 bool 整数，其余按 0 处理"""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _empty_runtime_status():
    """runtime 未接入时的空状态（前端据此优雅降级）"""
    return {
        'available': False,
        'phase': 'unknown',
        'running': False,
        'current_run_started_at': None,
        'last_run': None,
        'next_run_at': None,
    }


def _runtime_status(runtime):
    """读取 runtime.snapshot() 并规整为前端契约字段

    runtime 为 None、缺少 snapshot()、抛异常或返回非 dict 时均返回空默认，
    保证 /api/status 永不因运行状态模块故障而失败。
    """
    if runtime is None:
        return _empty_runtime_status()
    snapshot = getattr(runtime, 'snapshot', None)
    if not callable(snapshot):
        logging.warning("[WebUI] runtime 对象缺少 snapshot()，运行状态降级")
        return _empty_runtime_status()
    try:
        snap = snapshot()
    except Exception as e:
        logging.warning(f"[WebUI] 读取运行状态失败: {e}")
        return _empty_runtime_status()
    if not isinstance(snap, dict):
        try:
            snap = dict(snap)
        except (TypeError, ValueError):
            logging.warning("[WebUI] 运行状态快照不是映射，已忽略")
            return _empty_runtime_status()

    phase = snap.get('phase')
    if not isinstance(phase, str) or phase not in RUNTIME_PHASES:
        phase = 'unknown'

    last_run = None
    raw_last = snap.get('last_run')
    if isinstance(raw_last, dict):
        last_run = {
            'merged': _safe_count(raw_last.get('merged')),
            'compressed': _safe_count(raw_last.get('compressed')),
            'uploaded': _safe_count(raw_last.get('uploaded')),
            'finished_at': _as_iso(raw_last.get('finished_at')),
        }

    return {
        'available': True,
        'phase': phase,
        'running': bool(snap.get('running')),
        'current_run_started_at': _as_iso(snap.get('current_run_started_at')),
        'last_run': last_run,
        'next_run_at': _as_iso(snap.get('next_run_at')),
    }


def _build_status(config, runtime=None):
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
        'time': datetime.now().astimezone().isoformat(),
        'recent': db['recent'],
        'machine': _get_machine(),
        'runtime': _runtime_status(runtime),
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

    def __init__(self, server_address, handler_class, config, trigger_event, runtime=None):
        # 共享给所有请求线程的上下文；config 与主程序共用同一个 dict，
        # POST /api/config 就地修改后主程序下一轮循环即可读到新值
        self.config = config
        self.trigger_event = trigger_event
        self.runtime = runtime
        self.config_lock = threading.Lock()
        super().__init__(server_address, handler_class)


class _WebUIHandler(BaseHTTPRequestHandler):
    """WebUI 请求处理器"""

    server_version = 'PipelineWebUI/' + WEBUI_VERSION.lstrip('v')

    def log_message(self, format, *args):
        """访问日志走 logging，避免直接写 stderr"""
        logging.debug(f"[WebUI] {self.address_string()} {format % args}")

    # ---------- 响应辅助 ----------

    def _send_bytes(self, body, content_type, cache_control='no-store',
                    status=200, extra_headers=None):
        """发送字节响应，统一附带基础安全头"""
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', cache_control)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('X-Frame-Options', 'DENY')
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_json(self, obj, status=200):
        """发送 JSON 响应（UTF-8，中文不转义，禁止缓存）"""
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self._send_bytes(body, 'application/json; charset=utf-8', status=status)

    def _send_text(self, text, status=200):
        """发送纯文本响应（静态资源缺失等场景）"""
        body = text.encode('utf-8')
        self._send_bytes(body, 'text/plain; charset=utf-8', status=status)

    def _send_static(self, path):
        """按白名单发送静态资源；返回 False 表示该路径不归静态路由管"""
        route = STATIC_ROUTES.get(path)
        if not route:
            return False
        filename, content_type, cache_control = route
        if filename == 'index.html':
            body = _render_index_html()
        else:
            body = _read_static_asset(filename)
        if body is None:
            logging.warning(f"[WebUI] 静态资源缺失: {filename}")
            self._send_text('WebUI 静态资源缺失，请检查 src/webui_static 目录', 500)
            return True
        extra = None
        if content_type.startswith('text/html'):
            extra = {'Content-Security-Policy': CONTENT_SECURITY_POLICY}
        self._send_bytes(body, content_type, cache_control, extra_headers=extra)
        return True

    # ---------- 路由 ----------

    def do_GET(self):
        """处理 GET 请求"""
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if self._send_static(path):
                return
            if path == '/favicon.ico':
                # 避免浏览器控制台出现 JSON 404 噪声
                self._send_bytes(b'', 'image/x-icon',
                                 cache_control='public, max-age=86400', status=204)
            elif path == '/api/status':
                self._send_json(_build_status(self.server.config, self.server.runtime))
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

    def _origin_allowed(self):
        """拒绝跨站写操作；无 Origin 的命令行客户端保持兼容"""
        origin = self.headers.get('Origin')
        if origin:
            parsed = urlparse(origin)
            expected_hosts = {self.headers.get('Host', '')}
            forwarded_host = self.headers.get('X-Forwarded-Host', '').split(',')[0].strip()
            if forwarded_host:
                expected_hosts.add(forwarded_host)
            if parsed.scheme not in ('http', 'https') \
                    or parsed.netloc not in expected_hosts:
                logging.warning(f"[WebUI] 拒绝跨站写请求: {origin}")
                self._send_json({
                    'error': '拒绝跨站写请求；反向代理需保留 Host 或设置 X-Forwarded-Host'
                }, 403)
                return False
        fetch_site = self.headers.get('Sec-Fetch-Site')
        if fetch_site and fetch_site != 'same-origin':
            self._send_json({'error': '拒绝跨站写请求'}, 403)
            return False
        return True

    def do_POST(self):
        """处理 POST 请求"""
        try:
            path = urlparse(self.path).path
            if path in ('/api/run', '/api/config', '/api/config/reset') \
                    and not self._origin_allowed():
                return
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
        content_type = self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
        if content_type != 'application/json':
            self._send_json({'error': '配置更新需要 Content-Type: application/json'}, 415)
            return
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except (ValueError, TypeError):
            length = 0
        if length > 1024 * 1024:
            self._send_json({'error': '配置请求体不能超过 1 MiB'}, 413)
            return
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
            # 仅持久化本次提交的白名单字段，未修改项仍可由 config.yaml 调整
            patch = {
                sec: {
                    key: self.server.config[sec].get(key)
                    for key in values
                }
                for sec, values in update.items()
            }
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
        overrides_path = _get_overrides_file()
        if overrides_path:
            if delete_runtime_overrides is None:
                self._send_json({'error': 'config 模块不可用，无法删除覆盖文件'}, 503)
                return
            try:
                if not delete_runtime_overrides():
                    self._send_json({'error': '覆盖文件删除失败'}, 500)
                    return
                logging.info("[WebUI] 已删除运行时覆盖配置")
            except Exception as e:
                logging.warning(f"[WebUI] 删除覆盖文件失败: {e}")
                self._send_json({'error': f'删除覆盖文件失败: {e}'}, 500)
                return
        try:
            fresh = load_config()
        except Exception as e:
            logging.warning(f"[WebUI] 重载配置失败: {e}")
            self._send_json({'error': f'覆盖文件已删除，但重载配置失败: {e}'}, 500)
            return
        with self.server.config_lock:
            # 保持同一个 dict 对象且不清空，避免主循环读到空配置
            self.server.config.update(fresh)
            new_perf = _get_performance(self.server.config)
        logging.info("[WebUI] 配置已恢复为文件/环境变量设置")
        # 唤醒主循环：立即按恢复后的配置跑一轮
        self.server.trigger_event.set()
        self._send_json({'ok': True, 'performance': new_perf})


# ========== 对外入口 ==========

def start_webui(config, trigger_event, runtime=None):
    """启动 Web 管理界面

    config        load_config() 返回的完整配置 dict（就地修改 performance 段即生效）
    trigger_event threading.Event，set 后唤醒主循环立即执行一轮处理
    runtime       可选，提供 snapshot() 的运行状态对象（src.runtime.RuntimeState）

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
        server = _WebUIServer((host, port), _WebUIHandler, config, trigger_event, runtime)
    except Exception as e:
        logging.warning(f"[WebUI] 启动失败({host}:{port}): {e}")
        return None
    thread = threading.Thread(
        target=server.serve_forever, name='webui-http', daemon=True)
    thread.start()
    logging.info(f"[WebUI] 管理界面已启动: http://{host}:{port}")
    return server
