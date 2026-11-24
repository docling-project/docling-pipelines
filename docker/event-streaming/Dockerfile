# Install Python dependencies before copying application source.
FROM registry.access.redhat.com/ubi9/python-312 AS backend-builder

USER root
WORKDIR /opt/app-root

RUN pip install --no-cache-dir uv

# Cache dependencies separately from backend source changes.
COPY pyproject.toml uv.lock ./
COPY slim/pyproject.toml slim/uv.lock ./slim/
ARG BUILD_PROFILE=cpu
# Select CPU-only wheels, locked GPU dependencies, or the slim dependency set with Kafka support.
RUN uv venv --python /usr/bin/python3.12 /opt/docpipe-venv && \
    case "$BUILD_PROFILE" in \
        gpu) \
            uv export --locked --no-dev --extra event-streaming --no-emit-project \
                --format pylock.toml --output-file pylock.toml && \
            uv pip install --python /opt/docpipe-venv/bin/python \
                --no-cache --require-hashes -r pylock.toml ;; \
        cpu) \
            uv export --locked --no-dev --extra event-streaming --no-emit-project \
                --prune torch --prune torchvision \
                --format pylock.toml --output-file pylock.toml && \
            uv pip install --python /opt/docpipe-venv/bin/python \
                --no-cache --require-hashes -r pylock.toml && \
            uv export --locked --no-dev --extra event-streaming --no-emit-project --no-hashes \
                --only-emit-package torch --only-emit-package torchvision \
                --format requirements.txt --output-file requirements-cpu.txt && \
            uv pip install --python /opt/docpipe-venv/bin/python \
                --no-cache --torch-backend=cpu -r requirements-cpu.txt ;; \
        slim) \
            uv export --project slim --locked --no-dev --extra event-streaming --no-emit-project \
                --format pylock.toml --output-file pylock.toml && \
            uv pip install --python /opt/docpipe-venv/bin/python \
                --no-cache --require-hashes -r pylock.toml ;; \
        *) echo "BUILD_PROFILE must be cpu, gpu, or slim" >&2; exit 1 ;; \
    esac

# Run the API and serve the built UI as a non-root user.
FROM registry.access.redhat.com/ubi9/python-312-minimal

USER root
# Native Python extensions need GL, LDAP and OpenMP.
RUN microdnf install -y --nodocs --setopt=install_weak_deps=0 \
        mesa-libGL openldap libgomp && \
    microdnf clean all && \
    useradd -m -u 1000 docpipe

COPY --from=backend-builder --chown=1000:0 /opt/docpipe-venv/ /opt/docpipe-venv/
COPY --chown=1000:0 src/docpipe/ /opt/app-root/src/docpipe/

# Allow runtime downloads and storage writes under the supported data paths.
RUN mkdir -p \
        /opt/app-root/nltk_data \
        /opt/app-root/data \
        /opt/app-root/src/data \
        /data && \
    chown -R docpipe:root \
        /opt/app-root/nltk_data \
        /opt/app-root/data \
        /opt/app-root/src/data \
        /data

WORKDIR /opt/app-root/src
USER docpipe
ENV PYTHONPATH=/opt/app-root/src
ENV VIRTUAL_ENV=/opt/docpipe-venv
ENV PATH=/opt/docpipe-venv/bin:$PATH

EXPOSE 8080
CMD ["python", "-m", "uvicorn", "docpipe.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
