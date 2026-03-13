#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频合并模块"""

import os
import subprocess
import shutil
import logging

from .database import is_processed, mark_processed
from .utils import verify_video, get_video_dirs


def merge_videos(config):
    """合并 MP4 片段为 MOV"""
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
                logging.warning(f"[合并] 删除无效旧文件 {out_file}")
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
                        logging.error(f"[合并] 失败: 重命名出错 - {e}")
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
