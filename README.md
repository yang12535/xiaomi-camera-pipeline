# 小米摄像头视频处理流水线

小米摄像头视频自动化处理流水线：合并 → 压缩 → 上传

## 功能特性

- **合并**：将 1 分钟片段合并为小时级视频
- **压缩**：MOV → MKV (H.265)，节省 50-70% 空间
- **上传**：WebDAV 限速上传，适合夜间低带宽运行
- **断点续传**：SQLite 状态数据库，避免重复处理
- **稳定性保障**：临时文件机制、多重验证、时长检查

## 引用项目

本项目整合自以下开源项目：

- **合并功能**：[hslr-s/xiaomi-camera-merge](https://github.com/hslr-s/xiaomi-camera-merge) - Go 语言编写的小米摄像头视频合并工具
- **压缩功能**：[yang12535/xiaomi-compress](https://github.com/yang12535/xiaomi-compress) - H.265 视频压缩脚本

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

### 本地运行

```bash
# 1. 安装依赖
pip install pyyaml

# 2. 配置
cp config.yaml.example config.yaml
# 编辑 config.yaml

# 3. 运行
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
# config.yaml 或 docker-compose 环境变量
resolution: "original"     # 保持原始分辨率，不缩放
resolution: "1920x1080"    # 强制缩放到 1920x1080
resolution: "-2:1080"      # 高度固定 1080，宽度自动等比
resolution: "1920:-2"      # 宽度固定 1920，高度自动等比
```

docker-compose 中直接修改环境变量：
```yaml
environment:
  - COMPRESS_RESOLUTION=-2:1080  # 等高压缩
```

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
0 2 * * * cd /path/to/xiaomi-camera-pipeline && docker-compose up
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
| `COMPRESS_RESOLUTION` | - | 覆盖分辨率设置 |
| `COMPRESS_CRF` | - | 覆盖 CRF 质量设置 |
| `COMPRESS_THREADS` | - | 覆盖线程数设置 |

## 许可证

AGPL-3.0
