# 文件清单

## 项目文件

| 文件 | 说明 | 大小 |
|------|------|------|
| `pipeline.py` | 主程序 | ~19KB |
| `config.yaml.example` | 配置示例 | ~3.5KB |
| `requirements.txt` | Python 依赖 | ~216B |
| `Dockerfile` | Docker 构建文件 | ~682B |
| `docker-compose.yml` | Docker Compose 配置 | ~1.1KB |
| `README.md` | 项目文档 | ~6.7KB |
| `CHANGELOG.md` | 更新日志 | ~1.7KB |
| `LICENSE` | 许可证 (AGPL-3.0) | ~1.5KB |
| `.gitignore` | Git 忽略规则 | ~526B |
| `.dockerignore` | Docker 忽略规则 | ~435B |

## 快速开始

1. **Docker 部署**（推荐）：
   ```bash
   cp config.yaml.example config.yaml
   # 编辑 config.yaml
   docker-compose up -d
   ```

2. **本地运行**：
   ```bash
   pip install -r requirements.txt
   cp config.yaml.example config.yaml
   # 编辑 config.yaml
   python pipeline.py
   ```

## 许可证

AGPL-3.0 © 2026 xiaomi-camera-pipeline contributors
