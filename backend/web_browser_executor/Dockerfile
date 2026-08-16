FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    WEB_ARTIFACT_ROOT=/web-artifacts

RUN groupadd --gid 10003 webexecutor \
    && useradd --uid 10003 --gid webexecutor --no-create-home --shell /usr/sbin/nologin webexecutor \
    && install --directory --owner=10003 --group=10003 --mode=0750 /web-artifacts

WORKDIR /executor

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY app.py ./app.py

USER webexecutor

EXPOSE 8000
VOLUME ["/web-artifacts"]

ENTRYPOINT ["python", "/executor/app.py"]
