FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# Default: run the monitor in daemon mode
# To run the API server instead: docker run ... family-glucose-monitor uvicorn src.api_server:app --host 0.0.0.0 --port 8080
CMD ["python", "-m", "src.main"]
