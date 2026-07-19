FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ANSIBLE_FORCE_COLOR=0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       openssh-client \
       sshpass \
       rsync \
       ca-certificates \
    && python -m pip install --no-cache-dir ansible \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY ansible/requirements.txt /tmp/requirements.txt

RUN python -m pip install \
    --no-cache-dir \
    -r /tmp/requirements.txt

COPY ansible/ /app/ansible/
COPY scripts/ /app/scripts/

RUN mkdir -p \
    /app/incoming/new \
    /app/incoming/archive \
    /app/inventory \
    /app/pos-configs \
    /app/logs \
    && useradd \
       --create-home \
       --uid 10001 \
       --shell /bin/bash \
       ansible \
    && chown -R ansible:ansible /app

USER ansible

EXPOSE 8000

CMD ["uvicorn", "runner_api:app", "--app-dir", "/app/ansible", "--host", "0.0.0.0", "--port", "8000"]
