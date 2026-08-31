# QWC2 Custom Application with Geoprocessing Client Plugin

This is a custom [QWC2](https://github.com/qgis/qwc2) web mapping application extended with a **Geoprocessing Client Plugin** that allows users to discover, configure, and execute [OGC API - Processes](https://ogcapi.ogc.org/processes/) operations against a [pygeoapi](https://pygeoapi.io/) backend.

## Quick Start

1. Clone this repository:

       git clone <repo-url>
       cd qwc-custom

2. Install dependencies:

       yarn install

3. Configure the pygeoapi server URL in `static/config.json` (see [Configuration](#configuration)).

4. Run the development server:

       yarn start

5. Open the app, click the hamburger menu, and navigate to **Geoprocessing**.

---

## Geoprocessing Client Plugin

### Overview

The Geoprocessing Client plugin (`js/plugins/WpsClient.jsx`) provides a sidebar-based UI for interacting with an OGC API - Processes server. It supports:

- Fetching and displaying all available processes (`GET /processes`)
- Rendering a dynamic input form based on the process schema (`GET /processes/{id}`)
- Executing processes asynchronously with live progress polling
- Displaying results inline after completion

### Architecture

```
js/plugins/
├── WpsClient.jsx          # Main plugin component
└── style/
    └── WpsClient.css      # Plugin stylesheet
```

The plugin is a React class component connected to Redux, following standard QWC2 plugin conventions.

#### Component Hierarchy

```
SideBar (id="WpsClient", title="Geoprocessing")
└── wps-client-body
    ├── Process Selector (ComboBox, filterable)
    ├── Dynamic Form
    │   ├── ComboBox        (for enum / boolean inputs)
    │   ├── NumberInput     (for integer / float inputs)
    │   └── <input>         (for free-text string inputs)
    ├── Run Button / Spinner
    └── Results Table       (key-value pairs)
```

#### State Management

The plugin uses a **hybrid approach**:

- **Local component state** (`this.state`) for all UI-specific data: process list, selected process, form values, validation errors, execution status, and results.
- **Redux `processNotifications`** for tracking async job execution. This integrates with the global QWC2 notification system so users see progress toasts even if they navigate away from the sidebar.

#### OGC API - Processes Protocol Flow

```
┌─────────────────┐        ┌──────────────────────┐
│  Geoprocessing  │        │  pygeoapi             │
│  Client         │        │  (OGC API - Processes)│
└───────┬─────────┘        └──────────┬────────────┘
        │                             │
        │  GET /processes             │
        │────────────────────────────>│
        │  JSON process list          │
        │<────────────────────────────│
        │                             │
        │  GET /processes/{id}        │
        │────────────────────────────>│
        │  JSON schema (inputs/outputs│
        │<────────────────────────────│
        │                             │
        │  POST /processes/{id}/      │
        │        execution            │
        │  Prefer: respond-async      │
        │────────────────────────────>│
        │  201 + Location: /jobs/{id} │
        │<────────────────────────────│
        │                             │
        │  GET /jobs/{id}  (poll)     │
        │────────────────────────────>│
        │  {"status": "running", ...} │
        │<────────────────────────────│
        │                             │
        │  GET /jobs/{id}/results     │
        │────────────────────────────>│
        │  JSON results               │
        │<────────────────────────────│
        └─────────────────────────────┘
```

### Supported Input Types

| Schema Type | Form Control | Notes |
|-------------|-------------|-------|
| `string` with `enum` | ComboBox | Dropdown with allowed values |
| `boolean` | ComboBox | True / False dropdown |
| `integer` | NumberInput | Integer validation, no decimals |
| `number` | NumberInput | 6 decimal places |
| `string` (free) | `<input type="text">` | Free-text entry |

Required inputs (`minOccurs >= 1`) are marked with a red asterisk and validated before execution.

### Supported Output Types

String outputs are displayed as a key-value table in the sidebar after execution completes.

### Execution Mode

All processes run **asynchronously**. The plugin posts to `/processes/{id}/execution` with the `Prefer: respond-async` header, then polls the job URL from the `Location` response header every **3 seconds** (up to 1500 attempts — 75 minutes maximum). Progress percentage and status messages are shown live during polling.

For async processes, the plugin dispatches Redux `processStarted` / `processFinished` actions that trigger QWC2 global notification toasts.

---

## Configuration

### Plugin Registration (`js/appConfig.js`)

The plugin is imported and registered:

```javascript
import WpsClientPlugin from './plugins/WpsClient';

// In pluginsDef.plugins:
WpsClientPlugin: WpsClientPlugin,
```

### Runtime Configuration (`static/config.json`)

Add the plugin to the `plugins.common` array:

```json
{
  "name": "WpsClient",
  "cfg": {
    "pygeoApiUrl": "http://localhost:8088",
    "side": "right"
  }
}
```

| Property | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `pygeoApiUrl` | string | Yes | — | Base URL of the pygeoapi server. All API calls are constructed relative to this (e.g. `{pygeoApiUrl}/processes`). |
| `side` | string | No | `"right"` | Sidebar side: `"left"` or `"right"` |

### Menu Entry (`static/config.json`)

The plugin appears as an entry in the TopBar AppMenu:

```json
{"key": "WpsClient", "icon": "cog"}
```

### CORS

The pygeoapi server must allow CORS from the QWC2 application origin. This is enabled by default in the pygeoapi configuration (`flask-cors` is included in the server's dependencies).

---

## Development Guide

### Project Structure

```
qwc-custom/
├── js/
│   ├── app.jsx                  # React entry point
│   ├── appConfig.js             # Plugin registration
│   ├── IdentifyExtensions.js    # Custom identify behavior
│   └── plugins/
│       ├── WpsClient.jsx        # Geoprocessing Client plugin
│       └── style/
│           └── WpsClient.css    # Plugin styles
├── static/
│   ├── config.json              # Runtime configuration
│   ├── themes.json              # Theme definitions
│   └── translations/            # i18n files
├── package.json
└── webpack.config.js
```

### Build Commands

```bash
yarn install          # install dependencies
yarn run start        # dev server on :8081 (webpack-dev-server)
yarn run prod         # production build -> output in prod/
npx eslint .          # lint JS/JSX
```

`yarn run prod` chains: `tsupdate → themesconfig → iconfont → webpack --mode production`. All four steps must succeed.

### Key Dependencies Used by the Plugin

| Package | Purpose |
|---------|---------|
| `axios` | HTTP requests to pygeoapi |
| `react-redux` / `connect` | Redux integration for process notifications |
| QWC2 `SideBar` | Sidebar container component |
| QWC2 `ComboBox` | Filterable dropdown widget |
| QWC2 `NumberInput` | Numeric input with steppers |
| QWC2 `Spinner` | Loading indicator |
| QWC2 `processNotifications` | Redux actions for async job tracking |

### Execute Request Body

Process inputs are submitted as a JSON body:

```json
{
  "inputs": {
    "layer_name": "my_layer",
    "lmbgrid": "LMB0A",
    "color_by": "evt_count"
  }
}
```

Values are type-cast (parseInt, parseFloat, boolean) from the form state before submission.

### Testing

There are no automated tests. To manually test:

1. Start the full stack: `docker compose up -d --build` from `qwc-docker/`
2. Or run a standalone pygeoapi server: see [`pygeoapi/`](../pygeoapi/) instructions
3. Configure `pygeoApiUrl` in `static/config.json`
4. Run `yarn start`
5. Open the browser and click the **Geoprocessing** menu entry
6. Verify:
   - Process list loads in the selector
   - Selecting a process renders the correct input form
   - Required field validation fires on empty submit
   - Execution shows live progress and returns results
   - Async processes trigger QWC2 notification toasts
