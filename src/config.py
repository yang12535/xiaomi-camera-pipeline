#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置管理模块"""

import os
import logging
import yaml

DEFAULT_CONFIG = {
    'merge': {
        'source_dir': '/video',
        'output_dir': '/input',
        'delete_source': True,
    },
    'compress': {
        'input_dir': '/input',
        'output_dir': '/output',
        'crf': 35,
        'preset': 'medium',
        'threads': 4,
        'resolution': '1920x1080',
        'delete_source': True,
    },
    'upload': {
        'enabled': False,
        'webdav_url': '',
        'webdav_user': '',
        'webdav_pass': '',
        'rate_limit': '1M',
        'delete_after_upload': True,
        'resume': True,
        'max_retries': 3,
        'retry_delay': 30,
    },
    'schedule': {
        'interval': 3600,
        'run_once': False,
    },
    'logging': {
        'level': 'INFO',
        'format': '%(asctime)s - %(levelname)s - %(message)s',
        'retain_days': 30,
    },
    'performance': {
        'parallel': 1,      # 并行压缩任务数，1=串行（旧行为）
        'cores': 0,         # 允许使用的核心数，0=不限制
        'core_list': '',    # 显式核心列表如 "0-3,6"，非空时优先于 cores
        'bind': False,      # 是否将每个 ffmpeg 绑定到分配的核心片上
    },
    'webui': {
        'enabled': False,
        'host': '0.0.0.0',
        'port': 8080,
    }
}

CONFIG_FILE = os.getenv('CONFIG_FILE', '/app/config.yaml')

# 状态数据库路径（与 database.py 保持一致），覆盖文件默认放在数据目录
STATE_DB = os.getenv('STATE_DB', '/app/data/pipeline.db')

# WebUI 运行时覆盖文件：优先级高于 config.yaml、低于环境变量
RUNTIME_OVERRIDES = os.getenv(
    'RUNTIME_OVERRIDES',
    os.path.join(os.path.dirname(STATE_DB), 'runtime_overrides.yaml'))

# 由环境变量钉死的配置键（'段.键' 形式），load_config() 每次调用时重建。
# 被钉死的键不允许通过 WebUI 修改（环境变量优先级最高，改了也会被覆盖）。
ENV_PINNED = set()


def load_config():
    """加载配置

    优先级：默认值 < config.yaml < 运行时覆盖文件 < 环境变量。
    每应用一个环境变量覆盖，把对应 '段.键' 记入 ENV_PINNED。
    """
    ENV_PINNED.clear()
    # 逐段复制，避免嵌套 dict 共享引用导致运行时修改污染 DEFAULT_CONFIG
    config = {key: dict(section) for key, section in DEFAULT_CONFIG.items()}

    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            user_config = yaml.safe_load(f) or {}
            for key in config:
                if key in user_config:
                    config[key].update(user_config[key])

    # 运行时覆盖文件（WebUI 保存）：损坏时记 warning 后忽略，不影响启动
    if os.path.exists(RUNTIME_OVERRIDES):
        try:
            with open(RUNTIME_OVERRIDES, 'r', encoding='utf-8') as f:
                overrides = yaml.safe_load(f)
            if isinstance(overrides, dict):
                for key in config:
                    if key in overrides and isinstance(overrides[key], dict):
                        config[key].update(overrides[key])
        except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
            logging.warning(f"[配置] 运行时覆盖文件读取失败，忽略: {e}")
    
    # 压缩参数 - 环境变量覆盖
    if os.getenv('COMPRESS_RESOLUTION'):
        config['compress']['resolution'] = os.getenv('COMPRESS_RESOLUTION')
        ENV_PINNED.add('compress.resolution')
    if os.getenv('COMPRESS_CRF'):
        config['compress']['crf'] = int(os.getenv('COMPRESS_CRF'))
        ENV_PINNED.add('compress.crf')
    if os.getenv('COMPRESS_THREADS'):
        config['compress']['threads'] = int(os.getenv('COMPRESS_THREADS'))
        ENV_PINNED.add('compress.threads')
    if os.getenv('COMPRESS_PRESET'):
        config['compress']['preset'] = os.getenv('COMPRESS_PRESET')
        ENV_PINNED.add('compress.preset')
    if os.getenv('COMPRESS_DELETE_SOURCE'):
        config['compress']['delete_source'] = os.getenv('COMPRESS_DELETE_SOURCE').lower() in ('true', '1', 'yes')
        ENV_PINNED.add('compress.delete_source')

    # 上传参数 - 环境变量覆盖
    if os.getenv('UPLOAD_ENABLED'):
        config['upload']['enabled'] = os.getenv('UPLOAD_ENABLED').lower() in ('true', '1', 'yes')
        ENV_PINNED.add('upload.enabled')
    if os.getenv('WEBDAV_URL'):
        config['upload']['webdav_url'] = os.getenv('WEBDAV_URL')
        ENV_PINNED.add('upload.webdav_url')
    if os.getenv('WEBDAV_USER'):
        config['upload']['webdav_user'] = os.getenv('WEBDAV_USER')
        ENV_PINNED.add('upload.webdav_user')
    if os.getenv('WEBDAV_PASS'):
        config['upload']['webdav_pass'] = os.getenv('WEBDAV_PASS')
        ENV_PINNED.add('upload.webdav_pass')
    if os.getenv('UPLOAD_RATE_LIMIT'):
        config['upload']['rate_limit'] = os.getenv('UPLOAD_RATE_LIMIT')
        ENV_PINNED.add('upload.rate_limit')
    if os.getenv('UPLOAD_DELETE_AFTER'):
        config['upload']['delete_after_upload'] = os.getenv('UPLOAD_DELETE_AFTER').lower() in ('true', '1', 'yes')
        ENV_PINNED.add('upload.delete_after_upload')

    # 合并参数 - 环境变量覆盖
    if os.getenv('MERGE_INTERVAL'):
        # MERGE_INTERVAL(分钟) 为历史兼容别名，作用于 schedule.interval
        config['schedule']['interval'] = int(os.getenv('MERGE_INTERVAL')) * 60
        ENV_PINNED.add('schedule.interval')
    if os.getenv('MERGE_DELETE_SOURCE'):
        config['merge']['delete_source'] = os.getenv('MERGE_DELETE_SOURCE').lower() in ('true', '1', 'yes')
        ENV_PINNED.add('merge.delete_source')

    # 日志级别
    if os.getenv('LOG_LEVEL'):
        config['logging']['level'] = os.getenv('LOG_LEVEL').upper()
        ENV_PINNED.add('logging.level')

    # 性能参数 - 环境变量覆盖
    if os.getenv('PERF_PARALLEL'):
        config['performance']['parallel'] = int(os.getenv('PERF_PARALLEL'))
        ENV_PINNED.add('performance.parallel')
    if os.getenv('PERF_CORES'):
        config['performance']['cores'] = int(os.getenv('PERF_CORES'))
        ENV_PINNED.add('performance.cores')
    if os.getenv('PERF_CORE_LIST'):
        config['performance']['core_list'] = os.getenv('PERF_CORE_LIST')
        ENV_PINNED.add('performance.core_list')
    if os.getenv('PERF_BIND'):
        config['performance']['bind'] = os.getenv('PERF_BIND').lower() in ('true', '1', 'yes')
        ENV_PINNED.add('performance.bind')

    # WebUI 参数 - 环境变量覆盖
    if os.getenv('WEBUI_ENABLED'):
        config['webui']['enabled'] = os.getenv('WEBUI_ENABLED').lower() in ('true', '1', 'yes')
        ENV_PINNED.add('webui.enabled')
    if os.getenv('WEBUI_HOST'):
        config['webui']['host'] = os.getenv('WEBUI_HOST')
        ENV_PINNED.add('webui.host')
    if os.getenv('WEBUI_PORT'):
        config['webui']['port'] = int(os.getenv('WEBUI_PORT'))
        ENV_PINNED.add('webui.port')

    return config


def save_runtime_overrides(patch):
    """把 patch dict（如 {'performance': {...}}）原子写入 RUNTIME_OVERRIDES

    与文件中已有的其他段落合并后整体写回；先写同目录临时文件再 os.replace，
    避免写一半留下损坏文件。成功返回文件路径，失败抛异常。
    """
    dir_name = os.path.dirname(RUNTIME_OVERRIDES)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    data = {}
    if os.path.exists(RUNTIME_OVERRIDES):
        try:
            with open(RUNTIME_OVERRIDES, 'r', encoding='utf-8') as f:
                existing = yaml.safe_load(f)
            if isinstance(existing, dict):
                data = existing
        except (yaml.YAMLError, OSError):
            pass  # 旧文件损坏则以 patch 为准重写
    data.update(patch)

    tmp_file = RUNTIME_OVERRIDES + '.tmp'
    with open(tmp_file, 'w', encoding='utf-8') as f:
        f.write('# WebUI 运行时覆盖配置，优先级高于 config.yaml、低于环境变量\n')
        yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    os.replace(tmp_file, RUNTIME_OVERRIDES)
    return RUNTIME_OVERRIDES


def delete_runtime_overrides():
    """删除运行时覆盖文件，文件不存在或删除失败返回 False"""
    if not os.path.exists(RUNTIME_OVERRIDES):
        return False
    try:
        os.remove(RUNTIME_OVERRIDES)
        return True
    except OSError as e:
        logging.warning(f"[配置] 删除运行时覆盖文件失败: {e}")
        return False
