import logging
import os
import shutil
import math
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from pywps import Process, LiteralInput, LiteralOutput, UOM
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

log = logging.getLogger("gunicorn.error")

SHAPEFILES_DIR = Path("/data/LMB_grids")
EVT_DIR = Path("/data/EVT")
OUTPUT_DIR = Path("/data/layer")

shp_files = sorted(SHAPEFILES_DIR.glob("*.shp"))
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


class LMBStatistic(Process):
    def __init__(self):
        inputs = [
            LiteralInput("project", "Theme", data_type="string", default="lmb_grids"),
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
                "color_by",
                "Color by",
                data_type="string",
                allowed_values=["evt_count", "avg_resp_s"],
                default="evt_count",
            ),
            LiteralInput(
                "classification_method",
                "Classification method",
                data_type="string",
                allowed_values=["Equal Count", "Natural Breaks (Jenks)"],
                default="Equal Count",
            ),
        ]
        outputs = [LiteralOutput("response", "Output response", data_type="string")]

        super(LMBStatistic, self).__init__(
            self._handler,
            identifier="lmb_statistics",
            title="LMB grid statistics",
            abstract="Compute statistics over LMB grids",
            version="1.0",
            inputs=inputs,
            outputs=outputs,
            store_supported=True,
            status_supported=True,
        )

    def _handler(self, request, response):
        log.info("Starting lmbstat process")
        layer_name = request.inputs["layer_name"][0].data
        lmbgrid = request.inputs["lmbgrid"][0].data
        project = request.inputs["project"][0].data
        color_by = request.inputs["color_by"][0].data
        classification_method = request.inputs["classification_method"][0].data
        qgis_project_path = f"/data/scan/{project}.qgs"

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
            response.outputs["response"].data = (
                f"ERROR: Failed to load shapefile {shp_path}"
            )
            response.outputs["response"].uom = UOM("unity")
            return response

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
        response.update_status(f"Reading evt files", 3)
        # Speed rading by parsing only the used columns
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
        response.update_status(f"Filtering events", 5)
        events["LONG"] = pd.to_numeric(events["LONG"], errors="coerce")
        events["LAT"] = pd.to_numeric(events["LAT"], errors="coerce")
        events = events.dropna(subset=["LONG", "LAT"])
        events = events[~((events["LONG"] == 0.0) & (events["LAT"] == 0.0))]
        skipped_events = total_raw - len(events)

        # --- Step 9: Spatial matching ---
        matched_events = 0
        unmatched_events = 0
        response.update_status(f"Spatial matching", 6)

        for row in events.itertuples(index=False):
            lon = row.LONG
            lat = row.LAT

            # Transform point from WGS84 to shapefile CRS
            point_wgs = QgsPointXY(lon, lat)
            point_utm = transform.transform(point_wgs)
            geom_point = QgsGeometry.fromPointXY(point_utm)

            # Spatial index lookup
            candidate_ids = spatial_index.intersects(geom_point.boundingBox())
            found = False
            for cand_id in candidate_ids:
                feat = features[cand_id]
                if feat.geometry().contains(geom_point):
                    evt_count[cand_id] += 1
                    found = True

                    # Compute response time if both fields are present
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
                    response.update_status(
                        f"Processed {matched_events} events",
                        math.floor((matched_events / len(events)) * 100),
                    )

            else:
                unmatched_events += 1

        response.update_status("Spatial matching complete", 90)

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
        response.update_status("Updating QGIS project", 92)
        qgis_proj = QgsProject()
        qgis_proj.read(qgis_project_path)

        existing_layers = qgis_proj.mapLayersByName(layer_name)
        for existing_layer in existing_layers:
            qgis_proj.removeMapLayer(existing_layer.id())

        # --- Step 12: Add the new layer with absolute path ---
        # QGIS will store it as a relative path in the project file automatically
        new_layer = QgsVectorLayer(shp_path, layer_name, "ogr")
        if not new_layer.isValid():
            response.outputs["response"].data = (
                f"ERROR: Failed to load layer for project from {shp_path}"
            )
            response.outputs["response"].uom = UOM("unity")
            return response

        qgis_proj.addMapLayer(new_layer)

        # --- Step 13: Apply graduated choropleth symbology ---
        response.update_status("Applying choropleth symbology", 94)

        # Get YlOrRd color ramp from built-in styles
        style = QgsStyle.defaultStyle()
        color_ramp = style.colorRamp("YlOrRd")

        # Compute class breaks using the chosen method
        if classification_method == "Natural Breaks (Jenks)":
            classifier = QgsClassificationJenks()
        else:
            classifier = QgsClassificationQuantile()

        n_classes = 5
        breaks = classifier.classes(new_layer, color_by, n_classes)

        # Build renderer ranges from the computed breaks
        ranges = []
        for i, cls in enumerate(breaks):
            lower = cls.lowerBound()
            upper = cls.upperBound()

            # Sample color from the ramp
            color = color_ramp.color(i / max(n_classes - 1, 1))
            symbol = QgsFillSymbol.createSimple(
                {
                    "color": f"{color.red()},{color.green()},{color.blue()},192",
                    "outline_color": f"50,50,50,255",
                }
            )
            label = f"{lower:.0f} - {upper:.0f}"
            renderer_range = QgsRendererRange(lower, upper, symbol, label)
            ranges.append(renderer_range)

        renderer = QgsGraduatedSymbolRenderer(color_by, ranges)
        new_layer.setRenderer(renderer)
        new_layer.triggerRepaint()

        # --- Step 14: Save the project ---
        response.update_status("Saving project", 96)
        qgis_proj.write()

        # --- Step 15: Trigger QWC2 config regeneration ---
        response.update_status("Regenerating QWC2 config", 98)
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
        response.outputs["response"].data = msg
        response.outputs["response"].uom = UOM("unity")
        return response
