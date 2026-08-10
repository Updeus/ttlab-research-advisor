FROM node:22-bookworm-slim AS frontend-build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_API_BASE=""
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

FROM python:3.12-slim-bookworm AS python-build
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv ${VIRTUAL_ENV}
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
WORKDIR /src
COPY backend/requirements-gcp-lock.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements-gcp-lock.txt
ENV HF_HOME=/opt/huggingface
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='sentence-transformers/all-MiniLM-L6-v2', revision='826711e54e001c83835913827a843d8dd0a1def9')"
RUN python -c "import hashlib,pathlib; root=pathlib.Path('/opt/huggingface'); h=hashlib.sha256(); [h.update(p.relative_to(root).as_posix().encode()+b'\0'+p.read_bytes()) for p in sorted(root.rglob('*')) if p.is_file()]; pathlib.Path('/opt/dense-model.sha256').write_text(h.hexdigest()+'\n')"

FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/huggingface \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TTLAB_SERVE_FRONTEND=true \
    TTLAB_FRONTEND_DIST_DIR=/app/frontend_dist
RUN groupadd --system ttlab && useradd --system --gid ttlab --home /app ttlab
COPY --from=python-build /opt/venv /opt/venv
COPY --from=python-build /opt/huggingface /opt/huggingface
COPY --from=python-build /opt/dense-model.sha256 /opt/dense-model.sha256
WORKDIR /app
COPY backend/ ./backend/
COPY --from=frontend-build /src/frontend/dist ./frontend_dist/
RUN chown -R ttlab:ttlab /app
USER ttlab
WORKDIR /app/backend
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
