FROM node:22-bookworm-slim AS frontend-build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ENV VITE_API_BASE_URL=/api
RUN npm run build

FROM python:3.12-slim-bookworm AS api
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    KNEURA_DATA_DIR=/data
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install 'torch>=2.6,<3' 'torchvision>=0.21,<1' --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r backend/requirements.txt
RUN useradd --create-home --uid 10001 kneura && mkdir /data && chown kneura:kneura /data
COPY backend/ backend/
COPY knee_ai_inference.py ./
COPY Model/ Model/
COPY 01_MODEL/ 01_MODEL/
COPY 02_PERFORMANCE/ 02_PERFORMANCE/
USER kneura
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM nginx:stable-alpine AS web
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /app/dist /usr/share/nginx/html
EXPOSE 80
