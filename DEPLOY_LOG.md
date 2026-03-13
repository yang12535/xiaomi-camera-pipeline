# 部署日志 - 小米摄像头视频处理流水线

## 版本历史
- **v1.2.1** - 2026-03-13 - 代码优化、项目标准化（当前版本）
- **v1.2.0** - 2026-03-13 - 新增 WebDAV 日期归档、本地清理功能
- **v1.1.0** - 2026-03-12 - 编码兼容性和日志改进
- **v1.0.0** - 2026-03-12 - 初始稳定版本

---

## v1.2.1 部署说明

### 主要变更
1. **项目标准化**: UTF-8 编码统一、代码规范、文档完善
2. **本地清理**: 新增自动清理和手动清理脚本
3. **配置优化**: 默认 1080p/CRF35/4线程，环境变量优先级
4. **WebDAV 配置**: 不再捆绑服务端，提供完整配置指南

### 文档索引
- **WebDAV 配置指南**: [docs/webdav-setup-guide.md](docs/webdav-setup-guide.md)
- **项目标准化文档**: [docs/project-standard.md](docs/project-standard.md)
- **配置优先级说明**: 环境变量 > config.yaml > 代码默认值

---

## 历史部署信息

### 部署时间
2026-03-13

### 服务器信息
- **Pipeline 服务器**: <YOUR_PIPELINE_SERVER_IP>
- **WebDAV 服务器**: <YOUR_WEBDAV_SERVER_IP>
- **用户**: <YOUR_USERNAME>
- **Docker**: 28.x.x
- **Docker Compose**: v2.x.x

---

## 架构设计

### 网络拓扑
```
┌─────────────────────────────────────────────────────────────────┐
│  <YOUR_PIPELINE_SERVER>                                          │
│  ┌─────────────────────────────────────────┐                   │
│  │  Pipeline Docker                        │                   │
│  │  - 合并/压缩视频 (8核/CRF35)            │                   │
│  │  - 本地处理不限速                        │                   │
│  └──────────┬──────────────────────────────┘                   │
│             │ WebDAV (内网，不限速)                              │
│             ▼                                                    │
└─────────────┼──────────────────────────────────────────────────┘
              │
              │ OVS 网络
              ▼
┌─────────────┼──────────────────────────────────────────────────┐
│  <YOUR_WEBDAV_SERVER>                                          │
│             │                                                   │
│  ┌──────────▼──────────────────────────────────────────────┐  │
│  │  WebDAV Docker (限速容器)                                │  │
│  │  - 端口: 5246                                            │  │
│  │  - 上行限速: 1MB/s (tc qdisc)                            │  │
│  │  - 只限制容器出口，不影响宿主机其他应用                   │  │
│  └──────────┬──────────────────────────────────────────────┘  │
│             │ 外网上传                                          │
│             ▼                                                   │
│        百度盘 (限速1MB/s)                                        │
└─────────────────────────────────────────────────────────────────┘
```

### 限速策略说明

**为什么采用双机架构？**

1. **Pipeline → WebDAV**: 内网传输，**不限速**
   - 本地 WebDAV 上传速度取决于磁盘 IO
   - 316MB 文件几秒即可完成传输

2. **WebDAV → 百度盘**: 外网上传，**限速 1MB/s**
   - 避免占满出口带宽
   - 不影响宿主机其他应用（KVM 内其他 VM、Docker 其他容器）

---

## WebDAV 服务配置方法

本项目支持任意标准 WebDAV 服务。详细配置指南请参考 [docs/webdav-setup-guide.md](docs/webdav-setup-guide.md)。

### 快速配置

**1. Pipeline 端配置**

编辑 `config.yaml`：
```yaml
upload:
  enabled: true
  type: "webdav"
  webdav_url: "http://your-server:port/dav/storage/path"
  webdav_user: "username"
  webdav_pass: "password"
  rate_limit: "100M"  # 内网传输可不限制
```

**2. WebDAV 服务端限速（推荐）**

如需限速，建议在 WebDAV 服务端配置，而非 Pipeline 端。

OpenList Docker + tc 限速示例：
```yaml
# docker-compose.yml
cap_add:
  - NET_ADMIN
command: >
  sh -c "
    tc qdisc add dev eth0 root tbf rate 1mbit burst 32kbit latency 400ms 2>/dev/null || true &&
    /opt/openlist/openlist server --data /opt/openlist/data
  "
```

**3. 动态限速脚本**

容器重启后 veth 接口会变，使用脚本动态识别：
```bash
#!/bin/bash
CONTAINER_NAME="openlist-limited"
container_pid=$(docker inspect --format='{{.State.Pid}}' $CONTAINER_NAME)
eth_index=$(nsenter -t $container_pid -n ip link show eth0 | grep -o 'eth0@if[0-9]*' | cut -d'@' -f2 | tr -d 'if')
host_veth=$(ip link show | grep -E "^${eth_index}:" | awk -F': ' '{print $2}' | awk '{print $1}')
sudo tc qdisc add dev $host_veth root tbf rate 1mbit burst 32kbit latency 400ms
```

详细配置请参考 [WebDAV 配置指南](docs/webdav-setup-guide.md)。

---

## 遇到的问题及解决方案

### 1. Docker 镜像构建慢（apt 源慢）
**问题**: Ubuntu apt 官方源在国内访问慢，构建耗时过长

**解决**: 修改 Dockerfile，使用阿里云镜像源
```dockerfile
RUN sed -i 's/archive.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list && \
    sed -i 's/security.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list
```

### 2. 基础镜像 ENTRYPOINT 冲突
**问题**: 基础镜像 jrottenberg/ffmpeg 默认 ENTRYPOINT 是 ffmpeg，导致容器启动时执行 ffmpeg python3 ... 报错

**错误日志**:
```
Unable to choose an output format for 'python3'
Error opening output file python3
```

**解决**: 在 Dockerfile 中清空 ENTRYPOINT，使用 CMD
```dockerfile
ENTRYPOINT []
CMD ["python3", "/app/pipeline.py"]
```

### 3. SQLite 数据库文件挂载失败
**问题**: docker-compose.yml 中直接挂载文件 ./pipeline.db:/app/pipeline.db，文件不存在时导致权限错误

**错误日志**:
```
sqlite3.OperationalError: unable to open database file
```

**解决**: 改为挂载目录 ./data:/app/data，数据库文件放在目录内
- 修改挂载: ./data:/app/data
- 修改环境变量: STATE_DB=/app/data/pipeline.db

### 4. SQL 语法错误
**问题**: mark_processed 函数中 SQL 语句引号不匹配

**错误代码** (line 206):
```python
c.execute('INSERT OR REPLACE INTO processed VALUES (?, ?, ")',  # 引号不匹配
```

**解决**: 修正为正确的 SQL 语法
```python
c.execute("INSERT OR REPLACE INTO processed VALUES (?, ?, ?)",
          (path, stage, datetime.now().isoformat()))
```

### 5. locale 配置兼容性问题
**问题**: C.UTF-8 在某些 Ubuntu 版本上不被支持

**错误日志**:
```
Error: 'C.UTF-8' is not a supported language or locale
```

**解决**: 简化为只使用 en_US.UTF-8

### 6. docker-compose 版本警告
**问题**: version: "3.8" 已过时

**解决**: 可删除 version 行，或忽略该警告

### 7. 上传未启用
**问题**: 配置缺少 `enabled: true`，导致跳过上传阶段

**解决**: 添加 `enabled: true` 到 upload 配置

### 8. 配置项名称不匹配
**问题**: 代码使用 `webdav_url`/`webdav_user`/`webdav_pass`，但配置写 `url`/`username`/`password`

**解决**: 统一配置项名称与代码一致

### 9. 中文路径 URL 编码问题
**问题**: 文件名包含中文时，curl URL 格式错误

**解决**: 使用 urllib.parse.quote 对文件名编码
```python
from urllib.parse import quote
remote_url = f"{base_url}/{date_path}/{quote(filename)}"
```

### 10. WebDAV IP 配置错误
**问题**: Pipeline 配置的 WebDAV IP 错误，配置了本机 IP 而非 WebDAV 服务器 IP

**解决**: 修正为正确的 WebDAV 服务器 IP
```yaml
webdav_url: "http://<YOUR_WEBDAV_IP>:<PORT>/dav/<PATH>"
```

---

## 当前配置汇总

### Pipeline 配置示例
```yaml
upload:
  type: "webdav"
  enabled: true
  webdav_url: "http://<YOUR_WEBDAV_IP>:<PORT>/dav/<STORAGE>/<PATH>"
  webdav_user: "<YOUR_USERNAME>"
  webdav_pass: "<YOUR_PASSWORD>"
  rate_limit: "100M"        # 内网不限速

compress:
  resolution: "1920x1080"   # 1080p 输出
  crf: 35                   # 高压缩率
  threads: 4                # 4核

cleanup:
  enabled: true
  retain_days: 7            # 保留 7 天
  min_free_gb: 50           # 低于 50GB 强制清理
```

### WebDAV 服务端配置示例
```yaml
# Docker Compose
ports:
  - "5246:5244"

# tc 限速 (宿主机执行)
tc qdisc add dev <veth> root tbf rate 1mbit burst 32kbit latency 400ms
```

---

## 测试状态

- [x] 合并功能: 测试视频 (752MB) 合并成功
- [x] 压缩功能: 752MB → 316MB (CRF 35)
- [x] 上传功能: 已成功上传到目标存储
- [x] WebDAV 限速: 1MB/s 生效

---

## 快速命令

### Pipeline (<YOUR_PIPELINE_SERVER>)
```bash
cd /path/to/xiaomi-camera-pipeline

# 查看日志
docker compose logs -f

# 重启
docker compose restart

# 停止
docker compose down
```

### WebDAV 服务端 (<YOUR_WEBDAV_SERVER>)
```bash
cd /path/to/webdav-docker

# 查看日志
docker compose logs -f

# 调整限速 (先找到 veth)
VETH=$(ip link show | grep veth | awk -F: '{print $2}' | xargs -I {} sh -c 'docker exec webdav-limited ip link 2>/dev/null | grep -q {} && echo {}')
sudo tc qdisc change dev $VETH root tbf rate 2Mbit burst 8Kb lat 400ms

# 重启
docker compose restart
```

### 限速检查
```bash
# 查看所有 tc 规则
sudo tc qdisc show

# 查看特定接口
sudo tc qdisc show dev $(ip link | grep veth | head -1 | awk -F: '{print $2}')
```

---

## 待办事项

1. [ ] **限速持久化**: 容器重启后 veth 接口会变，需要脚本自动识别并限速
2. [ ] **监控告警**: 添加容器重启次数监控、上传失败告警
3. [ ] **日志收集**: 集中收集 Pipeline 和 WebDAV 日志
4. [ ] **配置优化**: CRF 35 压缩率较高，如需更好画质可调整为 28
5. [ ] **多存储支持**: 如需上传到其他网盘，可在 WebDAV 服务端添加更多存储

---

## 文件清单 (v1.2.1)

```
xiaomi-camera-pipeline/
├── pipeline.py              # 主程序
├── cleanup.py               # 本地清理脚本
├── config.yaml              # Pipeline 配置
├── docker-compose.yml       # Pipeline Docker 配置
├── Dockerfile               # Pipeline 构建文件
├── deploy.sh                # 部署脚本
├── requirements.txt         # Python 依赖
├── CHANGELOG.md             # 版本历史
├── DEPLOY.md                # 部署文档
├── DEPLOY_LOG.md            # 本文件
├── README.md                # 使用说明
├── OPTIMIZATION.md          # 优化说明
├── FILELIST.md              # 文件清单
├── docs/                    # 文档目录
│   ├── webdav-setup-guide.md    # WebDAV 配置指南
│   └── project-standard.md      # 项目标准化文档
└── data/                    # SQLite 数据库目录
```

---

## 性能数据

| 阶段 | 速度 | 耗时 | 备注 |
|-----|------|------|------|
| 合并 | 磁盘 IO 限制 | ~30s | 60个1分钟片段 |
| 压缩 | 8核满载 | ~19分钟 | CRF 35, 752MB→316MB |
| 内网上传 | ~100MB/s | ~3s | Pipeline→WebDAV |
| 外网上传 | 1MB/s | ~5分钟 | WebDAV→云存储 |
