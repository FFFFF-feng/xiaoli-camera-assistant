FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY mobile/package.json mobile/package-lock.json ./mobile/
RUN cd mobile && npm ci
COPY mobile ./mobile
COPY assets ./assets
RUN cd mobile && npm run build

FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/src
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[mobile]' && useradd --uid 10001 --create-home xiaoli
COPY knowledge ./knowledge
COPY --from=frontend /build/mobile/dist ./mobile/dist
RUN chmod -R a+rX /app/src /app/knowledge /app/mobile/dist \
    && mkdir -p /app/data && chown -R xiaoli:xiaoli /app/data
USER xiaoli
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
CMD ["uvicorn", "camera_assistant.web_app:from_env", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers"]

# Optional CPU detector image. Default compose explicitly selects runtime above.
FROM runtime AS dino
USER root
RUN pip install --no-cache-dir torch==2.10.0 torchvision==0.25.0 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir transformers==5.19.0
USER xiaoli
RUN python -m vision_lab_tool.detectors.prepare --detector grounding_dino --revision a2bb814dd30d776dcf7e30523b00659f4f141c71
USER root
RUN mkdir -p /opt/dino && cp -r /app/data/vision_lab/model_cache/grounding-dino-tiny /opt/dino/
USER xiaoli
ENV CAMERA_AI_DETECTOR_PYTHON=/usr/local/bin/python \
    CAMERA_AI_DETECTOR_WEIGHTS_PATH=/opt/dino/grounding-dino-tiny \
    CAMERA_AI_DETECTOR_DEVICE=cpu \
    CAMERA_AI_DETECTOR_REVISION=a2bb814dd30d776dcf7e30523b00659f4f141c71
CMD ["sh", "-c", "python -m vision_lab_tool.detectors.prepare --detector grounding_dino --probe-only && exec uvicorn camera_assistant.web_app:from_env --factory --host 0.0.0.0 --port 8080 --no-access-log --no-proxy-headers"]
