# The React app is built first; Django then serves it and the API from one image.

FROM node:24-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CACHE_DIR=/tmp/truckweather-cache
WORKDIR /app
COPY backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=frontend /build/dist frontend/dist/
WORKDIR /app/backend
# The built files are compressed here, once, with brotli and gzip; WhiteNoise
# then hands out the stored copies and nothing is compressed per request.
# The service user has uid 1000, the one a Hugging Face Space runs its
# container as; elsewhere the number does not matter.
RUN DJANGO_SECRET_KEY=build-time-only python manage.py collectstatic --noinput \
    && python -m whitenoise.compress -q ../frontend/dist \
    && useradd --uid 1000 --create-home app \
    && chown -R app:app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health/' % os.environ.get('PORT', '8000'))"
# Threads rather than more workers: a request spends its time waiting on the
# routing and weather services, not computing. With threaded workers the
# timeout is a heartbeat between the arbiter and the worker, not a cap on
# one request; it is generous so a worker busy with slow services is not
# taken for a hung one.
CMD ["sh", "-c", "exec gunicorn truckweather.wsgi --bind 0.0.0.0:${PORT:-8000} --workers 2 --threads 8 --timeout 120"]
