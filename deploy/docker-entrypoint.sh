#!/bin/sh
set -eu

mode="${1:-${CVA_PROCESS_MODE:-web}}"
if [ "$#" -gt 0 ]; then
    shift
fi

if [ "${CVA_P10_ENABLED:-false}" = "true" ]; then
    echo "Refusing P10 because Stage 1 is closed-context only" >&2
    exit 78
fi

case "${mode}" in
    web)
        exec python -m uvicorn \
            "${CVA_ASGI_APP:-comprehension_verification.web.app:app}" \
            --host 0.0.0.0 \
            --port "${PORT:-8080}" \
            --no-access-log \
            "$@"
        ;;
    worker)
        exec python -m "${CVA_WORKER_MODULE:-comprehension_verification.web.worker}" "$@"
        ;;
    *)
        echo "Unsupported process mode: ${mode}; expected web or worker" >&2
        exit 64
        ;;
esac
