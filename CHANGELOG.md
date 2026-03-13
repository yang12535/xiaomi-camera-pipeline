# 更新日志

所有 notable 更改都将记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [1.2.1] - 2026-03-13

### 新增
- 本地文件自动清理功能 (`cleanup_local_files()`)
- 独立清理脚本 `cleanup.py`，支持预览模式和自定义保留天数
- 手动清理工具，支持 `--dry-run`、`--days`、`--force` 参数
- 磁盘空间监控，低于阈值时自动强制清理
- 项目标准化文档 `docs/project-standard.md`
- WebDAV 配置指南 `docs/webdav-setup-guide.md`
- OpenList Docker + tc 限速配置示例和脚本

### 变更
- **默认输出分辨率**: `original` -> `1920x1080` (1080p)
- **默认 CRF**: `32` -> `35`（更高压缩率，适合监控录像）
- **默认线程数**: `8` -> `4`
- **docker-compose.yml 路径**: 移除个人路径 `/vol2/...`，改为通用路径 `/path/to/...`
- **配置优先级**: 环境变量 > config.yaml > 代码默认值
- **WebDAV 配置**: 改为占位符形式，用户按需配置

### UTF-8 标准化
- 统一 Windows/Linux 编码配置
- Windows: 强制 `zh_CN.UTF-8` + `io.TextIOWrapper`
- Linux/Docker: 使用 `en_US.UTF-8`
- 添加 `PYTHONIOENCODING=utf-8` 环境变量
- 所有 Python 文件添加 `# -*- coding: utf-8 -*-` 头

### 代码质量
- 清理重复导入（`urllib.parse` 导入 3 次）
- 添加全面的错误处理和异常捕获
- 改进数据库操作错误处理（try-except）
- 改进文件操作安全性（临时文件清理）
- 改进视频目录检测（添加 `isdigit()` 验证）
- 改进文件扩展名检测（大小写不敏感）
- 改进配置加载（带类型转换的环境变量映射）
- 改进日志清理（更安全的旧日志删除）
- 改进 WebDAV 上传（添加超时和异常处理）

### 文档
- 添加配置优先级说明
- 添加完整的 WebDAV 配置指南
- 添加 OpenList Docker + tc 限速配置
- 添加项目标准化文档
- 更新所有文档使用通用路径替代个人路径

### 移除
- 移除捆绑的 `openlist-docker/` 目录
- WebDAV 服务端改为用户按需自行部署

## [1.2.0] - 2026-03-13

### 新增
- WebDAV 上传自动按日期归档（年/月/日目录结构）
- 逐级创建 WebDAV 目录支持（MKCOL 多级目录）
- 新增 temp 挂载目录用于存储合并中间文件
- WebDAV 上传支持（支持任意 WebDAV 服务）

### 变更
- 上传路径格式：`/归档/2026/03/13/文件名.mkv`
- docker-compose.yml 添加 temp 目录挂载
- 上传限速配置：1MB/s (8Mbps)

### 配置更新

### 目录映射更新
| 宿主机路径 | 容器路径 | 说明 |
|-----------|---------|------|
| /path/to/xiaomi/video | /video | 小米原始视频（只读） |
| ./temp | /input | 合并中间文件（MOV） |
| ./output | /output | 压缩后文件（MKV） |
| ./logs | /logs | 日志文件 |

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
