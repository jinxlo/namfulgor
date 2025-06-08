# Dockerfile for the Email Processor Service
# Located at /home/ec2-user/namwoo_app/email_processor/Dockerfile

FROM python:3.9-slim

WORKDIR /app

# Ensure output is not buffered
ENV PYTHONUNBUFFERED=1

# Copy requirements.txt first for Docker caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the email_processor's code (e.g., processor.py)
COPY . .

# Ensure the data directory for processed UIDs exists (though volume mount is primary)
RUN mkdir -p /app/data

# Command to run the processor script
CMD ["python", "processor.py"]