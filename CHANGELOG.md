# 更新日志

所有 notable 更改都将记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.2.5] - 2026-03-15

### 优化
- **压缩质量优化**：默认 CRF 从 35 调整为 32，减少花屏/马赛克现象
- **编码预设调整**：默认 preset 从 medium 改为 fast，平衡编码速度与质量

### 文档
- **新增压缩参数调优指南**：`docs/compression-tuning-guide.md`
  - CRF 参数详解与推荐值
  - Preset 预设速度与质量对比表
  - 不同场景的配置建议（监控/存档/分享）
  - 编码耗时参考数据

### 配置变更
```yaml
compress:
  crf: 32        # 从 35 改为 32，减少花屏
  preset: fast   # 从 medium 改为 fast，平衡速度
```

## [1.2.4] - 2026-03-14

### 新增
- **Docker 容器出口限速方案**: 新增 `scripts/limit-container-bandwidth.sh` 脚本，使用 nsenter + tc HTB 对 OpenList 等容器进行出向带宽限速
- **限速使用文档**: 新增 `docs/bandwidth-limit-guide.md`，详细介绍限速原理、使用方法和自动化配置

### 技术改进
- 使用 `nsenter` 进入容器 network namespace，在 eth0 上设置 HTB 队列规则
- 支持 `setup`/`clear`/`status`/`restart` 四种操作模式
- 提供 crontab 和 systemd 两种自动化方案

### 文档更新
- 汉化 `docs/project-standard.md` 和 `docs/webdav-setup-guide.md`
- 更新版本号至 v1.2.4

## [1.2.3] - 2026-03-14

### 修复
- 修复 curl 输出解析错误，合并 stdout + stderr 正确获取 HTTP 状态码和上传速度

## [1.2.2] - 2026-03-13

### 新增
- **断点续传支持** (`upload.resume`): WebDAV 上传中断后自动恢复，无需从头开始
- **上传进度监控**: 实时显示上传速度、已传大小、剩余大小
- **智能重试机制**: 上传失败自动重试，最多 3 次（可配置）
- **上传进度数据库**: SQLite 记录上传进度，重启容器后自动续传
- **文件大小格式化**: 自动显示 B/KB/MB/GB，更易读

### 修复
- **时区问题**: 添加 `TZ=Asia/Shanghai` 环境变量，确保日志和上传目录使用北京时间（UTC+8），而非 UTC

### 优化
- **监控场景压缩参数推荐**: 默认 1920x1080 + CRF35 + medium preset（2K 太奢侈！）
- **上传速度报告**: 完成后显示平均上传速度
- **配置模板完善**: config.yaml.example 添加详细注释
- **docker-compose.yml 优化**: 添加更多使用说明和参数解释、时区设置

### 技术改进
- 新增 `upload_progress` 数据表存储断点续传状态
- 使用 `curl -C -` 实现断点续传
- 改进 curl 输出解析，提取 HTTP 状态码和上传速度
- 上传前检查远程文件大小，智能计算续传位置

### 配置变更
```yaml
upload:
  resume: true          # 新增：断点续传
  max_retries: 3        # 新增：最大重试次数
  retry_delay: 30       # 新增：重试间隔(秒)
```

## [1.2.1] - 2026-03-13

### 新增
- UTF-8 标准化（避免 GBK 乱码）
- Dockerfile 优化（阿里云镜像、en_US.UTF-8）
- docker-compose.yml 优化（移除 version 行、目录挂载）
- cleanup.py 清理脚本

### 变更
- 默认分辨率改为 1920x1080（监控场景不需要 2K）
- 默认 CRF 35（更高压缩率）
- 默认线程 4（降低 CPU 占用）

## [1.2.0] - 2026-03-13

### 新增
- WebDAV 上传自动按日期归档（年/月/日目录结构）
- 逐级创建 WebDAV 目录支持（MKCOL 多级目录）
- 新增 temp 挂载目录用于存储合并中间文件
- OpenList WebDAV 支持（对接百度盘）

### 变更
- WebDAV 配置更新：切换到 OpenList (your-openlist-ip:5246) -> 百度盘
- 上传路径格式：/视频归档/2026/03/13/filename.mkv
- docker-compose.yml 添加 temp 目录挂载
- 上传限速配置：1MB/s (8Mbps)

### 配置更新


### 目录映射更新
| 宿主机路径 | 容器路径 | 说明 |
|-----------|---------|------|
| /path/to/your/video/input | /video | 小米原始视频（只读） |
| /path/to/your/video/temp | /input | 合并中间文件（MOV） |
| /path/to/your/video/output | /output | 压缩后文件（MKV） |
| /path/to/your/video/log | /logs | 日志文件 |

## [1.1.0] - 2026-03-12

### 新增
- 环境自适应 UTF-8 编码配置（Windows 机房/Docker 兼容）
- 添加项目标准化文件（requirements.txt、.gitignore、.dockerignore）
- 日志级别配置支持
- 完善的编码处理文档

### 变更
- 优化 Dockerfile，添加 locale 支持避免中文乱码
- docker-compose.yml 添加编码环境变量
- 日志配置标准化，支持文件和控制台双输出

### 修复
- Windows 机房还原卡导致的编码问题（GBK/UTF-8）
- Docker 环境中可能出现的 locale 警告

## [1.0.0] - 2026-03-12

### 新增
- 完整的视频处理流水线：合并 → 压缩 → 上传
- SQLite 状态数据库，支持断点续传
- 临时文件机制，确保数据安全
- 多重验证：文件大小、ffprobe 完整性、时长检查
- WebDAV 限速上传功能
- Docker 容器化支持
- 环境变量覆盖配置

### 变更
- 合并功能引用自 hslr-s/xiaomi-camera-merge
- 压缩功能引用自 yang12535/xiaomi-compress
- 代码优化，提升稳定性

### 修复
- Windows 路径兼容性问题
- FFmpeg concat 文件 BOM 问题
- 临时文件扩展名识别问题

## [0.1.0] - 初始版本

- 基础合并功能
- 基础压缩功能

---

## 版本说明

- **主版本号**：不兼容的 API 修改
- **次版本号**：向下兼容的功能性新增
- **修订号**：向下兼容的问题修正
