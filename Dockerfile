FROM jrottenberg/ffmpeg:6.1-ubuntu2204

RUN sed -i 's/archive.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list &&     sed -i 's/security.ubuntu.com/mirrors.aliyun.com/g' /etc/apt/sources.list

RUN apt-get update && apt-get install -y     python3 python3-pip python3-yaml curl     && rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8     LC_ALL=en_US.UTF-8     PYTHONIOENCODING=utf-8

WORKDIR /app

# 复制主程序
COPY pipeline.py /app/pipeline.py

# 复制源代码模块
COPY src/ /app/src/

# 复制默认配置文件
COPY config.yaml /app/config.yaml.default

RUN mkdir -p /video /input /output /logs

ENV CONFIG_FILE=/app/config.yaml
ENV STATE_DB=/app/pipeline.db
ENV LOG_DIR=/logs

VOLUME ["/video", "/input", "/output", "/logs"]

ENTRYPOINT []
CMD ["python3", "/app/pipeline.py"]
