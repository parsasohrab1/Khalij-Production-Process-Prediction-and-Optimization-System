FROM python:3.10-slim

WORKDIR /app
RUN pip install --no-cache-dir influxdb-client==1.44.0
COPY infra/influxdb/init_buckets.py ./init_buckets.py
CMD ["python", "init_buckets.py"]
