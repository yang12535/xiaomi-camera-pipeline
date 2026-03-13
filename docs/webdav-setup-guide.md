# WebDAV Configuration Guide

This document describes how to configure WebDAV server to work with Pipeline.

## Supported WebDAV Services

Pipeline supports any standard WebDAV service, including but not limited to:

- OpenList
- AList
- Nginx WebDAV module
- Apache WebDAV
- Other WebDAV protocol compatible services

---

## Pipeline Configuration

Edit `config.yaml`:

```yaml
upload:
  enabled: true
  type: "webdav"
  webdav_url: "http://your-webdav-server:port/dav/storage/path"
  webdav_user: "your_username"
  webdav_pass: "your_password"
  rate_limit: "100M"        # Upload speed limit (optional for LAN)
  delete_after_upload: false
```

### Configuration Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `webdav_url` | WebDAV server address | `http://your-openlist-ip:5246/dav/baidu/archive` |
| `webdav_user` | Username | `admin` |
| `webdav_pass` | Password | `your_password` |
| `rate_limit` | Upload speed limit | `1M` (1MB/s), `100M` (no limit), `0` (no limit) |
| `delete_after_upload` | Delete local file after upload | `true`/`false` |

---

## Upload Path Format

Pipeline automatically creates directory structure by date:

```
/dav/storage/path/2026/03/13/filename.mkv
```

Format: `base URL` + `year/month/day` + `filename`

---

## Rate Limiting Guide

If you need to limit upload speed, it is recommended to configure at the WebDAV server side rather than the Pipeline side.

### Option 1: Server-side Rate Limiting (Recommended)

Configure upload speed limit at the WebDAV server, Pipeline transfers at full speed on LAN.

Advantages:
- Fast LAN transfer speed (Pipeline -> WebDAV server)
- Controllable outbound bandwidth (WebDAV server -> Cloud storage)
- Does not affect Pipeline processing efficiency

### Option 2: OpenList Docker + tc Rate Limiting

Below is an example of rate limiting using OpenList + Docker + tc:

#### 1. OpenList Docker Compose Configuration

```yaml
# openlist-docker-compose.yml
services:
  openlist:
    image: openlistteam/openlist:latest
    container_name: openlist-limited
    restart: unless-stopped
    user: "0:0"  # root user to execute tc commands
    ports:
      - "5246:5244"  # host 5246 maps to container 5244
    volumes:
      - ./data:/opt/openlist/data
      - ./temp:/opt/openlist/data/temp
    environment:
      - TZ=Asia/Shanghai
      - UMASK=022
    cap_add:
      - NET_ADMIN  # Allow network management permissions
    command: >
      sh -c "
        tc qdisc add dev eth0 root tbf rate 1mbit burst 32kbit latency 400ms 2>/dev/null || true &&
        /opt/openlist/openlist server --data /opt/openlist/data
      "
    networks:
      - openlist-net

networks:
  openlist-net:
    driver: bridge
```

#### 2. tc Rate Limiting Parameters

| Parameter | Description | Suggested Value |
|-----------|-------------|-----------------|
| `rate` | Rate limit | `1mbit` = 1 Mbps ~ 125 KB/s |
| `burst` | Burst bucket size | `32kbit` |
| `latency` | Maximum latency | `400ms` |

#### 3. Dynamic Rate Limiting Script

After container restart, the veth interface changes. Use the following script to dynamically identify and apply rate limiting:

```bash
#!/bin/bash
# apply-limit.sh - Apply tc rate limiting

CONTAINER_NAME="openlist-limited"
RATE="1mbit"

# Get container PID
container_pid=$(docker inspect --format='{{.State.Pid}}' $CONTAINER_NAME 2>/dev/null)
if [ -z "$container_pid" ]; then
    echo "Container not running"
    exit 1
fi

# Get eth0 interface index inside container
eth_index=$(nsenter -t $container_pid -n ip link show eth0 | grep -o 'eth0@if[0-9]*' | cut -d'@' -f2 | tr -d 'if')
if [ -z "$eth_index" ]; then
    echo "Cannot get interface index"
    exit 1
fi

# Find corresponding veth interface on host
host_veth=$(ip link show | grep -E "^${eth_index}:" | awk -F': ' '{print $2}' | awk '{print $1}')
if [ -z "$host_veth" ]; then
    echo "Cannot find host veth interface"
    exit 1
fi

# Delete old rule (if exists)
sudo tc qdisc del dev $host_veth root 2>/dev/null

# Add new rule
sudo tc qdisc add dev $host_veth root tbf rate $RATE burst 32kbit latency 400ms

if [ $? -eq 0 ]; then
    echo "Successfully set $host_veth rate limit to $RATE"
    sudo tc qdisc show dev $host_veth
else
    echo "Failed to set rate limit"
    exit 1
fi
```

Usage:
```bash
chmod +x apply-limit.sh
sudo ./apply-limit.sh
```

#### 4. Persistent Rate Limiting (Recommended)

Add to crontab to check and apply rate limiting every minute:

```bash
# crontab -e
* * * * * /path/to/apply-limit.sh >> /var/log/tc-limit.log 2>&1
```

Or use systemd timer for more reliability.

---

## Configuration Example

### Complete Deployment Example

```
Server A (Pipeline)
  └── Video processing (merge->compress->upload) -> WebDAV -> Server B

Server B (WebDAV + Rate Limiting)
  └── OpenList Docker (tc rate limit 1MB/s) -> Baidu Netdisk
```

#### Server A - Pipeline Configuration

```yaml
# config.yaml
upload:
  enabled: true
  webdav_url: "http://your-openlist-ip:5246/dav/baidu/archive"
  webdav_user: "admin"
  webdav_pass: "your_password"
  rate_limit: "100M"  # No limit on LAN
```

#### Server B - OpenList + Rate Limiting

Use the docker-compose.yml and apply-limit.sh above.

---

## Troubleshooting

### Chinese Filename Garbled

Ensure:
1. WebDAV server supports UTF-8
2. Pipeline is configured with UTF-8 (default configuration)

### Upload Failed

Check:
1. WebDAV service accessibility: `curl -v http://your-server:port/dav/`
2. Authentication information is correct
3. Directory exists (Pipeline will create automatically)

### Rate Limiting Not Working

Check:
1. Container has `NET_ADMIN` permission
2. tc rules are correctly applied: `tc qdisc show`
3. Rate limiting script executed successfully

---

## References

- OpenList Documentation: https://doc.oplist.org
- tc Command Manual: `man tc`
- WebDAV Protocol: RFC 4918
