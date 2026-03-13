#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2026 xiaomi-camera-pipeline contributors
# SPDX-License-Identifier: AGPL-3.0
#
# v1.2.2 - 断点续传 + 进度监控 + 监控场景优化

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
import yaml
import subprocess
import sqlite3
import shutil
import logging
import json
import re
from datetime import datetime
from urllib.parse import quote

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
        'resume': True,           # 断点续传
        'max_retries': 3,         # 最大重试次数
        'retry_delay': 30,        # 重试间隔(秒)
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


def setup_logging(config=None):
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
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    _cleanup_old_logs(log_dir, config)
    
    return log_file


def _cleanup_old_logs(log_dir, config=None):
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


def init_db():
    conn = sqlite3.connect(STATE_DB)
    c = conn.cursor()
    # 处理记录
    c.execute('''CREATE TABLE IF NOT EXISTS processed
                 (path TEXT PRIMARY KEY, stage TEXT, timestamp TEXT)''')
    # 上传进度（断点续传）
    c.execute('''CREATE TABLE IF NOT EXISTS upload_progress
                 (file_path TEXT PRIMARY KEY, remote_url TEXT, uploaded_size INTEGER, 
                  total_size INTEGER, last_try TEXT, retry_count INTEGER DEFAULT 0)''')
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


def get_upload_progress(file_path):
    """获取文件上传进度"""
    conn = sqlite3.connect(STATE_DB)
    c = conn.cursor()
    c.execute('SELECT remote_url, uploaded_size, total_size, retry_count FROM upload_progress WHERE file_path=?', (file_path,))
    result = c.fetchone()
    conn.close()
    if result:
        return {'remote_url': result[0], 'uploaded': result[1], 'total': result[2], 'retries': result[3]}
    return None


def save_upload_progress(file_path, remote_url, uploaded_size, total_size):
    """保存上传进度"""
    conn = sqlite3.connect(STATE_DB)
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO upload_progress 
                 VALUES (?, ?, ?, ?, ?, COALESCE((SELECT retry_count FROM upload_progress WHERE file_path=?), 0))''',
              (file_path, remote_url, uploaded_size, total_size, datetime.now().isoformat(), file_path))
    conn.commit()
    conn.close()


def clear_upload_progress(file_path):
    """清除上传进度（上传成功或放弃）"""
    conn = sqlite3.connect(STATE_DB)
    c = conn.cursor()
    c.execute('DELETE FROM upload_progress WHERE file_path=?', (file_path,))
    conn.commit()
    conn.close()


def increment_retry_count(file_path):
    """增加重试计数"""
    conn = sqlite3.connect(STATE_DB)
    c = conn.cursor()
    c.execute('UPDATE upload_progress SET retry_count = retry_count + 1, last_try = ? WHERE file_path=?',
              (datetime.now().isoformat(), file_path))
    conn.commit()
    c.execute('SELECT retry_count FROM upload_progress WHERE file_path=?', (file_path,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0


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
        with open(concat_file, 'w', encoding='utf-8', newline='\n') as f:
            for mp4 in mp4_files:
                file_path = os.path.join(video_dir, mp4).replace('\\', '/')
                f.write(f"file '{file_path}'\n")
        
        hour_str = dir_name[:10]
        year, month, day, hour = hour_str[:4], hour_str[4:6], hour_str[6:8], hour_str[8:10]
        
        out_dir = os.path.join(output, year, month, day)
        os.makedirs(out_dir, exist_ok=True)
        out_file = os.path.join(out_dir, f"{hour}.mov")
        temp_file = out_file.replace('.mov', '.tmp.mov')
        
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
                if os.path.getsize(temp_file) > 1048576 and verify_video(temp_file):
                    try:
                        os.rename(temp_file, out_file)
                        if os.path.exists(out_file):
                            logging.info(f"[合并] 成功: {out_file}")
                            mark_processed(video_dir, 'merge')
                            count += 1
                            
                            if merge_cfg['delete_source']:
                                try:
                                    shutil.rmtree(video_dir)
                                    logging.info(f"[合并] 已清理源目录: {video_dir}")
                                except OSError as e:
                                    logging.warning(f"[合并] 无法清理源目录（只读挂载）: {video_dir}, 错误: {e}")
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
        
        cmd = [
            'ffmpeg', '-y', '-i', mov_path,
            '-c:v', 'libx265', '-crf', str(compress_cfg['crf']),
            '-preset', compress_cfg['preset'],
            '-threads', str(compress_cfg['threads']),
            '-c:a', 'copy',
            '-tag:v', 'hvc1',
        ]
        
        resolution = compress_cfg.get('resolution', '1920x1080')
        if resolution and resolution.lower() != 'original':
            scale_vf = resolution.replace('x', ':')
            scale_vf = f"{scale_vf}:force_original_aspect_ratio=decrease"
            cmd.extend(['-vf', f'scale={scale_vf}'])
        
        cmd.append(temp_path)
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0 and os.path.exists(temp_path):
            output_size = os.path.getsize(temp_path)
            
            if output_size < 1048576:
                logging.error(f"[压缩] 失败: 输出文件过小 ({output_size} bytes)")
                os.remove(temp_path)
                continue
            
            if not verify_video(temp_path):
                logging.error(f"[压缩] 失败: ffprobe 验证未通过")
                os.remove(temp_path)
                continue
            
            input_duration = get_video_duration(mov_path)
            output_duration = get_video_duration(temp_path)
            
            if input_duration is not None and output_duration is not None:
                duration_diff = abs(input_duration - output_duration)
                if duration_diff > 30:
                    logging.error(f"[压缩] 失败: 时长差异过大 ({duration_diff:.1f}s > 30s)")
                    os.remove(temp_path)
                    continue
                logging.info(f"[压缩] 时长检查通过: 差异={duration_diff:.1f}s")
            
            try:
                os.rename(temp_path, out_path)
            except OSError as e:
                logging.error(f"[压缩] 失败: 重命名文件出- {e}")
                os.remove(temp_path)
                continue
            
            if os.path.exists(out_path):
                logging.info(f"[压缩] 成功: {rel_path} ({output_size / 1024 / 1024:.1f} MB)")
                mark_processed(mov_path, 'compress')
                count += 1
                
                if compress_cfg['delete_source']:
                    try:
                        os.remove(mov_path)
                        logging.info(f"[压缩] 已清理源文件: {rel_path}")
                    except OSError as e:
                        logging.error(f"[压缩] 警告: 无法删除源文- {e}")
            else:
                logging.error(f"[压缩] 失败: 最终文件不存在")
        else:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            logging.error(f"[压缩] 失败: ffmpeg 退出码 {result.returncode}")
            if result.stderr:
                logging.error(f"[压缩] 错误: {result.stderr[:300]}")
    
    return count


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


def parse_progress_from_stderr(stderr_line):
    """解析 ffmpeg curl 的进度输出"""
    # 匹配类似:  0  820M    0 15250    0     0   8697      0  27:22:46  0:00:01  27:22:45 15250
    match = re.search(r'(\d+)\s+([\d.]+)([kMG]?)\s+(\d+)\s+([\d.]+)([kMG]?)\s+', stderr_line)
    if match:
        try:
            total_size_str = match.group(2) + match.group(3)
            uploaded_size_str = match.group(5) + match.group(6)
            
            multiplier = {'': 1, 'k': 1024, 'M': 1024**2, 'G': 1024**3}
            total = float(match.group(2)) * multiplier.get(match.group(3), 1)
            uploaded = float(match.group(5)) * multiplier.get(match.group(6), 1)
            return int(uploaded), int(total)
        except:
            pass
    return None, None


def upload_videos(config):
    """带断点续传和进度监控的上传功能"""
    upload_cfg = config['upload']
    if not upload_cfg['enabled']:
        return 0
    
    import datetime
    # 使用本地时区（容器设置了 TZ=Asia/Shanghai）
    date_path = datetime.datetime.now().strftime('%Y/%m/%d')  # 本地时间，非 UTC
    
    output_dir = config['compress']['output_dir']
    if not os.path.exists(output_dir):
        return 0
    
    mkv_files = []
    for root, _, files in os.walk(output_dir):
        for f in files:
            if f.endswith('.mkv'):
                mkv_files.append(os.path.join(root, f))
    
    count = 0
    resume_enabled = upload_cfg.get('resume', True)
    max_retries = upload_cfg.get('max_retries', 3)
    retry_delay = upload_cfg.get('retry_delay', 30)
    
    for mkv_path in mkv_files:
        if is_processed(mkv_path, 'upload'):
            continue
        
        filename = os.path.basename(mkv_path)
        file_size = os.path.getsize(mkv_path)
        
        base_url = upload_cfg['webdav_url'].rstrip('/')
        remote_url = f"{base_url}/{date_path}/{quote(filename)}"
        
        logging.info(f"[上传] {filename} ({format_size(file_size)}) -> {date_path}/")
        
        # 检查之前的上传进度
        progress = get_upload_progress(mkv_path) if resume_enabled else None
        if progress:
            logging.info(f"[上传] 发现未完成上传: {format_size(progress['uploaded'])}/{format_size(progress['total'])}")
        
        # 创建目录结构
        path_parts = date_path.split('/')
        current_path = base_url
        for part in path_parts:
            current_path = f"{current_path}/{part}"
            mkcol_cmd = [
                'curl', '-X', 'MKCOL', current_path,
                '--user', f"{upload_cfg['webdav_user']}:{upload_cfg['webdav_pass']}",
                '-f', '-s'
            ]
            subprocess.run(mkcol_cmd, capture_output=True)
        
        # 构建 curl 命令
        cmd = [
            'curl', '-T', mkv_path, remote_url,
            '--user', f"{upload_cfg['webdav_user']}:{upload_cfg['webdav_pass']}",
            '--limit-rate', upload_cfg['rate_limit'],
            '-f', '-S',  # 显示错误，静默模式
            '--connect-timeout', '30',
            '--max-time', '0',  # 无限制（大文件）
        ]
        
        # 断点续传
        if resume_enabled and progress and progress['uploaded'] > 0:
            cmd.extend(['-C', '-'])  # 自动断点续传
            logging.info(f"[上传] 启用断点续传，从 {format_size(progress['uploaded'])} 继续")
        
        # 添加进度输出
        cmd.extend(['-o', '/dev/null', '-w', 
                    'HTTP%{http_code}\nSize:%{size_upload}\nSpeed:%{speed_upload}\n'])
        
        # 执行上传（带重试）
        attempt = 0
        success = False
        
        while attempt < max_retries and not success:
            if attempt > 0:
                logging.info(f"[上传] 第 {attempt+1}/{max_retries} 次尝试...")
                time.sleep(retry_delay)
            
            start_time = time.time()
            result = subprocess.run(cmd, capture_output=True, text=True)
            elapsed = time.time() - start_time
            
            if result.returncode == 0:
                # 解析 curl 输出
                http_code = None
                uploaded_size = file_size
                speed = 0
                
                for line in result.stderr.split('\n'):
                    if 'HTTP' in line:
                        try:
                            http_code = int(line.replace('HTTP', '').strip())
                        except:
                            pass
                    if 'Speed:' in line:
                        try:
                            speed_str = line.split(':')[1].strip()
                            speed = int(speed_str) if speed_str.isdigit() else 0
                        except:
                            pass
                
                # 验证上传成功
                if http_code in [200, 201, 204]:
                    success = True
                    avg_speed = file_size / elapsed if elapsed > 0 else 0
                    logging.info(f"[上传] 成功: {filename} (平均速度: {format_speed(avg_speed)})")
                    mark_processed(mkv_path, 'upload')
                    clear_upload_progress(mkv_path)
                    count += 1
                    
                    if upload_cfg['delete_after_upload']:
                        os.remove(mkv_path)
                        logging.info(f"[上传] 已删除本地文件: {mkv_path}")
                else:
                    logging.warning(f"[上传] 可能失败，HTTP 状态: {http_code}")
                    attempt += 1
            else:
                logging.error(f"[上传] 失败: {result.stderr[:200]}")
                
                # 保存进度（如果支持断点续传）
                if resume_enabled:
                    # 尝试获取已上传大小（通过检查远程文件）
                    check_cmd = [
                        'curl', '-I', remote_url,
                        '--user', f"{upload_cfg['webdav_user']}:{upload_cfg['webdav_pass']}",
                        '-f', '-s'
                    ]
                    check_result = subprocess.run(check_cmd, capture_output=True, text=True)
                    remote_size = 0
                    for line in check_result.stdout.split('\n'):
                        if 'Content-Length:' in line:
                            try:
                                remote_size = int(line.split(':')[1].strip())
                            except:
                                pass
                    
                    if remote_size > 0:
                        save_upload_progress(mkv_path, remote_url, remote_size, file_size)
                        logging.info(f"[上传] 已保存进度: {format_size(remote_size)}/{format_size(file_size)}")
                    
                    retry_count = increment_retry_count(mkv_path)
                    if retry_count >= max_retries:
                        logging.error(f"[上传] 超过最大重试次数 ({max_retries})，放弃上传")
                        clear_upload_progress(mkv_path)
                        break
                
                attempt += 1
        
        if not success:
            logging.error(f"[上传] 最终失败: {filename}")
    
    return count


def main():
    config = load_config()
    log_file = setup_logging(config.get('logging'))
    
    logging.info("="*50)
    logging.info("小米摄像头视频流水线 v1.2.2")
    logging.info("="*50)
    
    init_db()
    
    logging.info(f"配置: {CONFIG_FILE}")
    logging.info(f"数据: {STATE_DB}")
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
