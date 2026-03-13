# Deploy Documentation - Xiaomi Camera Video Processing Pipeline v1.2.1

## System Information
- Server: Your server IP
- User: Your username
- Deploy Time: 2026-03-13

## Directory Structure Example
/path/to/xiaomi-camera/
├── input/          # Xiaomi original video clips
├── temp/           # Merge intermediate files (MOV)
├── output/         # Compressed files (MKV)
└── log/            # Log files

## WebDAV Configuration (Optional)
If upload function is needed, configure WebDAV server. Supports any WebDAV service.

Configuration example (config.yaml):
```yaml
upload:
  enabled: true
  webdav_url: "http://your-webdav-server:port/dav/path"
  webdav_user: "username"
  webdav_pass: "password"
  rate_limit: "100M"
```

Rate limiting configuration method see [DEPLOY_LOG.md](DEPLOY_LOG.md).

## Quick Start
cd /path/to/xiaomi-camera-pipeline
docker-compose up -d

## View Logs
docker-compose logs -f
tail -f /path/to/xiaomi-camera/logs/pipeline.log

## Manual Cleanup Local Files
docker exec -it xiaomi-camera-pipeline python3 /app/cleanup.py --dry-run
