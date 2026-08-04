"""
PyQGIS script that:
  1. Discovers all shapefiles in /data/LMB_grids/
  2. Loads each shapefile as a QGIS vector layer (with all sidecar files:
     .shx, .dbf, .prj, .cpg, .qix spatial index, .qmd metadata)
  3. Applies uniform styling to all layers
  4. Configures WMS/WFS/WMTS service metadata for QGIS Server
  5. Saves a .qgs project file ready to be served

The project CRS matches the native CRS of the shapefiles (EPSG:32632).
QGIS Server will reproject on-the-fly to EPSG:3857 for QWC2 WMS requests.

Requirements:
  - QGIS >= 3.16  (python3-qgis from the official qgis.org Ubuntu repo)
  - Shapefiles in /data/LMB_grids/
"""

import os
import sys
from glob import glob
from pathlib import Path

print("run lmb_grids.py")

# ============================================================================
# STEP 1 – Bootstrap QgsApplication
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

_qgs_app = None
if QgsApplication.instance() is None:
    _qgs_app = QgsApplication([], False)
    QgsApplication.setPrefixPath(QGIS_PREFIX, True)
    _qgs_app.initQgis()
    print(f"[init] QgsApplication started  (prefix={QGIS_PREFIX})")

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsMapLayerServerProperties,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    QgsFillSymbol,
)
from qgis.PyQt.QtGui import QColor

# ============================================================================
# Configuration
# ============================================================================

INPUT_DIR: Path = Path("/data/LMB_grids")
OUTPUT_PROJECT: Path = Path("/data/scan/lmb_grids.qgs")

# Project CRS will be determined from the first loaded layer (expected: EPSG:32632)

# ── Styling ──────────────────────────────────────────────────────────────────
FILL_COLOR = QColor("#4a90d9")
STROKE_COLOR = QColor("#1a5276")
STROKE_WIDTH = "0.5"
LAYER_OPACITY = 0.30

# ── Service metadata ─────────────────────────────────────────────────────────
WMS_TITLE = "LMB Grids"
WMS_ABSTRACT = (
    "Griglie LMB (Lombardia). "
    "Proiezione nativa: UTM zone 32N (EPSG:32632). "
    "Riproiezione on-the-fly disponibile per EPSG:3857 e EPSG:4326."
)
WMS_KEYWORDS = ["LMB", "grids", "Lombardia", "boundaries"]
WMS_FEES = "None"
WMS_ACCESS_CONSTRAINTS = "None"

CONTACT_PERSON = "GIS Administrator"
CONTACT_ORGANIZATION = "My Organisation"
CONTACT_POSITION = "GIS Manager"
CONTACT_EMAIL = "gis@example.com"
CONTACT_PHONE = "+39 000 0000000"
CONTACT_ADDRESS = "Via Example 1, 00000 Roma, Italy"

# ============================================================================
# STEP 2 – Discover shapefiles
# ============================================================================

if OUTPUT_PROJECT.exists():
    OUTPUT_PROJECT.unlink()

if not INPUT_DIR.exists():
    sys.exit(f"ERROR: Input directory not found: {INPUT_DIR}")

shp_files = sorted(INPUT_DIR.glob("*.shp"))

if not shp_files:
    sys.exit(f"ERROR: No .shp files found in {INPUT_DIR}")

print(f"[1/5] Found {len(shp_files)} shapefiles in {INPUT_DIR}:")
for shp in shp_files:
    print(f"       - {shp.name}")

# ============================================================================
# STEP 3 – Load layers
# ============================================================================

print("[2/5] Loading layers ...")

layers = []
for shp in shp_files:
    layer_name = shp.stem  # e.g. "LMB0A"
    layer = QgsVectorLayer(str(shp), layer_name, "ogr")
    if not layer.isValid():
        print(f"  WARNING: Failed to load {shp.name} – skipping")
        continue
    print(
        f"       {layer_name}: {layer.featureCount()} features, CRS={layer.crs().authid()}"
    )
    layers.append(layer)

if not layers:
    sys.exit("ERROR: No valid layers could be loaded.")

# Determine native CRS from the first layer
project_crs = layers[0].crs()
PROJECT_CRS = project_crs.authid()
print(f"       Native CRS detected: {PROJECT_CRS}")

# ============================================================================
# STEP 4 – Configure layer server properties & styling
# ============================================================================

print("[3/5] Configuring layer properties and styling ...")

for layer in layers:
    # Server properties
    sp: QgsMapLayerServerProperties = layer.serverProperties()
    sp.setShortName(layer.name().lower())
    sp.setTitle(layer.name())
    sp.setAbstract(f"Griglia {layer.name()} – LMB grid layer.")
    sp.setKeywordList(", ".join(WMS_KEYWORDS))

    # Styling – uniform semi-transparent blue fill
    symbol = QgsFillSymbol.createSimple(
        {
            "color": "74,144,217,128",
            "outline_color": STROKE_COLOR.name(),
            "outline_width": STROKE_WIDTH,
            "style": "solid",
            "outline_style": "solid",
        }
    )
    layer.renderer().setSymbol(symbol)
    layer.triggerRepaint()

# ============================================================================
# STEP 5 – Create project
# ============================================================================

print("[4/5] Creating QGIS project ...")

project = QgsProject.instance()
project.clear()
project.setCrs(project_crs)

# Set the filename early so QGIS can compute relative paths from the project location
project.setFileName(str(OUTPUT_PROJECT))

root = project.layerTreeRoot()

for layer in layers:
    project.addMapLayer(layer)

    node = root.findLayer(layer.id())
    if node:
        node.setItemVisibilityChecked(False)

project.setTitle(WMS_TITLE)

meta = project.metadata()
meta.setTitle(WMS_TITLE)
meta.setAbstract(WMS_ABSTRACT)
meta.setKeywords({"general": WMS_KEYWORDS})
meta.setLanguage("it")
meta.setType("dataset")
project.setMetadata(meta)

# ============================================================================
# STEP 6 – WMS/WFS/WMTS service metadata
# ============================================================================

print("[5/5] Writing OWS service metadata ...")

W = project.writeEntry

# ── WMS ──────────────────────────────────────────────────────────────────────
W("WMSServiceTitle", "/", WMS_TITLE)
W("WMSServiceAbstract", "/", WMS_ABSTRACT)
W("WMSKeywordList", "/", WMS_KEYWORDS)
W("WMSFees", "/", WMS_FEES)
W("WMSAccessConstraints", "/", WMS_ACCESS_CONSTRAINTS)

W("WMSContactPerson", "/", CONTACT_PERSON)
W("WMSContactOrganization", "/", CONTACT_ORGANIZATION)
W("WMSContactPosition", "/", CONTACT_POSITION)
W("WMSContactMail", "/", CONTACT_EMAIL)
W("WMSContactPhone", "/", CONTACT_PHONE)
W("WMSContactAddress", "/", CONTACT_ADDRESS)

# Advertise native CRS + 3857 for on-the-fly reprojection to QWC2 + 4326 for interop
W("WMSCrsList", "/", [PROJECT_CRS, "EPSG:3857", "EPSG:4326"])
project.writeEntryBool("WMSUseLayerIDs", "/", False)
project.writeEntryBool("WMSAddWktGeometry", "/", True)
W("WMSPrecision", "/", "3")  # 3 decimals sufficient for metres
W("WMSImageQuality", "/", 90)
W("WMSMaxWidth", "/", 4096)
W("WMSMaxHeight", "/", 4096)

# Compute combined extent from all layers (in native CRS)
combined_extent = QgsRectangle()
for layer in layers:
    ext = layer.extent()
    if not ext.isEmpty():
        if combined_extent.isEmpty():
            combined_extent = ext
        else:
            combined_extent.combineExtentWith(ext)

# WMSExtent must be in the project CRS (EPSG:32632)
if not combined_extent.isEmpty():
    W(
        "WMSExtent",
        "/",
        [
            str(combined_extent.xMinimum()),
            str(combined_extent.yMinimum()),
            str(combined_extent.xMaximum()),
            str(combined_extent.yMaximum()),
        ],
    )
    print(
        f"       Extent ({PROJECT_CRS}): {combined_extent.xMinimum():.0f}, "
        f"{combined_extent.yMinimum():.0f}, {combined_extent.xMaximum():.0f}, "
        f"{combined_extent.yMaximum():.0f}"
    )

W("WMSRestrictedLayers", "/", [])

# ── WFS ──────────────────────────────────────────────────────────────────────
layer_names = [l.name() for l in layers]

W("WFSServiceTitle", "/", WMS_TITLE + " – WFS")
W("WFSServiceAbstract", "/", WMS_ABSTRACT)
W("WFSLayers", "/", layer_names)
W("WFSVersion", "/", "1.1.0")

# ── WMTS ─────────────────────────────────────────────────────────────────────
W("WMTSServiceTitle", "/", WMS_TITLE + " – WMTS")
W("WMTSServiceAbstract", "/", WMS_ABSTRACT)
W("WMTSLayers", "/", layer_names)
W("WMTSGrids", "/", [PROJECT_CRS, "EPSG:3857", "EPSG:4326"])

# ============================================================================
# Save
# ============================================================================

project.setFileName(str(OUTPUT_PROJECT))
if not project.write():
    print("ERROR: project.write() returned False — check file permissions.")
    sys.exit(1)

print(f"\nDone! Project saved to: {OUTPUT_PROJECT}")
print(f"  Layers: {len(layers)}")
print(f"  Project CRS: {PROJECT_CRS}")
print(f"  WMS CRS list: {PROJECT_CRS}, EPSG:3857, EPSG:4326")
