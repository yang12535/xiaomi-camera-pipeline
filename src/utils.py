#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具函数模块"""

import os
import subprocess
import logging
import logging.handlers


def format_size(size_bytes):
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024**2:
        return f"{size_bytes/1024:.1f}KB"
    elif size_bytes < 1024**3:
        return f"{size_bytes/1024**2:.1f}MB"
    else:
        return f"{size_bytes/1024**3:.2f}GB"


def format_speed(bytes_per_sec):
    """格式化速度"""
    if bytes_per_sec < 1024:
        return f"{bytes_per_sec}B/s"
    elif bytes_per_sec < 1024**2:
        return f"{bytes_per_sec/1024:.1f}KB/s"
    else:
        return f"{bytes_per_sec/1024**2:.2f}MB/s"


def get_video_duration(path):
    """使用 ffprobe 获取视频时长（秒）"""
    cmd = [
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        try:
            return float(result.stdout.strip())
        except ValueError:
            return None
    return None


def verify_video(path):
    """使用 ffprobe 验证视频文件完整性"""
    cmd = ['ffprobe', '-v', 'error', '-show_format', '-show_streams', path]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0


def get_video_dirs(source_dir):
    """获取视频目录列表（按小时命名的 10 位数字目录）"""
    dirs = []
    if not os.path.exists(source_dir):
        return dirs
    for item in sorted(os.listdir(source_dir)):
        item_path = os.path.join(source_dir, item)
        if os.path.isdir(item_path) and len(item) == 10 and item.isdigit():
            dirs.append(item_path)
    return dirs


def setup_logging(config=None):
    """配置日志"""
    import sys
    from datetime import datetime
    
    log_dir = os.getenv('LOG_DIR', '/logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'pipeline.log')
    
    if config and 'level' in config:
        level_str = config['level']
    else:
        level_str = os.getenv('LOG_LEVEL', 'INFO')
    
    level = getattr(logging, level_str.upper(), logging.INFO)
    
    if config and 'format' in config:
        fmt = config['format']
    else:
        fmt = '%(asctime)s - %(levelname)s - %(message)s'
    
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.handlers.RotatingFileHandler(
                log_file, maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
            ),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # 清理旧日志
    _cleanup_old_logs(log_dir, config)
    
    return log_file


def _cleanup_old_logs(log_dir, config=None):
    """清理超过保留天数的旧日志文件"""
    from datetime import datetime
    
    retain_days = 30
    if config and 'retain_days' in config:
        retain_days = config['retain_days']
    
    if retain_days <= 0:
        return
    
    try:
        cutoff = datetime.now().timestamp() - (retain_days * 86400)
        for filename in os.listdir(log_dir):
            if filename.endswith('.log'):
                filepath = os.path.join(log_dir, filename)
                if os.path.isfile(filepath):
                    if os.path.getmtime(filepath) < cutoff:
                        os.remove(filepath)
                        logging.debug(f"已清理旧日志: {filename}")
    except OSError:
        pass
