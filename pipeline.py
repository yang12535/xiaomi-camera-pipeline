#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2026 xiaomi-camera-pipeline contributors
# SPDX-License-Identifier: AGPL-3.0
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
小米摄像头视频流水线
阶段：合并 → 压缩 → 上传

本项目整合自：
- 合并功能: https://github.com/hslr-s/xiaomi-camera-merge
- 压缩功能: https://github.com/yang12535/xiaomi-compress
"""

import urllib.parse
import os
import urllib.parse
import sys
import urllib.parse
import io

# ========== 强制 UTF-8 编码配置（Windows 机房环境）==========
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Windows 环境下强制设置 stdout/stderr 编码（机房还原卡问题）
if sys.platform == 'win32':
    os.environ['LC_ALL'] = 'zh_CN.UTF-8'
    os.environ['LANG'] = 'zh_CN.UTF-8'
    # 仅在 Windows 下强制重定向 stdout/stderr
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        pass  # 某些环境下 buffer 可能不可用
else:
    # Linux/Docker 环境：使用 C.UTF-8（无需额外安装）
    os.environ.setdefault('LC_ALL', 'C.UTF-8')
    os.environ.setdefault('LANG', 'C.UTF-8')
# ===================================================
import time
import yaml
import subprocess
import sqlite3
import shutil
import logging
from datetime import datetime

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
        'resolution': '1920x1080',  # 默认 1080p
        'delete_source': True,
    },
    'upload': {
        'enabled': False,
        'webdav_url': '',
        'webdav_user': '',
        'webdav_pass': '',
        'rate_limit': '1M',
        'delete_after_upload': True,
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
STATE_DB = os.getenv('STATE_DB', '/app/pipeline.db')


def load_config():
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            user_config = yaml.safe_load(f) or {}
            for key in config:
                if key in user_config:
                    config[key].update(user_config[key])
    
    # 环境变量覆盖（支COMPRESS_* 前缀
    if os.getenv('COMPRESS_RESOLUTION'):
        config['compress']['resolution'] = os.getenv('COMPRESS_RESOLUTION')
    if os.getenv('COMPRESS_CRF'):
        config['compress']['crf'] = int(os.getenv('COMPRESS_CRF'))
    if os.getenv('COMPRESS_THREADS'):
        config['compress']['threads'] = int(os.getenv('COMPRESS_THREADS'))
    if os.getenv('COMPRESS_PRESET'):
        config['compress']['preset'] = os.getenv('COMPRESS_PRESET')
    
    return config


def setup_logging(config=None):
    """配置日志：同时输出到文件和 stdout
    
    Args:
        config: 日志配置字典，包含 level, format, retain_days
    
    Returns:
        log_file: 日志文件路径
    """
    log_dir = os.getenv('LOG_DIR', '/logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'pipeline.log')
    
    # 从配置或环境变量获取日志级别
    if config and 'level' in config:
        level_str = config['level']
    else:
        level_str = os.getenv('LOG_LEVEL', 'INFO')
    
    level = getattr(logging, level_str.upper(), logging.INFO)
    
    # 日志格式
    if config and 'format' in config:
        fmt = config['format']
    else:
        fmt = '%(asctime)s - %(levelname)s - %(message)s'
    
    # 配置根日志记录器
    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # 清理旧日志文件
    _cleanup_old_logs(log_dir, config)
    
    return log_file


def _cleanup_old_logs(log_dir, config=None):
    """清理超过保留天数的旧日志文件"""
    retain_days = 30  # 默认 30 天
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
        pass  # 清理失败不影响主程序


def init_db():
    conn = sqlite3.connect(STATE_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS processed
                 (path TEXT PRIMARY KEY, stage TEXT, timestamp TEXT)''')
    conn.commit()
    conn.close()


def is_processed(path, stage):
    conn = sqlite3.connect(STATE_DB)
    c = conn.cursor()
    c.execute('SELECT 1 FROM processed WHERE path=? AND stage=?', (path, stage))
    result = c.fetchone()
    conn.close()
    return result is not None


def mark_processed(path, stage):
    conn = sqlite3.connect(STATE_DB)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO processed VALUES (?, ?, ?)",
              (path, stage, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_video_dirs(source_dir):
    dirs = []
    if not os.path.exists(source_dir):
        return dirs
    for item in sorted(os.listdir(source_dir)):
        item_path = os.path.join(source_dir, item)
        if os.path.isdir(item_path) and len(item) == 10:
            dirs.append(item_path)
    return dirs


def merge_videos(config):
    merge_cfg = config['merge']
    source = merge_cfg['source_dir']
    output = merge_cfg['output_dir']
    
    if not os.path.exists(source):
        logging.info(f"[合并] 源目录不存在: {source}")
        return 0
    
    os.makedirs(output, exist_ok=True)
    dirs = get_video_dirs(source)
    
    if not dirs:
        logging.info("[合并] 没有新视频需要处理")
        return 0
    
    count = 0
    for video_dir in dirs:
        dir_name = os.path.basename(video_dir)
        if is_processed(video_dir, 'merge'):
            continue
        
        logging.info(f"[合并] 处理目录: {dir_name}")
        
        mp4_files = sorted([
            f for f in os.listdir(video_dir)
            if f.endswith('.mp4')
        ])
        
        if not mp4_files:
            continue
        
        concat_file = os.path.join(os.environ.get('TEMP', '/tmp'), f"concat_{dir_name}.txt")
        # 使用 utf-8-sig 会带 BOM，用 utf-8 不带 BOM
        with open(concat_file, 'w', encoding='utf-8', newline='\n') as f:
            for mp4 in mp4_files:
                # Windows 路径转为正斜杠以兼容 ffmpeg
                file_path = os.path.join(video_dir, mp4).replace('\\', '/')
                f.write(f"file '{file_path}'\n")
        
        hour_str = dir_name[:10]
        year, month, day, hour = hour_str[:4], hour_str[4:6], hour_str[6:8], hour_str[8:10]
        
        out_dir = os.path.join(output, year, month, day)
        os.makedirs(out_dir, exist_ok=True)
        out_file = os.path.join(out_dir, f"{hour}.mov")
        temp_file = out_file.replace('.mov', '.tmp.mov')
        
        # 跳过已存在的有效文件
        if os.path.exists(out_file):
            if verify_video(out_file):
                logging.info(f"[合并] 跳过已存 {out_file}")
                mark_processed(video_dir, 'merge')
                count += 1
                os.remove(concat_file)
                continue
            else:
                logging.warning(f"[合并] 删除无效旧文 {out_file}")
                os.remove(out_file)
        
        cmd = [
            'ffmpeg', '-y', '-f', 'concat', '-safe', '0',
            '-i', concat_file, '-c', 'copy', '-movflags', '+faststart',
            temp_file
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0 and os.path.exists(temp_file):
                # 验证输出文件
                if os.path.getsize(temp_file) > 1048576 and verify_video(temp_file):
                    try:
                        os.rename(temp_file, out_file)
                        if os.path.exists(out_file):
                            logging.info(f"[合并] 成功: {out_file}")
                            mark_processed(video_dir, 'merge')
                            count += 1
                            
                            if merge_cfg['delete_source']:
                                shutil.rmtree(video_dir)
                                logging.info(f"[合并] 已清理源目录: {video_dir}")
                        else:
                            logging.error(f"[合并] 失败: 最终文件不存在")
                    except OSError as e:
                        logging.error(f"[合并] 失败: 重命名出- {e}")
                        os.remove(temp_file)
                else:
                    logging.error(f"[合并] 失败: 输出文件无效")
                    os.remove(temp_file)
            else:
                logging.error(f"[合并] 失败: ffmpeg 退出码 {result.returncode}")
                if result.stderr:
                    logging.error(f"[合并] 错误: {result.stderr[:300]}")
        finally:
            if os.path.exists(concat_file):
                os.remove(concat_file)
            if os.path.exists(temp_file):
                os.remove(temp_file)
    
    return count


def get_video_duration(path):
    """使用 ffprobe 获取视频时长（秒"""
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


def compress_videos(config):
    compress_cfg = config['compress']
    input_dir = compress_cfg['input_dir']
    output_dir = compress_cfg['output_dir']
    
    if not os.path.exists(input_dir):
        return 0
    
    os.makedirs(output_dir, exist_ok=True)
    
    mov_files = []
    for root, _, files in os.walk(input_dir):
        for f in files:
            if f.endswith('.mov'):
                mov_files.append(os.path.join(root, f))
    
    count = 0
    for mov_path in mov_files:
        rel_path = os.path.relpath(mov_path, input_dir)
        if is_processed(mov_path, 'compress'):
            continue
        
        out_path = os.path.join(output_dir, rel_path.replace('.mov', '.mkv'))
        temp_path = out_path.replace('.mkv', '.tmp.mkv')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        
        # 跳过已存在的有效文件
        if os.path.exists(out_path):
            existing_size = os.path.getsize(out_path)
            if existing_size > 1048576 and verify_video(out_path):
                logging.info(f"[压缩] 跳过已存 {rel_path}")
                mark_processed(mov_path, 'compress')
                count += 1
                continue
            else:
                logging.warning(f"[压缩] 删除无效旧文 {rel_path}")
                os.remove(out_path)
        
        logging.info(f"[压缩] 开始 {rel_path}")
        
        # 构建 ffmpeg 命令（输出到临时文件
        cmd = [
            'ffmpeg', '-y', '-i', mov_path,
            '-c:v', 'libx265', '-crf', str(compress_cfg['crf']),
            '-preset', compress_cfg['preset'],
            '-threads', str(compress_cfg['threads']),
            '-c:a', 'copy',
            '-tag:v', 'hvc1',
        ]
        
        # 处理分辨率设- 只缩小不放大
        resolution = compress_cfg.get('resolution', '1920x1080')
        if resolution and resolution.lower() != 'original':
            # 支持 1920x1080 1920:-2 -2:1080 格式
            # 添加 force_original_aspect_ratio=decrease 确保只缩小不放大
            scale_vf = resolution.replace('x', ':')
            scale_vf = f"{scale_vf}:force_original_aspect_ratio=decrease"
            cmd.extend(['-vf', f'scale={scale_vf}'])
        
        cmd.append(temp_path)
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # 严格验证流程（参xiaomi-compress
        if result.returncode == 0 and os.path.exists(temp_path):
            output_size = os.path.getsize(temp_path)
            
            # 1. 文件大小检查（至少 1MB
            if output_size < 1048576:
                logging.error(f"[压缩] 失败: 输出文件过小 ({output_size} bytes)")
                os.remove(temp_path)
                continue
            
            # 2. ffprobe 完整性验证"
            if not verify_video(temp_path):
                logging.error(f"[压缩] 失败: ffprobe 验证未通过")
                os.remove(temp_path)
                continue
            
            # 3. 时长检查（输入输出差异应在 ±30 秒内
            input_duration = get_video_duration(mov_path)
            output_duration = get_video_duration(temp_path)
            
            if input_duration is not None and output_duration is not None:
                duration_diff = abs(input_duration - output_duration)
                if duration_diff > 30:
                    logging.error(f"[压缩] 失败: 时长差异过大 ({duration_diff:.1f}s > 30s)")
                    os.remove(temp_path)
                    continue
                logging.info(f"[压缩] 时长检查通过: 差异={duration_diff:.1f}s")
            
            # 4. 重命名临时文件到最终输
            try:
                os.rename(temp_path, out_path)
            except OSError as e:
                logging.error(f"[压缩] 失败: 重命名文件出- {e}")
                os.remove(temp_path)
                continue
            
            # 5. 确认最终文件存在后标记完成
            if os.path.exists(out_path):
                logging.info(f"[压缩] 成功: {rel_path} ({output_size / 1024 / 1024:.1f} MB)")
                mark_processed(mov_path, 'compress')
                count += 1
                
                # 6. 安全删除源文
                if compress_cfg['delete_source']:
                    try:
                        os.remove(mov_path)
                        logging.info(f"[压缩] 已清理源文件: {rel_path}")
                    except OSError as e:
                        logging.error(f"[压缩] 警告: 无法删除源文- {e}")
            else:
                logging.error(f"[压缩] 失败: 最终文件不存在")
        else:
            # ffmpeg 执行失败或临时文件不存在
            if os.path.exists(temp_path):
                os.remove(temp_path)
            logging.error(f"[压缩] 失败: ffmpeg 退出码 {result.returncode}")
            if result.stderr:
                logging.error(f"[压缩] 错误: {result.stderr[:300]}")
    
    return count


def upload_videos(config):
    upload_cfg = config['upload']
    if not upload_cfg['enabled']:
        return 0
    
    # 支持动态日期路径
    import datetime
    date_path = datetime.datetime.now().strftime('%Y/%m/%d')  # 2026/03
    
    output_dir = config['compress']['output_dir']
    if not os.path.exists(output_dir):
        return 0
    
    mkv_files = []
    for root, _, files in os.walk(output_dir):
        for f in files:
            if f.endswith('.mkv'):
                mkv_files.append(os.path.join(root, f))
    
    count = 0
    for mkv_path in mkv_files:
        if is_processed(mkv_path, 'upload'):
            continue
        
        filename = os.path.basename(mkv_path)
        
        # 动态构建远程路径: url/2026/03/filename.mkv
        base_url = upload_cfg['webdav_url'].rstrip('/')
        remote_url = f"{base_url}/{date_path}/{urllib.parse.quote(filename)}"
        
        logging.info(f"[上传] {filename} -> {date_path}/")
        
        # 逐级创建目录 年/月/日
        path_parts = date_path.split('/')
        current_path = base_url
        for part in path_parts:
            current_path = f"{current_path}/{part}"
            mkcol_cmd = [
                'curl', '-X', 'MKCOL', current_path,
                '--user', f"{upload_cfg['webdav_user']}:{upload_cfg['webdav_pass']}",
                '-f', '-s'
            ]
            subprocess.run(mkcol_cmd, capture_output=True)  # 忽略已存在错误
        
        cmd = [
            'curl', '-T', mkv_path, remote_url,
            '--user', f"{upload_cfg['webdav_user']}:{upload_cfg['webdav_pass']}",
            '--limit-rate', upload_cfg['rate_limit'],
            '-f'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            logging.info(f"[上传] 成功: {filename}")
            mark_processed(mkv_path, 'upload')
            count += 1
            
            if upload_cfg['delete_after_upload']:
                os.remove(mkv_path)
                logging.info(f"[上传] 已删除本地文件: {mkv_path}")
        else:
            logging.error(f"[上传] 失败: {result.stderr}")
    
    return count



def main():
    # 先加载配置获取日志设置
    config = load_config()
    log_file = setup_logging(config.get('logging'))
    
    logging.info("="*50)
    logging.info("小米摄像头视频流水线")
    logging.info("="*50)
    
    init_db()
    
    logging.info(f"配置: {CONFIG_FILE}")
    logging.info(f"数据 {STATE_DB}")
    logging.info(f"日志文件: {log_file}")
    logging.info(f"轮询间隔: {config['schedule']['interval']}")
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
        
        logging.info(f"等待 {config['schedule']['interval']} ..")
        time.sleep(config['schedule']['interval'])


if __name__ == '__main__':
    main()
