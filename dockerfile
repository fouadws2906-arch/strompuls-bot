FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

ENV PYTHONPATH=/app

CMD ["python3", "-m", "uvicorn", "test_scraper:app", "--host", "0.0.0.0", "--port", "10000"]
