# Optimization Documentation v1.2.1

## Overview

Based on deployment logs of GitHub 1.1 version and local 1.2 version, comprehensive optimization was performed to resolve discovered issues and enhance robustness.

---

## 1. UTF-8 Standardization

### Issues Fixed

| Issue | Cause | Solution |
|-------|-------|----------|
| Chinese garbled characters on Windows | Console encoding reset to GBK by restore card | Force zh_CN.UTF-8 + io.TextIOWrapper |
| Locale compatibility issues on Linux | Some Ubuntu versions don't support C.UTF-8 | Unified use of en_US.UTF-8 |
| Full-width character confusion | Mixed use of full-width and half-width punctuation | Unified replacement with half-width characters |
| Line ending confusion | CRLF and LF mixed | Unified use of LF |

### Implementation Details

**Python files:**
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Windows: Force UTF-8
if sys.platform == 'win32':
    os.environ['LC_ALL'] = 'zh_CN.UTF-8'
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Linux/Docker: Use en_US.UTF-8
else:
    os.environ.setdefault('LC_ALL', 'en_US.UTF-8')
```

**Dockerfile:**
```dockerfile
ENV LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    PYTHONIOENCODING=utf-8
```

---

## 2. Dockerfile Optimization

### Improvements

| Issue | Before | After |
|-------|--------|-------|
| Slow apt sources | Official Ubuntu sources | Alibaba Cloud mirror |
| Locale compatibility | C.UTF-8 | en_US.UTF-8 |
| ENTRYPOINT conflict | jrottenberg/ffmpeg default ENTRYPOINT | Clear ENTRYPOINT |
| Missing locales package | Not installed | Added installation |

---

## 3. docker-compose.yml Optimization

### Improvements

| Issue | Before | After |
|-------|--------|-------|
| Version warning | version: "3.8" | Removed version line |
| Database file mount failure | File mount ./pipeline.db | Directory mount ./data |
| Personal paths | /vol2/1000/2/... | Generic paths /path/to/... |
| Missing comments | Unclear configuration items | Detailed comments added |

---

## 4. pipeline.py Optimization

### Code Quality

**Clean up duplicate imports:**
```python
# Before
import urllib.parse
import os
import urllib.parse      # Duplicate
import sys
import urllib.parse      # Duplicate

# After
import os
import sys
from urllib.parse import quote
```

**Enhanced error handling:**
- Database operations: Added try-except
- File operations: Added try-except
- Network requests: Added timeout and exception handling

**Improved configuration loading:**
```python
# Environment variable mapping with type conversion
env_mappings = {
    'COMPRESS_RESOLUTION': ('compress', 'resolution'),
    'COMPRESS_CRF': ('compress', 'crf', int),
    'COMPRESS_THREADS': ('compress', 'threads', int),
}
```

### New Features

**Local cleanup function:**
- Automatic cleanup of uploaded old files
- Disk space monitoring
- Manual cleanup script support

---

## 5. Configuration Priority

Priority from high to low:

1. **docker-compose.yml environment variables** (highest)
2. **config.yaml configuration file**
3. **Code defaults** (lowest)

Recommended configuration in docker-compose.yml:
```yaml
environment:
  - COMPRESS_RESOLUTION=1920x1080
  - COMPRESS_CRF=35
  - COMPRESS_THREADS=4
```

---

## 6. Default Configuration Changes

| Parameter | Before | After |
|-----------|--------|-------|
| Resolution | original | 1920x1080 |
| CRF | 32 | 35 |
| Threads | 8 | 4 |
| CPU limit | 8 cores | 4 cores |

---

## 7. Deployment Log Issue Fixes

| # | Issue | Status | Fix Method |
|---|-------|--------|------------|
| 1 | Docker image build slow (apt sources) | Fixed | Use Alibaba Cloud mirror |
| 2 | FFmpeg base image ENTRYPOINT conflict | Fixed | Clear ENTRYPOINT |
| 3 | SQLite database file mount failure | Fixed | Use directory mount |
| 4 | SQL syntax error | Fixed | Fix quote mismatch |
| 5 | Locale configuration compatibility | Fixed | Use en_US.UTF-8 |
| 6 | docker-compose version warning | Fixed | Remove version line |
| 7 | Upload not enabled | Fixed | Add enabled: true |
| 8 | Configuration item name mismatch | Fixed | Unified to webdav_* |
| 9 | Chinese path URL encoding | Fixed | Use urllib.parse.quote |
| 10 | WebDAV IP configuration error | Fixed | Correct to actual IP |

---

## 8. New Cleanup Function

### Automatic Cleanup (pipeline.py built-in)

Configuration in config.yaml:
```yaml
cleanup:
  enabled: true
  retain_days: 7      # Keep uploaded files for 7 days
  min_free_gb: 50     # Force cleanup when disk below 50GB
```

Cleanup strategy:
1. Delete uploaded MKV files exceeding retain_days
2. If disk space below min_free_gb, force delete oldest uploaded files

### Manual Cleanup Script (cleanup.py)

```bash
# Preview mode (view files to be deleted)
python cleanup.py --dry-run

# Default cleanup (keep 7 days)
python cleanup.py

# Keep only 3 days
python cleanup.py --days 3

# Force deletion (do not check upload status)
python cleanup.py --force
```

---

## 9. File Structure

```
xiaomi-camera-pipeline-v1.2.1/
├── pipeline/
│   ├── pipeline.py              # Main program
│   ├── cleanup.py               # Cleanup script
│   ├── config.yaml              # Configuration
│   ├── docker-compose.yml       # Docker Compose config
│   ├── Dockerfile               # Docker build file
│   ├── deploy.sh                # Deploy script
│   ├── requirements.txt         # Python dependencies
│   ├── docs/                    # Documentation
│   │   ├── webdav-setup-guide.md
│   │   └── project-standard.md
│   └── ...
```

---

## 10. To-Do

- [ ] Add unit tests
- [ ] Implement WebDAV upload failure retry mechanism
- [ ] Add Prometheus monitoring metrics
- [ ] Implement Web interface to view processing status
