"""
PyQGIS script that reads /data/layer/lmb_grids.gpkg and prints a summary
of its contents: layers, feature counts, geometry types, CRS, extents,
and field definitions.

Requirements:
  - QGIS >= 3.16  (python3-qgis from the official qgis.org Ubuntu repo)
  - GeoPackage at /data/layer/lmb_grids.gpkg
"""

import os
import sys
from pathlib import Path

print("run inspect_gpkg.py")

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

from qgis.core import QgsProviderRegistry, QgsVectorLayer

# ============================================================================
# Configuration
# ============================================================================

GPKG_PATH: Path = Path("/data/layer/lmb_grids.gpkg")

# ============================================================================
# STEP 2 – Validate input
# ============================================================================

if not GPKG_PATH.exists():
    sys.exit(f"ERROR: GeoPackage not found: {GPKG_PATH}")

# ============================================================================
# STEP 3 – Discover sublayers
# ============================================================================

# Use OGR provider to list sublayers in the GeoPackage
uri = str(GPKG_PATH)
provider_registry = QgsProviderRegistry.instance()
sublayers = provider_registry.querySublayers(uri)

if not sublayers:
    sys.exit(f"ERROR: No layers found in {GPKG_PATH}")

# ============================================================================
# STEP 4 – Print summary
# ============================================================================

file_size_bytes = GPKG_PATH.stat().st_size
if file_size_bytes >= 1024 * 1024:
    file_size_str = f"{file_size_bytes / (1024 * 1024):.1f} MB"
elif file_size_bytes >= 1024:
    file_size_str = f"{file_size_bytes / 1024:.1f} KB"
else:
    file_size_str = f"{file_size_bytes} bytes"

layer_names = [sl.name() for sl in sublayers]

print("")
print("=" * 50)
print("  GeoPackage Summary")
print("=" * 50)
print(f"  File:   {GPKG_PATH}")
print(f"  Size:   {file_size_str}")
print(f"  Layers: {len(layer_names)}")

# Load each layer and collect details
total_features = 0

print("")
print("-" * 50)
print("  Layers")
print("-" * 50)

for i, name in enumerate(layer_names, start=1):
    layer_uri = f"{GPKG_PATH}|layername={name}"
    layer = QgsVectorLayer(layer_uri, name, "ogr")

    if not layer.isValid():
        print(f"\n  {i}. {name}")
        print("     ERROR: Could not load layer")
        continue

    feat_count = layer.featureCount()
    total_features += feat_count
    geom_type = layer.geometryType()
    geom_type_str = layer.wkbType().name if hasattr(layer.wkbType(), "name") else str(layer.wkbType())

    # Get human-readable geometry type name
    from qgis.core import QgsWkbTypes
    geom_type_str = QgsWkbTypes.displayString(layer.wkbType())

    crs = layer.crs().authid() if layer.crs().isValid() else "Unknown"
    extent = layer.extent()

    # Fields
    fields = layer.fields()
    field_strs = [f"{f.name()} ({f.typeName()})" for f in fields]

    print(f"\n  {i}. {name}")
    print(f"     Geometry: {geom_type_str}")
    print(f"     CRS:      {crs}")
    print(f"     Features: {feat_count:,}")
    print(
        f"     Extent:   {extent.xMinimum():.1f}, {extent.yMinimum():.1f} "
        f"-> {extent.xMaximum():.1f}, {extent.yMaximum():.1f}"
    )
    print(f"     Fields:   {', '.join(field_strs)}")

print("")
print("-" * 50)
print(f"  Total features: {total_features:,}")
print("=" * 50)
