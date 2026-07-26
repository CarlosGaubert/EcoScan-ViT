import geopandas as gpd
from shapely.geometry import Polygon

# Crea una geometría (en este caso, un polígono)
polygon = Polygon([
    [-72.92011097902237, -36.78100537892693],
    [-72.92919956617702, -36.78091317492149],
    [-72.92946747707144, -36.78896084678219],
    [-72.91940786501739, -36.78889860913151],
    [-72.91982435300024, -36.78582969857882],
    [-72.92011097902237, -36.78100537892693]
])

# Crea un GeoDataFrame con la geometría
gdf = gpd.GeoDataFrame({'geometry': [polygon]})

# Define la ruta donde deseas guardar el archivo shapefile
ruta_guardar = 'shapefiles/examples/shapefile3/nombre_shapefile.shp'
import os
os.makedirs(os.path.dirname(ruta_guardar), exist_ok=True)

# Guarda el GeoDataFrame como un archivo shapefile
gdf.to_file(ruta_guardar)

print(f'Shapefile guardado en: {ruta_guardar}')
