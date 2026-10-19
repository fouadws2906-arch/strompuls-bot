FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias del sistema y de Python
RUN pip install --no-cache-dir playwright fastapi "uvicorn[standard]" \
    && playwright install --with-deps chromium

# Copiar archivos
COPY scraper.py server.py plz.txt ./

# Indicar el directorio para la base de datos
ENV DATA_DIR=/data
EXPOSE 8000

# Lanzar el servidor en 0.0.0.0
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port 8080 --workers 1"]
