# Web Publication of a QGIS Project with OGC WPS Integration

Thesis project demonstrating the publication of a QGIS project on the web using [QWC2](https://github.com/qgis/qwc2), integrated with an OGC Web Processing Service (WPS) that enables execution of custom geoprocessing algorithms built with PyQGIS.

## Overview

The system publishes geospatial data through QGIS Server and exposes it via a QWC2 web map viewer. A custom WPS Client plugin in the viewer allows users to discover and execute geoprocessing operations served by a PyWPS backend. The WPS processes leverage PyQGIS to perform geospatial analysis and transformations on the server side.

### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                   NGINX Reverse Proxy (:8088)                │
├──────────────┬──────────────┬──────────────┬─────────────────┤
│  QWC2 Map    │  QGIS Server │  QWC         │  PyWPS          │
│  Viewer      │  (WMS/WFS)   │  Services    │  Server         │
│              │              │              │  (PyQGIS-based) │
├──────────────┴──────────────┴──────────────┴─────────────────┤
│                     PostgreSQL / PostGIS                     │
└──────────────────────────────────────────────────────────────┘
```

The QWC2 viewer includes a custom **WPS Client plugin** that communicates with the PyWPS server using the OGC WPS 1.0.0 protocol (GetCapabilities, DescribeProcess, Execute) to run geoprocessing tasks directly from the browser.

## Repository Structure

```
thesis/
├── pywps/          # PyWPS Flask server exposing WPS geoprocessing endpoints
├── qwc-custom/     # Custom QWC2 build with WPS Client plugin
└── qwc-docker/     # Docker Compose deployment orchestration
```

## Components


### pywps/

A Flask application publishing an OGC WPS 1.0.0 service using [PyWPS](https://pywps.readthedocs.io/). It exposes geoprocessing algorithms as standardized WPS endpoints. The server is designed to host processes that use PyQGIS internally, enabling full access to QGIS analysis tools from within WPS operations.

Key features:
- Standard WPS protocol (GetCapabilities, DescribeProcess, Execute)
- Synchronous and asynchronous process execution
- Extensible process architecture -- new algorithms are added as Python classes

See [`pywps/README.md`](pywps/README.md) for process development guide and API documentation.

### qwc-custom/

A custom [QWC2](https://github.com/qgis/qwc2) web mapping application extended with a **WPS Client plugin**. The plugin provides a sidebar UI for:

- Discovering available WPS processes via GetCapabilities
- Rendering dynamic input forms based on process metadata
- Executing processes (synchronous or asynchronous with polling)
- Displaying results inline

See [`qwc-custom/README.md`](qwc-custom/README.md) for plugin architecture, configuration, and development guide.

### qwc-docker/

Docker Compose setup orchestrating all services behind an NGINX reverse proxy. Includes QGIS Server, the QWC2 viewer, QWC microservices (auth, config, legend, feature info), PostGIS, and the PyWPS server.

See [`qwc-docker/README.md`](qwc-docker/README.md) for deployment instructions.

## Getting Started

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) (v20.10+)
- [Docker Compose](https://docs.docker.com/compose/install/) (v2.0+)
- [Node.js](https://nodejs.org/) and [Yarn](https://yarnpkg.com/) (for QWC2 development builds)

### Quick Start

1. Clone the repository with submodules:

       git clone --recurse-submodules <repository-url>
       cd thesis

2. Build the QWC2 viewer (if not already built):

       cd qwc-custom
       yarn install
       yarn run prod

3. Copy the build output to the Docker volumes:

       cp -r prod/* ../qwc-docker/volumes/qwc2/

4. Start all services:

       cd ../qwc-docker
       docker compose up -d

5. Access the application:

   | URL | Description |
   |-----|-------------|
   | http://localhost:8088/ | Map viewer |
   | http://localhost:8088/wps | WPS service |
   | http://localhost:8088/qwc_admin | Admin GUI |

## Technologies

| Component | Technology |
|-----------|-----------|
| Map viewer | QWC2 (React, OpenLayers) |
| Map server | QGIS Server 3.40 (WMS/WFS) |
| Geoprocessing server | PyWPS + Flask + Gunicorn |
| Processing engine | PyQGIS (headless QGIS) |
| Database | PostgreSQL / PostGIS |
| Reverse proxy | NGINX |
| Containerization | Docker Compose |


# Resources
- https://docs.qwc.app/master/
- https://pywps.readthedocs.io/en/latest/index.html
- https://github.com/geopython/pywps-flask
- https://github.com/qgis/qwc2-demo-app