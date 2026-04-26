FROM python:3.13-slim

# Install system dependencies for Playwright and llama-cpp-python
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    build-essential \
    python3-dev \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install --with-deps chromium

# Copy the rest of the scraper code
COPY . .

# Default command (can be overridden in docker-compose or when running)
CMD ["python", "scripts/run_cpu_scraper.py", "--headless"]
