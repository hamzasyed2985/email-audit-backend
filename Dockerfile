FROM python:3.11-slim

# Install system dependencies for Playwright


# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Install Playwright browsers
RUN playwright install --with-deps

# Copy application code
COPY . .

# Run the application
CMD ["python", "main.py"]
