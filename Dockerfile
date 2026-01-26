# Use Playwright Python image which includes browsers and dependencies
FROM mcr.microsoft.com/playwright/python:latest

WORKDIR /app

# Install python deps early to leverage cache
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . /app

# Ensure Playwright browsers are installed (safe no-op if present)
RUN python -m playwright install --with-deps --force

# Make entrypoint executable and ensure ownership
RUN chmod +x /app/docker-entrypoint.sh || true

# Use a non-root user provided by the base image (pwuser)
USER pwuser

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["/bin/bash"]
