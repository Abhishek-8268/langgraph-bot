# Dockerfile
FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy files
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

# Copy application
COPY . .

# Expose port
EXPOSE 8000

# Default environment variables (can be overridden)
ENV REDIS_HOST=localhost
ENV REDIS_PORT=6379
ENV SESSION_TTL_HOURS=1
ENV REDIS_MAX_CONNECTIONS=50

# Run application
CMD ["uv", "run", "python", "main.py"]
