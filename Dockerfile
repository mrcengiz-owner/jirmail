FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/staticfiles && chmod -R 755 /app/static /app/staticfiles

# Statik dosyalar image içinde hazır (entrypoint collectstatic ile güncellenir)
ENV SECRET_KEY=build-collectstatic-only
ENV DEBUG=False
RUN python manage.py collectstatic --noinput 2>/dev/null || true \
    && test -f /app/staticfiles/css/webmail.css || test -f /app/static/css/webmail.css

RUN chmod +x manage.py
RUN chmod +x docker-entrypoint.sh

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "60", "config.wsgi:application"]