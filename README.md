# 小米摄像头视频处理流水线

小米摄像头视频自动化处理流水线：合并 → 压缩 → 上传

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-Supported-blue.svg)](https://docker.com)
[![License](https://img.shields.io/badge/License-AGPL--3.0-green.svg)](LICENSE)

## 功能特性

- **合并**：将 1 分钟片段合并为小时级视频
- **压缩**：MOV → MKV (H.265)，节省 50-70% 空间
- **上传**：WebDAV 限速上传，适合夜间低带宽运行
- **本地清理**：自动清理已上传的旧文件，释放磁盘空间
- **断点续传**：SQLite 状态数据库，避免重复处理
- **稳定性保障**：临时文件机制、多重验证、时长检查
- **编码兼容**：支持 Windows 机房环境和 Docker 容器

## 引用项目

本项目整合自以下开源项目：

- **合并功能**：[hslr-s/xiaomi-camera-merge](https://github.com/hslr-s/xiaomi-camera-merge) - Go 语言编写的小米摄像头视频合并工具
- **压缩功能**：[yang12535/xiaomi-compress](https://github.com/yang12535/xiaomi-compress) - H.265 视频压缩脚本

## 文档

- [WebDAV 配置指南](docs/webdav-setup-guide.md) - WebDAV 配置和限速指南
- [项目标准化文档](docs/project-standard.md) - 编码规范、配置优先级、版本管理等
- [CHANGELOG](CHANGELOG.md) - 版本历史
- [DEPLOY_LOG](DEPLOY_LOG.md) - 部署日志和故障排查

## 快速开始

### Docker 部署（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/yang12535/xiaomi-camera-pipeline.git
cd xiaomi-camera-pipeline

# 2. 配置
cp config.yaml.example config.yaml
# 编辑 config.yaml，设置 WebDAV 等参数

# 3. 启动
docker-compose up -d

# 4. 查看日志
docker-compose logs -f
```

### Windows 本地运行（机房环境）

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 下载 FFmpeg
# 下载地址: https://github.com/BtbN/FFmpeg-Builds/releases
# 解压后将 bin 目录添加到系统 PATH

# 3. 配置
cp config.yaml.example config.yaml
# 编辑 config.yaml，修改目录路径为 Windows 格式

# 4. 运行
python pipeline.py
```

### Linux/macOS 本地运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 确保 FFmpeg 已安装
ffmpeg -version

# 3. 配置并运行
cp config.yaml.example config.yaml
# 编辑 config.yaml
python pipeline.py
```

## 目录映射

| 宿主机路径 | 容器路径 | 说明 |
|-----------|---------|------|
| `/path/to/xiaomi/video` | `/video` | 小米摄像头原始视频（只读） |
| `./input` | `/input` | 合并后的 MOV 文件 |
| `./output` | `/output` | 压缩后的 MKV 文件 |
| `./logs` | `/logs` | 日志文件 |

## 分辨率配置

支持多种分辨率设置方式：

```yaml
# config.yaml
resolution: "1920x1080"    # 强制缩放到 1920x1080 (默认)
resolution: "original"     # 保持原始分辨率，不缩放
resolution: "-2:1080"      # 高度固定 1080，宽度自动等比
resolution: "1920:-2"      # 宽度固定 1920，高度自动等比
```

### 配置优先级

Configuration priority from high to low:

1. **docker-compose environment variables** (highest priority)
   ```yaml
   environment:
     - COMPRESS_RESOLUTION=1920x1080
     - COMPRESS_CRF=35
     - COMPRESS_THREADS=4
   ```

2. **config.yaml configuration file**
   ```yaml
   compress:
     resolution: "1920x1080"
     crf: 35
     threads: 4
   ```

3. **Code defaults** (lowest priority)
   - resolution: `1920x1080`
   - crf: `35`
   - threads: `4`

**Recommendation**: Set environment variables in docker-compose.yml, which has the highest priority and is easy to manage.

## 运行模式

### 常驻模式（默认）
每小时自动检查一次新视频：
```yaml
schedule:
  interval: 3600
  run_once: false
```

### Cron 模式
处理完立即退出，适合用系统 cron 调度：
```yaml
schedule:
  run_once: true
```

```bash
# crontab 示例：每天凌晨 2 点运行
0 2 * * * cd /path/to/xiaomi-camera-pipeline && python pipeline.py
```

## 编码与国际化

### Windows 机房环境
Windows 机房常见的还原卡可能导致控制台编码被重置为 GBK。代码已自动检测并处理：

```python
# 代码中自动处理（无需手动配置）
if sys.platform == 'win32':
    os.environ['LC_ALL'] = 'zh_CN.UTF-8'
    # 强制 stdout/stderr 使用 UTF-8
```

### Docker 环境
Dockerfile 已预配置 UTF-8 locale：

```dockerfile
RUN locale-gen zh_CN.UTF-8 en_US.UTF-8 C.UTF-8 \
    && update-locale LANG=C.UTF-8 LC_ALL=C.UTF-8

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=utf-8
```

### 手动设置编码
如果遇到乱码，可以手动设置环境变量：

```bash
# Windows PowerShell
$env:PYTHONIOENCODING="utf-8"
$env:LC_ALL="zh_CN.UTF-8"

# Linux/macOS
export PYTHONIOENCODING=utf-8
export LC_ALL=C.UTF-8
```

## 日志配置

日志同时输出到文件和控制台，日志文件位于 `logs/pipeline.log`。

### 日志级别

通过环境变量设置日志级别：

```bash
# 只显示警告和错误
LOG_LEVEL=WARNING python pipeline.py

# 调试模式（显示详细信息）
LOG_LEVEL=DEBUG python pipeline.py
```

### Docker 日志

```bash
# 查看实时日志
docker-compose logs -f

# 查看最近 100 行
docker-compose logs --tail=100
```

## 本地清理

自动清理 uploaded old files to free disk space:

```bash
# View files to be deleted (preview mode)
python cleanup.py --dry-run

# Execute cleanup (keep 7 days)
python cleanup.py

# Keep only 3 days
python cleanup.py --days 3

# Force deletion (do not check upload status)
python cleanup.py --force
```

**Docker environment:**
```bash
docker exec -it xiaomi-camera-pipeline python3 /app/cleanup.py --dry-run
```

## 稳定性机制

### 合并阶段
1. 生成 concat 列表文件
2. ffmpeg 合并到临时文件 (`.tmp.mov`)
3. ffprobe 验证视频完整性
4. 重命名为最终文件
5. 安全删除源目录

### 压缩阶段
1. ffmpeg 压缩到临时文件 (`.tmp.mkv`)
2. **文件大小检查**：必须 > 1MB
3. **ffprobe 完整性验证**
4. **时长检查**：输入输出差异 ≤ 30 秒
5. 重命名为最终文件
6. 安全删除源文件

### 上传阶段
1. curl 上传文件
2. 验证上传成功
3. 可选删除本地文件

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CONFIG_FILE` | `/app/config.yaml` | 配置文件路径 |
| `STATE_DB` | `/app/pipeline.db` | SQLite 数据库路径 |
| `LOG_DIR` | `/logs` | 日志目录 |
| `LOG_LEVEL` | `INFO` | 日志级别 (DEBUG/INFO/WARNING/ERROR) |
| `COMPRESS_RESOLUTION` | - | 覆盖分辨率设置 |
| `COMPRESS_CRF` | - | 覆盖 CRF 质量设置 |
| `COMPRESS_THREADS` | - | 覆盖线程数设置 |
| `COMPRESS_PRESET` | - | 覆盖编码预设 |

## 故障排除

### 中文乱码

**现象**：日志或控制台显示乱码

**解决**：
1. 确保设置环境变量 `PYTHONIOENCODING=utf-8`
2. Windows 下使用 PowerShell 而非 CMD
3. Docker 环境已预配置，无需处理

### FFmpeg 未找到

**现象**：报错 `ffmpeg not found`

**解决**：
```bash
# 检查 FFmpeg 是否安装
ffmpeg -version

# Windows 下将 FFmpeg bin 目录添加到系统 PATH
```

### 权限问题

**现象**：无法读取视频文件或写入输出目录

**解决**：
```bash
# Docker 下检查目录权限
chmod 755 /path/to/video

# Windows 下以管理员身份运行
```

## 开发

```bash
# 安装开发依赖
pip install -r requirements.txt

# 代码检查
python -m py_compile pipeline.py

# 本地测试
python pipeline.py
```

## 许可证

[AGPL-3.0](LICENSE) © 2026 xiaomi-camera-pipeline contributors
