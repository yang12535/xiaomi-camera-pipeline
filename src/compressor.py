#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频压缩模块"""

import os
import subprocess
import logging
from concurrent.futures import ThreadPoolExecutor

from .database import is_processed, mark_processed
from .utils import verify_video, get_video_duration
from .affinity import resolve_allowed_cores, allocate_core_pools, make_bind_fn, parse_core_list


def _format_core_set(core_set):
    """把核心集合格式化为紧凑表达式，如 {0,1,2,3,6} -> "0-3,6" """
    cores = sorted(core_set)
    if not cores:
        return ''
    parts = []
    start = prev = cores[0]
    for core in cores[1:]:
        if core == prev + 1:
            prev = core
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = core
    parts.append(str(start) if start == prev else f"{start}-{prev}")
    return ','.join(parts)


def _compress_one(mov_path, compress_cfg, input_dir, output_dir, core_pool, threads_override=None):
    """压缩单个 MOV 为 MKV (H.265)，成功返回 1，失败返回 0

    -threads 取值优先级：绑核核心数 > threads_override（cores/parallel 派生）> compress.threads。
    core_pool 非空时通过 preexec_fn 绑定核心。
    """
    rel_path = os.path.relpath(mov_path, input_dir)

    out_path = os.path.join(output_dir, rel_path.replace('.mov', '.mkv'))
    temp_path = out_path.replace('.mkv', '.tmp.mkv')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    if os.path.exists(out_path):
        existing_size = os.path.getsize(out_path)
        if existing_size > 1048576 and verify_video(out_path):
            logging.info(f"[压缩] 跳过已存在 {rel_path}")
            mark_processed(mov_path, 'compress')
            return 1
        else:
            logging.warning(f"[压缩] 删除无效旧文件 {rel_path}")
            os.remove(out_path)

    logging.info(f"[压缩] 开始 {rel_path}")

    threads = threads_override if threads_override else compress_cfg['threads']
    run_kwargs = {}
    if core_pool:
        threads = len(core_pool)
        bind_fn = make_bind_fn(core_pool)
        if bind_fn is not None:
            run_kwargs['preexec_fn'] = bind_fn

    cmd = [
        'ffmpeg', '-y', '-i', mov_path,
        '-c:v', 'libx265', '-crf', str(compress_cfg['crf']),
        '-preset', compress_cfg['preset'],
        '-threads', str(threads),
        '-c:a', 'copy',
        '-tag:v', 'hvc1',
    ]

    resolution = compress_cfg.get('resolution', '1920x1080')
    if resolution and resolution.lower() != 'original':
        scale_vf = resolution.replace('x', ':')
        scale_vf = f"{scale_vf}:force_original_aspect_ratio=decrease"
        cmd.extend(['-vf', f'scale={scale_vf}'])

    cmd.append(temp_path)

    result = subprocess.run(cmd, capture_output=True, text=True, **run_kwargs)

    if result.returncode == 0 and os.path.exists(temp_path):
        output_size = os.path.getsize(temp_path)

        if output_size < 1048576:
            logging.error(f"[压缩] 失败: 输出文件过小 ({output_size} bytes)")
            os.remove(temp_path)
            return 0

        if not verify_video(temp_path):
            logging.error(f"[压缩] 失败: ffprobe 验证未通过")
            os.remove(temp_path)
            return 0

        input_duration = get_video_duration(mov_path)
        output_duration = get_video_duration(temp_path)

        if input_duration is not None and output_duration is not None:
            duration_diff = abs(input_duration - output_duration)
            if duration_diff > 30:
                logging.error(f"[压缩] 失败: 时长差异过大 ({duration_diff:.1f}s > 30s)")
                os.remove(temp_path)
                return 0
            logging.info(f"[压缩] 时长检查通过: 差异={duration_diff:.1f}s")

        try:
            os.rename(temp_path, out_path)
        except OSError as e:
            logging.error(f"[压缩] 失败: 重命名文件出错 - {e}")
            os.remove(temp_path)
            return 0

        if os.path.exists(out_path):
            logging.info(f"[压缩] 成功: {rel_path} ({output_size / 1024 / 1024:.1f} MB)")
            mark_processed(mov_path, 'compress')

            if compress_cfg['delete_source']:
                try:
                    os.remove(mov_path)
                    logging.info(f"[压缩] 已清理源文件: {rel_path}")
                except OSError as e:
                    logging.error(f"[压缩] 警告: 无法删除源文件 - {e}")
            return 1
        else:
            logging.error(f"[压缩] 失败: 最终文件不存在")
            return 0
    else:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        logging.error(f"[压缩] 失败: ffmpeg 退出码 {result.returncode}")
        if result.stderr:
            logging.error(f"[压缩] 错误: {result.stderr[:300]}")
        return 0


def compress_videos(config):
    """压缩 MOV 为 MKV (H.265)，支持 performance 配置的并行与绑核"""
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

    # 提交任务前统一过滤已处理文件
    mov_files = [p for p in mov_files if not is_processed(p, 'compress')]
    if not mov_files:
        return 0

    perf_cfg = config.get('performance', {})
    parallel = int(perf_cfg.get('parallel') or 1)
    bind = bool(perf_cfg.get('bind'))

    # 派生每任务线程数：core_list 非空按其长度，否则按 cores；统一 cores/parallel
    eff_cores = 0
    core_list = str(perf_cfg.get('core_list') or '').strip()
    if core_list:
        try:
            eff_cores = len(parse_core_list(core_list))
        except ValueError:
            eff_cores = 0
    if eff_cores == 0:
        eff_cores = int(perf_cfg.get('cores') or 0)
    threads_override = max(1, eff_cores // max(1, parallel)) if eff_cores > 0 else None

    # 核心池生效条件：bind 开启且分配结果非空
    n_workers = parallel if parallel > 1 else 1
    pools = []
    if bind:
        pools = allocate_core_pools(resolve_allowed_cores(perf_cfg), n_workers)

    if parallel <= 1:
        # 串行模式（旧行为），bind=true 时单 worker 拿整段核心池
        core_pool = pools[0] if pools else None
        count = 0
        for mov_path in mov_files:
            count += _compress_one(mov_path, compress_cfg, input_dir, output_dir, core_pool, threads_override)
        return count

    if pools:
        bind_desc = ' / '.join(_format_core_set(p) for p in pools)
        logging.info(f"[压缩] 并行模式: {parallel} 任务 × {len(pools[0])} 核心 (绑定: {bind_desc})")
    else:
        threads_desc = threads_override or compress_cfg['threads']
        logging.info(f"[压缩] 并行模式: {parallel} 任务 × {threads_desc} 线程 (未绑定核心)")

    count = 0
    with ThreadPoolExecutor(max_workers=parallel) as executor:
        futures = []
        for i, mov_path in enumerate(mov_files):
            # 池数量 == 并行数 == max_workers，取模复用保证并发任务各占一个池、
            # 长队列后续任务不裸奔（取模后并发集合 {k..k+parallel-1} 映射互不重叠）
            core_pool = pools[i % len(pools)] if pools else None
            futures.append(executor.submit(
                _compress_one, mov_path, compress_cfg, input_dir, output_dir, core_pool, threads_override))
        for future in futures:
            try:
                count += future.result()
            except Exception as e:
                logging.error(f"[压缩] 失败: 任务异常 - {e}")

    return count
