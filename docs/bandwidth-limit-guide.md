# Docker 容器出口带宽限速指南

## 概述

本指南介绍如何对 Docker 容器（如 OpenList）进行出口带宽限速，以控制上传到云存储（百度网盘等）的速率。

## 使用场景

- 限制 OpenList 上传百度网盘的带宽，避免占用全部上行带宽
- 控制其他容器的外网访问速率
- 在多容器环境下合理分配网络资源

## 完整架构

```
┌─────────────────────────────────────────────────────────────────┐
│                          宿主机 (Linux)                          │
│  ┌─────────────────────┐         ┌──────────────────────────┐  │
│  │  Pipeline 容器      │         │  OpenList 容器           │  │
│  │  ┌──────────────┐   │         │  ┌──────────────────┐    │  │
│  │  │ 合并视频     │   │ WebDAV  │  │ 接收上传         │    │  │
│  │  │ 压缩视频     │───┼────────>│  │ 上传到百度网盘   │    │  │
│  │  └──────────────┘   │  LAN    │  └──────────────────┘    │  │
│  └─────────────────────┘         │           │              │  │
│                                   │     eth0│tc HTB限速     │  │
│                                   │           ▼              │  │
│                                   │    ┌──────────────┐      │  │
│                                   │    │ 出口限速     │      │  │
│                                   │    │ 10mbit       │      │  │
│                                   │    └──────────────┘      │  │
│                                   └──────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼  互联网
                           ┌────────────────┐
                           │  百度网盘      │
                           └────────────────┘
```

## OpenList 部署与限速配置

### 1. OpenList Docker Compose 配置

创建 `openlist-docker-compose.yml`：

```yaml
version: "3.8"

services:
  openlist:
    image: openlistteam/openlist:latest
    container_name: openlist-test
    restart: unless-stopped
    ports:
      - "15245:5244"  # 宿主机 15245 映射到容器 5244
    volumes:
      - ./data:/opt/openlist/data
    environment:
      - TZ=Asia/Shanghai
      - PUID=0
      - PGID=0
    networks:
      - openlist-net

networks:
  openlist-net:
    driver: bridge
```

启动容器：

```bash
docker-compose -f openlist-docker-compose.yml up -d
```

### 2. OpenList 初始配置

1. 访问 `http://your-server:15245/@manage`
2. 查看容器日志获取初始密码：`docker logs openlist-test`
3. 登录后添加百度网盘存储：
   - 存储名称：`baidu`
   - 挂载路径：`/baidu`
   - 刷新令牌：从百度网盘获取
   - WebDAV 策略：本地代理
   - 根文件夹路径：`/视频归档`（可选）

### 3. 应用限速

容器启动后，使用限速脚本进行出口限速：

```bash
# 设置 10Mbps 限速（约 1.25MB/s 上传速度）
./scripts/limit-container-bandwidth.sh openlist-test 10mbit setup

# 验证限速生效
./scripts/limit-container-bandwidth.sh openlist-test status
```

### 4. Pipeline 配置

在 `config.yaml` 中配置 WebDAV 上传：

```yaml
upload:
  enabled: true
  webdav_url: http://your-server:15245/dav/baidu/视频归档
  webdav_user: admin
  webdav_pass: your_password
  rate_limit: 0       # Pipeline 不限速，由 OpenList 容器限速
  delete_after_upload: false
  resume: true        # 启用断点续传
  max_retries: 5
  retry_delay: 60
```

## 原理

使用 Linux Traffic Control (tc) 的 HTB (Hierarchical Token Bucket) 队列规则，通过 `nsenter` 进入容器的 network namespace，在容器的 `eth0` 接口上设置出向流量限速。

```
数据流向:
容器进程 → eth0 (tc HTB 限速) → veth → 宿主机 → 外网
```

## 使用方法

### 1. 快速限速

```bash
# 限制 openlist-test 容器为 10Mbps
./scripts/limit-container-bandwidth.sh openlist-test 10mbit setup
```

### 2. 查看限速状态

```bash
./scripts/limit-container-bandwidth.sh openlist-test status
```

### 3. 清除限速

```bash
./scripts/limit-container-bandwidth.sh openlist-test clear
```

### 4. 重启限速

```bash
./scripts/limit-container-bandwidth.sh openlist-test 10mbit restart
```

## 参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| `容器名` | Docker 容器名称 | `openlist-test` |
| `限速` | 带宽限制值 | `10mbit`, `1mbit`, `500kbit` |
| `操作` | 执行的操作 | `setup`, `clear`, `status`, `restart` |

### 限速单位参考

| 值 | 实际速度 | 适用场景 |
|----|---------|---------|
| `10mbit` | ~1.25MB/s | 百度网盘上传推荐 |
| `5mbit` | ~625KB/s | 保守限速 |
| `1mbit` | ~125KB/s | 极低带宽环境 |
| `50mbit` | ~6.25MB/s | 较宽松限速 |

## 限速方案对比

| 方案 | 位置 | 优点 | 缺点 |
|------|------|------|------|
| **本脚本** (nsenter+tc) | 容器 eth0 | 精确控制出向、配置简单 | 容器重启需重新设置 |
| tc on veth (宿主机) | 宿主机 veth | 无需进入容器 | 难以确定 veth 名称 |
| OpenList 内置 | 应用层 | 配置持久化 | 依赖应用支持 |
| 路由器限速 | 网关 | 全局控制 | 影响其他设备 |

**推荐方案**：使用本脚本进行容器 eth0 限速，配合自动化脚本持久化。

## 自动化设置

### 方法一：crontab 开机自动限速

```bash
# 编辑 crontab
crontab -e

# 添加以下行（容器启动后 30 秒执行）
@reboot sleep 30 && /path/to/scripts/limit-container-bandwidth.sh openlist-test 10mbit setup
```

### 方法二：systemd 服务

创建 `/etc/systemd/system/openlist-bandwidth-limit.service`:

```ini
[Unit]
Description=OpenList Container Bandwidth Limit
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/path/to/scripts/limit-container-bandwidth.sh openlist-test 10mbit setup
ExecStop=/path/to/scripts/limit-container-bandwidth.sh openlist-test clear
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

启用服务:

```bash
sudo systemctl daemon-reload
sudo systemctl enable openlist-bandwidth-limit.service
sudo systemctl start openlist-bandwidth-limit.service
```

### 方法三：Docker Compose 健康检查

在 `docker-compose.yml` 中使用健康检查脚本间接限速（需要在宿主机预先设置）。

## 注意事项

1. **容器重启后失效**: tc 规则存储在内存中，容器重启后需要重新设置
2. **需要 root 权限**: 执行脚本需要 sudo 权限（nsenter 和 tc 需要）
3. **容器必须运行**: 脚本执行时容器必须处于运行状态
4. **仅限制出向**: 本方案只限制容器上传（出向）流量，下载（入向）不受影响

## 故障排查

### 检查限速是否生效

```bash
# 查看容器 tc 配置
docker exec openlist-test tc qdisc show dev eth0

# 或进入 network namespace
sudo nsenter -t $(docker inspect -f "{{.State.Pid}}" openlist-test) -n tc class show dev eth0
```

### 上传速度仍过快

1. 检查是否有其他进程在传输数据
2. 确认限速脚本成功执行（无错误输出）
3. 尝试降低限速值测试

### OpenList 限速专用排查

#### 问题：限速脚本执行成功但上传仍很快

**可能原因 1**：限速仅作用于容器 eth0，但 OpenList 可能通过其他方式传输
- 检查 OpenList 配置中的「WebDAV 策略」应为「本地代理」
- 确认上传确实经过容器网络出口

**可能原因 2**：百度网盘本身限速高于预期
- 百度网盘非会员通常限制在 100-200KB/s
- 限速 10mbit 在这种情况下无明显效果

**验证方法**：
```bash
# 在宿主机监控容器上传速度
sudo nsenter -t $(docker inspect -f "{{.State.Pid}}" openlist-test) -n \
  watch -n 1 "tc -s class show dev eth0"
```

观察 `Sent` 字段增长速率是否符合限速。

#### 问题：OpenList 容器重启后限速失效

这是预期行为，tc 规则存储在内存中。解决方案：

```bash
# 创建开机启动脚本
cat > /usr/local/bin/openlist-limit.sh << 'EOF'
#!/bin/bash
# 等待 Docker 启动
sleep 30

# 等待容器启动
while ! docker ps | grep -q openlist-test; do
    sleep 5
done

# 应用限速
/path/to/scripts/limit-container-bandwidth.sh openlist-test 10mbit setup
EOF

chmod +x /usr/local/bin/openlist-limit.sh

# 添加到 crontab
echo "@reboot /usr/local/bin/openlist-limit.sh" | sudo crontab -
```

#### 问题：无法进入容器 network namespace

错误信息：`nsenter: cannot open /proc/xxx/ns/net: Permission denied`

**解决**：
```bash
# 使用 sudo 执行脚本
sudo ./scripts/limit-container-bandwidth.sh openlist-test 10mbit setup

# 或检查容器状态
docker inspect openlist-test --format "{{.State.Status}}"
```

### 脚本执行失败

```bash
# 检查 nsenter 是否可用
which nsenter

# 检查 tc 是否可用
which tc

# 检查容器状态
docker ps | grep openlist-test
```

## 测试验证

上传 20MB 测试文件验证限速:

```bash
# 创建测试文件
dd if=/dev/urandom of=/tmp/test_20mb.bin bs=1M count=20

# 通过 WebDAV 上传测试
curl -T /tmp/test_20mb.bin \
  http://your-openlist:5244/dav/baidu/test/test.bin \
  --user "admin:password" \
  -o /dev/null \
  --progress-bar

# 清理
rm -f /tmp/test_20mb.bin
```

**预期结果**:
- 限速 10mbit: 20MB 文件应耗时 15-20 秒
- 无限速时: 20MB 文件通常只需 2-4 秒

## OpenList 快速配置清单

按顺序执行以下步骤完成 OpenList 限速配置：

### 步骤 1：部署 OpenList
```bash
mkdir -p /path/to/openlist && cd /path/to/openlist
cat > docker-compose.yml << 'EOF'
version: "3.8"
services:
  openlist:
    image: openlistteam/openlist:latest
    container_name: openlist-test
    restart: unless-stopped
    ports:
      - "15245:5244"
    volumes:
      - ./data:/opt/openlist/data
    environment:
      - TZ=Asia/Shanghai
EOF

docker-compose up -d
```

### 步骤 2：获取初始密码
```bash
docker logs openlist-test 2>&1 | grep -i password
```

### 步骤 3：配置百度网盘
1. 访问 `http://your-server:15245/@manage`
2. 使用 admin / 初始密码登录
3. 修改密码
4. 添加存储 → 百度网盘 → 填写刷新令牌
5. 挂载路径：`/baidu`，勾选 WebDAV 管理权限

### 步骤 4：应用限速
```bash
cd /path/to/xiaomi-camera-pipeline
./scripts/limit-container-bandwidth.sh openlist-test 10mbit setup
```

### 步骤 5：配置 Pipeline
```yaml
upload:
  enabled: true
  webdav_url: http://your-server:15245/dav/baidu/视频归档
  webdav_user: admin
  webdav_pass: your_new_password
  rate_limit: 0
  resume: true
```

### 步骤 6：测试上传
```bash
# 创建测试文件
dd if=/dev/urandom of=/tmp/test.bin bs=1M count=20

# 测试上传
curl -T /tmp/test.bin \
  http://your-server:15245/dav/baidu/视频归档/test.bin \
  -u admin:your_password \
  --progress-bar

# 清理
rm /tmp/test.bin
```

### 步骤 7：设置开机自动限速（可选）
```bash
echo "@reboot sleep 30 && /path/to/limit-container-bandwidth.sh openlist-test 10mbit setup" \
  | sudo crontab -
```

---

## 参考

- [Linux TC 文档](https://man7.org/linux/man-pages/man8/tc.8.html)
- [HTB 手册](http://luxik.cdi.cz/~devik/qos/htb/manual/userg.htm)
- [Docker Network Namespace](https://docs.docker.com/network/)
- [OpenList 官方文档](https://github.com/OpenListTeam/OpenList)
- [本项目 GitHub](https://github.com/yang12535/xiaomi-camera-pipeline)
