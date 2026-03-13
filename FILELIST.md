# 文件清单

## 项目文件

| 文件 | 说明 | 大小 |
|------|------|------|
| `pipeline.py` | 主程序 | ~24KB |
| `cleanup.py` | 本地清理脚本 | ~7KB |
| `config.yaml` | 配置文件 | ~2KB |
| `requirements.txt` | Python 依赖 | ~216B |
| `Dockerfile` | Docker 构建文件 | ~987B |
| `docker-compose.yml` | Docker Compose 配置 | ~1.6KB |
| `README.md` | 项目文档 | ~7KB |
| `CHANGELOG.md` | 更新日志 | ~3KB |
| `OPTIMIZATION.md` | 优化说明文档 | ~8.5KB |
| `DEPLOY_LOG.md` | 部署日志 | ~12KB |
| `FILELIST.md` | 文件清单 | ~1KB |
| `LICENSE` | 许可证 (AGPL-3.0) | ~1.5KB |
| `.gitignore` | Git 忽略规则 | ~526B |
| `.dockerignore` | Docker 忽略规则 | ~435B |

### 文档目录 docs/

| 文件 | 说明 |
|------|------|
| `webdav-setup-guide.md` | WebDAV 配置和限速指南 |
| `project-standard.md` | 项目标准化文档 |

## 快速开始

1. **Docker 部署**（推荐）：
   ```bash
   # 编辑 config.yaml 配置 WebDAV 等参数
   docker-compose up -d
   ```

2. **本地运行**：
   ```bash
   pip install -r requirements.txt
   # 编辑 config.yaml
   python pipeline.py
   ```

## 许可证

AGPL-3.0 © 2026 xiaomi-camera-pipeline contributors
