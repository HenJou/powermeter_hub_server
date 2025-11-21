FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy this service's files (hub-server.py, database.py, requirements.txt, etc)
COPY . .

# Install the Python dependencies (if any)
RUN pip install --no-cache-dir -r requirements.txt

# Install editors for debugging
RUN apt-get update \
    && apt-get install -y nano vim \
    && rm -rf /var/lib/apt/lists/*

# Expose the port the app runs on
EXPOSE 5000

# The command to run the Python server
CMD ["python3", "hub_server.py"]