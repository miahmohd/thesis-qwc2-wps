import logging
import math
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from qgis_init import ensure_qgis, cleanup_qgis
from pywps import Process, LiteralInput, LiteralOutput, UOM
from qgis.core import (
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
    QgsClassificationJenks,
)
from PyQt5.QtCore import QVariant

log = logging.getLogger("gunicorn.error")

EVT_DIR = Path("/data/EVT")
GPKG_PATH = Path("/data/layer/lmb_grids.gpkg")

evt_files = sorted(EVT_DIR.glob("*.tab"))


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


class WindowStatistic(Process):
    def __init__(self):
        inputs = [
            LiteralInput(
                "project",
                "Theme",
                data_type="string",
                default="lmb_grids_gpkg",
                allowed_values=["lmb_grids_gpkg"],
            ),
            LiteralInput("layer_name", "Layer name", data_type="string"),
            LiteralInput(
                "lmbgrid",
                "LMB grid",
                data_type="string",
                allowed_values=[
                    "LMB0A",
                    "LMB1A",
                    "LMB1B",
                    "LMB1C",
                    "LMB2A",
                    "LMB2B",
                    "LMB2C",
                    "LMB3A",
                    "LMB3B",
                    "LMB4A",
                    "LMB4B",
                    "LMB5A",
                ],
                default="LMB0A",
            ),
            LiteralInput(
                "window_size",
                "Window size (days)",
                data_type="integer",
                default="30",
            ),
            LiteralInput(
                "slide_size",
                "Slide size (days)",
                data_type="integer",
                default="30",
            ),
        ]
        outputs = [LiteralOutput("response", "Output response", data_type="string")]

        super(WindowStatistic, self).__init__(
            self._handler,
            identifier="window_statistics",
            title="LMB sliding window statistics",
            abstract="Compute sliding window event counts over LMB grids as temporal layer",
            version="1.0",
            inputs=inputs,
            outputs=outputs,
            store_supported=True,
            status_supported=True,
        )

    def _handler(self, request, response):
        log.info("Starting window_stat process")
        try:
            return self._run(request, response)
        finally:
            cleanup_qgis()

    def _run(self, request, response):
        layer_name = request.inputs["layer_name"][0].data
        project = request.inputs["project"][0].data
        lmbgrid = request.inputs["lmbgrid"][0].data
        window_size = int(request.inputs["window_size"][0].data)
        slide_size = int(request.inputs["slide_size"][0].data)
        qgis_project_path = f"/data/scan/{project}.qgs"

        gpkg_path = str(GPKG_PATH)

        # --- Load polygons from GeoPackage ---
        response.update_status("Loading grid polygons from GeoPackage", 2)
        uri = f"{gpkg_path}|layername={lmbgrid}"
        grid_layer = QgsVectorLayer(uri, lmbgrid, "ogr")
        if not grid_layer.isValid():
            response.outputs["response"].data = (
                f"ERROR: Failed to load layer {lmbgrid} from {gpkg_path}"
            )
            response.outputs["response"].uom = UOM("unity")
            return response

        # Build spatial index and store features keyed by fid
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
        response.update_status("Reading event files", 5)
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
        response.update_status("Filtering invalid coordinates", 8)
        events["LONG"] = pd.to_numeric(events["LONG"], errors="coerce")
        events["LAT"] = pd.to_numeric(events["LAT"], errors="coerce")
        events = events.dropna(subset=["LONG", "LAT"])
        events = events[~((events["LONG"] == 0.0) & (events["LAT"] == 0.0))]

        # Parse INVIO timestamps
        response.update_status("Parsing timestamps", 10)
        events["invio_dt"] = events["INVIO"].apply(parse_timestamp_safe)
        events = events.dropna(subset=["invio_dt"])
        log.info(f"Events with valid coords and timestamps: {len(events)}")

        # --- Spatial matching (once for all events) ---
        response.update_status("Spatial matching events to polygons", 12)
        matched_fids = []
        matched_times = []
        unmatched = 0
        total_to_match = len(events)

        for i, row in enumerate(events.itertuples(index=False)):
            lon = row.LONG
            lat = row.LAT
            ts = row.invio_dt

            # Transform point from WGS84 to grid CRS
            point_wgs = QgsPointXY(lon, lat)
            point_transformed = transform.transform(point_wgs)
            geom_point = QgsGeometry.fromPointXY(point_transformed)

            # Spatial index lookup
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

            if (i + 1) % 10000 == 0:
                pct = 12 + int((i / total_to_match) * 60)
                response.update_status(
                    f"Spatial matching: {min(pct, 72)}", min(pct, 72)
                )

        response.update_status("Spatial matching complete", 75)
        log.info(f"Matched: {len(matched_fids)}, Unmatched: {unmatched}")

        # --- Build matched DataFrame and bin by time window ---
        response.update_status("Computing sliding window counts", 76)
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
        for w_idx, (w_start, w_end) in enumerate(windows):
            # Filter events in this window: [w_start, w_end)
            mask = (matched_df["timestamp"] >= w_start) & (
                matched_df["timestamp"] < w_end
            )
            window_events = matched_df[mask]

            # Count per fid
            counts = window_events.groupby("fid").size()

            # Create a row for every polygon (even if count is 0)
            w_start_iso = w_start.strftime("%Y-%m-%dT%H:%M:%S")
            w_end_iso = w_end.strftime("%Y-%m-%dT%H:%M:%S")
            for fid in all_fids:
                evt_count = int(counts.get(fid, 0))
                historical_rows.append((fid, evt_count, w_start_iso, w_end_iso))

            if (w_idx + 1) % 5 == 0:
                pct = 76 + int((w_idx / len(windows)) * 10)
                response.update_status(
                    f"Window {w_idx + 1}/{len(windows)}", min(pct, 86)
                )

        log.info(f"Generated {len(historical_rows)} historical_data rows")

        # --- Write to GeoPackage using sqlite3 ---
        response.update_status("Writing historical data to GeoPackage", 87)
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
        # Get the SRS ID and extent from the grid table
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
        # Get geometry column info from the source table
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
        response.update_status("Updating QGIS project", 90)
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
            response.outputs["response"].data = (
                f"ERROR: Failed to load temporal_layer view from {gpkg_path}"
            )
            response.outputs["response"].uom = UOM("unity")
            return response

        qgis_proj.addMapLayer(new_layer)

        # --- Configure QGIS Server WMS Dimension (TIME) ---
        # https://docs.qwc.app/2024-lts/topics/TimeManager/
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

        # --- Apply graduated symbology (fixed global classes) ---
        response.update_status("Applying symbology", 93)
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
        response.update_status("Saving project", 96)
        qgis_proj.write()

        # --- Trigger QWC2 config regeneration ---
        response.update_status("Regenerating QWC2 config", 98)
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
        response.outputs["response"].data = msg
        response.outputs["response"].uom = UOM("unity")
        return response
