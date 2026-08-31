import logging
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError
from pygeoapi.util import get_current_datetime

from qgis_init import ensure_qgis, cleanup_qgis
from qgis.core import (
    QgsClassificationJenks,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsGraduatedSymbolRenderer,
    QgsPointXY,
    QgsProject,
    QgsRendererRange,
    QgsServerWmsDimensionProperties,
    QgsSpatialIndex,
    QgsStyle,
    QgsVectorLayer,
)
from PyQt5.QtCore import QVariant

log = logging.getLogger(__name__)

EVT_DIR = Path("/data/EVT")
GPKG_PATH = Path("/data/layer/lmb_grids.gpkg")

LMB_GRIDS = [
    "LMB0A", "LMB1A", "LMB1B", "LMB1C",
    "LMB2A", "LMB2B", "LMB2C",
    "LMB3A", "LMB3B",
    "LMB4A", "LMB4B",
    "LMB5A",
]

METADATA = {
    "version": "1.0",
    "id": "lmb-sliding-window",
    "title": "LMB sliding window statistics",
    "description": "Compute sliding window event counts over LMB grids as temporal layer",
    "jobControlOptions": ["async-execute"],
    "inputs": {
        "project": {
            "title": "Theme",
            "description": "QGIS project theme name",
            "schema": {
                "type": "string",
                "default": "lmb_grids_gpkg",
                "enum": ["lmb_grids_gpkg"],
            },
        },
        "layer_name": {
            "title": "Layer name",
            "description": "Name for the output temporal layer in the QGIS project",
            "schema": {"type": "string"},
            "minOccurs": 1,
        },
        "lmbgrid": {
            "title": "LMB grid",
            "description": "LMB grid identifier to process",
            "schema": {
                "type": "string",
                "default": "LMB0A",
                "enum": LMB_GRIDS,
            },
        },
        "window_size": {
            "title": "Window size (days)",
            "description": "Number of days in each sliding window",
            "schema": {
                "type": "integer",
                "default": 30,
            },
        },
        "slide_size": {
            "title": "Slide size (days)",
            "description": "Number of days to advance the window",
            "schema": {
                "type": "integer",
                "default": 30,
            },
        },
    },
    "outputs": {
        "response": {
            "title": "Output response",
            "description": "Summary message of the processing result",
            "schema": {"type": "string"},
        }
    },
}


def parse_timestamp(s):
    """Parse SAS datetime like '01JAN2015:00:06:01.000' into a datetime object."""
    normalized = s[:2] + s[2:5].capitalize() + s[5:]
    return datetime.strptime(normalized, "%d%b%Y:%H:%M:%S.%f")


def parse_timestamp_safe(s):
    """Parse timestamp, returning None on failure."""
    if not isinstance(s, str) or not s.strip():
        return None
    try:
        return parse_timestamp(s.strip())
    except (ValueError, IndexError):
        return None


class LmbSlidingWindowProcessor(BaseProcessor):
    """Processor for LMB sliding window temporal statistics."""

    def __init__(self, processor_def):
        super().__init__(processor_def, METADATA)
        self.job_id = None

    def set_job_id(self, job_id):
        self.job_id = job_id

    def _update_progress(self, progress, message):
        log.info(f"[{progress}%] {message}")
        if self.job_id is None:
            return
        try:
            from pygeoapi.flask_app import api_
            api_.manager.update_job(self.job_id, {
                "progress": progress,
                "message": message,
                "updated": get_current_datetime(),
            })
        except Exception as e:
            log.warning(f"Could not update job progress: {e}")

    def execute(self, data, outputs=None):
        ensure_qgis()
        log.info("Starting lmb-sliding-window process")
        try:
            res =  self._run(data)
            cleanup_qgis()
            return res

    def _run(self, data):
        # Extract inputs with defaults
        layer_name = data.get("layer_name")
        if not layer_name:
            raise ProcessorExecuteError("layer_name is required")

        project = data.get("project", "lmb_grids_gpkg")
        lmbgrid = data.get("lmbgrid", "LMB0A")
        window_size = int(data.get("window_size", 30))
        slide_size = int(data.get("slide_size", 30))
        qgis_project_path = f"/data/scan/{project}.qgs"

        gpkg_path = str(GPKG_PATH)

        # --- Load polygons from GeoPackage ---
        self._update_progress(8, f"Loading grid polygons for {lmbgrid}")
        uri = f"{gpkg_path}|layername={lmbgrid}"
        grid_layer = QgsVectorLayer(uri, lmbgrid, "ogr")
        if not grid_layer.isValid():
            raise ProcessorExecuteError(
                f"Failed to load layer {lmbgrid} from {gpkg_path}"
            )

        # Build spatial index and store features keyed by fid
        self._update_progress(12, "Building spatial index")
        spatial_index = QgsSpatialIndex()
        features = {}
        for feat in grid_layer.getFeatures():
            spatial_index.addFeature(feat)
            features[feat.id()] = feat

        log.info(f"Loaded {len(features)} polygons from {lmbgrid}")

        # --- Set up coordinate transform (WGS84 -> grid CRS) ---
        crs_src = QgsCoordinateReferenceSystem("EPSG:4326")
        crs_dst = grid_layer.crs()
        transform = QgsCoordinateTransform(crs_src, crs_dst, QgsProject.instance())

        # --- Read all EVT files ---
        self._update_progress(15, "Reading event files")
        evt_files = sorted(EVT_DIR.glob("*.tab"))
        USECOLS = ["LONG", "LAT", "INVIO"]
        dfs = []
        for evt_file in evt_files:
            df = pd.read_csv(
                evt_file,
                sep="\t",
                encoding="latin-1",
                usecols=USECOLS,
                dtype={"INVIO": str, "LAT": float, "LONG": float},
            )
            dfs.append(df)

        events = pd.concat(dfs, ignore_index=True)
        total_raw = len(events)
        log.info(f"Read {total_raw} raw events")

        # --- Filter invalid coordinates ---
        self._update_progress(20, "Filtering invalid coordinates")
        events["LONG"] = pd.to_numeric(events["LONG"], errors="coerce")
        events["LAT"] = pd.to_numeric(events["LAT"], errors="coerce")
        events = events.dropna(subset=["LONG", "LAT"])
        events = events[~((events["LONG"] == 0.0) & (events["LAT"] == 0.0))]

        # Parse INVIO timestamps
        self._update_progress(23, "Parsing timestamps")
        events["invio_dt"] = events["INVIO"].apply(parse_timestamp_safe)
        events = events.dropna(subset=["invio_dt"])
        log.info(f"Events with valid coords and timestamps: {len(events)}")

        # --- Spatial matching (once for all events) ---
        matched_fids = []
        matched_times = []
        unmatched = 0
        total_to_match = len(events)
        self._update_progress(26, f"Spatial matching {total_to_match} events")

        # Progress spans 26% -> 75% during spatial matching
        MATCH_PROGRESS_START = 26
        MATCH_PROGRESS_END = 75
        last_reported_pct = MATCH_PROGRESS_START

        for i, row in enumerate(events.itertuples(index=False)):
            lon = row.LONG
            lat = row.LAT
            ts = row.invio_dt

            point_wgs = QgsPointXY(lon, lat)
            point_transformed = transform.transform(point_wgs)
            geom_point = QgsGeometry.fromPointXY(point_transformed)

            candidate_ids = spatial_index.intersects(geom_point.boundingBox())
            found = False
            for cand_id in candidate_ids:
                feat = features[cand_id]
                if feat.geometry().contains(geom_point):
                    matched_fids.append(cand_id)
                    matched_times.append(ts)
                    found = True
                    break

            if not found:
                unmatched += 1

            if total_to_match > 0 and (i + 1) % 10000 == 0:
                pct = int(
                    MATCH_PROGRESS_START
                    + (i + 1) / total_to_match * (MATCH_PROGRESS_END - MATCH_PROGRESS_START)
                )
                if pct > last_reported_pct:
                    self._update_progress(
                        pct,
                        f"Spatial matching: {i + 1}/{total_to_match} events processed",
                    )
                    last_reported_pct = pct

        log.info(f"Matched: {len(matched_fids)}, Unmatched: {unmatched}")

        # --- Build matched DataFrame and bin by time window ---
        self._update_progress(77, "Computing sliding window counts")
        matched_df = pd.DataFrame(
            {
                "fid": matched_fids,
                "timestamp": matched_times,
            }
        )

        # Determine date range from data
        min_time = matched_df["timestamp"].min()
        max_time = matched_df["timestamp"].max()

        # Generate windows
        window_delta = timedelta(days=window_size)
        slide_delta = timedelta(days=slide_size)

        windows = []
        window_start = min_time.replace(hour=0, minute=0, second=0, microsecond=0)
        while window_start < max_time:
            window_end = window_start + window_delta
            windows.append((window_start, window_end))
            window_start += slide_delta

        log.info(f"Generated {len(windows)} windows")

        # All feature IDs for the grid
        all_fids = list(features.keys())

        # For each window, count events per fid
        historical_rows = []
        n_windows = len(windows)
        for w_idx, (w_start, w_end) in enumerate(windows):
            mask = (matched_df["timestamp"] >= w_start) & (
                matched_df["timestamp"] < w_end
            )
            window_events = matched_df[mask]

            counts = window_events.groupby("fid").size()

            w_start_iso = w_start.strftime("%Y-%m-%dT%H:%M:%S")
            w_end_iso = w_end.strftime("%Y-%m-%dT%H:%M:%S")
            for fid in all_fids:
                evt_count_val = int(counts.get(fid, 0))
                historical_rows.append((fid, evt_count_val, w_start_iso, w_end_iso))

            if n_windows > 0 and (w_idx + 1) % max(1, n_windows // 5) == 0:
                pct = int(77 + (w_idx + 1) / n_windows * 5)
                self._update_progress(
                    pct,
                    f"Window aggregation: {w_idx + 1}/{n_windows}",
                )

        log.info(f"Generated {len(historical_rows)} historical_data rows")

        # --- Write to GeoPackage using sqlite3 ---
        self._update_progress(83, "Writing historical data to GeoPackage")
        conn = sqlite3.connect(gpkg_path)
        cursor = conn.cursor()

        # Drop existing view and table
        cursor.execute("DROP VIEW IF EXISTS temporal_layer")
        cursor.execute("DROP TABLE IF EXISTS historical_data")

        # Remove from gpkg metadata tables
        cursor.execute("DELETE FROM gpkg_contents WHERE table_name = 'temporal_layer'")
        cursor.execute(
            "DELETE FROM gpkg_geometry_columns WHERE table_name = 'temporal_layer'"
        )
        cursor.execute("DELETE FROM gpkg_contents WHERE table_name = 'historical_data'")

        # Create historical_data table
        cursor.execute("""
            CREATE TABLE historical_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feature_fid INTEGER NOT NULL,
                evt_count INTEGER NOT NULL,
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL
            )
        """)

        # Bulk insert
        cursor.executemany(
            "INSERT INTO historical_data (feature_fid, evt_count, window_start, window_end) VALUES (?, ?, ?, ?)",
            historical_rows,
        )

        # Create index for faster joins
        cursor.execute(
            "CREATE INDEX idx_historical_fid ON historical_data(feature_fid)"
        )

        # Create view joining geometry with historical data
        cursor.execute(f"""
            CREATE VIEW temporal_layer AS
            SELECT
                h.id AS fid,
                g.geom,
                h.evt_count,
                h.window_start,
                h.window_end
            FROM {lmbgrid} g
            JOIN historical_data h ON h.feature_fid = g.fid
        """)

        # Register the view in gpkg_contents
        cursor.execute(
            "SELECT srs_id, min_x, min_y, max_x, max_y FROM gpkg_contents WHERE table_name = ?",
            (lmbgrid,),
        )
        row = cursor.fetchone()
        if row:
            srs_id, min_x, min_y, max_x, max_y = row
        else:
            srs_id, min_x, min_y, max_x, max_y = 32632, 0, 0, 0, 0

        cursor.execute(
            """
            INSERT INTO gpkg_contents (table_name, data_type, identifier, description, min_x, min_y, max_x, max_y, srs_id)
            VALUES (?, 'features', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "temporal_layer",
                "temporal_layer",
                "Sliding window event counts",
                min_x,
                min_y,
                max_x,
                max_y,
                srs_id,
            ),
        )

        # Register geometry column for the view
        cursor.execute(
            "SELECT column_name, geometry_type_name, srs_id, z, m FROM gpkg_geometry_columns WHERE table_name = ?",
            (lmbgrid,),
        )
        geom_info = cursor.fetchone()
        if geom_info:
            geom_col, geom_type, geom_srs, geom_z, geom_m = geom_info
        else:
            geom_col, geom_type, geom_srs, geom_z, geom_m = (
                "geom",
                "MULTIPOLYGON",
                32632,
                0,
                0,
            )

        cursor.execute(
            """
            INSERT INTO gpkg_geometry_columns (table_name, column_name, geometry_type_name, srs_id, z, m)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("temporal_layer", geom_col, geom_type, geom_srs, geom_z, geom_m),
        )

        conn.commit()
        conn.close()

        # --- Add temporal layer to QGIS project ---
        self._update_progress(88, "Updating QGIS project")
        qgis_proj = QgsProject()
        qgis_proj.read(qgis_project_path)

        # Remove existing layer with same name if present
        existing_layers = qgis_proj.mapLayersByName(layer_name)
        for existing_layer in existing_layers:
            qgis_proj.removeMapLayer(existing_layer.id())

        # Add the view as a new layer
        view_uri = f"{gpkg_path}|layername=temporal_layer"
        new_layer = QgsVectorLayer(view_uri, layer_name, "ogr")
        if not new_layer.isValid():
            raise ProcessorExecuteError(
                f"Failed to load temporal_layer view from {gpkg_path}"
            )

        qgis_proj.addMapLayer(new_layer)

        # --- Configure QGIS Server WMS Dimension (TIME) ---
        server_props = new_layer.serverProperties()
        dim_info = QgsServerWmsDimensionProperties.WmsDimensionInfo(
            "TIME",
            "window_start",
            "window_end",
            "ISO8601",
            "",
            QgsServerWmsDimensionProperties.WmsDimensionInfo.AllValues,
        )
        server_props.addWmsDimension(dim_info)

        # --- Apply graduated symbology ---
        self._update_progress(91, "Applying symbology")
        style = QgsStyle.defaultStyle()
        color_ramp = style.colorRamp("YlOrRd")

        n_classes = 5
        classifier = QgsClassificationJenks()
        breaks = classifier.classes(new_layer, "evt_count", n_classes)

        ranges = []
        for i, cls in enumerate(breaks):
            lower = cls.lowerBound()
            upper = cls.upperBound()
            color = color_ramp.color(i / max(n_classes - 1, 1))
            symbol = QgsFillSymbol.createSimple(
                {
                    "color": f"{color.red()},{color.green()},{color.blue()},192",
                    "outline_color": "50,50,50,255",
                }
            )
            label = f"{lower:.0f} - {upper:.0f}"
            renderer_range = QgsRendererRange(lower, upper, symbol, label)
            ranges.append(renderer_range)

        renderer = QgsGraduatedSymbolRenderer("evt_count", ranges)
        new_layer.setRenderer(renderer)
        new_layer.triggerRepaint()

        # --- Save the project ---
        self._update_progress(94, "Saving QGIS project")
        qgis_proj.write()

        # --- Trigger QWC2 config regeneration ---
        self._update_progress(96, "Regenerating QWC2 config")
        try:
            requests.get(
                "http://qwc-config-service:9090/generate_configs",
                params={"tenant": "default"},
                timeout=120,
            )
        except Exception as e:
            log.warning(f"Config regeneration failed: {e}")

        # --- Return result ---
        total_matched = len(matched_fids)
        msg = (
            f"Sliding window analysis complete. "
            f"Grid: {lmbgrid} ({len(features)} polygons). "
            f"Events matched: {total_matched}, unmatched: {unmatched}. "
            f"Windows: {len(windows)} (size={window_size}d, slide={slide_size}d). "
            f"Date range: {min_time.strftime('%Y-%m-%d')} to {max_time.strftime('%Y-%m-%d')}. "
            f"Historical rows: {len(historical_rows)}. "
            f"Layer '{layer_name}' added to project as temporal layer."
        )

        return "application/json", {"response": msg}

    def __repr__(self):
        return "<LmbSlidingWindowProcessor>"
