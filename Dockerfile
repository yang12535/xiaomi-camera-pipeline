FROM jrottenberg/ffmpeg:6.1-ubuntu2204

# 安装 Python 和 locale 支持，配置 UTF-8
RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-yaml curl locales \
    && locale-gen zh_CN.UTF-8 en_US.UTF-8 C.UTF-8 \
    && update-locale LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=utf-8

WORKDIR /app

COPY pipeline.py /app/pipeline.py

RUN mkdir -p /video /input /output /logs

ENV CONFIG_FILE=/app/config.yaml
ENV STATE_DB=/app/pipeline.db
ENV LOG_DIR=/logs

VOLUME ["/video", "/input", "/output", "/logs"]

ENTRYPOINT ["python3", "/app/pipeline.py"]
