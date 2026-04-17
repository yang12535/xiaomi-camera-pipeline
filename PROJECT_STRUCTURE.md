# 项目结构

```
xiaomi-camera-pipeline/
├── .dockerignore          # Docker 构建忽略文件
├── .gitignore             # Git 忽略文件
├── CHANGELOG.md           # 版本变更日志
├── CONTRIBUTING.md        # 贡献指南
├── DEPLOY.md              # 部署指南
├── DEPLOY_LOG.md          # 部署记录
├── Dockerfile             # Docker 镜像构建
├── FILELIST.md            # 文件清单
├── LICENSE                # AGPL-3.0 许可证
├── PROJECT_STRUCTURE.md   # 本文件
├── README.md              # 项目说明
├── VERSION                # 版本号文件
├── config.yaml            # 主配置文件（根目录默认配置）
├── docker-compose.yml     # Docker Compose 配置
├── pipeline.py            # 主程序入口
├── requirements.txt       # Python 依赖
├── deploy.sh              # 部署脚本
├── config/                # 配置模板目录
│   └── config.yaml.example # 配置模板（建议复制到根目录使用）
├── src/                   # 源代码模块
│   ├── __init__.py
│   ├── compressor.py      # 视频压缩
│   ├── database.py        # SQLite 数据库操作
│   ├── merger.py          # 视频合并
│   ├── uploader.py        # WebDAV 上传
│   ├── utils.py           # 工具函数
│   └── config.py          # 配置加载
└── docs/                  # 文档目录
    ├── bandwidth-limit-guide.md
    ├── compression-tuning-guide.md
    ├── project-standard.md
    └── webdav-setup-guide.md

# 运行时生成的目录
├── data/                  # SQLite 数据库与状态持久化（需创建或挂载）
│   └── pipeline.db
└── logs/                  # 日志目录（需创建或挂载）
    └── pipeline.log
```

## 核心文件说明

### pipeline.py

主程序，包含以下模块：

| 函数 | 功能 |
|------|------|
| `load_config()` | 加载配置（支持环境变量覆盖） |
| `merge_videos()` | 合并 MP4 片段为 MOV |
| `compress_videos()` | H.265 压缩 MOV 为 MKV |
| `upload_videos()` | WebDAV 上传（支持断点续传） |
| `main()` | 主循环 |

### 配置文件优先级

从高到低：

1. 环境变量（`COMPRESS_RESOLUTION` 等）
2. `config.yaml` 配置文件
3. `DEFAULT_CONFIG` 代码默认值

### 数据库表结构

**processed** - 处理记录
```sql
CREATE TABLE processed (
    path TEXT,                   -- 文件路径
    stage TEXT,                  -- 阶段：merge/compress/upload
    timestamp TEXT,              -- 处理时间 ISO8601
    PRIMARY KEY (path, stage)    -- 复合主键，确保同一路径在不同阶段独立记录
);
```

**upload_progress** - 上传进度（v1.2.2+）
```sql
CREATE TABLE upload_progress (
    file_path TEXT PRIMARY KEY,
    remote_url TEXT,
    uploaded_size INTEGER,
    total_size INTEGER,
    last_try TEXT,
    retry_count INTEGER DEFAULT 0
);
```

## 编码规范

- **编码**: UTF-8（无 BOM）
- **换行符**: LF（Unix）
- **缩进**: 4 空格

## 版本控制

```bash
# 关键文件必须提交
git add pipeline.py docker-compose.yml config.yaml.example

# 运行时文件不提交
git add .gitignore  # 已包含 data/*.db, config.yaml
```
