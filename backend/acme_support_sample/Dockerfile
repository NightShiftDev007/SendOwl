FROM python:3.12.11-slim-bookworm

WORKDIR /app

COPY __init__.py server.py /app/acme_support_sample/

USER 65532:65532

EXPOSE 8000

ENTRYPOINT ["python", "-m", "acme_support_sample.server"]
