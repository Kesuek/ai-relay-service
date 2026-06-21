FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy node code
COPY storage_node.py poller.py ./

# NAS mount point
VOLUME ["/storage"]

ENV RELAY_STORAGE_PATH=/storage
ENV RELAY_POLL_INTERVAL=8

CMD ["python", "storage_node.py"]
