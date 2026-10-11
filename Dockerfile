FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY app/ ./app/

# Expose port
EXPOSE 8123

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8123"]