# 小米摄像头视频流水线

[![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/License-AGPL--3.0-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/Version-v1.2.2-orange.svg)](VERSION)

> 自动化视频处理流水线：合并 → 压缩 → ~~上传~~（上传功能暂不可用，网络限速调试中）

## 功能特性

- 📹 **视频合并**：将小米摄像头按小时分割的 MP4 片段合并为完整 MOV
- 🗜️ **智能压缩**：H.265 编码，CRF35，可配置分辨率（建议 1080P）
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

### 1. 克隆项目

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
  crf: 35              # 压缩质量，监控场景建议 35-40
  preset: medium       # veryfast(快) / medium(平衡) / slow(小文件)
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

| 场景 | resolution | crf | preset | 说明 |
|------|-----------|-----|--------|------|
| 快速处理 | 1920x1080 | 35 | veryfast | 推荐，CPU 占用低 |
| 平衡质量 | 1920x1080 | 35 | medium | 当前配置 |
| 极致压缩 | 1280x720 | 40 | slow | 文件最小 |

> 💡 **监控场景 1080P 足够**，2K 太奢侈！CRF35 压缩率约 60-70%。

### 环境变量覆盖

环境变量优先级高于配置文件：

```yaml
environment:
  - COMPRESS_RESOLUTION=1920x1080
  - COMPRESS_CRF=35
  - COMPRESS_THREADS=4
  - COMPRESS_PRESET=medium
  - TZ=Asia/Shanghai      # 时区设置（重要！）
```

## 断点续传

v1.2.2+ 支持断点续传：

1. **自动保存进度**：上传中断时自动记录已传大小
2. **自动续传**：下次上传时从断点继续
3. **重试机制**：失败自动重试，最多 3 次

进度存储在 `./data/pipeline.db` 中。

## 常见问题

### Q: 上传速度慢？

检查 OpenList/Alist 的网络限速：
```bash
# 在宿主机执行
tc qdisc show
# 如果有限速，调整为 10Mbit
tc qdisc change dev vethxxx root tbf rate 10mbit burst 128kbit latency 400ms
```

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
