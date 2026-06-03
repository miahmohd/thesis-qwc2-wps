"""
update_comuni_style.py
----------------------
Changes the fill colour, stroke colour, and fill transparency of the
"Comuni" layer inside an existing comuni.qgs project file, then saves
it so QGIS Server picks up the change on the next request.

Usage:
    python3 update_comuni_style.py

Edit the Style section below to change colours and transparency.
"""

import os
import sys
from pathlib import Path

print("run change_color.py")


# ── QGIS bootstrap ───────────────────────────────────────────────────────────


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QGIS_PREFIX = os.environ.get("QGIS_PREFIX_PATH", "/usr")

try:
    from qgis.core import QgsApplication
except ImportError as exc:
    sys.exit(
        "ERROR: QGIS Python bindings not found.\n"
        f"  sys.path : {sys.path}\n"
        f"  Error    : {exc}"
    )

_qgs_app = None
if QgsApplication.instance() is None:
    _qgs_app = QgsApplication([], False)
    QgsApplication.setPrefixPath(QGIS_PREFIX, True)
    _qgs_app.initQgis()

from qgis.core import QgsProject, QgsFillSymbol
from qgis.PyQt.QtGui import QColor


# ── Configuration ─────────────────────────────────────────────────────────────

PROJECT_FILE : Path = Path("/data/comuni.qgs")

# Name of the layer to restyle — must match exactly what is in the project
LAYER_NAME   = "Comuni"


# ── Style ─────────────────────────────────────────────────────────────────────

STROKE_COLOR = QColor("#1a5276")
STROKE_WIDTH = "0.5"


# ── Load project ──────────────────────────────────────────────────────────────

print(f"Loading project : {PROJECT_FILE}")

if not PROJECT_FILE.exists():
    sys.exit(f"ERROR: project file not found → {PROJECT_FILE}")

project = QgsProject.instance()
if not project.read(str(PROJECT_FILE)):
    sys.exit(f"ERROR: failed to read project → {PROJECT_FILE}")

print(f"         Layers : {[l.name() for l in project.mapLayers().values()]}")


# ── Find the target layer ─────────────────────────────────────────────────────

matches = project.mapLayersByName(LAYER_NAME)
if not matches:
    sys.exit(
        f"ERROR: no layer named '{LAYER_NAME}' found in {PROJECT_FILE.name}.\n"
        f"  Available layers: {[l.name() for l in project.mapLayers().values()]}"
    )

layer = matches[0]
print(f"Found layer     : '{layer.name()}'  ({layer.featureCount()} features)")


# ── Apply new style ───────────────────────────────────────────────────────────


symbol = QgsFillSymbol.createSimple({
    "color":         "144,60,217,96",
    "outline_color": STROKE_COLOR.name(),
    "outline_width": STROKE_WIDTH,
    "style":         "solid",
    "outline_style": "solid",
})

layer.renderer().setSymbol(symbol)
layer.triggerRepaint()

# ── Save — required for QGIS Server to pick up the change ────────────────────
# QGIS Server reads the .qgs file on every request; without this write
# the style change only exists in memory and has no effect on the service.

if not project.write():
    sys.exit("ERROR: project.write() failed — check file permissions.")

print(f"\n✅  Project saved → {PROJECT_FILE}")
print("   QGIS Server will use the new style on the next request.")

backup = PROJECT_FILE.with_suffix(PROJECT_FILE.suffix + "~")
if backup.exists():
    backup.unlink()