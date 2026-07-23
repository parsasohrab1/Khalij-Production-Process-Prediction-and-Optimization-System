FROM python:3.10-slim

WORKDIR /app

COPY services/prediction/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY services/prediction/app ./app

ENV PYTHONPATH=/app
EXPOSE 8003

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
