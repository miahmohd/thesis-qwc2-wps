import logging
import math
import os
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from pygeoapi.process.base import BaseProcessor, ProcessorExecuteError

from qgis_init import ensure_qgis, cleanup_qgis
from qgis.core import (
    QgsClassificationJenks,
    QgsClassificationQuantile,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsField,
    QgsFillSymbol,
    QgsGeometry,
    QgsGraduatedSymbolRenderer,
    QgsPointXY,
    QgsProject,
    QgsRendererRange,
    QgsSpatialIndex,
    QgsStyle,
    QgsVectorLayer,
)
from PyQt5.QtCore import QVariant

log = logging.getLogger(__name__)

SHAPEFILES_DIR = Path("/data/LMB_grids")
EVT_DIR = Path("/data/EVT")
OUTPUT_DIR = Path("/data/layer")

METADATA = {
    "version": "1.0",
    "id": "lmb-grid-statistics",
    "title": "LMB grid statistics",
    "description": "Compute statistics over LMB grids",
    "jobControlOptions": ["async-execute"],
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


class LmbGridStatisticsProcessor(BaseProcessor):
    """Processor for LMB grid statistics computation."""

    def __init__(self, processor_def):
        super().__init__(processor_def, METADATA)

    def execute(self, data, outputs=None):
        ensure_qgis()
        log.info("Starting lmb-grid-statistics process")
        try:
            return self._run(data)
        finally:
            cleanup_qgis()

    def _run(self, data):
        # Extract inputs with defaults
        layer_name = data.get("layer_name")
        if not layer_name:
            raise ProcessorExecuteError("layer_name is required")

        lmbgrid = data.get("lmbgrid", "LMB0A")
        project = data.get("project", "lmb_grids")
        color_by = data.get("color_by", "evt_count")
        classification_method = data.get(
            "classification_method", "Natural Breaks (Jenks)"
        )
        day_filter = data.get("day_filter", "all")
        months_str = data.get("months", "1,2,3,4,5,6,7,8,9,10,11,12").strip()
        qgis_project_path = f"/data/scan/{project}.qgs"

        # --- Validate months input ---
        months_filter = None
        if months_str:
            tokens = [t.strip() for t in months_str.split(",")]
            for token in tokens:
                if not token.isdigit() or int(token) < 1 or int(token) > 12:
                    raise ProcessorExecuteError(
                        f"Invalid month value '{token}'. "
                        f"Months must be comma-separated integers between 1 and 12."
                    )
            months_filter = set(int(t) for t in tokens)

        temporal_filter_active = day_filter != "all" or months_filter is not None

        # --- Step 1: Copy shapefile to output directory ---
        os.makedirs(str(OUTPUT_DIR), exist_ok=True)

        for src_file in SHAPEFILES_DIR.glob(f"{lmbgrid}.*"):
            ext = src_file.suffix
            dst_file = OUTPUT_DIR / f"{layer_name}{ext}"
            shutil.copy2(str(src_file), str(dst_file))

        # --- Step 2: Open the copied shapefile ---
        shp_path = str(OUTPUT_DIR / f"{layer_name}.shp")
        layer = QgsVectorLayer(shp_path, layer_name, "ogr")
        if not layer.isValid():
            raise ProcessorExecuteError(f"Failed to load shapefile {shp_path}")

        # --- Step 3: Add attribute fields ---
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("evt_count", QVariant.Int),
                QgsField("avg_resp_s", QVariant.Int),
            ]
        )
        layer.updateFields()

        # --- Step 4: Build spatial index ---
        spatial_index = QgsSpatialIndex()
        features = {}
        for feat in layer.getFeatures():
            spatial_index.addFeature(feat)
            features[feat.id()] = feat

        # --- Step 5: Set up coordinate transform (WGS84 -> shapefile CRS) ---
        crs_src = QgsCoordinateReferenceSystem("EPSG:4326")
        crs_dst = layer.crs()
        transform = QgsCoordinateTransform(crs_src, crs_dst, QgsProject.instance())

        # --- Step 6: Initialize accumulators per feature ---
        evt_count = {fid: 0 for fid in features}
        resp_time_sum = {fid: 0.0 for fid in features}
        resp_time_count = {fid: 0 for fid in features}

        # --- Step 7: Read all .tab files into a single DataFrame ---
        log.info("Reading evt files")
        evt_files = sorted(EVT_DIR.glob("*.tab"))
        USECOLS = ["LONG", "LAT", "INVIO", "POSTO_1"]
        dfs = []
        for evt_file in evt_files:
            df = pd.read_csv(
                evt_file,
                sep="\t",
                encoding="latin-1",
                usecols=USECOLS,
                dtype={"INVIO": str, "POSTO_1": str, "LAT": float, "LONG": float},
            )
            dfs.append(df)

        events = pd.concat(dfs, ignore_index=True)
        total_raw = len(events)

        # --- Step 8: Filter invalid coordinates ---
        log.info("Filtering events")
        events["LONG"] = pd.to_numeric(events["LONG"], errors="coerce")
        events["LAT"] = pd.to_numeric(events["LAT"], errors="coerce")
        events = events.dropna(subset=["LONG", "LAT"])
        events = events[~((events["LONG"] == 0.0) & (events["LAT"] == 0.0))]
        skipped_events = total_raw - len(events)

        # --- Step 8b: Apply temporal filter (day of week / months) ---
        filtered_events = 0
        if temporal_filter_active:
            log.info("Applying temporal filter")
            events["_invio_dt"] = events["INVIO"].apply(parse_timestamp_safe)
            unparseable_mask = events["_invio_dt"].isna()
            filtered_events += unparseable_mask.sum()
            events = events[~unparseable_mask]

            if day_filter == "weekday":
                weekday_mask = events["_invio_dt"].apply(lambda dt: dt.weekday() < 5)
                filtered_events += (~weekday_mask).sum()
                events = events[weekday_mask]
            elif day_filter == "weekend":
                weekend_mask = events["_invio_dt"].apply(lambda dt: dt.weekday() >= 5)
                filtered_events += (~weekend_mask).sum()
                events = events[weekend_mask]

            if months_filter is not None:
                month_mask = events["_invio_dt"].apply(
                    lambda dt: dt.month in months_filter
                )
                filtered_events += (~month_mask).sum()
                events = events[month_mask]

        # --- Step 9: Spatial matching ---
        matched_events = 0
        unmatched_events = 0
        log.info("Spatial matching")

        for row in events.itertuples(index=False):
            lon = row.LONG
            lat = row.LAT

            point_wgs = QgsPointXY(lon, lat)
            point_utm = transform.transform(point_wgs)
            geom_point = QgsGeometry.fromPointXY(point_utm)

            candidate_ids = spatial_index.intersects(geom_point.boundingBox())
            found = False
            for cand_id in candidate_ids:
                feat = features[cand_id]
                if feat.geometry().contains(geom_point):
                    evt_count[cand_id] += 1
                    found = True

                    invio_str = row.INVIO
                    posto1_str = row.POSTO_1

                    t_invio = parse_timestamp_safe(invio_str)
                    t_posto1 = parse_timestamp_safe(posto1_str)

                    if t_invio is not None and t_posto1 is not None:
                        delta_s = (t_posto1 - t_invio).total_seconds()
                        if delta_s >= 0:
                            resp_time_sum[cand_id] += delta_s
                            resp_time_count[cand_id] += 1

                    break

            if found:
                matched_events += 1
                if matched_events % 10000 == 0:
                    log.info(f"Processed {matched_events} events")
            else:
                unmatched_events += 1

        log.info("Spatial matching complete")

        # --- Step 10: Write statistics to shapefile attributes ---
        field_names = [field.name() for field in provider.fields()]
        evt_count_field_idx = field_names.index("evt_count")
        avg_resp_field_idx = field_names.index("avg_resp_s")

        attr_map = {}
        for fid in features:
            avg_resp = 0
            if resp_time_count[fid] > 0:
                avg_resp = int(resp_time_sum[fid] / resp_time_count[fid])
            attr_map[fid] = {
                evt_count_field_idx: evt_count[fid],
                avg_resp_field_idx: avg_resp,
            }

        provider.changeAttributeValues(attr_map)
        layer.updateFields()

        # --- Step 11: Open QGIS project and remove existing layer if present ---
        log.info("Updating QGIS project")
        qgis_proj = QgsProject()
        qgis_proj.read(qgis_project_path)

        existing_layers = qgis_proj.mapLayersByName(layer_name)
        for existing_layer in existing_layers:
            qgis_proj.removeMapLayer(existing_layer.id())

        # --- Step 12: Add the new layer ---
        new_layer = QgsVectorLayer(shp_path, layer_name, "ogr")
        if not new_layer.isValid():
            raise ProcessorExecuteError(
                f"Failed to load layer for project from {shp_path}"
            )

        qgis_proj.addMapLayer(new_layer)

        # --- Step 13: Apply graduated choropleth symbology ---
        log.info("Applying choropleth symbology")
        style = QgsStyle.defaultStyle()
        color_ramp = style.colorRamp("YlOrRd")

        if classification_method == "Natural Breaks (Jenks)":
            classifier = QgsClassificationJenks()
        else:
            classifier = QgsClassificationQuantile()

        n_classes = 5
        breaks = classifier.classes(new_layer, color_by, n_classes)

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

        renderer = QgsGraduatedSymbolRenderer(color_by, ranges)
        new_layer.setRenderer(renderer)
        new_layer.triggerRepaint()

        # --- Step 14: Save the project ---
        log.info("Saving project")
        qgis_proj.write()

        # --- Step 15: Trigger QWC2 config regeneration ---
        log.info("Regenerating QWC2 config")
        try:
            requests.get(
                "http://qwc-config-service:9090/generate_configs",
                params={"tenant": "default"},
                timeout=120,
            )
        except Exception as e:
            log.warning(f"Config regeneration failed: {e}")

        # --- Step 16: Return result ---
        total_events = matched_events + unmatched_events
        msg = (
            f"Computed statistics for {len(features)} polygons. "
            f"Processed {total_events} events: "
            f"{matched_events} matched, {unmatched_events} unmatched, "
            f"{skipped_events} skipped (invalid coordinates)."
        )
        if temporal_filter_active:
            filter_desc_parts = []
            if day_filter != "all":
                filter_desc_parts.append(f"day_filter={day_filter}")
            if months_filter is not None:
                filter_desc_parts.append(f"months={months_str}")
            filter_desc = ", ".join(filter_desc_parts)
            msg += f" {filtered_events} excluded by time filter ({filter_desc})."

        return "application/json", {"response": msg}

    def __repr__(self):
        return "<LmbGridStatisticsProcessor>"
