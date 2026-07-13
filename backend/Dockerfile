# 1. THIS MUST BE THE VERY FIRST LINE (Use whatever your original FROM was)
FROM python:3.12-slim 

# (You probably have a WORKDIR line here, like WORKDIR /app, keep it!)
WORKDIR /app

# 2. NOW you can install the system build tools
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 3. Then copy your files and run pip
COPY . .

# NOW run the pip install, so hatchling can see your code directories
RUN pip install --no-cache-dir -e ".[standard]" --break-system-packages || pip install --no-cache-dir -e .

RUN playwright install chromium --with-deps