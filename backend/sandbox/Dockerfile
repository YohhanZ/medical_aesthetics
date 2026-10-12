FROM python:3.12.10-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANGSMITH_TRACING=false
WORKDIR /worker
COPY sandbox/requirements.lock /build/requirements.lock
RUN pip install --no-cache-dir --no-deps --index-url https://mirrors.aliyun.com/pypi/simple -r /build/requirements.lock && pip check && rm -rf /build
LABEL medical.consultation.worker="v1"
COPY app /worker/app
USER 65532:65532
ENTRYPOINT ["python", "-I", "-u", "-c", "import runpy,sys;sys.path.insert(0,'/worker');runpy.run_module('app.sandbox_worker',run_name='__main__')"]
