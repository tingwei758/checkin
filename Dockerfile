FROM python:3.12-slim

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHECKIN_CONFIG=/config/config.yaml \
    CHECKIN_COOKIES=/config/cookies.yaml \
    CHECKIN_DB=/data/checkin.sqlite \
    CHECKIN_HOST=0.0.0.0 \
    CHECKIN_PORT=18320

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY checkin ./checkin

VOLUME ["/config", "/data"]
EXPOSE 18320

CMD ["python", "-m", "checkin"]
