FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir playwright fastapi "uvicorn[standard]" \
    && playwright install --with-deps chromium
COPY scraper.py server.py plz.txt ./
ENV DATA_DIR=/data
EXPOSE 8000
# Nur ein Prozess: die Warteschlange liegt im Speicher
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
