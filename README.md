# 小米摄像头视频流水线

## v1.2.5 压缩质量优化：默认 CRF 32 平衡模式，遇到问题请先阅读文档，如果没有请issues/PR

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-AGPL--3.0-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-v1.2.5-orange.svg)](VERSION)

> 自动化视频处理流水线：合并 → 压缩 → 上传

✅ **v1.2.5 优化压缩质量** - 默认 CRF 32 + fast 预设，减少花屏同时保持压缩率 - 使用 `scripts/limit-container-bandwidth.sh` 对 OpenList 容器进行出口限速

## 功能特性

- 📹 **视频合并**：将小米摄像头按小时分割的 MP4 片段合并为完整 MOV
- 🗜️ **智能压缩**：H.265 编码，CRF32 平衡模式，可配置分辨率（建议 1080P）
- ☁️ **云端备份**：WebDAV 上传至百度网盘（OpenList/Alist）
- 🔄 **断点续传**：上传中断自动恢复，无需从头开始
- 📊 **进度监控**：实时显示上传速度、已传/剩余大小
- ⏰ **定时轮询**：每小时自动检查新视频
- 🗄️ **状态持久化**：SQLite 数据库记录处理状态

## 系统架构

```
小米摄像头片段 (/video/YYYYMMDDHH/*.mp4)
    ↓
[合并] → 按小时合并为 MOV (/input/YYYY/MM/DD/HH.mov)
    ↓
[压缩] → H.265 压缩为 MKV (/output/YYYY/MM/DD/HH.mkv)
    ↓
[上传] → WebDAV 上传至云端 (百度网盘)
    ↓
[清理] → 删除已上传的本地文件（可选）
```

## 快速开始

### 方式一：使用预构建 Docker 镜像（推荐）

直接从 GitHub Container Registry 拉取，无需克隆：

```bash
# 拉取最新镜像（约 320MB，精简版）
docker pull ghcr.io/yang12535/xiaomi-camera-pipeline:latest
```

```bash
# 创建本地目录
mkdir -p xiaomi-pipeline/{input,output,logs,data}

# 基础运行（仅压缩，不上传）
docker run -d \
  --name xiaomi-camera-pipeline \
  -v $(pwd)/xiaomi-pipeline/input:/video \
  -v $(pwd)/xiaomi-pipeline/output:/output \
  -v $(pwd)/xiaomi-pipeline/logs:/logs \
  -v $(pwd)/xiaomi-pipeline/data:/app/data \
  -e COMPRESS_CRF=32 \
  -e COMPRESS_PRESET=fast \
  -e COMPRESS_THREADS=4 \
  -e TZ=Asia/Shanghai \
  --restart unless-stopped \
  ghcr.io/yang12535/xiaomi-camera-pipeline:latest
```

**完整配置（压缩+上传）：**

```bash
docker run -d \
  --name xiaomi-camera-pipeline \
  -v $(pwd)/xiaomi-pipeline/input:/video \
  -v $(pwd)/xiaomi-pipeline/output:/output \
  -v $(pwd)/xiaomi-pipeline/logs:/logs \
  -v $(pwd)/xiaomi-pipeline/data:/app/data \
  -e COMPRESS_CRF=32 \
  -e COMPRESS_PRESET=fast \
  -e UPLOAD_ENABLED=true \
  -e WEBDAV_URL=http://your-openlist:5244/dav/baidu/视频 \
  -e WEBDAV_USER=admin \
  -e WEBDAV_PASS=your_password \
  -e TZ=Asia/Shanghai \
  --restart unless-stopped \
  ghcr.io/yang12535/xiaomi-camera-pipeline:latest
```

使用自定义配置文件（挂载 config.yaml）：

```bash
docker run -d \
  --name xiaomi-camera-pipeline \
  -v $(pwd)/xiaomi-pipeline/input:/video \
  -v $(pwd)/xiaomi-pipeline/output:/output \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -e TZ=Asia/Shanghai \
  --restart unless-stopped \
  ghcr.io/yang12535/xiaomi-camera-pipeline:latest
```

### 方式二：克隆项目构建

```bash
git clone https://github.com/yang12535/xiaomi-camera-pipeline.git
cd xiaomi-camera-pipeline
```

### 2. 配置

复制配置模板：

```bash
cp config/config.yaml.example config.yaml
```

编辑 `config.yaml`：

```yaml
# 视频源目录（小米摄像头原始视频）
merge:
  source_dir: /path/to/your/video/input
  output_dir: /path/to/your/video/temp
  delete_source: true

# 压缩配置
compress:
  input_dir: /path/to/your/video/temp
  output_dir: /path/to/your/video/output
  crf: 32              # 压缩质量: 28(高质量) / 32(平衡) / 35(高压缩)
  preset: fast          # faster(快) / fast(平衡) / medium(慢但省空间)
  threads: 4           # 编码线程数
  resolution: 1920x1080  # 监控建议 1080P，2K 太奢侈！
  delete_source: true

# 上传配置
upload:
  enabled: true
  webdav_url: http://YOUR_OPENLIST_IP:5246/dav/baidu/视频归档
  webdav_user: admin
  webdav_pass: your_password
  rate_limit: 2M       # 上传限速，避免占满带宽
  delete_after_upload: false
  resume: true         # 断点续传
  max_retries: 3
  retry_delay: 30
```

### 3. 启动

```bash
docker-compose up -d
```

查看日志：

```bash
docker-compose logs -f
```

## 目录映射

| 宿主机路径 | 容器路径 | 说明 |
|-----------|---------|------|
| `/path/to/input` | `/video` | 小米摄像头原始视频 |
| `/path/to/temp` | `/input` | 合并后的 MOV 文件 |
| `/path/to/output` | `/output` | 压缩后的 MKV 文件 |
| `/path/to/log` | `/logs` | 日志文件 |
| `./data` | `/app/data` | 状态数据库 |
| `./config.yaml` | `/app/config.yaml` | 配置文件 |

## 配置说明

### 压缩参数建议

| 使用场景 | resolution | crf | preset | 说明 |
|----------|-----------|-----|--------|------|
| **平衡模式（默认）** | original | 32 | fast | 推荐，质量与体积平衡 |
| 高质量存档 | 1920x1080 | 28 | slow | 重要视频长期保存 |
| 高压缩率 | 1280x720 | 35 | medium | 存储空间有限 |
| 极速处理 | original | 32 | faster | 快速处理大量视频 |

> 💡 **监控场景 1080P 足够**，2K 太奢侈！默认 CRF 32 压缩率约 50-60%，详见[压缩参数调优指南](docs/compression-tuning-guide.md)。

### 环境变量配置（飞牛 Docker 直接配置）

所有配置都支持通过环境变量设置，**优先级高于配置文件**，适合在飞牛 Docker 界面直接配置：

| 环境变量 | 默认值 | 说明 | 示例 |
|---------|--------|------|------|
| **压缩参数** ||||
| `COMPRESS_CRF` | 32 | 压缩质量: 28(高)/32(平衡)/35(压缩) | `32` |
| `COMPRESS_PRESET` | fast | 编码速度: faster/fast/medium | `fast` |
| `COMPRESS_THREADS` | 4 | 编码线程数 | `4` |
| `COMPRESS_RESOLUTION` | original | 分辨率: original/1920x1080/1280x720 | `original` |
| `COMPRESS_DELETE_SOURCE` | true | 压缩后删除源 MOV | `true`/`false` |
| **上传参数** ||||
| `UPLOAD_ENABLED` | false | 是否启用上传 | `true`/`false` |
| `WEBDAV_URL` | - | WebDAV 服务器地址 | `http://ip:5244/dav/baidu/视频` |
| `WEBDAV_USER` | - | WebDAV 用户名 | `admin` |
| `WEBDAV_PASS` | - | WebDAV 密码 | `your_password` |
| `UPLOAD_RATE_LIMIT` | 1M | 上传限速 (0=不限速) | `1M`/`0` |
| `UPLOAD_DELETE_AFTER` | true | 上传后删除本地文件 | `true`/`false` |
| **合并参数** ||||
| `MERGE_INTERVAL` | 60 | 合并间隔（分钟） | `60` |
| `MERGE_DELETE_SOURCE` | true | 合并后删除源片段 | `true`/`false` |
| **系统参数** ||||
| `TZ` | Asia/Shanghai | 时区设置 | `Asia/Shanghai` |
| `LOG_LEVEL` | INFO | 日志级别 | `INFO`/`DEBUG`/`WARNING` |

> ⚠️ **飞牛 WebUI 限制警告**
> 
> 飞牛 Docker 管理界面对环境变量数量有限制，可能无法输入过多变量（如上传相关的 4 个变量）。
> 
> **解决方案：**
> 1. **精简变量**：仅保留 `COMPRESS_CRF`、`COMPRESS_PRESET`、`COMPRESS_THREADS`、`TZ` 等关键变量
> 2. **使用配置文件**：将其他配置写入 `config.yaml` 并挂载到容器
> 3. **命令行启动**：使用 `docker run` 或 `docker-compose` 命令行方式启动

**飞牛 Docker 配置示例（精简版，仅关键变量）：**

```yaml
COMPRESS_CRF=32
COMPRESS_PRESET=fast
COMPRESS_THREADS=4
TZ=Asia/Shanghai
```

**如需上传功能，建议使用配置文件方式：**

挂载 `config.yaml` 到 `/app/config.yaml:ro`，并在其中配置上传参数。

## 断点续传

v1.2.2+ 支持断点续传：

1. **自动保存进度**：上传中断时自动记录已传大小
2. **自动续传**：下次上传时从断点继续
3. **重试机制**：失败自动重试，最多 3 次

进度存储在 `./data/pipeline.db` 中。

## 常见问题

### Q: 上传速度慢？

使用限速脚本对 OpenList 容器进行出口限速：
```bash
# 限速 10Mbps（推荐）
./scripts/limit-container-bandwidth.sh openlist-test 10mbit setup

# 查看限速状态
./scripts/limit-container-bandwidth.sh openlist-test status

# 清除限速
./scripts/limit-container-bandwidth.sh openlist-test clear
```

详见 [docs/bandwidth-limit-guide.md](docs/bandwidth-limit-guide.md)

### Q: 时区不对？

确保 `docker-compose.yml` 设置了时区：
```yaml
environment:
  - TZ=Asia/Shanghai
```

### Q: 如何禁用上传？

```yaml
upload:
  enabled: false
```

### Q: 如何只运行一次？

```yaml
schedule:
  run_once: true
```

## 性能调优

### CPU 限制

```yaml
deploy:
  resources:
    limits:
      cpus: "4"      # 限制 4 核，降低功耗
      memory: 2G
```

### 压缩速度

- `preset: veryfast` - 最快，文件稍大
- `preset: medium` - 平衡（推荐）
- `preset: slow` - 最慢，文件最小

### 上传限速

```yaml
upload:
  rate_limit: 2M     # 2MB/s，避免影响其他设备上网
```

## 版本历史

详见 [CHANGELOG.md](CHANGELOG.md)

## 许可证

AGPL-3.0 License
