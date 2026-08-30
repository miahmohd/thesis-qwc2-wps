"""Fork-safe QgsApplication initializer.

Call ensure_qgis() at the start of any code path that uses PyQGIS.
This delays QgsApplication creation until the process that actually
needs it (i.e. the Gunicorn worker), avoiding Qt singleton issues
across fork boundaries.
"""

import os

from qgis.core import QgsApplication

_qgs_app = None


def ensure_qgis():
    """Initialize QgsApplication if not already running."""
    global _qgs_app
    if QgsApplication.instance() is None:
        prefix = os.environ.get("QGIS_PREFIX_PATH", "/usr")
        _qgs_app = QgsApplication([], False)
        QgsApplication.setPrefixPath(prefix, True)
        _qgs_app.initQgis()


def cleanup_qgis():
    """Exit QgsApplication and release resources."""
    global _qgs_app
    if _qgs_app is not None:
        _qgs_app.exitQgis()
        _qgs_app = None
