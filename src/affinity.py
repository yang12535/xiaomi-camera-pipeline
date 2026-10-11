#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CPU 核心分配工具（仅标准库，Linux 生效，其他平台优雅降级为空操作）"""

import os


def parse_core_list(spec):
    """解析核心列表表达式，如 "0-3,6" -> [0, 1, 2, 3, 6]

    非法输入抛出 ValueError。
    """
    cores = set()
    for part in str(spec).split(','):
        part = part.strip()
        if not part:
            raise ValueError(f"非法核心列表表达式: {spec!r}")
        if '-' in part:
            bounds = part.split('-')
            if len(bounds) != 2:
                raise ValueError(f"非法核心范围: {part!r}")
            try:
                start, end = int(bounds[0]), int(bounds[1])
            except ValueError:
                raise ValueError(f"非法核心编号: {part!r}")
            if start < 0 or end < start:
                raise ValueError(f"非法核心范围: {part!r}")
            cores.update(range(start, end + 1))
        else:
            try:
                core = int(part)
            except ValueError:
                raise ValueError(f"非法核心编号: {part!r}")
            if core < 0:
                raise ValueError(f"非法核心编号: {part!r}")
            cores.add(core)
    return sorted(cores)


def resolve_allowed_cores(perf_cfg):
    """根据 performance 配置解析允许使用的核心列表（升序）

    以 os.sched_getaffinity(0) 为基础（容器 cpuset 感知）：
    - core_list 非空时与允许集合取交集；
    - 否则 cores > 0 时取前 cores 个；
    - cores = 0 且 core_list 为空时返回全部允许核心。
    平台不支持 sched_getaffinity 时返回 []。
    """
    if not hasattr(os, 'sched_getaffinity'):
        return []

    allowed = sorted(os.sched_getaffinity(0))

    core_list = str(perf_cfg.get('core_list') or '').strip()
    if core_list:
        try:
            requested = set(parse_core_list(core_list))
        except ValueError as e:
            import logging
            logging.warning(f"[性能] core_list 配置无效，忽略: {e}")
            return allowed
        return sorted(set(allowed) & requested)

    cores = int(perf_cfg.get('cores') or 0)
    if cores > 0:
        return allowed[:cores]

    return allowed


def allocate_core_pools(cores, n_workers):
    """把核心列表尽量均匀切成 n_workers 片，返回 list[set]

    cores 为空时返回 []。
    """
    if not cores:
        return []
    n_workers = max(1, int(n_workers))
    pools = [[] for _ in range(n_workers)]
    for idx, core in enumerate(cores):
        pools[idx % n_workers].append(core)
    return [set(pool) for pool in pools if pool]


def make_bind_fn(core_set):
    """返回可作为 subprocess preexec_fn 的绑定函数

    将子进程绑定到 core_set；平台不支持 sched_setaffinity 时返回 None。
    """
    if not core_set or not hasattr(os, 'sched_setaffinity'):
        return None

    def _bind():
        os.sched_setaffinity(0, core_set)

    return _bind
