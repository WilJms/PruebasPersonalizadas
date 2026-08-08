# syntax=docker/dockerfile:1.7

ARG NODE_IMAGE=node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436
ARG PYTHON_IMAGE=python:3.12-alpine3.22@sha256:a190708a2dec1bd18b1decb539f8e8f5407abaa9bf39cacda583f7f8c11db322

FROM ${NODE_IMAGE} AS frontend-build
WORKDIR /build/frontend

ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY
ENV VITE_SUPABASE_URL=${VITE_SUPABASE_URL}
ENV VITE_SUPABASE_PUBLISHABLE_KEY=${VITE_SUPABASE_PUBLISHABLE_KEY}

COPY frontend/package*.json ./
RUN npm ci
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
COPY requirements.lock ./
COPY src/ ./src/
COPY specification/ ./specification/
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
    && pip uninstall --yes pip


FROM ${PYTHON_IMAGE} AS runtime-base
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
ENV PYTHONPATH=/app/src
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
ENV CVA_REQUIRE_LIBMAGIC=true
ENV CVA_FRONTEND_DIST=/app/static
ENV CVA_RENDERER_MODE=weasyprint

# Minimal native surface and fonts used by WeasyPrint for cloud exports.
RUN apk upgrade --no-cache \
    && apk add --no-cache \
        font-dejavu \
        harfbuzz \
        libffi \
        libjpeg-turbo \
        libmagic \
        libseccomp \
        openjpeg \
        pango \
    && python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.12/ensurepip \
    && addgroup -S -g 65532 cva \
    && adduser -S -D -H -h /nonexistent -s /sbin/nologin -u 65532 -G cva cva

WORKDIR /app
COPY --from=python-build /opt/venv /opt/venv
COPY --from=python-build /app /app
COPY --from=frontend-build /build/frontend/dist /app/static
COPY deploy/docker-entrypoint.sh /usr/local/bin/cva-entrypoint
RUN chmod 0555 /usr/local/bin/cva-entrypoint \
    && chown -R root:root /app \
    && chmod -R a-w /app

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
