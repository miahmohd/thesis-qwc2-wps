# QWC2 + PyWPS Docker Deployment

Docker Compose setup for deploying a custom [QWC2](https://github.com/qgis/qwc2) map viewer with a [PyWPS](https://pywps.org/) geoprocessing server, backed by QGIS Server and the QWC Services ecosystem.

## Architecture

All services are orchestrated via Docker Compose behind an NGINX reverse proxy exposed on port **8088**.

| Service | Description |
|---------|-------------|
| `qwc-api-gateway` | NGINX reverse proxy (entry point, port 8088) |
| `qwc-map-viewer` | Custom QWC2 web map viewer |
| `qwc-qgis-server` | QGIS Server (WMS/WFS) |
| `qwc-ogc-service` | OGC proxy service |
| `wps-service` | PyWPS geoprocessing server (Flask + Gunicorn) |
| `qwc-postgis` | PostgreSQL/PostGIS database |
| `qwc-config-service` | Configuration generator |
| `qwc-admin-gui` | Administration interface |
| `qwc-auth-service` | Authentication service (JWT) |
| `qwc-feature-info-service` | Feature info service |
| `qwc-legend-service` | Legend service |

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (v20.10+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2.0+)

## Project Structure

```
qwc-docker/             # This directory - Docker orchestration
├── docker-compose.yml
├── .env                # JWT secret key
├── api-gateway/
│   └── nginx.conf      # NGINX routing configuration
├── pg_service.conf     # PostgreSQL connection config
└── volumes/
    ├── config-in/      # Input configuration for config generator
    ├── config/         # Generated service configurations
    ├── qgs-resources/  # QGIS project files (.qgs)
    ├── qwc2/           # Custom QWC2 viewer build (assets + dist)
    ├── wps-logs/       # PyWPS log files
    ├── wps-outputs/    # PyWPS process outputs
    └── wps-workdir/    # PyWPS temporary working directory
```

## Getting Started

### 1. Clone the repository

```bash
git clone --recurse-submodules <repository-url>
cd thesis/qwc-docker
```

### 2. Configure environment

The `.env` file contains the JWT secret used for authentication across services. A default value is provided, but you should generate a new one for production:

```bash
# Generate a new secret
python3 -c "import secrets; print(secrets.token_hex(48))"
```

Update the `JWT_SECRET_KEY` value in `.env` with the generated secret.

### 3. Start the services

```bash
docker compose up -d
```

This will:
1. Start the PostgreSQL database
2. Run database migrations
3. Start QGIS Server
4. Build and start the PyWPS service from `../pywps`
5. Start all QWC2 microservices
6. Start the NGINX gateway on port 8088

### 4. Generate configuration

<!-- TODO rewrite doc -->
- go to the admin panel /qwc_admin,(default admin credentials: username admin, password admin, requires password change on first login).
- run auto "Generate service configuration"

### 5. Access the application

| URL | Description |
|-----|-------------|
| http://localhost:8088/ | Map viewer |
| http://localhost:8088/wps | WPS service endpoint |
| http://localhost:8088/qwc_admin | Admin GUI |

## Development

### Hot-reload for PyWPS

The `wps-service` is configured with Docker Compose Watch for live-reloading during development. Changes to files in `../pywps` are automatically synced into the container:

```bash
docker compose watch
```

Alternatively, the service runs with `gunicorn --reload` so changes to Python files will restart the worker automatically.

### View logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f wps-service
```

### Rebuild the PyWPS service

After changing dependencies in `../pywps/requirements.txt`:

```bash
docker compose up --build
```

## Stopping the services

```bash
# Stop all services
docker compose down

# Stop and remove volumes (WARNING: deletes database data)
docker compose down -v
```

## Adding QGIS Projects

Place `.qgs` project files in `volumes/qgs-resources/scan` and then regenerate the configuration.

