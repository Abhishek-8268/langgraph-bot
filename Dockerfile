FROM python:3.12-slim

WORKDIR /app

# Install UV using the official installer
RUN apt-get update && apt-get install -y curl && \
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    apt-get remove -y curl && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Add UV to PATH
ENV PATH="/root/.local/bin:$PATH"

# Copy everything to the container
COPY . .

# Let UV handle everything - it will create venv and install deps on first run
EXPOSE 8080

# Since you're already authenticated with gcloud, Cloud Run will handle auth automatically
# Just run with UV
CMD ["uv", "run", "python", "main.py"]
