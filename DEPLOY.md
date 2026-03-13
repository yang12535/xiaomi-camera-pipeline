# 部署指南

## 环境要求

- Docker 20.10+
- Docker Compose 2.0+
- 宿主机 Linux (推荐 Ubuntu/Debian/飞牛 OS)

## 目录准备

```bash
# 创建必要的目录
mkdir -p /path/to/your/video/{input,temp,output,log}
mkdir -p /path/to/pipeline/{data,config}

# 设置权限（重要！）
chmod -R 755 /path/to/your/video
```

## 部署步骤

### 1. 下载项目

```bash
cd /path/to/pipeline
git clone https://github.com/yang12535/xiaomi-camera-pipeline.git .
```

### 2. 配置

```bash
# 复制配置模板
cp config.yaml.example config.yaml

# 编辑配置
nano config.yaml
```

### 3. 启动

```bash
docker-compose up -d
```

### 4. 验证

```bash
# 查看容器状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 查看数据库状态
docker exec xiaomi-camera-pipeline sqlite3 /app/data/pipeline.db \
  "SELECT stage, COUNT(*) FROM processed GROUP BY stage;"
```

## OpenList 配置

### 安装 OpenList

```bash
mkdir -p /tmp/openlist-docker && cd /tmp/openlist-docker
cat > docker-compose.yml << 'EOF'
version: "3.8"

services:
  openlist:
    image: openlistteam/openlist:latest
    container_name: openlist
    restart: unless-stopped
    ports:
      - "5246:5244"
    volumes:
      - ./data:/opt/alist/data
    environment:
      - PUID=1000
      - PGID=1000
EOF

docker-compose up -d
```

### 添加百度网盘存储

1. 访问 `http://your-openlist-ip:5246/@manage`
2. 登录 admin 账号
3. 进入"存储" → "添加"
4. 选择"百度网盘"
5. 填写 refresh_token（从百度获取）
6. **重要**：勾选 WebDAV 管理权限

### 配置 WebDAV

```
存储名称: baidu
挂载路径: /baidu
WebDAV 策略: 本地代理
根文件夹路径: /视频归档  # 或留空
```

### 限速配置（可选）

如果 OpenList 容器内有限速，调整为 10Mbit：

```bash
# 查找容器网卡
docker exec openlist cat /sys/class/net/eth0/iflink
# 或
tc qdisc show | grep veth

# 修改限速为 10Mbit（在宿主机执行）
sudo tc qdisc change dev vethxxx root tbf rate 10mbit burst 128kbit latency 400ms
```

## 验证部署

### 1. 合并测试

```bash
# 创建一个测试目录
mkdir -p /path/to/your/video/input/2026031310
cp /path/to/test.mp4 /path/to/your/video/input/2026031310/

# 触发处理
docker exec xiaomi-camera-pipeline python3 /app/pipeline.py
```

### 2. 压缩测试

```bash
# 检查输出
ls -lh /path/to/your/video/output/2026/03/13/
```

### 3. 上传测试

```bash
# 手动测试 WebDAV
curl -T /path/to/your/video/output/2026/03/13/10.mkv \
  -u admin:password \
  http://your-openlist-ip:5246/dav/baidu/视频归档/2026/03/13/test.mkv
```

## 故障排查

### 容器无法启动

```bash
# 检查日志
docker-compose logs

# 检查权限
ls -la /path/to/your/video/

# 检查配置文件格式
python3 -c "import yaml; yaml.safe_load(open('config.yaml'))"
```

### 合并失败

```bash
# 检查输入文件
ls /path/to/your/video/input/*/

# 检查 FFmpeg
docker exec xiaomi-camera-pipeline ffmpeg -version
```

### 压缩失败

```bash
# 检查磁盘空间
df -h /path/to/your/video/

# 检查内存
docker stats xiaomi-camera-pipeline
```

### 上传失败

```bash
# 检查 WebDAV 连接
curl -X PROPFIND -u admin:password http://your-openlist-ip:5246/dav/baidu/

# 检查限速
tc qdisc show

# 检查 OpenList 日志
docker logs openlist
```

## 性能优化

### 提高压缩速度

```yaml
# docker-compose.yml
environment:
  - COMPRESS_PRESET=veryfast  # 从 medium 改为 veryfast
  - COMPRESS_THREADS=8        # 增加线程数

deploy:
  resources:
    limits:
      cpus: "8"                # 增加 CPU 限制
```

### 降低 CPU 占用

```yaml
environment:
  - COMPRESS_PRESET=medium
  - COMPRESS_THREADS=2        # 减少线程数
  - COMPRESS_CRF=40           # 增加 CRF，降低质量

deploy:
  resources:
    limits:
      cpus: "2"
```

## 维护

### 清理旧日志

```bash
# 日志保留 30 天，自动清理
# 或手动清理
find /path/to/your/video/log -name "*.log" -mtime +30 -delete
```

### 备份数据库

```bash
# 备份状态数据库
cp /path/to/pipeline/data/pipeline.db /path/to/backup/pipeline-$(date +%Y%m%d).db
```

### 更新版本

```bash
# 拉取最新代码
git pull

# 重启容器
docker-compose down
docker-compose up -d
```

## 安全建议

1. **修改默认密码**：OpenList 和 pipeline 的默认密码
2. **限制网络访问**：防火墙限制 5246 端口访问
3. **定期备份**：重要视频文件多重备份
4. **监控磁盘**：设置磁盘使用率告警
