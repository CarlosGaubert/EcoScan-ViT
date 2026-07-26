import ee
import traceback

try:
    print("Initializing Earth Engine...")
    ee.Initialize()
    print("Earth Engine initialized successfully.")

    # A sample geometry ( Concepción, Chile - similar to the maps center )
    geometria = [
        [-73.13105258175706, -36.7745272641162],
        [-73.13105258175706, -36.705746266993266],
        [-73.0368104858098, -36.705746266993266],
        [-73.0368104858098, -36.7745272641162],
        [-73.13105258175706, -36.7745272641162]
    ]

    fecha_inicio = "2020-01-01"
    fecha_fin = "2020-12-31"

    # Test Sentinel-2
    print("\nTesting Sentinel-2...")
    geometry_ee = ee.Geometry.Polygon([geometria], None, False)
    
    # Try fetching Sentinel-2 collection
    collection = ee.ImageCollection('COPERNICUS/S2') \
        .filterDate(fecha_inicio, fecha_fin) \
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)) \
        .filterBounds(geometry_ee)
    
    count = collection.size().getInfo()
    print(f"Sentinel-2 collection size: {count}")
    
    if count > 0:
        # Select bands first to avoid heterogeneous collection error
        dataset = collection.select(['B4', 'B3', 'B2']).median().clip(geometry_ee)
        # Try visualizing
        imagenRGB = dataset.visualize(**{'min': 0, 'max': 2500, 'bands': ['B4', 'B3', 'B2']})
        url = imagenRGB.getThumbURL({ 'region': geometry_ee, 'dimensions': 500, 'format': 'png' })
        print(f"Sentinel-2 URL: {url}")
        
        # Test HTTP request to the URL
        print("Fetching thumbnail content...")
        import requests
        resp = requests.get(url)
        print(f"HTTP Status: {resp.status_code}")
        print(f"Headers Content-Type: {resp.headers.get('Content-Type')}")
        if resp.status_code != 200:
            print(f"Error Response Content: {resp.text[:500]}")
    else:
        print("No Sentinel-2 images found for this criteria.")

    # Test Landsat 8
    print("\nTesting Landsat 8...")
    collection_l8 = ee.ImageCollection('LANDSAT/LC08/C02/T1_TOA') \
        .filterDate(fecha_inicio, fecha_fin) \
        .filterBounds(geometry_ee) \
        .filterMetadata('CLOUD_COVER', 'less_than', 20)
    
    count_l8 = collection_l8.size().getInfo()
    print(f"Landsat 8 T1_TOA collection size: {count_l8}")

    collection_l8_rt = ee.ImageCollection('LANDSAT/LC08/C02/T1_RT_TOA') \
        .filterDate(fecha_inicio, fecha_fin) \
        .filterBounds(geometry_ee) \
        .filterMetadata('CLOUD_COVER', 'less_than', 20)
    
    count_l8_rt = collection_l8_rt.size().getInfo()
    print(f"Landsat 8 T1_RT_TOA collection size: {count_l8_rt}")

    if count_l8 > 0:
        dataset_l8 = collection_l8.median().clip(geometry_ee)
        imagenRGB_l8 = dataset_l8.visualize(**{'min': 0, 'max': 0.5, 'bands': ['B4', 'B3', 'B2']})
        url_l8 = imagenRGB_l8.getThumbURL({ 'region': geometry_ee, 'dimensions': 500, 'format': 'png' })
        print(f"Landsat 8 T1_TOA URL: {url_l8}")
    
except Exception as e:
    print("\nAn error occurred:")
    traceback.print_exc()
