FROM jrottenberg/ffmpeg:6.1-ubuntu2204

RUN sed -i 's/archive.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list &&     sed -i 's/security.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list

RUN apt-get update && apt-get install -y     python3 python3-pip python3-yaml curl     && rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8     LC_ALL=en_US.UTF-8     PYTHONIOENCODING=utf-8

WORKDIR /app

# 复制主程序
COPY pipeline.py /app/pipeline.py

# 复制源代码模块
COPY src/ /app/src/

# 创建默认配置文件
RUN echo 'directories:\n  video_source: "/video"\n  merge_output: "/input"\n  compress_output: "/output"\nmerge:\n  interval_minutes: 60\n  delete_source: true\ncompress:\n  codec: "libx265"\n  resolution: "original"\n  crf: 32\n  preset: "fast"\n  threads: 4\n  audio_codec: "copy"\n  delete_source: true\nupload:\n  type: "webdav"\n  enabled: false\n  webdav_url: ""\n  webdav_user: ""\n  webdav_pass: ""\n  rate_limit: 0\n  verify: true\n  delete_after_upload: false\n  resume: true\n  max_retries: 3\n  retry_delay: 30\nlogging:\n  level: "INFO"' > /app/config.yaml.default

RUN mkdir -p /video /input /output /logs

ENV CONFIG_FILE=/app/config.yaml
ENV STATE_DB=/app/pipeline.db
ENV LOG_DIR=/logs

VOLUME ["/video", "/input", "/output", "/logs"]

ENTRYPOINT []
CMD ["python3", "/app/pipeline.py"]
