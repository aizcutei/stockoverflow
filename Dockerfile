FROM python:3.12-slim

WORKDIR /app

# install uv for fast dependency management
RUN pip install --no-cache-dir uv

# copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# copy application code
COPY . .

# create data directory
RUN mkdir -p data

# expose port
EXPOSE 8000

# health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# run
CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
