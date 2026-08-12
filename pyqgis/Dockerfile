# PyQGIS Docker Image
# Based on Ubuntu 22.04 LTS with QGIS official repository

FROM ubuntu:22.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/Rome

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    wget \
    gnupg \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Add QGIS official repository ─────────────────────────────────────────────
RUN wget -qO /etc/apt/keyrings/qgis-archive-keyring.gpg \
        https://download.qgis.org/downloads/qgis-archive-keyring.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/qgis-archive-keyring.gpg] \
        https://qgis.org/ubuntu jammy main" \
        > /etc/apt/sources.list.d/qgis.list

# ── Install QGIS + Python bindings ───────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    qgis-server \
    spawn-fcgi \
    xauth \
    xvfb \
    python3-qgis \
    qgis-plugin-grass \
    python3-pip \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# ── Environment variables required by PyQGIS ─────────────────────────────────
ENV QGIS_PREFIX_PATH=/usr
ENV LD_LIBRARY_PATH=/usr/lib/qgis:${LD_LIBRARY_PATH}
ENV PYTHONPATH=/usr/share/qgis/python:/usr/share/qgis/python/plugins:${PYTHONPATH}
ENV QT_QPA_PLATFORM=offscreen
ENV DISPLAY=:99

# ── Install Python dependencies ───────────────────────────────────────────────
# Copy requirements first for better layer caching
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

# ── Copy application scripts ──────────────────────────────────────────────────
WORKDIR /app
COPY *.py .

# ── Entrypoint ────────────────────────────────────────────────────────────────
# Default script is lmb_grids.py. Override the CMD to run a different script:
#   docker run <image> shp_to_gpkg.py
#   docker run <image> transform.py
ENTRYPOINT ["python3"]
CMD ["lmb_grids.py"]