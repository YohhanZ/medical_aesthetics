FROM docker:27.5.1-cli AS dockercli
# Build sandbox/Dockerfile first. Both stages use the same Python 3.12 base/locked runtime.
FROM medical-consultation-sandbox:local
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANGSMITH_TRACING=false
WORKDIR /app
USER 0
LABEL medical.consultation.worker="api-not-worker"
COPY deployment/requirements.lock /build/requirements.lock
RUN pip install --no-cache-dir --no-deps --index-url https://mirrors.aliyun.com/pypi/simple -r /build/requirements.lock && pip check && rm -rf /build
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY app /app/app
COPY deployment/*.py /app/deployment/
COPY migrations /app/migrations
COPY data /app/data
COPY scripts /app/scripts
USER 65532:65532
ENTRYPOINT []
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--no-access-log"]
