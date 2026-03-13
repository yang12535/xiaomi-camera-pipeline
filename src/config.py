#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置管理模块"""

import os
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
    }
}

CONFIG_FILE = os.getenv('CONFIG_FILE', '/app/config.yaml')


def load_config():
    """加载配置，环境变量优先级最高"""
    config = DEFAULT_CONFIG.copy()
    
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            user_config = yaml.safe_load(f) or {}
            for key in config:
                if key in user_config:
                    config[key].update(user_config[key])
    
    # 环境变量覆盖
    if os.getenv('COMPRESS_RESOLUTION'):
        config['compress']['resolution'] = os.getenv('COMPRESS_RESOLUTION')
    if os.getenv('COMPRESS_CRF'):
        config['compress']['crf'] = int(os.getenv('COMPRESS_CRF'))
    if os.getenv('COMPRESS_THREADS'):
        config['compress']['threads'] = int(os.getenv('COMPRESS_THREADS'))
    if os.getenv('COMPRESS_PRESET'):
        config['compress']['preset'] = os.getenv('COMPRESS_PRESET')
    
    return config
