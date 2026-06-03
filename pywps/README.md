# PyWPS Flask Server

A Flask application that publishes an OGC Web Processing Service (WPS) using [PyWPS](https://pywps.readthedocs.io/en/latest/index.html). The service exposes geospatial (and general-purpose) processing algorithms as standardized WPS endpoints, accessible via HTTP GET and POST requests.

## Project Structure

```
pywps/
├── main.py              # Flask application entry point
├── pywps.cfg            # PyWPS server configuration
├── requirements.txt     # Python dependencies
├── Dockerfile           # Container build (Ubuntu 22.04 + QGIS)
├── processes/           # WPS process definitions
│   ├── sayhello.py
│   ├── jsonprocess.py
│   └── sleep.py
├── outputs/             # Process execution outputs
├── workdir/             # Temporary working directory for processes
└── logs/                # Log files and SQLite log database
```

## Requirements

- Python 3
- Flask
- PyWPS
- flask-cors
- lxml
- gunicorn (production)

Install dependencies:

```bash
pip install -r requirements.txt
```

## Running the Application

### Development

```bash
python main.py
```

Optional flags:

| Flag | Description |
|------|-------------|
| `-d`, `--daemon` | Run in daemon mode (fork to background) |
| `-a`, `--all-addresses` | Bind to `0.0.0.0` instead of `127.0.0.1` |

### Production (Gunicorn)

```bash
gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 300 main:app
```

### Docker

```bash
docker build -t pywps-server .
docker run -p 5000:5000 pywps-server
```

## WPS Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/wps` | GET, POST | WPS service endpoint |
| `/wps-outputs/<filename>` | GET | Retrieve process output files |

### Example WPS Requests

**GetCapabilities:**

```
GET /wps?service=WPS&request=GetCapabilities
```

**DescribeProcess:**

```
GET /wps?service=WPS&request=DescribeProcess&identifier=say_hello&version=1.0.0
```

**Execute:**

```
GET /wps?service=WPS&request=Execute&identifier=say_hello&version=1.0.0&datainputs=name=World
```

## Configuration

The service is configured through `pywps.cfg`. Key sections:

- **`[metadata:main]`** -- Service title, provider info, and contact details.
- **`[server]`** -- Server URL, output paths, max processes, parallelism, and request size limits.
- **`[processing]`** -- Processing mode (`default`).
- **`[logging]`** -- Log level, log file path, and SQLite database for execution logs.

## Creating a New Process

Follow these steps to add a new WPS process to the service:

### Step 1: Create the process file

Create a new Python file in the `processes/` directory (e.g., `processes/my_process.py`):

```python
from pywps import Process, LiteralInput, LiteralOutput

class MyProcess(Process):
    def __init__(self):
        inputs = [
            LiteralInput('input_name', 'Human-readable title', data_type='string')
        ]
        outputs = [
            LiteralOutput('output_name', 'Human-readable title', data_type='string')
        ]

        super().__init__(
            self._handler,
            identifier='my_process',         # Unique process identifier
            title='My Process Title',        # Short title
            abstract='Description of what this process does.',
            version='1.0.0',
            inputs=inputs,
            outputs=outputs,
            store_supported=True,  # Mark the process as async
            status_supported=True. # Mark the process as async
        )

    def _handler(self, request, response):
        # Read inputs
        input_value = request.inputs['input_name'][0].data

        # Process logic
        result = f"Processed: {input_value}"

        # Set output
        response.outputs['output_name'].data = result
        return response
```

### Step 2: Register the process in `main.py`

Import your process class and add it to the `processes` list:

```python
from processes.my_process import MyProcess

processes = [
    SayHello(),
    TestJson(),
    Sleep(),
    MyProcess(),   # Add your new process here
]
```

### Step 3: Restart the server

Restart the application for the new process to become available through the WPS service.

### Notes on Process Development

- **Input types:** Use `LiteralInput` for simple values (string, integer, float), `ComplexInput` for files/data (GeoJSON, GML, raster), and `BoundingBoxInput` for spatial extents.
- **Output types:** Use `LiteralOutput` for simple values and `ComplexOutput` for files or structured data. For complex outputs, specify supported formats (e.g., `Format('application/geo+json')`).
- **Async execution:** Set `store_supported=True` and `status_supported=True` to allow clients to run the process asynchronously and poll for status updates. Update progress with `response.update_status('message', percent)`.
- **Identifier uniqueness:** Each process must have a unique `identifier` string -- this is what clients use to reference the process in WPS requests.
