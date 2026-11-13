#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""流水线运行状态

供主循环写入、WebUI 线程读取的轻量状态容器：
- update(**fields)  就地更新字段（加锁）
- snapshot()        返回独立 dict，调用方修改不会影响内部状态
"""

import threading
from copy import deepcopy

PHASES = frozenset({
    'starting', 'merging', 'compressing', 'uploading',
    'backlog', 'waiting', 'stopped',
})


class RuntimeState:
    """线程安全的运行状态"""

    def __init__(self):
        self._lock = threading.Lock()
        self._state = {
            'phase': 'starting',
            'running': False,
            'current_run_started_at': None,
            'last_run': None,
            'next_run_at': None,
        }

    def update(self, **fields):
        """更新状态字段"""
        if 'phase' in fields and fields['phase'] not in PHASES:
            raise ValueError(f"无效的 phase: {fields['phase']!r}")
        with self._lock:
            self._state.update(fields)

    def snapshot(self):
        """返回状态快照（深拷贝，last_run 等嵌套结构不与内部共享）"""
        with self._lock:
            return deepcopy(self._state)
