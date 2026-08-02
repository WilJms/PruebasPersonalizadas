# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:22-bookworm-slim
ARG PYTHON_IMAGE=python:3.12-slim-bookworm

FROM ${NODE_IMAGE} AS frontend-build
WORKDIR /build/frontend

ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY
ENV VITE_SUPABASE_URL=${VITE_SUPABASE_URL}
ENV VITE_SUPABASE_PUBLISHABLE_KEY=${VITE_SUPABASE_PUBLISHABLE_KEY}

COPY frontend/package*.json ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build


FROM ${PYTHON_IMAGE} AS python-build
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

RUN python -m venv "${VIRTUAL_ENV}"
WORKDIR /app

# The canonical contracts deliberately remain under specification/. Installing
# the project editable keeps contracts.py anchored at /app in the runtime image
# without duplicating the Pydantic models.
COPY pyproject.toml ./
COPY src/ ./src/
COPY specification/ ./specification/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e . "uvicorn[standard]>=0.30,<1"


FROM ${PYTHON_IMAGE} AS runtime-base
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV XDG_CACHE_HOME=/tmp/.cache
ENV PORT=8080
ENV CVA_ENVIRONMENT=cloud
ENV CVA_AUTH_MODE=supabase
ENV CVA_OBJECT_STORE_MODE=r2
ENV CVA_JOB_RUNNER_MODE=cloud_run
ENV CVA_MODEL_MODE=mock
ENV CVA_P10_ENABLED=false
ENV CVA_FRONTEND_DIST=/app/static
ENV CVA_RENDERER_MODE=weasyprint

# libmagic supports MIME inspection. The remaining libraries are the minimal
# runtime surface used by WeasyPrint when the web export adapter is enabled.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libffi8 \
        libharfbuzz-subset0 \
        libjpeg62-turbo \
        libmagic1 \
        libopenjp2-7 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 cva \
    && useradd --uid 65532 --gid 65532 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin cva

WORKDIR /app
COPY --from=python-build /opt/venv /opt/venv
COPY --from=python-build /app /app
COPY --from=frontend-build /build/frontend/dist /app/static
COPY deploy/docker-entrypoint.sh /usr/local/bin/cva-entrypoint
RUN chmod 0555 /usr/local/bin/cva-entrypoint \
    && chown -R 65532:65532 /app

USER 65532:65532
EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/cva-entrypoint"]
CMD ["web"]


# Verification-only image: keeps synthetic fixtures out of the deployable
# runtime while allowing the Stage 0 export path to run inside a container.
FROM runtime-base AS audit
COPY --chown=65532:65532 fixtures/ /app/fixtures/


# Keep the deployable image as the default (last) target.
FROM runtime-base AS runtime
