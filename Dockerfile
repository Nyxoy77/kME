FROM python:3.11-slim

# Install system libraries required for Discord Voice
RUN echo "force-rebuild" && apt-get update && apt-get install -y \
    ffmpeg \
    libopus-dev \
    libffi-dev \
    libsodium-dev \
    && rm -rf /var/lib/apt/lists/*
    
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your bot files
COPY . .

# Start bot
CMD ["python", "bot.py"]
