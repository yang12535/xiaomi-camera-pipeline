#!/bin/bash
# Deploy script - Run Pipeline using Docker
# Please modify path configuration before use

# Configuration variables (please modify according to actual paths)
VIDEO_SOURCE="/path/to/xiaomi/video"  # Xiaomi camera original video directory
TEMP_DIR="./temp"                      # Merge intermediate files directory
OUTPUT_DIR="./output"                  # Compressed files directory
LOGS_DIR="./logs"                      # Log directory
DATA_DIR="./data"                      # Data directory (contains SQLite database)

cd "$(dirname "$0")"

echo "=== Stopping old container ==="
docker stop xiaomi-camera-pipeline 2>/dev/null
docker rm xiaomi-camera-pipeline 2>/dev/null

echo "=== Creating directories ==="
mkdir -p "$TEMP_DIR" "$OUTPUT_DIR" "$LOGS_DIR" "$DATA_DIR"

echo "=== Building image ==="
docker build -t xiaomi-camera-pipeline:latest .

echo "=== Starting container ==="
docker run -d \
  --name xiaomi-camera-pipeline \
  --restart unless-stopped \
  -v "$VIDEO_SOURCE:/video:ro" \
  -v "$TEMP_DIR:/input" \
  -v "$OUTPUT_DIR:/output" \
  -v "$LOGS_DIR:/logs" \
  -v "$(pwd)/config.yaml:/app/config.yaml:ro" \
  -v "$DATA_DIR:/app/data" \
  -e CONFIG_FILE=/app/config.yaml \
  -e STATE_DB=/app/data/pipeline.db \
  -e LOG_DIR=/logs \
  -e LANG=en_US.UTF-8 \
  -e LC_ALL=en_US.UTF-8 \
  -e PYTHONIOENCODING=utf-8 \
  -e COMPRESS_RESOLUTION=1920x1080 \
  -e COMPRESS_CRF=35 \
  -e COMPRESS_THREADS=4 \
  xiaomi-camera-pipeline:latest

echo "=== Viewing logs ==="
sleep 3
docker logs --tail 20 xiaomi-camera-pipeline
