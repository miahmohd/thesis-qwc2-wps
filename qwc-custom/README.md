# QWC2 Custom Application with WPS Client Plugin

This is a custom [QWC2](https://github.com/qgis/qwc2) web mapping application extended with a **WPS Client Plugin** that allows users to discover, configure, and execute OGC WPS 1.0.0 processes from a remote server.

## Quick Start

1. Clone this repository:

       git clone <repo-url>
       cd qwc-custom

2. Install dependencies:

       yarn install

3. Configure the WPS server URL in `static/config.json` (see [Configuration](#configuration)).

4. Run the development server:

       yarn start

5. Open the app, click the hamburger menu, navigate to **Tools > WPS Client**.

---

## WPS Client Plugin

### Overview

The WPS Client plugin provides a sidebar-based UI for interacting with an OGC WPS 1.0.0 server (designed for [PyWPS](https://pywps.org/)). It supports:

- Fetching and displaying all available processes via `GetCapabilities`
- Rendering a dynamic input form based on `DescribeProcess` metadata
- Executing processes (synchronous or asynchronous, auto-detected)
- Displaying literal output results inline

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
SideBar (id="WpsClient")
└── wps-client-body
    ├── Process Selector (ComboBox, filterable)
    ├── Dynamic Form
    │   ├── ComboBox        (for AllowedValues / boolean inputs)
    │   ├── NumberInput     (for integer/float inputs)
    │   └── <input>         (for free-text string inputs)
    ├── Run Button / Spinner
    └── Results Table       (literal key-value pairs)
```

#### State Management

The plugin uses a **hybrid approach**:

- **Local component state** (`this.state`) for all UI-specific data: process list, selected process, form values, validation errors, execution status, and results.
- **Redux `processNotifications`** for tracking async process execution. This integrates with the global QWC2 notification system so users see progress toasts even if they navigate away from the sidebar.

#### WPS Protocol Flow

```
┌─────────────┐         ┌────────────┐
│  WpsClient  │         │  PyWPS     │
│  (browser)  │         │  Server    │
└──────┬──────┘         └──────┬─────┘
       │                       │
       │  GET GetCapabilities  │
       │──────────────────────>│
       │  XML process list     │
       │<──────────────────────│
       │                       │
       │  GET DescribeProcess  │
       │──────────────────────>│
       │  XML input/output def │
       │<──────────────────────│
       │                       │
       │  POST Execute (XML)   │
       │──────────────────────>│
       │  XML response/status  │
       │<──────────────────────│
       │                       │
       │  [if async] GET poll  │
       │──────────────────────>│
       │  XML status update    │
       │<──────────────────────│
       └───────────────────────┘
```

### Supported Input Types

| WPS Data Type | Form Control | Notes |
|---------------|-------------|-------|
| String (LiteralData) | Text input | Free-text entry |
| Integer | NumberInput | Validates integer format |
| Float/Double | NumberInput | 6 decimal places |
| Boolean | ComboBox (True/False) | Dropdown selection |
| Enumerated (AllowedValues) | ComboBox | Dropdown with allowed options |

All inputs are treated as **single-value** (`maxOccurs` > 1 is not yet supported).

Required fields (`minOccurs >= 1`) are marked with a red asterisk and validated before execution.

### Supported Output Types

Currently only **LiteralData** outputs are supported. They are displayed as a key-value table in the sidebar after execution completes.

### Execution Modes

The plugin auto-detects the execution mode from `DescribeProcess`:

| Mode | Condition | Behavior |
|------|-----------|----------|
| Synchronous | `storeSupported=false` or `statusSupported=false` | POST blocks until result |
| Asynchronous | Both `storeSupported=true` and `statusSupported=true` | POST returns immediately; plugin polls `statusLocation` every 3 seconds (max 100 attempts = 5 min timeout) |

For async processes, the plugin dispatches Redux `processStarted` / `processFinished` actions that trigger QWC2's global notification toasts.

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
    "wpsUrl": "http://localhost:5000/wps",
    "side": "right"
  }
}
```

| Property | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `wpsUrl` | string | Yes | — | Full URL to the WPS server endpoint |
| `side` | string | No | `"right"` | Sidebar side: `"left"` or `"right"` |

### Menu Entry (`static/config.json`)

The plugin appears in the TopBar AppMenu under the "Tools" submenu:

```json
{"key": "WpsClient", "icon": "cog"}
```

### CORS

The WPS server must allow CORS from the QWC2 application origin. For PyWPS, configure this in your Flask/Werkzeug wrapper or reverse proxy.

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
│       ├── WpsClient.jsx        # WPS Client plugin
│       └── style/
│           └── WpsClient.css    # Plugin styles
├── static/
│   ├── config.json              # Runtime configuration
│   ├── themes.json              # Theme definitions
│   └── translations/            # i18n files
├── package.json
└── webpack.config.js
```

### Key Dependencies Used by the Plugin

| Package | Purpose |
|---------|---------|
| `axios` | HTTP requests to WPS server |
| `fast-xml-parser` | Parsing WPS XML responses (GetCapabilities, DescribeProcess, Execute) |
| `react-redux` / `connect` | Redux integration for process notifications |
| QWC2 `SideBar` | Container component |
| QWC2 `ComboBox` | Filterable dropdown widget |
| QWC2 `NumberInput` | Numeric input with steppers |
| QWC2 `Spinner` | Loading indicator |
| QWC2 `processNotifications` | Redux actions for async tracking |

### How to Extend

#### Adding BoundingBox input support

1. Import `MapSelection` from `qwc2/components/MapSelection`
2. Detect `BoundingBoxData` in `extractDescription()`
3. Add a new branch in `renderInputControl()` that renders a `MapSelection` component with `geomType="Box"`
4. Capture the drawn extent and format it for the WPS Execute request

#### Adding Complex output support (GeoJSON on map)

1. Import `addLayerFeatures` / `removeLayer` from `qwc2/actions/layers`
2. In `extractOutputs()`, detect MIME type `application/json` or `application/geojson`
3. Parse the GeoJSON and call `addLayerFeatures()` to display results on the map
4. Clear the layer in `onHide()`

#### Adding file download outputs

1. In `extractOutputs()`, detect reference outputs (outputs with `@_href` attribute)
2. Render a download link/button using the href URL
3. Use `file-saver` (already in dependencies) for client-side downloads if needed

#### Supporting `maxOccurs > 1` (repeatable inputs)

1. Change `formValues[identifier]` from a single value to an array
2. Use QWC2's `ListInput` widget or render add/remove buttons
3. In `buildExecuteRequest()`, emit multiple `<wps:Input>` elements for the same identifier

#### Adding caching

1. Move `DescribeProcess` results to a `Map` stored in component state or a module-level variable
2. Before fetching, check if the identifier already exists in the cache
3. Consider a TTL or "refresh" button to invalidate stale data

### XML Parsing Notes

The plugin uses `fast-xml-parser` with these options:

```javascript
{
  ignoreAttributes: false,        // Preserve XML attributes
  attributeNamePrefix: '@_',      // Attributes prefixed with @_
  removeNSPrefix: true            // Strip namespace prefixes (wps:, ows:, etc.)
}
```

This means:
- `<wps:Identifier>foo</wps:Identifier>` becomes `{ Identifier: "foo" }`
- `<ProcessDescription storeSupported="true">` becomes `{ '@_storeSupported': 'true' }`
- Single child elements are objects; multiple siblings with the same tag become arrays (always check with `Array.isArray()`)

### Testing

There are currently no automated tests. To manually test:

1. Start a PyWPS server with sample processes (e.g., the PyWPS demo processes)
2. Configure `wpsUrl` in `static/config.json`
3. Run `yarn start`
4. Open the browser, click **Menu > Tools > WPS Client**
5. Verify:
   - Process list loads in the ComboBox
   - Selecting a process shows the correct input form
   - Required field validation works (submit with empty required fields)
   - Execution returns results displayed in the table
   - Async processes show the notification and poll correctly

