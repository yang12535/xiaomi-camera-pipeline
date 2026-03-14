# 项目标准文档

## 项目信息

| 项目 | 内容 |
|------|------|
| 名称 | xiaomi-camera-pipeline |
| 版本 | v1.2.4 |
| 许可证 | AGPL-3.0 |
| Python 版本 | 3.8+ |
| GitHub | https://github.com/yang12535/xiaomi-camera-pipeline |

## 编码标准

### UTF-8 标准化

项目使用统一的 UTF-8 编码，确保 Windows/Linux 兼容性：

#### Python 文件
```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
```

#### 环境配置
- **Windows**: 强制使用 `zh_CN.UTF-8`
- **Linux/Docker**: 使用 `en_US.UTF-8`
- **Python**: `PYTHONIOENCODING=utf-8`

#### Docker 配置
```dockerfile
ENV LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    PYTHONIOENCODING=utf-8
```

### 代码风格

- 遵循 PEP 8 规范
- 函数和变量使用 snake_case
- 常量使用 UPPER_CASE
- 类使用 CamelCase

## 目录结构

```
pipeline/
├── pipeline.py          # 主程序入口
├── cleanup.py           # 本地清理工具
├── config.yaml          # 配置文件模板
├── docker-compose.yml   # Docker Compose 配置
├── Dockerfile           # Docker 构建文件
├── deploy.sh            # 部署脚本
├── requirements.txt     # Python 依赖
├── docs/                # 文档目录
│   ├── webdav-setup-guide.md
│   ├── project-standard.md
│   └── bandwidth-limit-guide.md
├── data/                # 数据目录 (SQLite 数据库)
├── temp/                # 临时文件 (合并中间文件)
├── output/              # 输出目录 (压缩后的 MKV)
└── logs/                # 日志目录
```

## 配置标准

### 配置优先级（从高到低）

1. **docker-compose.yml 环境变量**（最高优先级）
   ```yaml
   environment:
     - COMPRESS_RESOLUTION=1920x1080
     - COMPRESS_CRF=35
   ```

2. **config.yaml 配置文件**
   ```yaml
   compress:
     resolution: "1920x1080"
     crf: 35
   ```

3. **代码默认值**（最低优先级）

### 默认配置标准

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 分辨率 | 1920x1080 | 1080P 输出 |
| CRF | 35 | 高压缩率，适合监控场景 |
| 线程数 | 4 | CPU 线程数 |
| 预设 | medium | 编码速度/质量平衡 |

## Docker 标准

### 镜像构建

```dockerfile
FROM jrottenberg/ffmpeg:6.1-ubuntu2204
```

### 端口映射

- 不暴露外部端口（Pipeline 在内部运行）

### 卷挂载

| 宿主机 | 容器 | 说明 |
|--------|------|------|
| `/path/to/video` | `/video` | 视频源（只读） |
| `./temp` | `/input` | 合并中间文件 |
| `./output` | `/output` | 压缩后文件 |
| `./logs` | `/logs` | 日志文件 |
| `./data` | `/app/data` | SQLite 数据库 |

### 资源限制

```yaml
deploy:
  resources:
    limits:
      cpus: "4"
      memory: 2G
```

## 日志标准

### 日志格式
```
%(asctime)s - %(levelname)s - %(message)s
```

### 日志级别
- DEBUG: 调试信息
- INFO: 一般信息（默认）
- WARNING: 警告
- ERROR: 错误

### 日志文件
- 位置: `/logs/pipeline.log`
- 保留: 30 天

## 数据库标准

### SQLite
- 文件: `/app/data/pipeline.db`
- 表: `processed`
- 字段: `path`, `stage`, `timestamp`

### 状态定义
- `merge`: 已合并
- `compress`: 已压缩
- `upload`: 已上传

## 版本管理

### 版本号规则
遵循 [SemVer](https://semver.org/lang/zh-CN/)：

```
主版本号.次版本号.修订号
```

- **主版本号**：不兼容的 API 修改
- **次版本号**：向下兼容的功能新增
- **修订号**：向下兼容的问题修复

### 版本记录
详见 [CHANGELOG.md](../CHANGELOG.md)

## 提交标准

### 提交信息格式
```
<类型>(<范围>): <主题>

<正文>

<脚注>
```

### 类型说明
- feat: 新功能
- fix: 修复
- docs: 文档
- style: 格式
- refactor: 重构
- test: 测试
- chore: 构建/工具

### 示例
```
feat(upload): 添加 WebDAV 按日期归档目录结构

- 自动创建年/月/日目录
- 支持嵌套路径的递归 MKCOL

Closes #123
```

## 文档标准

### 文件命名
- 使用小写字母
- 使用连字符分隔单词
- 优先使用英文

### 示例
- `webdav-setup-guide.md`
- `project-standard.md`

## 依赖管理

### Python 依赖
```
PyYAML>=5.4.1
```

### 系统依赖
- FFmpeg 6.1+
- Python 3.8+
- SQLite 3

## 安全标准

### 敏感信息
- 密码等敏感信息通过环境变量传递
- 配置文件不上传到版本控制
- 数据库文件定期备份

### 权限控制
- 视频源目录只读挂载
- 容器内使用非 root 用户（如不需要 tc 限速）

## 测试标准

### 测试类型
- 单元测试（待添加）
- 集成测试（待添加）
- 手动测试

### 测试清单
- [ ] 合并功能正常
- [ ] 压缩功能正常
- [ ] 上传功能正常
- [ ] 中文文件名正常
- [ ] 日志输出正常
- [ ] 数据库记录正常

## 发布流程

1. 更新版本号（代码、文档）
2. 更新 CHANGELOG.md
3. 打标签: `git tag v1.2.4`
4. 构建 Docker 镜像
5. 推送镜像
6. 创建 Release

## 参考

- [PEP 8](https://pep8.org/)
- [SemVer](https://semver.org/lang/zh-CN/)
- [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/)
- [GitHub 项目](https://github.com/yang12535/xiaomi-camera-pipeline)
