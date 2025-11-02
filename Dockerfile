# ===============================
# 🐍 Base image with Python
# ===============================
FROM python:3.10-slim

# Prevent Python from buffering logs
ENV PYTHONUNBUFFERED=1

# Set working directory
WORKDIR /app

# Copy requirement list
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

COPY bcb77977-752f-4c46-ae2d-d236a0c7d62f.png /app/

# Copy all project files
COPY . .

# Expose default ports for FastAPI and Streamlit
EXPOSE 8000 8501

# Default command (will be overridden by docker-compose)
CMD ["bash"]
