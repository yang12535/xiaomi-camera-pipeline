#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据库操作模块"""

import os
import sqlite3
from datetime import datetime

STATE_DB = os.getenv('STATE_DB', '/app/data/pipeline.db')


def init_db():
    """初始化数据库"""
    os.makedirs(os.path.dirname(STATE_DB), exist_ok=True)
    conn = sqlite3.connect(STATE_DB)
    c = conn.cursor()
    
    # 处理记录
    c.execute('''CREATE TABLE IF NOT EXISTS processed
                 (path TEXT, stage TEXT, timestamp TEXT,
                  PRIMARY KEY (path, stage))''')
    
    # 上传进度（断点续传）
    c.execute('''CREATE TABLE IF NOT EXISTS upload_progress
                 (file_path TEXT PRIMARY KEY, remote_url TEXT, uploaded_size INTEGER, 
                  total_size INTEGER, last_try TEXT, retry_count INTEGER DEFAULT 0)''')
    
    conn.commit()
    conn.close()


def is_processed(path, stage):
    """检查是否已处理"""
    conn = sqlite3.connect(STATE_DB)
    c = conn.cursor()
    c.execute('SELECT 1 FROM processed WHERE path=? AND stage=?', (path, stage))
    result = c.fetchone()
    conn.close()
    return result is not None


def mark_processed(path, stage):
    """标记为已处理"""
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
    """清除上传进度"""
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
