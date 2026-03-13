#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Local file cleanup script
Used to manually clean up expired MKV files and free disk space

Usage:
    python cleanup.py [options]

Options:
    --dry-run    Only show files to be deleted, do not actually delete
    --days N     Specify retention days (default 7 days)
    --force      Force deletion without checking upload status
    --help       Show help information
"""

import os
import sys
import argparse
import sqlite3
from datetime import datetime, timedelta

# Default configuration
DEFAULT_OUTPUT_DIR = '/output'
DEFAULT_RETAIN_DAYS = 7
DEFAULT_MIN_FREE_GB = 50
STATE_DB = os.getenv('STATE_DB', '/app/data/pipeline.db')


def get_disk_free_gb(path):
    """Get free disk space of the specified path (GB)"""
    try:
        stat = os.statvfs(path)
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
        return free_gb
    except OSError:
        return None


def is_processed(path, stage):
    """Check if file has been processed"""
    if not os.path.exists(STATE_DB):
        return False
    
    try:
        conn = sqlite3.connect(STATE_DB)
        c = conn.cursor()
        c.execute('SELECT 1 FROM processed WHERE path=? AND stage=?', (path, stage))
        result = c.fetchone()
        conn.close()
        return result is not None
    except sqlite3.Error:
        return False


def format_size(size_bytes):
    """Format file size display"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def cleanup(output_dir, retain_days, dry_run=False, force=False):
    """Clean up local old files"""
    print(f"Cleanup directory: {output_dir}")
    print(f"Retention days: {retain_days} days")
    print(f"Mode: {'Preview mode (dry-run)' if dry_run else 'Actual deletion'}")
    print(f"Force mode: {'Yes (do not check upload status)' if force else 'No (only delete uploaded files)'}")
    print("-" * 60)
    
    if not os.path.exists(output_dir):
        print(f"Error: Directory does not exist: {output_dir}")
        return 1
    
    # Collect all MKV files
    mkv_files = []
    for root, _, files in os.walk(output_dir):
        for f in files:
            if f.lower().endswith('.mkv'):
                filepath = os.path.join(root, f)
                try:
                    stat = os.stat(filepath)
                    mkv_files.append({
                        'path': filepath,
                        'name': f,
                        'mtime': stat.st_mtime,
                        'size': stat.st_size,
                        'uploaded': is_processed(filepath, 'upload')
                    })
                except OSError:
                    continue
    
    if not mkv_files:
        print("No MKV files found")
        return 0
    
    # Sort by modification time
    mkv_files.sort(key=lambda x: x['mtime'])
    
    cutoff_time = datetime.now().timestamp() - (retain_days * 86400)
    total_size = sum(f['size'] for f in mkv_files)
    
    print(f"\nFound {len(mkv_files)} MKV files, total {format_size(total_size)}")
    print()
    
    to_delete = []
    keep = []
    
    for file_info in mkv_files:
        age_days = (datetime.now().timestamp() - file_info['mtime']) / 86400
        expired = file_info['mtime'] < cutoff_time
        can_delete = force or file_info['uploaded']
        
        status = []
        if file_info['uploaded']:
            status.append("uploaded")
        else:
            status.append("not uploaded")
        if expired:
            status.append("expired")
        else:
            status.append("within retention")
        
        if expired and can_delete:
            to_delete.append(file_info)
            action = "[DELETE]"
        else:
            keep.append(file_info)
            action = "[KEEP]"
        
        print(f"{action} {file_info['name']}")
        print(f"       Size: {format_size(file_info['size'])}, Age: {age_days:.1f} days")
        print(f"       Status: {', '.join(status)}")
        print()
    
    # Show statistics
    print("-" * 60)
    print(f"To delete: {len(to_delete)} files, {format_size(sum(f['size'] for f in to_delete))}")
    print(f"Keep:      {len(keep)} files, {format_size(sum(f['size'] for f in keep))}")
    
    # Show disk space
    free_gb = get_disk_free_gb(output_dir)
    if free_gb is not None:
        print(f"Free disk space: {free_gb:.1f} GB")
    print()
    
    if dry_run:
        print("Preview mode completed, no files were deleted")
        return 0
    
    if not to_delete:
        print("No files to delete")
        return 0
    
    # Confirm deletion
    if not force:
        confirm = input(f"Confirm deletion of {len(to_delete)} files? [y/N]: ").strip().lower()
        if confirm != 'y':
            print("Cancelled")
            return 0
    
    # Execute deletion
    deleted_count = 0
    deleted_size = 0
    failed = []
    
    for file_info in to_delete:
        try:
            os.remove(file_info['path'])
            deleted_count += 1
            deleted_size += file_info['size']
            print(f"Deleted: {file_info['name']}")
        except OSError as e:
            failed.append((file_info['name'], str(e)))
            print(f"Delete failed: {file_info['name']} - {e}")
    
    print()
    print("-" * 60)
    print(f"Cleanup completed: Successfully deleted {deleted_count} files, freed {format_size(deleted_size)}")
    if failed:
        print(f"Failed: {len(failed)} files")
    
    # Show disk space after cleanup
    free_gb = get_disk_free_gb(output_dir)
    if free_gb is not None:
        print(f"Free disk space: {free_gb:.1f} GB")
    
    return 0


def main():
    parser = argparse.ArgumentParser(
        description='Clean up local MKV video files and free disk space',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python cleanup.py                    # Default cleanup, keep 7 days
    python cleanup.py --dry-run          # Preview mode, see what will be deleted
    python cleanup.py --days 3           # Keep only 3 days
    python cleanup.py --force            # Force deletion without checking upload status
        """
    )
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview mode, do not actually delete files')
    parser.add_argument('--days', type=int, default=DEFAULT_RETAIN_DAYS,
                        help=f'Retention days (default {DEFAULT_RETAIN_DAYS} days)')
    parser.add_argument('--force', action='store_true',
                        help='Force deletion without checking upload status')
    parser.add_argument('--output-dir', default=DEFAULT_OUTPUT_DIR,
                        help=f'Output directory (default {DEFAULT_OUTPUT_DIR})')
    
    args = parser.parse_args()
    
    return cleanup(args.output_dir, args.days, args.dry_run, args.force)


if __name__ == '__main__':
    sys.exit(main())
