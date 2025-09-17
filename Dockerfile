# Dockerfile
FROM ubuntu:24.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PATH="/root/.local/bin:${PATH}"

RUN apt-get update && apt-get install -y \
    python3 \
    python3-venv \
    python3-dev \
    python3-pip \
    build-essential \
    gcc \
    gfortran \
    cmake \
    libudunits2-dev \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    libsqlite3-dev \
    libssl-dev \
    libbz2-dev \
    liblzma-dev \
    zlib1g-dev \
    libpcre2-dev \
    libcurl4-openssl-dev \
    libreadline-dev \
    libxml2-dev \
    software-properties-common \
    dirmngr \
    wget \
    unzip \
    curl \
    git

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

RUN pip install --upgrade pip setuptools wheel

WORKDIR /tmp
# Copy requirements file and install dependencies  
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN pip install redis
RUN pip install eventlet
RUN pip install rq


# Return to app directory
WORKDIR /app

# Expose the port
EXPOSE 5000
