#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WebDAV 上传模块"""

import os
import subprocess
import time
import re
import logging
from datetime import datetime
from urllib.parse import quote

from .database import (
    is_processed, mark_processed, get_upload_progress,
    save_upload_progress, clear_upload_progress, increment_retry_count
)
from .utils import format_size, format_speed


def upload_videos(config):
    """带断点续传和进度监控的上传功能"""
    upload_cfg = config['upload']
    if not upload_cfg['enabled']:
        return 0
    
    date_path = datetime.now().strftime('%Y/%m/%d')
    
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
        
        cmd = [
            'curl', '-T', mkv_path, remote_url,
            '--user', f"{upload_cfg['webdav_user']}:{upload_cfg['webdav_pass']}",
            '--limit-rate', upload_cfg['rate_limit'],
            '-f', '-S',
            '--connect-timeout', '30',
            '--max-time', '0',
        ]
        
        if resume_enabled and progress and progress['uploaded'] > 0:
            cmd.extend(['-C', '-'])
            logging.info(f"[上传] 启用断点续传，从 {format_size(progress['uploaded'])} 继续")
        
        cmd.extend(['-o', '/dev/null', '-w',
                    'HTTP%{http_code}\nSize:%{size_upload}\nSpeed:%{speed_upload}\n'])
        
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
                
                if resume_enabled:
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
