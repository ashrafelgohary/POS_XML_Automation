FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ANSIBLE_FORCE_COLOR=0
ENV PATH="/home/ansible/.local/bin:${PATH}"

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openssh-client \
        sshpass \
        rsync \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user first
RUN useradd \
    --create-home \
    --uid 10001 \
    --shell /bin/bash \
    ansible

# Create directories
RUN mkdir -p \
        /app/incoming/new \
        /app/incoming/archive \
        /app/inventory \
        /app/pos-configs \
        /app/logs \
        /app/ansible \
        /app/scripts \
    && chown -R ansible:ansible /app

WORKDIR /app

# Install Python dependencies as ansible user
USER ansible

COPY --chown=ansible:ansible ansible/requirements.txt /tmp/requirements.txt

RUN python -m pip install --no-cache-dir --user \
        ansible-core==2.16.14 \
        -r /tmp/requirements.txt

# Copy application code
COPY --chown=ansible:ansible ansible/ /app/ansible/
COPY --chown=ansible:ansible scripts/ /app/scripts/

WORKDIR /app/ansible

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "runner_api:app", "--host", "0.0.0.0", "--port", "8000"]
