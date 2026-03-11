FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends inotify-tools && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pytest

WORKDIR /app
COPY . /app

# Install syncoid package in editable mode
RUN pip install --no-cache-dir -e .

# Install termux stubs into PATH
COPY tests/stubs/ /usr/local/bin/

# Default env for stubs
ENV STUB_BATTERY_PCT=80 \
    STUB_BATTERY_PLUGGED=UNPLUGGED \
    STUB_WIFI_CONNECTED=true \
    STUB_NET_TYPE=wifi

CMD ["pytest", "tests/", "-v", "--tb=short"]
