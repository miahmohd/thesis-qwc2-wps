# QWC2 + pygeoapi Docker Deployment

Docker Compose setup for deploying a custom [QWC2](https://github.com/qgis/qwc2) map viewer with a [pygeoapi](https://pygeoapi.io/) OGC API - Processes server, backed by QGIS Server and the QWC Services ecosystem.

## Architecture

All services are orchestrated via Docker Compose behind a reverse proxy exposed on port **8088**. Two proxy options are available:

- **Production / authenticated**: `auth-proxy` (OAuth2 Proxy with OIDC). Users authenticate via an OIDC provider before reaching backend services.
- **Development / unauthenticated**: `qwc-api-gateway` (NGINX). Enabled by swapping the commented blocks in `docker-compose.yml` (see [Development without authentication](#development-without-authentication)).

### Services

| Service | Description |
|---------|-------------|
| `auth-proxy` | OAuth2 Proxy — reverse proxy + OIDC authentication (entry point, port 8088) |
| `qwc-map-viewer` | Custom QWC2 web map viewer (built from `../qwc-custom`) |
| `qwc-qgis-server` | QGIS Server 3.40 (WMS/WFS), mounts `../data:/data` |
| `qwc-ogc-service` | OGC proxy service |
| `pygeoapi-service` | pygeoapi OGC API - Processes server (built from `../pygeoapi`) |
| `qwc-postgis` | PostgreSQL/PostGIS database |
| `qwc-config-service` | Configuration generator (produces runtime configs for QWC services) |
| `qwc-admin-gui` | Administration interface |
| `qwc-auth-service` | Authentication service (JWT, used internally by QWC services) |
| `qwc-feature-info-service` | Feature info service |
| `qwc-legend-service` | Legend service |

### URL Routing

| Path prefix | Upstream service |
|-------------|-----------------|
| `/processes/`, `/jobs/`, `/openapi/` | `pygeoapi-service:5000` |
| `/ows/` | `qwc-ogc-service:9090` |
| `/auth/` | `qwc-auth-service:9090` |
| `/qwc_admin/` | `qwc-admin-gui:9090` |
| `/api/v1/featureinfo/` | `qwc-feature-info-service:9090` |
| `/api/v1/legend/` | `qwc-legend-service:9090` |
| `/` (catch-all) | `qwc-map-viewer:9090` |

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (v20.10+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2.0+)

## Project Structure

```
qwc-docker/
├── docker-compose.yml
├── .env                    # Secrets (JWT key, OAuth2 Proxy credentials)
├── api-gateway/
│   └── nginx.conf          # NGINX routing config (used when auth-proxy is disabled)
├── pg_service.conf         # PostgreSQL connection config
└── volumes/
    ├── config-in/          # Input configuration for the config generator
    ├── config/             # Generated service configurations (output)
    ├── qgs-resources/      # QGIS project files (.qgs)
    └── qgis-server-plugins/ # Custom QGIS Server plugins
```

## Getting Started

### 1. Clone the repository

```bash
git clone <repository-url>
cd thesis-qwc2-wps/qwc-docker
```

### 2. Configure environment

Copy and edit the `.env` file:

```bash
cp .env.example .env
```

The `.env` file holds secrets used across services:

| Variable | Description |
|----------|-------------|
| `JWT_SECRET_KEY` | Shared JWT secret for QWC services. Generate with: `python3 -c "import secrets; print(secrets.token_hex(48))"` |
| `OAUTH_COOKIE_SECRET` | Cookie encryption secret for OAuth2 Proxy |
| `OAUTH_CLIENT_SECRET` | OIDC client secret from your identity provider |

### 3. Build and start all services

```bash
docker compose up -d --build
```

This builds the two custom images (`qwc-map-viewer` from `../qwc-custom` and `pygeoapi-service` from `../pygeoapi`) and starts all services. Subsequent starts without code changes can omit `--build`.

### 4. Generate QWC2 service configuration

- Open `http://localhost:8088/qwc_admin` (default credentials: `admin` / `admin`, you will be prompted to change the password on first login)
- Click **Generate service configuration**

### 5. Access the application

| URL | Description |
|-----|-------------|
| http://localhost:8088/ | Map viewer |
| http://localhost:8088/processes | OGC API - Processes endpoint |
| http://localhost:8088/qwc_admin | Admin GUI |

---

## Development

### Development without authentication

For local development, replace the `auth-proxy` service with the plain NGINX reverse proxy to skip OIDC. In `docker-compose.yml`:

1. **Comment out** the `auth-proxy` service block.
2. **Uncomment** the `qwc-api-gateway` service block.

The NGINX gateway uses `api-gateway/nginx.conf` and exposes the application on port **8088**.

### Hot-reload for pygeoapi

The `pygeoapi-service` is configured with Docker Compose Watch. Changes to files in `../pygeoapi/` (excluding `venv/` and `__pycache__/`) trigger an automatic rebuild:

```bash
docker compose watch
```

### View logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f pygeoapi-service
docker compose logs -f qwc-map-viewer
```

### Rebuild a single service

After changing Python dependencies in `../pygeoapi/requirements.txt` or the frontend in `../qwc-custom/`:

```bash
docker compose up -d --build pygeoapi-service
docker compose up -d --build qwc-map-viewer
```

---

## Stopping the Services

```bash
# Stop all services (preserves volumes)
docker compose down

# Stop and remove all volumes (WARNING: deletes database data)
docker compose down -v
```

---

## Adding QGIS Projects

Place `.qgs` project files in `volumes/qgs-resources/scan/`, then regenerate the configuration from the admin panel.

## Adding a New Geoprocess

1. Create a Python class in `../pygeoapi/processes/` inheriting from `pygeoapi.process.base.BaseProcessor`
2. Register it under `resources:` in `../pygeoapi/pygeoapi-config.yml`
3. Rebuild the pygeoapi service:

   ```bash
   docker compose up -d --build pygeoapi-service
   ```
