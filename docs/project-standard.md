# Project Standard Documentation

## Project Information

| Item | Content |
|------|---------|
| Name | xiaomi-camera-pipeline |
| Version | v1.2.1 |
| License | AGPL-3.0 |
| Python Version | 3.8+ |

## Encoding Standard

### UTF-8 Standardization

Project uses unified UTF-8 encoding to ensure Windows/Linux compatibility:

#### Python Files
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
```

#### Environment Configuration
- **Windows**: Force `zh_CN.UTF-8`
- **Linux/Docker**: Use `en_US.UTF-8`
- **Python**: `PYTHONIOENCODING=utf-8`

#### Docker Configuration
```dockerfile
ENV LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    PYTHONIOENCODING=utf-8
```

### Code Style

- Follow PEP 8 specification
- Functions and variables use snake_case
- Constants use UPPER_CASE
- Classes use CamelCase

## Directory Structure

```
pipeline/
├── pipeline.py          # Main program entry
├── cleanup.py           # Local cleanup tool
├── config.yaml          # Configuration file template
├── docker-compose.yml   # Docker Compose configuration
├── Dockerfile           # Docker build file
├── deploy.sh            # Deployment script
├── requirements.txt     # Python dependencies
├── docs/                # Documentation directory
│   ├── webdav-setup-guide.md
│   └── project-standard.md
├── data/                # Data directory (SQLite database)
├── temp/                # Temp files (merge intermediate files)
├── output/              # Output directory (compressed MKV)
└── logs/                # Log directory
```

## Configuration Standard

### Configuration Priority (High to Low)

1. **docker-compose.yml environment variables** (Highest priority)
   ```yaml
   environment:
     - COMPRESS_RESOLUTION=1920x1080
     - COMPRESS_CRF=35
   ```

2. **config.yaml configuration file**
   ```yaml
   compress:
     resolution: "1920x1080"
     crf: 35
   ```

3. **Code defaults** (Lowest priority)

### Default Configuration Standard

| Parameter | Default Value | Description |
|-----------|---------------|-------------|
| Resolution | 1920x1080 | 1080p output |
| CRF | 35 | High compression, suitable for surveillance |
| Threads | 4 | CPU thread count |
| Preset | medium | Encoding speed/quality balance |

## Docker Standard

### Image Build

```dockerfile
FROM jrottenberg/ffmpeg:6.1-ubuntu2204
```

### Port Mapping

- No external ports exposed (Pipeline runs internally)

### Volume Mounts

| Host | Container | Description |
|------|-----------|-------------|
| `/path/to/video` | `/video` | Video source (read-only) |
| `./temp` | `/input` | Merge intermediate files |
| `./output` | `/output` | Compressed files |
| `./logs` | `/logs` | Log files |
| `./data` | `/app/data` | SQLite database |

### Resource Limits

```yaml
deploy:
  resources:
    limits:
      cpus: "4"
      memory: 2G
```

## Log Standard

### Log Format
```
%(asctime)s - %(levelname)s - %(message)s
```

### Log Levels
- DEBUG: Debug information
- INFO: General information (default)
- WARNING: Warnings
- ERROR: Errors

### Log Files
- Location: `/logs/pipeline.log`
- Retention: 30 days

## Database Standard

### SQLite
- File: `/app/data/pipeline.db`
- Table: `processed`
- Fields: `path`, `stage`, `timestamp`

### Status Definitions
- `merge`: Merged
- `compress`: Compressed
- `upload`: Uploaded

## Version Management

### Version Number Rules
Follow [SemVer](https://semver.org/lang/zh-CN/):

```
MAJOR.MINOR.PATCH
```

- **MAJOR**: Incompatible API changes
- **MINOR**: Backward-compatible functionality additions
- **PATCH**: Backward-compatible bug fixes

### Version Record
See [CHANGELOG.md](../CHANGELOG.md)

## Submit Standard

### Commit Message Format
```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type Types
- feat: New feature
- fix: Bug fix
- docs: Documentation
- style: Format
- refactor: Refactoring
- test: Test
- chore: Build/tool

### Example
```
feat(upload): add WebDAV date-based directory structure

- Auto create year/month/day directories
- Support recursive MKCOL for nested paths

Closes #123
```

## Document Standard

### File Naming
- Use lowercase letters
- Use hyphens between words
- English preferred

### Examples
- `webdav-setup-guide.md`
- `project-standard.md`

## Dependency Management

### Python Dependencies
```
PyYAML>=5.4.1
```

### System Dependencies
- FFmpeg 6.1+
- Python 3.8+
- SQLite 3

## Security Standard

### Sensitive Information
- Passwords and other sensitive information passed through environment variables
- Configuration files not uploaded to version control
- Database files backed up regularly

### Permission Control
- Video source directory mounted read-only
- Non-root user in container (if tc rate limiting not needed)

## Test Standard

### Test Types
- Unit tests (to be added)
- Integration tests (to be added)
- Manual tests

### Test Checklist
- [ ] Merge function works
- [ ] Compression function works
- [ ] Upload function works
- [ ] Chinese filenames work
- [ ] Log output works
- [ ] Database records work

## Release Process

1. Update version number (code, documentation)
2. Update CHANGELOG.md
3. Tag: `git tag v1.2.1`
4. Build Docker image
5. Push image
6. Create Release

## References

- [PEP 8](https://pep8.org/)
- [SemVer](https://semver.org/lang/zh-CN/)
- [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/)
