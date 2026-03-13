#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小米摄像头视频流水线

模块化的视频处理流水线：
合并 → 压缩 → 上传

v1.2.2 - 断点续传 + 进度监控 + 监控场景优化
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

import time
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
    logging.info("小米摄像头视频流水线 v1.2.2")
    logging.info("="*50)
    
    init_db()
    
    logging.info(f"配置: {os.getenv('CONFIG_FILE', '/app/config.yaml')}")
    logging.info(f"数据: {os.getenv('STATE_DB', '/app/data/pipeline.db')}")
    logging.info(f"日志文件: {log_file}")
    logging.info(f"轮询间隔: {config['schedule']['interval']}秒")
    logging.info("-"*50)
    
    while True:
        logging.info("开始处理..")
        
        merged = merge_videos(config)
        compressed = compress_videos(config)
        uploaded = upload_videos(config)
        
        logging.info(f"本次处理: 合并{merged} 压缩{compressed} 上传{uploaded}")
        
        if config['schedule']['run_once']:
            logging.info("单次运行模式，退出")
            break
        
        logging.info(f"等待 {config['schedule']['interval']}秒 ..")
        time.sleep(config['schedule']['interval'])


if __name__ == '__main__':
    main()
