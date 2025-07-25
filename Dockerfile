# Dockerfile

# 1. Base Image: Use an official, slim Python image.
FROM python:3.12-slim

# 2. Set Environment Variables
ENV PYTHONDONTWRITEBYTECODE=1  # Prevents python from writing .pyc files
ENV PYTHONUNBUFFERED=1         # Keeps logs visible immediately
ENV PORT=8080                  # The port Cloud Run will use

# 3. Set Working Directory
WORKDIR /app

# 4. Install uv (your package manager)
RUN pip install uv

# 5. Copy and Install Dependencies
# Copy only the dependency files first to leverage Docker's caching.
# The build will only re-install dependencies if these files change.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-cache

# 6. Copy the rest of your application code
COPY . .

# 7. Command to Run the Application
# Your app must listen on 0.0.0.0 to be accessible from outside the container.
# Cloud Run will automatically map external traffic on port 443 (HTTPS) to this port.
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]