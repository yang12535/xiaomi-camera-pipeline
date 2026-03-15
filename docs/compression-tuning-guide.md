# 压缩参数调优指南

本文档详细介绍小米摄像头视频流水线的压缩参数配置，帮助你在**视频质量**、**文件大小**和**编码速度**之间找到最佳平衡。

## 快速参考

| 使用场景 | CRF | Preset | 适用说明 |
|---------|-----|--------|---------|
| **平衡模式（默认）** | 32 | fast | 推荐日常使用，质量与体积平衡 |
| **高质量存档** | 28 | slow | 重要视频长期保存 |
| **高压缩率** | 35 | medium | 存储空间有限，接受轻微质量损失 |
| **极速处理** | 32 | faster | 快速处理大量视频 |

## 核心参数详解

### CRF (Constant Rate Factor) - 质量控制

CRF 是 H.265/H.264 编码的质量控制参数，**数值越小，质量越好，文件越大**。

| CRF 值 | 质量等级 | 文件大小 | 适用场景 |
|-------|---------|---------|---------|
| 18-23 | 无损/极高质量 | 很大 | 专业制作、母带存档 |
| 24-28 | 高质量 | 大 | 重要视频存档 |
| **29-32** | **良好质量** | **中等** | **日常使用（推荐）** |
| 33-35 | 标准质量 | 较小 | 监控场景、一般存储 |
| 36-40 | 低质量 | 很小 | 预览、临时文件 |
| 41-51 | 很差 | 极小 | 不推荐 |

#### 小米摄像头监控场景推荐

- **默认 32**：平衡模式，文件大小合理，无明显花屏
- **如果发现花屏**：降至 28-30
- **存储紧张**：可升至 33-35，但可能偶尔出现马赛克

### Preset - 编码速度预设

Preset 控制编码器的压缩效率，**越慢预设，压缩率越高，文件越小，但耗时越长**。

| Preset | 相对速度 | 相对质量 | 相对文件大小 | 适用场景 |
|--------|---------|---------|-------------|---------|
| ultrafast | 10x | 低 | 大 40% | 快速预览 |
| superfast | 8x | 较低 | 大 30% | 快速处理 |
| veryfast | 6x | 中等 | 大 20% | 较快处理 |
| **faster** | **4x** | **较好** | **大 15%** | **快速+质量平衡** |
| **fast** | **2.5x** | **好** | **大 8%** | **推荐默认** |
| medium | 1.5x | 很好 | 基准 | 较慢但省空间 |
| slow | 1x (基准) | 优秀 | 小 5% | 高质量存档 |
| slower | 0.5x | 更优 | 小 10% | 最佳压缩 |
| veryslow | 0.25x | 最优 | 小 15% | 极限压缩 |

#### 预设选择建议

- **fast（默认）**：编码时间适中，质量良好，适合 24 小时运行
- **faster**：如果你发现编码跟不上摄像头产生速度
- **medium/slow**：如果你追求更小文件，且不在意编码时间

## 编码耗时参考

以下数据基于 Intel i5-10400 处理器，1080p 视频：

| Preset | 1小时视频编码耗时 | 预估速度 |
|--------|-----------------|---------|
| faster | ~10 分钟 | 6x 实时 |
| fast | ~15 分钟 | 4x 实时 |
| medium | ~25 分钟 | 2.4x 实时 |
| slow | ~45 分钟 | 1.3x 实时 |

**说明**：
- 6x 实时 = 编码速度是播放速度的 6 倍
- 实际速度取决于 CPU 核心数和视频内容复杂度
- 监控画面相对简单，通常比上述数据更快

## 配置方法

### 方法一：修改配置文件（推荐）

编辑宿主机上的 `config.yaml`：

```yaml
compress:
  # 分辨率: original(保持原分辨率) 或指定如 "1920x1080"
  resolution: "original"
  
  # CRF 质量（18-35，越小质量越好）
  # 28=高质量  32=平衡(默认)  35=高压缩
  crf: 32
  
  # 编码预设（faster, fast, medium, slow）
  # faster=快但大  fast=平衡(默认)  slow=慢但省空间
  preset: fast
  
  # 线程数（根据 CPU 核心数调整）
  threads: 4
```

**修改后需要重启容器生效**：
```bash
docker restart xiaomi-camera-pipeline
```

### 方法二：环境变量（优先级最高）

在 `docker-compose.yml` 中设置：

```yaml
environment:
  - COMPRESS_CRF=32
  - COMPRESS_PRESET=fast
  - COMPRESS_THREADS=4
```

**修改后需要重建容器**：
```bash
docker-compose up -d --force-recreate
```

### 方法三：运行时动态调整（仅新任务生效）

直接修改配置文件后，新处理的视频会使用新参数，正在编码的视频保持原有参数。

## 场景配置建议

### 场景 1：家庭监控（推荐默认）

```yaml
compress:
  crf: 32
  preset: fast
  resolution: "original"  # 保持摄像头原始分辨率
```

**理由**：
- CRF 32 避免花屏，同时文件大小合理
- fast 预设编码速度适中，不会积压
- 适合 24 小时持续运行

### 场景 2：重要事件存档

```yaml
compress:
  crf: 28
  preset: slow
  resolution: "1920x1080"
```

**理由**：
- CRF 28 确保高质量，无明显压缩损失
- slow 预设获得最佳压缩率
- 适合保存几天内的重要片段

### 场景 3：存储空间紧张

```yaml
compress:
  crf: 35
  preset: medium
  resolution: "1280x720"  # 降低分辨率进一步节省空间
```

**理由**：
- CRF 35 获得高压缩率
- medium 预设比 fast 节省约 10-15% 空间
- 720p 分辨率在监控场景通常足够

### 场景 4：快速处理积压视频

```yaml
compress:
  crf: 32
  preset: faster
  threads: 8  # 增加线程数
```

**理由**：
- faster 预设加快编码速度
- 更多线程充分利用多核 CPU
- 适合一次性处理大量历史视频

## 花屏问题排查

如果压缩后的视频出现花屏、马赛克：

### 1. 降低 CRF 值

```yaml
crf: 30  # 或更低 28
```

### 2. 检查源视频质量

```bash
# 使用 ffprobe 检查原始 MOV 文件
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,bit_rate -of default=noprint_wrappers=1 input.mov
```

### 3. 尝试 H.264 编码

如果 H.265 持续有问题，可改用 H.264：

```yaml
compress:
  codec: "libx264"
  crf: 23  # H.264 的 23 约等于 H.265 的 28
```

### 4. 保留原始分辨率

避免不必要的缩放：

```yaml
resolution: "original"
```

## 性能监控

观察编码是否跟得上产生速度：

```bash
# 查看容器日志
docker logs -f xiaomi-camera-pipeline

# 查看待处理文件数量
docker exec xiaomi-camera-pipeline ls -la /input | wc -l
docker exec xiaomi-camera-pipeline ls -la /output | wc -l
```

**判断标准**：
- 如果待压缩文件持续增加 → 编码太慢，需要更快的 preset 或更多线程
- 如果待压缩文件保持稳定 → 编码速度合适

## 常见问题

### Q: CRF 32 和 35 文件大小差多少？

大约 20-30%。例如 100MB 的视频：
- CRF 32：约 80-90MB
- CRF 35：约 60-70MB

### Q: preset 对质量有影响吗？

对最终画质影响很小，主要影响压缩率和编码速度。相同 CRF 下：
- slow 比 fast 文件小 5-10%
- 画质差异肉眼几乎不可见

### Q: 线程数设置多少合适？

- 4 核 CPU：threads: 2-3
- 6 核 CPU：threads: 4
- 8 核 CPU：threads: 6-8

**注意**：留 1-2 个核心给系统和上传任务

### Q: 如何测试不同参数效果？

```bash
# 提取一小段测试
docker exec xiaomi-camera-pipeline ffmpeg -i /input/test.mov -t 30 -c copy /tmp/test_30s.mov

# 用不同 CRF 测试
docker exec xiaomi-camera-pipeline ffmpeg -i /tmp/test_30s.mov -c:v libx265 -crf 28 -preset fast /tmp/test_crf28.mkv
docker exec xiaomi-camera-pipeline ffmpeg -i /tmp/test_30s.mov -c:v libx265 -crf 32 -preset fast /tmp/test_crf32.mkv

# 对比文件大小
docker exec xiaomi-camera-pipeline ls -lh /tmp/test_*.mkv
```

## 参考

- [FFmpeg x265 编码指南](https://trac.ffmpeg.org/wiki/Encode/H.265)
- [CRF 指南](https://slhck.info/video/2017/02/24/crf-guide.html)
- [x265 预设说明](https://x265.readthedocs.io/en/stable/presets.html)

---

**提示**：建议先用默认配置（CRF 32 + fast）运行一段时间，观察效果后再根据实际需求微调。
