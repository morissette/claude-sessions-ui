# Stage 1: Build frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.11-slim
WORKDIR /app

# Install pipenv and Python deps from lock file
COPY Pipfile Pipfile.lock ./
RUN pip install pipenv --no-cache-dir && \
    pipenv install --system --deploy

# Copy backend
COPY backend.py ./

# Copy built frontend from stage 1
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Claude data directory is volume-mounted from the host
VOLUME ["/root/.claude"]

EXPOSE 8765

CMD ["python3", "backend.py"]
