QWC QGIS Server plugins
=======================

Plugins for extending QGIS Server for QWC.

# filter_geom

This plugin implements `FILTER_GEOM` for WMS GetMap and GetLegendGraphics. It works by injecting a corresponding `FILTER` expression for each applicable layer. Currently, only postgis layers will be filtered.

# print_templates

This plugin allows managing print templates as `.qpt` files in a specified `PRINT_LAYOUT_DIR`, which are then made available to all projects in `GetPrint` requests.

See [print templates documentation](https://qwc-services.github.io/master/topics/Printing/#layout-templates).

# split_categorized

This plugin will expose categorized layer symbologies as separate layers.

See [categorized layers documentation](https://qwc-services.github.io/master/configuration/ThemesConfiguration/#split-categorized-layers).

# wms_geotiff_output

This plugin adds support for geotiff output to WMS GetMap.

# clear_capabilities

Clears the WMS cache before GetCapabilities or GetProjectSettings requests.
