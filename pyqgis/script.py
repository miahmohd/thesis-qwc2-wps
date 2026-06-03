"""
PyQGIS script that:
  1. Reads geometry data from comuni.geojson
  2. Creates a QGIS vector layer from it
  3. Configures all metadata, CRS, and WMS/WFS service settings
     required for correct QGIS Server publication
  4. Saves a .qgs project file ready to be served

Requirements:
  - QGIS >= 3.16  (python3-qgis from the official qgis.org Ubuntu repo)
  - comuni.geojson in the same directory as this script  (or update INPUT_GEOJSON)
"""

import os
import sys
from pathlib import Path



print("run script.py")


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
        "ERROR: Cannot import QgsApplication – QGIS Python bindings not found.\n"
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

# ============================================================================
# Configuration  —  edit to match your environment
# ============================================================================

OUTPUT_PROJECT: Path = Path("/data/comuni.qgs")
INPUT_GEOJSON: Path = Path("/data/comuni_3857.geojson")


if OUTPUT_PROJECT.exists():
    OUTPUT_PROJECT.unlink()


LAYER_NAME       = "Comuni"
LAYER_SHORT_NAME = "comuni"

PROJECT_CRS = "EPSG:3857"   # Web Mercator – target CRS for publication
crs_3857 = QgsCoordinateReferenceSystem(PROJECT_CRS)


# ── Service metadata ─────────────────────────────────────────────────────────
WMS_TITLE            = "Comuni d'Italia"
WMS_ABSTRACT         = (
    "Confini amministrativi dei comuni italiani. "
    "Proiezione: Web Mercator (EPSG:3857). Fonte: comuni.geojson"
)
WMS_KEYWORDS         = ["comuni", "Italy", "administrative", "boundaries", "ISTAT"]
WMS_FEES             = "None"
WMS_ACCESS_CONSTRAINTS = "None"

CONTACT_PERSON       = "GIS Administrator"
CONTACT_ORGANIZATION = "My Organisation"
CONTACT_POSITION     = "GIS Manager"
CONTACT_EMAIL        = "gis@example.com"
CONTACT_PHONE        = "+39 000 0000000"
CONTACT_ADDRESS      = "Via Example 1, 00000 Roma, Italy"

# WMS_ONLINE_RESOURCE  = "https://your-qgis-server.example.com/wms"

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
# STEP 4 – Load the reprojected layer
# ============================================================================

print(f"[3/6] Loading reprojected layer …")

layer = QgsVectorLayer(str(INPUT_GEOJSON), LAYER_NAME, "ogr")
if not layer.isValid():
    sys.exit(f"ERROR: Reprojected layer failed to load from {INPUT_GEOJSON}")

print(f"       Features  : {layer.featureCount()}")
print(f"       Layer CRS : {layer.crs().authid()}")

# ============================================================================
# STEP 5 – Layer-level server properties
# ============================================================================

print("[4/6] Configuring layer server properties …")

sp: QgsMapLayerServerProperties = layer.serverProperties()
sp.setShortName(LAYER_SHORT_NAME)
sp.setTitle(LAYER_NAME)
sp.setAbstract(
    "Confini amministrativi dei comuni italiani. "
    "Coordinate in Web Mercator (EPSG:3857)."
)
sp.setKeywordList(", ".join(WMS_KEYWORDS))
sp.setAttribution("Dati comuni italiani – ISTAT")
sp.setAttributionUrl("https://www.istat.it/")
sp.setDataUrl(str(INPUT_GEOJSON))
sp.setDataUrlFormat("text/plain")

# ============================================================================
# STEP 6 – Create the QGIS project in EPSG:3857
# ============================================================================

print("[5/6] Creating QGIS project (EPSG:3857) …")

project = QgsProject.instance()
project.clear()

project.setCrs(crs_3857)
project.addMapLayer(layer)
project.setTitle(WMS_TITLE)

meta = project.metadata()
meta.setTitle(WMS_TITLE)
meta.setAbstract(WMS_ABSTRACT)
meta.setKeywords({"general": WMS_KEYWORDS})
meta.setLanguage("it")
meta.setType("dataset")
project.setMetadata(meta)

# ============================================================================
# STEP 7 – Write QGIS Server / OWS service metadata
# ============================================================================

print("[6/6] Writing OWS service metadata …")

W = project.writeEntry

# ── WMS ──────────────────────────────────────────────────────────────────────
W("WMSServiceTitle",        "/", WMS_TITLE)
W("WMSServiceAbstract",     "/", WMS_ABSTRACT)
W("WMSKeywordList",         "/", WMS_KEYWORDS)
# W("WMSOnlineResource",      "/", WMS_ONLINE_RESOURCE)
W("WMSFees",                "/", WMS_FEES)
W("WMSAccessConstraints",   "/", WMS_ACCESS_CONSTRAINTS)

W("WMSContactPerson",       "/", CONTACT_PERSON)
W("WMSContactOrganization", "/", CONTACT_ORGANIZATION)
W("WMSContactPosition",     "/", CONTACT_POSITION)
W("WMSContactMail",         "/", CONTACT_EMAIL)
W("WMSContactPhone",        "/", CONTACT_PHONE)
W("WMSContactAddress",      "/", CONTACT_ADDRESS)

# Advertise 3857 first (native), also offer 4326 for interoperability
W("WMSCrsList",             "/", ["EPSG:3857", "EPSG:4326", "EPSG:32632"])
project.writeEntryBool("WMSUseLayerIDs", "/", False)
project.writeEntryBool("WMSAddWktGeometry", "/", True)
W("WMSPrecision",           "/", "3")   # 3 decimals is sufficient for metres
W("WMSImageQuality",        "/", 90)
W("WMSMaxWidth",            "/", 4096)
W("WMSMaxHeight",           "/", 4096)

# Bounding box in EPSG:3857 coordinates (already in target CRS)
extent = layer.extent()
if not extent.isEmpty():
    W("WMSExtent", "/", [
        str(extent.xMinimum()), str(extent.yMinimum()),
        str(extent.xMaximum()), str(extent.yMaximum()),
    ])
    print(f"       Extent (3857): {extent.xMinimum():.0f}, {extent.yMinimum():.0f}, "
          f"{extent.xMaximum():.0f}, {extent.yMaximum():.0f}")

# Empty = all project layers are published via WMS
W("WMSRestrictedLayers",    "/", [])

# ── WFS ──────────────────────────────────────────────────────────────────────
W("WFSServiceTitle",    "/", WMS_TITLE + " – WFS")
W("WFSServiceAbstract", "/", WMS_ABSTRACT)
# W("WFSUrl",             "/", WMS_ONLINE_RESOURCE.replace("/wms", "/wfs"))
W("WFSLayers",          "/", [LAYER_NAME])
W("WFSVersion",         "/", "1.1.0")
# ── WMTS ─────────────────────────────────────────────────────────────────────
W("WMTSServiceTitle",    "/", WMS_TITLE + " – WMTS")
W("WMTSServiceAbstract", "/", WMS_ABSTRACT)
W("WMTSLayers",          "/", [LAYER_NAME])
W("WMTSGrids",           "/", ["EPSG:3857", "EPSG:4326"])

# ============================================================================
# STEP 8 – Style the layer: fill colour, stroke, and transparency
# ============================================================================

# ── Colours ──────────────────────────────────────────────────────────────────
# Any CSS colour name, hex string ("#RRGGBB"), or QColor(r, g, b) works here.
FILL_COLOR   = QColor("#4a90d9")   # blue fill
STROKE_COLOR = QColor("#1a5276")   # darker blue outline
STROKE_WIDTH = "0.5"               # in millimetres

# ── Layer-level opacity (0.0 = fully transparent, 1.0 = fully opaque) ────────
# This is the quickest knob: it scales the entire layer uniformly.
LAYER_OPACITY = 0.30               # 70 % opaque / 30 % transparent

# Build a simple fill symbol from a properties dict.
# All numeric values must be passed as strings.
symbol = QgsFillSymbol.createSimple({
    "color":         "74,144,217,128",           # hex fill colour
    "outline_color": STROKE_COLOR.name(),          # hex stroke colour
    "outline_width": STROKE_WIDTH,                 # stroke width (mm)
    "style":         "solid",                      # fill pattern
    "outline_style": "solid",                      # stroke pattern
})

# Apply the symbol to the layer's renderer
layer.renderer().setSymbol(symbol)

# Persist the style changes into the layer object
layer.triggerRepaint()

# ============================================================================
# Save
# ============================================================================

project.setFileName(str(OUTPUT_PROJECT))
if not project.write():
    print("❌  ERROR: project.write() returned False — check file permissions.")
    sys.exit(1)

