FROM python:3.14-slim

LABEL org.opencontainers.image.description="PowerMeter Hub Server."

ENV PORT=5000

# Set the working directory inside the container
WORKDIR /app

# Copy this service's files (hub-server.py, database.py, requirements.txt, etc)
COPY . .

# Install the Python dependencies (if any) and editors for debugging
RUN apt-get update \
    && apt-get install -y nano vim \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

# Expose the port the app runs on
EXPOSE $PORT

# The command to run the Python server
CMD ["python3", "hub_server.py"]