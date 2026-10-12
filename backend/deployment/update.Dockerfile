# Code-only patch on this release's verified Linux dependency image. Build full Dockerfile for dependency changes.
FROM medical-aesthetics-api:demo-20261013
COPY app /app/app
COPY deployment/*.py /app/deployment/
COPY migrations /app/migrations
COPY data /app/data
COPY scripts /app/scripts
