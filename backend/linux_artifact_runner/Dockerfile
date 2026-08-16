FROM python:3.12.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LINUX_ARTIFACT_ROOT=/linux-artifacts

RUN groupadd --gid 10004 linuxrunner \
    && useradd --uid 10004 --gid linuxrunner --no-create-home --shell /usr/sbin/nologin linuxrunner \
    && install --directory --owner=10004 --group=10004 --mode=0750 /linux-artifacts

WORKDIR /runner
COPY app.py ./app.py

USER linuxrunner

EXPOSE 8000
VOLUME ["/linux-artifacts"]

ENTRYPOINT ["python", "/runner/app.py"]
