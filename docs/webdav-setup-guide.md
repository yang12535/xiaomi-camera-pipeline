# WebDAV 配置指南

本文档介绍如何配置 WebDAV 服务器以配合 Pipeline 使用。

## 支持的 WebDAV 服务

Pipeline 支持任何标准 WebDAV 服务，包括但不限于：

- OpenList
- AList
- Nginx WebDAV 模块
- Apache WebDAV
- 其他兼容 WebDAV 协议的服务

---

## Pipeline 配置

编辑 `config.yaml`：

```yaml
upload:
  enabled: true
  type: "webdav"
  webdav_url: "http://your-webdav-server:port/dav/storage/path"
  webdav_user: "your_username"
  webdav_pass: "your_password"
  rate_limit: "100M"        # 上传限速（局域网可不限制）
  delete_after_upload: false
```

### 配置参数

| 参数 | 说明 | 示例 |
|------|------|------|
| `webdav_url` | WebDAV 服务器地址 | `http://your-openlist-ip:5246/dav/baidu/archive` |
| `webdav_user` | 用户名 | `admin` |
| `webdav_pass` | 密码 | `your_password` |
| `rate_limit` | 上传速度限制 | `1M` (1MB/s), `100M` (不限速), `0` (不限速) |
| `delete_after_upload` | 上传后删除本地文件 | `true`/`false` |

---

## 上传路径格式

Pipeline 自动按日期创建目录结构：

```
/dav/storage/path/2026/03/13/filename.mkv
```

格式: `基础 URL` + `年/月/日` + `文件名`

---

## 限速指南

如需限制上传速度，建议在 WebDAV 服务器端配置，而非 Pipeline 端。

### 方案一：服务器端限速（推荐）

在 WebDAV 服务器配置上传限速，Pipeline 在局域网内全速传输。

优点：
- 局域网传输速度快（Pipeline -> WebDAV 服务器）
- 外网带宽可控（WebDAV 服务器 -> 云存储）
- 不影响 Pipeline 处理效率

### 方案二：OpenList Docker + nsenter + tc 限速（推荐）

推荐使用本项目提供的限速脚本对 OpenList 容器进行出口限速。这是最简单可靠的方案。

#### 快速配置

```bash
# 1. 启动 OpenList 容器
docker run -d \
  --name openlist-test \
  -p 15245:5244 \
  -v ./data:/opt/openlist/data \
  -e TZ=Asia/Shanghai \
  openlistteam/openlist:latest

# 2. 应用限速（10Mbps）
./scripts/limit-container-bandwidth.sh openlist-test 10mbit setup
```

#### 详细配置

详见 [bandwidth-limit-guide.md](./bandwidth-limit-guide.md)，包含：
- 完整的 Docker Compose 配置
- 百度网盘存储设置
- Pipeline 配置对接
- 自动化限速方案
- 故障排查指南

#### 旧方案（不推荐）

以下方案已过时，仅供参考：

<details>
<summary>点击查看旧方案（容器内 tc + cap_add NET_ADMIN）</summary>

```yaml
# 旧方案 - 需要 cap_add NET_ADMIN，且容器重启后失效
services:
  openlist:
    image: openlistteam/openlist:latest
    cap_add:
      - NET_ADMIN
    command: >
      sh -c "
        tc qdisc add dev eth0 root tbf rate 1mbit burst 32kbit latency 400ms || true &&
        /opt/openlist/openlist server --data /opt/openlist/data
      "
```

**缺点**：
- 需要特权模式
- 容器重启后限速失效
- 配置复杂

</details>

---

## 配置示例

### 完整部署示例

```
服务器 A (Pipeline)
  └── 视频处理（合并->压缩->上传）-> WebDAV -> 服务器 B

服务器 B (WebDAV + 限速)
  └── OpenList Docker (tc 限速 1MB/s) -> 百度网盘
```

#### 服务器 A - Pipeline 配置

```yaml
# config.yaml
upload:
  enabled: true
  webdav_url: "http://your-openlist-ip:5246/dav/baidu/archive"
  webdav_user: "admin"
  webdav_pass: "your_password"
  rate_limit: "100M"  # 局域网不限速
```

#### 服务器 B - OpenList + 限速

使用上面的 docker-compose.yml 和 apply-limit.sh。

---

## 故障排查

### 中文文件名乱码

确保：
1. WebDAV 服务器支持 UTF-8
2. Pipeline 配置了 UTF-8（默认配置）

### 上传失败

检查：
1. WebDAV 服务可访问：`curl -v http://your-server:port/dav/`
2. 认证信息正确
3. 目录存在（Pipeline 会自动创建）

### 限速不生效

检查：
1. 容器具有 `NET_ADMIN` 权限
2. tc 规则正确应用：`tc qdisc show`
3. 限速脚本执行成功

---

## 参考

- OpenList 文档：https://doc.oplist.org
- tc 命令手册：`man tc`
- WebDAV 协议：RFC 4918
- 项目地址：https://github.com/yang12535/xiaomi-camera-pipeline
