# Dockerfile for the NamFulgor Flask Application
# Located at /home/ec2-user/namwoo_app/Dockerfile

FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Install system dependencies that might be needed by Python packages (if any)
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#  && rm -rf /var/lib/apt/lists/*

# Copy the requirements file first to leverage Docker cache
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code from the build context (namwoo_app/)
# This includes api/, config/, data/, models/, services/, utils/, run.py, __init__.py etc.
# It will also copy email_processor/ and initial_data_scripts/ if they are present
# during the build, though they are not directly used by this Flask app image.
 COPY . .

# Set environment variables for Flask (can also be set in docker-compose.yml)
ENV FLASK_APP=run:app
ENV FLASK_ENV=production
# Gunicorn settings can also be passed via CMD or a gunicorn_config.py
# ENV PYTHONUNBUFFERED=1 # Often good for seeing logs immediately

# Port the application will listen on inside the container
EXPOSE 5000

# Command to run the application using Gunicorn
# Ensure 'run:app' correctly points to your Flask app instance.
# 'run' refers to run.py, and 'app' is the Flask app object created within it.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "run:app"]