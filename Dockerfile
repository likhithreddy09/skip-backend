FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APP_ENV=production PORT=8000
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --create-home api && chown -R api /app
USER api

EXPOSE 8000
CMD gunicorn --workers 2 --threads 4 --timeout 30 --bind 0.0.0.0:${PORT} wsgi:app
