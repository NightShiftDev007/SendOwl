FROM python:3.12.11-slim-bookworm

WORKDIR /app

COPY pyproject.toml /app/
RUN pip install --no-cache-dir .

COPY __init__.py server.py /app/acme_support_mcp_sample/

USER 65532:65532

EXPOSE 8000

ENTRYPOINT ["python", "-m", "acme_support_mcp_sample.server"]
