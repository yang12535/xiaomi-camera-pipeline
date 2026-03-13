#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频压缩模块"""

import os
import subprocess
import logging

from .database import is_processed, mark_processed
from .utils import verify_video, get_video_duration


def compress_videos(config):
    """压缩 MOV 为 MKV (H.265)"""
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
                logging.info(f"[压缩] 跳过已存在 {rel_path}")
                mark_processed(mov_path, 'compress')
                count += 1
                continue
            else:
                logging.warning(f"[压缩] 删除无效旧文件 {rel_path}")
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
                logging.error(f"[压缩] 失败: 重命名文件出错 - {e}")
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
                        logging.error(f"[压缩] 警告: 无法删除源文件 - {e}")
            else:
                logging.error(f"[压缩] 失败: 最终文件不存在")
        else:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            logging.error(f"[压缩] 失败: ffmpeg 退出码 {result.returncode}")
            if result.stderr:
                logging.error(f"[压缩] 错误: {result.stderr[:300]}")
    
    return count
