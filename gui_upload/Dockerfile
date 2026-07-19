FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/gui_upload
COPY requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt
COPY . /app/gui_upload/
RUN mkdir -p /app/incoming/new /app/incoming/archive /app/logs \
    && useradd --create-home --uid 10002 --shell /usr/sbin/nologin gui \
    && chown -R gui:gui /app
USER gui
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3)"
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "1900", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
