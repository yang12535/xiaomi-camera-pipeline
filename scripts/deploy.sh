#!/bin/bash
cd /path/to/xiaomi-camera-pipeline

echo "=== 停止旧容器 ==="
docker stop xiaomi-camera-pipeline 2>/dev/null
docker rm xiaomi-camera-pipeline 2>/dev/null

echo "=== 构建镜像 ==="
docker build -t xiaomi-camera-pipeline:latest .

echo "=== 启动容器 ==="
docker run -d \
  --name xiaomi-camera-pipeline \
  --restart unless-stopped \
  -v /path/to/your/video/input:/video:ro \
  -v /path/to/your/video/output:/output \
  -v /path/to/your/video/log:/logs \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  -v $(pwd)/pipeline.db:/app/pipeline.db \
  -e CONFIG_FILE=/app/config.yaml \
  -e STATE_DB=/app/pipeline.db \
  -e LOG_DIR=/logs \
  -e LANG=C.UTF-8 \
  -e LC_ALL=C.UTF-8 \
  -e PYTHONIOENCODING=utf-8 \
  xiaomi-camera-pipeline:latest

echo "=== 查看日志 ==="
sleep 3
docker logs --tail 20 xiaomi-camera-pipeline
