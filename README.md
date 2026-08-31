# Web Publication of a QGIS Project with OGC API - Processes Integration

Thesis project demonstrating the publication of a QGIS project on the web using [QWC2](https://github.com/qgis/qwc2), integrated with an OGC API - Processes service that enables execution of custom geoprocessing algorithms built with PyQGIS.

## Overview

The system publishes geospatial data through QGIS Server and exposes it via a QWC2 web map viewer. A custom **Geoprocessing Client plugin** in the viewer allows users to discover and execute geoprocessing operations served by a [pygeoapi](https://pygeoapi.io/) backend. The processes leverage PyQGIS to perform geospatial analysis and transformations on the server side, and update the live QGIS project with the results.

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│               OAuth2 Proxy / NGINX Reverse Proxy (:8088)         │
├──────────────┬──────────────┬──────────────┬─────────────────────┤
│  QWC2 Map    │  QGIS Server │  QWC         │  pygeoapi           │
│  Viewer      │  (WMS/WFS)   │  Services    │  (OGC API -         │
│              │              │              │   Processes)        │
├──────────────┴──────────────┴──────────────┴─────────────────────┤
│                        PostgreSQL / PostGIS                      │
└──────────────────────────────────────────────────────────────────┘
```

The QWC2 viewer includes a custom **Geoprocessing Client plugin** that communicates with the pygeoapi server using the [OGC API - Processes](https://ogcapi.ogc.org/processes/) REST/JSON protocol to run geoprocessing tasks directly from the browser.

## Repository Structure

```
thesis-qwc2-wps/
├── pygeoapi/       # pygeoapi OGC API - Processes server (PyQGIS-based processes)
├── pyqgis/         # Standalone PyQGIS scripts for data preparation
├── qwc-custom/     # Custom QWC2 build with Geoprocessing Client plugin
├── qwc-docker/     # Docker Compose deployment orchestration
├── data/           # Geospatial source data (shapefiles, QGIS project files)
└── thesis/         # LaTeX thesis document
```

## Components

### pygeoapi/

A [pygeoapi](https://pygeoapi.io/) server exposing geoprocessing algorithms as OGC API - Processes endpoints. Processes are Python classes inheriting from `pygeoapi.process.base.BaseProcessor` and registered in `pygeoapi-config.yml`. All processes run asynchronously, with job state managed by TinyDB and outputs stored in an ephemeral Docker volume.

The server is built on Ubuntu 22.04 with the official QGIS apt repository, giving processes full access to PyQGIS (headless, via Xvfb). A single Gunicorn worker with 4 threads handles requests to avoid Qt fork-safety issues.

Key features:
- OGC API - Processes REST/JSON protocol
- Asynchronous execution with job polling
- Full PyQGIS access inside process handlers
- Config-driven process registration (`pygeoapi-config.yml`)
- Extensible: new processes are added as Python classes in `processes/`

### qwc-custom/

A custom [QWC2](https://github.com/qgis/qwc2) web mapping application extended with a **Geoprocessing Client plugin** (`js/plugins/WpsClient.jsx`). The plugin provides a sidebar UI for:

- Discovering available processes (`GET /processes`)
- Rendering a dynamic input form from process schema metadata
- Executing processes with async polling
- Displaying results inline

See [`qwc-custom/README.md`](qwc-custom/README.md) for plugin architecture, configuration, and development guide.

### qwc-docker/

Docker Compose setup orchestrating all 11 services. The entry point is an **OAuth2 Proxy** (with AWS Cognito OIDC) or, for development without authentication, a commented-out NGINX reverse proxy — both exposed on port **8088**.

See [`qwc-docker/README.md`](qwc-docker/README.md) for deployment instructions.

### pyqgis/

Standalone PyQGIS scripts used for offline data preparation (run inside a Docker container with QGIS available). Not part of the live service stack.

---

## Geoprocessing Processes

The following processes are published by the pygeoapi server as the initial proof-of-concept.

### `lmb-grid-statistics`

Spatially joins emergency response event data to an LMB (Lombardia) grid polygon layer, computes per-cell event counts and average response times, applies a graduated choropleth symbology, and writes the result as a new layer into the live QGIS project.

**Inputs**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `layer_name` | string | yes | — | Name for the output layer |
| `lmbgrid` | string | no | `LMB0A` | Grid area to process (`LMB0A`–`LMB5A`) |
| `color_by` | string | no | `evt_count` | Attribute to use for symbology (`evt_count` or `avg_resp_s`) |
| `classification_method` | string | no | `Natural Breaks (Jenks)` | Classification method (`Equal Count` or `Natural Breaks (Jenks)`) |
| `day_filter` | string | no | `all` | Filter events by day type (`all`, `weekday`, `weekend`) |
| `months` | string | no | `1,2,...,12` | Comma-separated list of months to include |
| `project` | string | no | `lmb_grids` | QGIS project to update |

**Output:** `response` — a summary message with event counts and timing statistics.

**What it does:**
1. Copies the selected LMB shapefile from `/data/LMB_grids/` to `/data/layer/`
2. Loads it as a `QgsVectorLayer` and adds `evt_count` and `avg_resp_s` attribute fields
3. Reads all `.tab` event files from `/data/EVT/` into a pandas DataFrame; parses SAS-format timestamps
4. Optionally filters events by day of week and/or month
5. Spatially matches each event point to a grid polygon via `QgsSpatialIndex`; accumulates counts and response time deltas
6. Writes attribute values back to the shapefile
7. Applies a 5-class YlOrRd graduated choropleth symbology (Jenks or Equal Count)
8. Adds the layer to the QGIS project at `/data/scan/{project}.qgs`
9. Calls the QWC2 config service to regenerate the viewer configuration

---

### `lmb-sliding-window`

Runs a temporal sliding-window analysis over the event dataset, computing event counts per grid polygon for each time window. Stores the results in a GeoPackage with a temporal SQL view and configures the QGIS Server WMS TIME dimension so the layer can be animated in the viewer.

**Inputs**

| Name | Type | Required | Default | Description |
|------|------|----------|---------|-------------|
| `layer_name` | string | yes | — | Name for the output layer |
| `lmbgrid` | string | no | `LMB0A` | Grid area to process (`LMB0A`–`LMB5A`) |
| `window_size` | integer | no | `30` | Time window width in days |
| `slide_size` | integer | no | `30` | Step between windows in days |
| `project` | string | no | `lmb_grids_gpkg` | QGIS project to update |

**Output:** `response` — a summary message with window count and event statistics.

**What it does:**
1. Loads the polygon grid from `/data/layer/lmb_grids.gpkg` for the chosen `lmbgrid` layer
2. Reads and spatially indexes all event points from `/data/EVT/`
3. Matches events to polygons in a single pass, collecting `(fid, timestamp)` pairs
4. Generates sliding time windows from the dataset's temporal extent
5. For each window, counts events per polygon and writes to a `historical_data` table in the GeoPackage
6. Creates a `temporal_layer` SQL view joining geometry with historical counts; registers it in GeoPackage metadata
7. Configures the QGIS Server WMS TIME dimension on the layer (ISO 8601 `window_start`/`window_end`)
8. Applies a 5-class YlOrRd graduated choropleth symbology
9. Adds the temporal layer to the QGIS project and calls the QWC2 config service

---

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (v20.10+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2.0+)
- [Node.js](https://nodejs.org/) and [Yarn](https://yarnpkg.com/) (for QWC2 development builds only)

### Quick Start

1. Clone the repository:

       git clone <repository-url>
       cd thesis-qwc2-wps

2. Configure environment secrets (see [`qwc-docker/README.md`](qwc-docker/README.md)):

       cp qwc-docker/.env.example qwc-docker/.env
       # Edit qwc-docker/.env with your secrets

3. Build and start all services:

       cd qwc-docker
       docker compose up -d --build

4. Generate the QWC2 service configuration:
   - Open `http://localhost:8088/qwc_admin` (default credentials: `admin` / `admin`, change on first login)
   - Click **Generate service configuration**

5. Access the application:

   | URL | Description |
   |-----|-------------|
   | http://localhost:8088/ | Map viewer |
   | http://localhost:8088/processes | OGC API - Processes endpoint |
   | http://localhost:8088/qwc_admin | Admin GUI |

## Technologies

| Component | Technology |
|-----------|-----------|
| Map viewer | QWC2 (React, OpenLayers) |
| Map server | QGIS Server 3.40 (WMS/WFS) |
| Geoprocessing server | pygeoapi + Flask + Gunicorn |
| Processing engine | PyQGIS (headless QGIS via Xvfb) |
| Database | PostgreSQL / PostGIS |
| Gateway | OAuth2 Proxy (OIDC) / NGINX (dev) |
| Containerization | Docker Compose |

## Resources

- https://docs.qwc.app/master/
- https://pygeoapi.io/
- https://docs.ogc.org/is/18-062r2/18-062r2.html
- https://github.com/geopython/pygeoapi
- https://github.com/qgis/qwc2-demo-app
