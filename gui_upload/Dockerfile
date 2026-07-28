FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd \
    --create-home \
    --uid 10002 \
    --shell /usr/sbin/nologin \
    gui

# Create directories
RUN mkdir -p \
        /app/gui_upload \
        /app/incoming/new \
        /app/logs \
    && chown -R gui:gui /app

WORKDIR /app/gui_upload

# Install dependencies
COPY --chown=gui:gui gui_upload/requirements.txt /tmp/requirements.txt

USER gui

RUN python -m pip install --no-cache-dir --user \
        -r /tmp/requirements.txt

ENV PATH="/home/gui/.local/bin:${PATH}"

# Copy application
COPY --chown=gui:gui gui_upload/ /app/gui_upload/

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD curl -f http://localhost:5000/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "1900", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
