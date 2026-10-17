FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY server ./server
RUN useradd --create-home synapse
USER synapse
EXPOSE 8000
CMD ["uvicorn", "server.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
