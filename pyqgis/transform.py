import os
import sys
from pathlib import Path

# ============================================================================
# STEP 0 – Patch sys.path BEFORE any QGIS import
#
# When running as plain `python3` (not via the QGIS GUI or qgis_process) the
# interpreter does NOT automatically include the directories where python3-qgis
# installs its .so/.py files.  We probe every known location and add any that
# are missing.
# ============================================================================

def _patch_qgis_paths() -> None:
    import glob
    import sysconfig

    candidates: list = [
        "/usr/share/qgis/python",           # QGIS Python package root (Ubuntu)
        "/usr/share/qgis/python/plugins",   # bundled plugins
        "/usr/lib/python3/dist-packages",   # compiled .so extensions
        sysconfig.get_path("purelib") or "",
        sysconfig.get_path("platlib") or "",
    ]
    # e.g. /usr/lib/python3.10/dist-packages
    candidates += glob.glob("/usr/lib/python3.*/dist-packages")

    for p in candidates:
        if p and Path(p).is_dir() and p not in sys.path:
            sys.path.insert(0, p)

    # Make sure the QGIS native shared library is discoverable
    qgis_lib = "/usr/lib/qgis"
    ld = os.environ.get("LD_LIBRARY_PATH", "")
    if qgis_lib not in ld:
        os.environ["LD_LIBRARY_PATH"] = f"{qgis_lib}:{ld}".strip(":")


_patch_qgis_paths()

# ============================================================================
# STEP 1 – Bootstrap QgsApplication  (MUST come before any other qgis.* import)
#
# In a headless/Docker environment Qt requires QT_QPA_PLATFORM=offscreen
# (already set in the Dockerfile). QGIS_PREFIX_PATH is also read from the
# environment so the Dockerfile value (/usr) is honoured automatically.
# ============================================================================

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QGIS_PREFIX = os.environ.get("QGIS_PREFIX_PATH", "/usr")

try:
    from qgis.core import QgsApplication
except ImportError as exc:
    sys.exit(
        "ERROR: Cannot import QgsApplication - QGIS Python bindings not found.\n"
        f"  sys.path searched : {sys.path}\n"
        f"  Underlying error  : {exc}\n\n"
        "Fix: ensure python3-qgis is installed and PYTHONPATH includes\n"
        "  /usr/share/qgis/python and /usr/lib/python3/dist-packages"
    )

# Instantiate only when no QgsApplication exists yet (safe inside the GUI too)
_qgs_app = None
if QgsApplication.instance() is None:
    _qgs_app = QgsApplication([], False)   # False = non-GUI / offscreen
    QgsApplication.setPrefixPath(QGIS_PREFIX, True)
    _qgs_app.initQgis()
    print(f"[init] QgsApplication started  (prefix={QGIS_PREFIX})")

# Now safe to import the full QGIS API
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsMapLayerServerProperties,
    QgsProject,
    QgsVectorLayer,
    QgsVectorFileWriter,
    QgsCoordinateTransformContext,
    QgsFillSymbol,
)
from qgis.PyQt.QtGui import QColor


INPUT_GEOJSON: Path  = Path("/data/comuni.geojson")
OUTPUT_GEOJSON: Path = Path("/data/comuni_3857.geojson")

if OUTPUT_GEOJSON.exists():
    OUTPUT_GEOJSON.unlink()

LAYER_NAME       = "Comuni"
LAYER_SHORT_NAME = "comuni"

SOURCE_CRS  = "EPSG:4326"   # WGS 84  – native GeoJSON CRS
PROJECT_CRS = "EPSG:3857"   # Web Mercator – target CRS for publication

# ============================================================================
# STEP 2 – Load the source GeoJSON (EPSG:4326)
# ============================================================================

print(f"[1/6] Loading source layer: {INPUT_GEOJSON}")

if not INPUT_GEOJSON.exists():
    sys.exit(f"ERROR: GeoJSON not found → {INPUT_GEOJSON}")

src_layer = QgsVectorLayer(str(INPUT_GEOJSON), LAYER_NAME, "ogr")
if not src_layer.isValid():
    sys.exit(f"ERROR: Layer failed to load from {INPUT_GEOJSON}")

print(f"       Features  : {src_layer.featureCount()}")
print(f"       Source CRS: {src_layer.crs().authid()}")

# ============================================================================
# STEP 3 – Reproject to EPSG:3857 and write comuni_3857.geojson
#
# QGIS Server can reproject on the fly, but storing the layer in the
# target CRS avoids runtime conversion costs and makes the published
# bounding box accurate in 3857 coordinates.
# ============================================================================

print(f"[2/6] Reprojecting {SOURCE_CRS} → {PROJECT_CRS} …")

crs_3857 = QgsCoordinateReferenceSystem(PROJECT_CRS)

save_options = QgsVectorFileWriter.SaveVectorOptions()
save_options.driverName = "GeoJSON"
save_options.fileEncoding = "UTF-8"
save_options.ct = QgsCoordinateTransform(
    src_layer.crs(),
    crs_3857,
    QgsCoordinateTransformContext(),
)

error_code, error_msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
    src_layer,
    str(OUTPUT_GEOJSON),
    QgsCoordinateTransformContext(),
    save_options,
)

if error_code != QgsVectorFileWriter.WriterError.NoError:
    sys.exit(f"ERROR: Reprojection failed (code {error_code}): {error_msg}")

print(f"       Written   : {OUTPUT_GEOJSON}")

