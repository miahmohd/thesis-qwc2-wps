"""
PyQGIS script that converts all shapefiles in /data/LMB_grids/ into a single
GeoPackage at /data/layer/lmb_grids.gpkg.

Each shapefile becomes a layer in the GeoPackage, named after the shapefile
(e.g. LMB0A.shp → layer "LMB0A"). Original CRS is preserved (no reprojection).

If the output GeoPackage already exists, it is overwritten entirely.

Requirements:
  - QGIS >= 3.16  (python3-qgis from the official qgis.org Ubuntu repo)
  - Shapefiles in /data/LMB_grids/
"""

import os
import sys
from pathlib import Path

print("run shp_to_gpkg.py")

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
    QgsCoordinateTransformContext,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

# ============================================================================
# Configuration
# ============================================================================

INPUT_DIR: Path = Path("/data/LMB_grids")
OUTPUT_GPKG: Path = Path("/data/layer/lmb_grids.gpkg")

# ============================================================================
# STEP 2 – Discover shapefiles
# ============================================================================

if not INPUT_DIR.exists():
    sys.exit(f"ERROR: Input directory not found: {INPUT_DIR}")

shp_files = sorted(INPUT_DIR.glob("*.shp"))

if not shp_files:
    sys.exit(f"ERROR: No .shp files found in {INPUT_DIR}")

print(f"[1/3] Found {len(shp_files)} shapefiles in {INPUT_DIR}:")
for shp in shp_files:
    print(f"       - {shp.name}")

# ============================================================================
# STEP 3 – Remove existing output if present
# ============================================================================

if OUTPUT_GPKG.exists():
    OUTPUT_GPKG.unlink()
    print(f"[2/3] Removed existing {OUTPUT_GPKG}")
else:
    print(f"[2/3] Output path clear: {OUTPUT_GPKG}")

# Ensure the output directory exists
OUTPUT_GPKG.parent.mkdir(parents=True, exist_ok=True)

# ============================================================================
# STEP 4 – Convert each shapefile to a layer in the GeoPackage
# ============================================================================

print("[3/3] Converting shapefiles to GeoPackage ...")

success_count = 0
fail_count = 0
failed_files = []

for i, shp in enumerate(shp_files):
    layer_name = shp.stem  # e.g. "LMB0A"
    layer = QgsVectorLayer(str(shp), layer_name, "ogr")

    if not layer.isValid():
        print(f"  WARNING: Failed to load {shp.name} – skipping", file=sys.stderr)
        fail_count += 1
        failed_files.append(shp.name)
        continue

    # Configure write options
    save_options = QgsVectorFileWriter.SaveVectorOptions()
    save_options.driverName = "GPKG"
    save_options.fileEncoding = "UTF-8"
    save_options.layerName = layer_name

    # For the first layer, create the file; for subsequent layers, append
    if i == 0 or not OUTPUT_GPKG.exists():
        save_options.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
        )
    else:
        save_options.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        )

    error_code, error_msg, _, _ = QgsVectorFileWriter.writeAsVectorFormatV3(
        layer,
        str(OUTPUT_GPKG),
        QgsCoordinateTransformContext(),
        save_options,
    )

    if error_code != QgsVectorFileWriter.WriterError.NoError:
        print(
            f"  WARNING: Failed to write {shp.name} (code {error_code}): {error_msg}",
            file=sys.stderr,
        )
        fail_count += 1
        failed_files.append(shp.name)
        continue

    print(
        f"       [{i + 1}/{len(shp_files)}] {layer_name}: "
        f"{layer.featureCount()} features, CRS={layer.crs().authid()}"
    )
    success_count += 1

# ============================================================================
# Summary
# ============================================================================

print(f"\nDone! Output: {OUTPUT_GPKG}")
print(f"  Layers written: {success_count}/{len(shp_files)}")

if fail_count > 0:
    print(f"  FAILED ({fail_count}): {', '.join(failed_files)}", file=sys.stderr)
    sys.exit(1)
