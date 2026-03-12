# 更新日志

所有 notable 更改都将记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

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
