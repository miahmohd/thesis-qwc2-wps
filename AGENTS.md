# AGENTS.md

## Project overview

Thesis project: publishes a QGIS project via QWC2 web viewer with a custom Geoprocessing Client plugin that executes PyQGIS geoprocessing through a pygeoapi (OGC API - Processes) backend. Deployed as multi-service Docker Compose.

## Repository layout

| Directory | What it is |
|-----------|-----------|
| `pygeoapi/` | Python pygeoapi OGC API - Processes server. Config: `pygeoapi-config.yml`. Processes in `processes/`. |
| `qwc-custom/` | Custom QWC2 React app. Custom plugin: `js/plugins/WpsClient.jsx`. |
| `qwc-docker/` | Docker Compose orchestration (11 services). Entry via OAuth2 Proxy on `:8088`. |
| `pyqgis/` | Standalone PyQGIS scripts for data preparation (run in Docker). |
| `data/` | Geospatial source data (shapefiles, `.qgs` project files). |
| `thesis/` | LaTeX thesis document. |

## Commands

### QWC2 frontend (`qwc-custom/`)

```bash
yarn install          # install deps (uses Yarn, but scripts use npm run internally)
yarn run prod         # full production build -> output in prod/
yarn run start        # dev server on :8081 (webpack-dev-server)
npx eslint .          # lint JS/JSX
```

Note: `yarn run prod` chains `tsupdate -> themesconfig -> iconfont -> webpack --mode production`. All four steps must succeed.

### Docker Compose (`qwc-docker/`)

```bash
docker compose up -d              # start all services
docker compose up -d --build      # rebuild custom images (qwc-map-viewer, pygeoapi-service)
docker compose logs -f pygeoapi-service  # follow pygeoapi logs
```

The `qwc-map-viewer` service builds from `./qwc-custom/Dockerfile`. The `pygeoapi-service` builds from `./pygeoapi/Dockerfile`. Both are built by Compose, not pre-pushed images.

### pygeoapi (`pygeoapi/`)

No separate build step. Runs via `gunicorn pygeoapi.flask_app:APP --bind 0.0.0.0:5000` inside Docker. For local dev without Docker: `pip install -r requirements.txt && PYGEOAPI_CONFIG=pygeoapi-config.yml PYGEOAPI_OPENAPI=pygeoapi-openapi.yml pygeoapi serve`.

## Code style

### JavaScript/JSX (qwc-custom)

- ESLint 9 flat config (`eslint.config.mjs`)
- 4-space indent, semicolons required, no trailing commas
- `no-var`, `prefer-const`, `camelcase`
- `react/jsx-sort-props` (alphabetical JSX props)
- `perfectionist/sort-imports` (grouped, natural order, newlines between groups)
- No Prettier; formatting enforced by ESLint rules

### Python (pygeoapi, pyqgis)

- Black formatter (configured in `.vscode/settings.json`)
- No mypy, no type checking configured

## Architecture notes

- The gateway is **OAuth2 Proxy** (not NGINX by default; NGINX config exists but is commented out in compose).
- OAuth2 Proxy routes to upstream services by path prefix (`/processes/`, `/jobs/`, `/ows/`, `/auth/`, etc.).
- QWC services share a JWT secret (`JWT_SECRET_KEY` from `.env`).
- QGIS Server mounts `../data` as `/data`; the `.qgs` project file path must match this mount.
- pygeoapi uses TinyDB for async job management; job outputs are stored in `/tmp/pygeoapi-process-outputs` (ephemeral Docker volume).
- Process results are returned inline via `GET /jobs/{jobId}/results` (JSON). No separate output file serving.

## Testing

No automated test suites exist. Manual testing only. Verify changes by:
1. Running `npx eslint .` in `qwc-custom/`
2. Running `yarn run prod` to confirm build succeeds
3. `docker compose up -d --build` and testing in browser at `http://localhost:8088/`

## Adding a new geoprocess

1. Create a class in `pygeoapi/processes/` inheriting from `pygeoapi.process.base.BaseProcessor`
2. Add the process resource definition to `pygeoapi/pygeoapi-config.yml` under `resources:`
3. Rebuild: `docker compose up -d --build pygeoapi-service`

## OGC API - Processes endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/processes` | GET | List available processes |
| `/processes/{processId}` | GET | Describe a process (inputs/outputs schema) |
| `/processes/{processId}/execution` | POST | Execute a process (use `Prefer: respond-async` header for async) |
| `/jobs` | GET | List jobs |
| `/jobs/{jobId}` | GET | Get job status |
| `/jobs/{jobId}/results` | GET | Get job results |

## Gotchas

- Both `yarn.lock` and `package-lock.json` exist in `qwc-custom/`. Use `yarn` for dependency management.
- The `qwc2` dependency is a full framework pulled as an npm package (version-locked to `2026.02.16`). Its internal components are imported directly (e.g., `import ConfigUtils from 'qwc2/utils/ConfigUtils'`).
- `.gitignore` excludes `.env`, `LMB_grids/`, and `EVT/` data directories.
- pygeoapi Docker image is based on Ubuntu 22.04 with the official QGIS apt repo for PyQGIS access.
- The `static/config.json` in `qwc-custom` is a large runtime config (themes, services, plugins). It is NOT the webpack/build config.
- The OpenAPI document (`pygeoapi-openapi.yml`) is generated at Docker build time via `pygeoapi openapi generate`.
- Process plugins import `qgis_init.py` from the app root (`/app/`) which is on `PYTHONPATH` inside the container.
