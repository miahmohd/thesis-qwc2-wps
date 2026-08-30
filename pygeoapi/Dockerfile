# PyQGIS + pygeoapi OGC API - Processes server
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
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# ── Environment variables required by PyQGIS ─────────────────────────────────
ENV QGIS_PREFIX_PATH=/usr
ENV LD_LIBRARY_PATH=/usr/lib/qgis:${LD_LIBRARY_PATH}
ENV PYTHONPATH=/usr/share/qgis/python:/usr/share/qgis/python/plugins:${PYTHONPATH}
ENV QT_QPA_PLATFORM=offscreen
ENV DISPLAY=:99

# ── pygeoapi configuration ───────────────────────────────────────────────────
ENV PYGEOAPI_CONFIG=/app/pygeoapi-config.yml
ENV PYGEOAPI_OPENAPI=/app/pygeoapi-openapi.yml

WORKDIR /app

# ── Install Python dependencies ───────────────────────────────────────────────
COPY requirements.txt ./requirements.txt
RUN pip3 install --no-cache-dir -r ./requirements.txt

# ── Copy application code ─────────────────────────────────────────────────────
COPY . .

# ── Generate OpenAPI document ─────────────────────────────────────────────────
RUN pygeoapi openapi generate ${PYGEOAPI_CONFIG} --output-file ${PYGEOAPI_OPENAPI}

# Create necessary directories
RUN mkdir -p /tmp/pygeoapi-process-outputs

# ── Expose port and run ───────────────────────────────────────────────────────
EXPOSE 5000

RUN chmod +x ./entrypoint.sh
ENTRYPOINT ["./entrypoint.sh"]
