FROM python:3.10-slim

WORKDIR /app

# Abhängigkeiten kopieren und installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Anwendungscode kopieren
COPY . .

# FastAPI via Uvicorn starten
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
