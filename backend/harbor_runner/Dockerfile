FROM docker:27-cli AS dockercli

FROM python:3.12.11-slim-bookworm

ARG MATRAIX_REPOSITORY=https://github.com/MatrAIx-ai/MatrAIx-Persona-8B.git
ARG MATRAIX_COMMIT=ea16f1839cde597f54b6ff06ecd47abd9779ebd5

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --filter=blob:none "${MATRAIX_REPOSITORY}" /opt/matraix \
    && git -C /opt/matraix checkout "${MATRAIX_COMMIT}" \
    && rm -rf /opt/matraix/.git

COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

RUN pip install --no-cache-dir \
      "fastapi>=0.128.0" \
      "httpx>=0.27.0" \
      "jinja2>=3.1.6" \
      "litellm>=1.83.14" \
      "packaging>=25.0" \
      "pathspec>=1.0.3" \
      "pydantic>=2.11.7" \
      "pyyaml>=6.0.2" \
      "requests>=2.32.4" \
      "rich>=14.1.0" \
      "shortuuid>=1.0.13" \
      "tenacity>=9.1.2" \
      "toml>=0.10.2" \
      "typer>=0.16.0" \
      "uvicorn>=0.38.0" \
    && pip install --no-cache-dir --no-deps \
      /opt/matraix \
      /opt/matraix/packages/playground

RUN pip install --no-cache-dir uv==0.11.6

COPY entrypoint.sh /usr/local/bin/sandowl-harbor-entrypoint
RUN chmod 0555 /usr/local/bin/sandowl-harbor-entrypoint

ENV PYTHONPATH=/workspace:/workspace/src:/workspace/environment/runtime:/workspace/environment/agents:/workspace/packages/playground/src:/workspace/application/playground
ENV DOCKER_HOST=tcp://harbor-dind:2375
ENV REMOTE_RUNNER_INLINE=0

EXPOSE 9100
ENTRYPOINT ["/usr/local/bin/sandowl-harbor-entrypoint"]
