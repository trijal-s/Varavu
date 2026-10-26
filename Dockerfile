# Varavu HTTP server for hosting. Build: docker build -t varavu .   Run: docker run -p 8000:8000 --env-file .env varavu
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements-host.txt .
RUN pip install --no-cache-dir -r requirements-host.txt

COPY backend ./backend
COPY scripts ./scripts

# Hosts (Render, Azure) set PORT; the server reads it.
EXPOSE 8000
CMD ["python", "-m", "backend.app.mcp_server.http_app"]
