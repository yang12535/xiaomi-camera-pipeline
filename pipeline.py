#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小米摄像头视频流水线

模块化的视频处理流水线：
合并 → 压缩 → 上传

v1.3.0 - 并行压缩与 CPU 绑核、WebUI 与立即运行触发
"""

import os
import sys
import io

# ========== 强制 UTF-8 编码配置 ==========
os.environ['PYTHONIOENCODING'] = 'utf-8'

if sys.platform == 'win32':
    os.environ['LC_ALL'] = 'zh_CN.UTF-8'
    os.environ['LANG'] = 'zh_CN.UTF-8'
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass
else:
    os.environ.setdefault('LC_ALL', 'C.UTF-8')
    os.environ.setdefault('LANG', 'C.UTF-8')
# ===================================================

import threading
import logging

# 确保 src 目录在路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config
from src.database import init_db
from src.utils import setup_logging
from src.merger import merge_videos
from src.compressor import compress_videos
from src.uploader import upload_videos


def main():
    """主循环"""
    config = load_config()
    log_file = setup_logging(config.get('logging'))
    
    logging.info("="*50)
    logging.info("小米摄像头视频流水线 v1.3.0")
    logging.info("="*50)
    
    init_db()
    
    trigger_event = threading.Event()
    
    if config.get('webui', {}).get('enabled'):
        try:
            from src.webui import start_webui
            start_webui(config, trigger_event)
            logging.info(f"[WebUI] 已启动: http://{config['webui']['host']}:{config['webui']['port']}")
        except Exception as e:
            logging.warning(f"[WebUI] 启动失败: {e}")
    
    logging.info(f"配置: {os.getenv('CONFIG_FILE', '/app/config.yaml')}")
    logging.info(f"数据: {os.getenv('STATE_DB', '/app/data/pipeline.db')}")
    logging.info(f"日志文件: {log_file}")
    logging.info(f"轮询间隔: {config['schedule']['interval']}秒")
    logging.info("-"*50)
    
    while True:
        perf_cfg = config.get('performance', {})
        logging.info(f"性能配置: 并行={perf_cfg.get('parallel', 1)} "
                     f"核心={perf_cfg.get('core_list') or perf_cfg.get('cores', 0) or '不限'} "
                     f"绑核={'开' if perf_cfg.get('bind') else '关'}")
        logging.info("开始处理..")
        
        merged = merge_videos(config)
        compressed = compress_videos(config)
        uploaded = upload_videos(config)
        
        logging.info(f"本次处理: 合并{merged} 压缩{compressed} 上传{uploaded}")
        
        if config['schedule']['run_once']:
            logging.info("单次运行模式，退出")
            break
        
        logging.info(f"等待 {config['schedule']['interval']}秒 ..")
        trigger_event.wait(timeout=config['schedule']['interval'])
        trigger_event.clear()


if __name__ == '__main__':
    main()
