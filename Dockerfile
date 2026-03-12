FROM jrottenberg/ffmpeg:6.1-ubuntu2204

RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-yaml curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pipeline.py /app/pipeline.py

RUN mkdir -p /video /input /output /logs

ENV CONFIG_FILE=/app/config.yaml
ENV STATE_DB=/app/pipeline.db
ENV LOG_DIR=/logs

VOLUME ["/video", "/input", "/output", "/logs"]

ENTRYPOINT ["python3", "/app/pipeline.py"]
