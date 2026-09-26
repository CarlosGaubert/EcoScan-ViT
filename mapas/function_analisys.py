import numpy as np
from shapely.ops import split
import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon, LineString
import ee
import requests
import os
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import shutil
import torchvision
import rasterio
import rasterio.plot
import matplotlib.pyplot as plt
import cv2
from rasterio.features import geometry_mask
from shapely.geometry import mapping
from torchvision import models, transforms
import torch.nn.functional as F  # Import functional interface
from PIL import Image
from torch import nn
import torch
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
import time

def export_rectangle_to_drive(Rectangle, name_file, start_date, end_date):
    try:
        ee.Initialize(project=os.getenv('EE_PROJECT_ID', 'proyecto-forest-2026'))
    except Exception:
        ee.Initialize()
    """
    Exports the envelope of a geometry from a shapefile to Google Drive.

    Args:
    - geo_filepath (str): Path to the shapefile.
    - scale (int): Resolution scale. Default is 10 for Sentinel-2.

    Returns:
    - str: Status of the export task.
    """

    # Convert the shapely geometry to an Earth Engine Geometry
    coords = list(Rectangle.exterior.coords)
    region = ee.Geometry.Polygon(coords)

    # Define the image collection for Sentinel-2 and filter by the region
    collection = ee.ImageCollection('COPERNICUS/S2_HARMONIZED') \
        .filterDate(start_date, end_date) \
        .filterBounds(region) \
        .sort('CLOUDY_PIXEL_PERCENTAGE', True)

    # Filtrar imágenes limpias con menos de 20% si están disponibles
    collection_clean = collection.filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20))
    try:
        if collection_clean.size().getInfo() > 0:
            collection = collection_clean
    except Exception:
        pass

    # Usar las escenas con menor cobertura de nubes para el compuesto
    image = collection.limit(5).median().select(['B4', 'B3', 'B2'])  # RGB bands for Sentinel-2

    # Define export parameters
    task_config = {
        'description': name_file,
        'folder': 'rasters',
        'fileNamePrefix': name_file, 
        'scale': 10,
        'region': region,
        'maxPixels': 1e13  # Increase this if you get an error related to pixel count
    }

    # Start the export task to Google Drive
    task = ee.batch.Export.image.toDrive(image, **task_config)
    task.start()

    return task

def check_task_status(task):
    return task.status()

def get_file_id_by_name(filename, drive):
    """
    Get the file ID of a file in Google Drive based on its name.

    Args:
    - filename (str): The name of the file.

    Returns:
    - str: The file ID or None if not found.
    """
 
    # Search for the file by its name
    file_list = drive.ListFile({'q': f"title='{filename}'"}).GetList()

    # If the file is found, return its ID
    for file in file_list:
        if file['title'] == filename:
            return file['id']
    return None

def extract_patch_from_masked_data(red_clip, green_clip, blue_clip, mask):
    # Find where the mask is True
    rows, cols = np.where(mask)

    # Get the bounding box coordinates
    top_row = np.min(rows)
    bottom_row = np.max(rows)
    left_col = np.min(cols)
    right_col = np.max(cols)

    # Extract the patch using the bounding box
    red_patch = red_clip[top_row:bottom_row+1, left_col:right_col+1]
    green_patch = green_clip[top_row:bottom_row+1, left_col:right_col+1]
    blue_patch = blue_clip[top_row:bottom_row+1, left_col:right_col+1]

    return red_patch, green_patch, blue_patch

def calcular_porcentaje_bosques():
    # Autenticación con almacenamiento de credenciales para evitar loguearse cada vez
    gauth = GoogleAuth()
    try:
        gauth.LoadCredentialsFile("mycreds.txt")
        if gauth.credentials is None:
            gauth.LocalWebserverAuth()
        elif gauth.access_token_expired:
            gauth.Refresh()
        else:
            gauth.Authorize()
        gauth.SaveCredentialsFile("mycreds.txt")
    except Exception as e:
        print(f"Error de autenticación con Google Drive, reautenticando: {e}")
        if os.path.exists("mycreds.txt"):
            try:
                os.remove("mycreds.txt")
            except Exception as remove_err:
                print(f"No se pudo eliminar mycreds.txt: {remove_err}")
        gauth = GoogleAuth()
        gauth.LocalWebserverAuth()
        gauth.SaveCredentialsFile("mycreds.txt")

    # Crear un objeto de GoogleDrive utilizando la autenticación
    drive = GoogleDrive(gauth)
    

    id_carpeta = '1TvcWff-3Qt-U7WFuzRDRRbnP3UHHezVB'

    archivos_en_carpeta = drive.ListFile({'q': f"'{id_carpeta}' in parents and trashed=false"}).GetList()

    for archivo in archivos_en_carpeta:
        try:
            archivo.Delete()
            print(f"Archivo '{archivo['title']}' eliminado correctamente.")
        except:
            print(f"No se pudo eliminar el archivo '{archivo['title']}'.")

    print("Archivos en la carpeta eliminados correctamente.")

    
    # obtener geometria
    geo_filepath = "./shapefiles/generated/nombre_shapefile.shp"
    GeoDF = gpd.read_file(geo_filepath)
    G = np.random.choice(GeoDF.geometry.values)
    Rectangle = G.envelope
    
    # Call the function
    fechas_dict = [2018, 2019, 2020, 2021]

    for i, fecha in enumerate(fechas_dict):
        start_date = str(fecha) + "-01-01" 
        fecha += 1
        end_date = str(fecha) + "-01-01" 
        name_file =  f"RectangleExport_{i+1}"
        task = export_rectangle_to_drive(Rectangle,name_file=name_file,start_date=start_date, end_date=end_date)

    while task.active():
        print("Polling for task (id: {}).".format(task.id))
        time.sleep(10)  # Wait for 5 minutes
        status = check_task_status(task)
        print(status)

    # Usage
    for i, fecha in enumerate(fechas_dict):
        file_id = get_file_id_by_name(f'RectangleExport_{i+1}.tif', drive)

        downloaded = drive.CreateFile({'id': file_id})
        os.makedirs('imagenes/descargas', exist_ok=True)
        downloaded.GetContentFile(f'imagenes/descargas/downloaded_image_{i+1}.tif')
    
    #Calcular division de geometrias
    rect_coords = np.array(Rectangle.boundary.coords.xy)
    y_list = rect_coords[1]
    x_list = rect_coords[0]
    y1 = min(y_list)
    y2 = max(y_list)
    x1 = min(x_list)
    x2 = max(x_list)
    width = x2 - x1
    height = y2 - y1
    xcells = int(width * 100)
    ycells = int(height * 100)
    yindices = np.linspace(y1, y2, ycells + 3)
    xindices = np.linspace(x1, x2, xcells + 5)
    horizontal_splitters = [
    LineString([(x, yindices[0]), (x, yindices[-1])]) for x in xindices
    ]
    vertical_splitters = [
        LineString([(xindices[0], y), (xindices[-1], y)]) for y in yindices
    ]
    result = Rectangle
    for splitter in vertical_splitters:
        result = MultiPolygon(split(result, splitter))

    for splitter in horizontal_splitters:
        result = MultiPolygon(split(result, splitter))
    square_polygons = list(result.geoms)
    SquareGeoDF  = gpd.GeoDataFrame(square_polygons).rename(columns={0: "geometry"})
    SquareGeoDF = gpd.GeoDataFrame(square_polygons)

    SquareGeoDF = SquareGeoDF.set_geometry(0)

    Geoms = SquareGeoDF[SquareGeoDF.intersects(G)].geometry.values
    shape = "square"
    thresh = 0.9

    if shape == "rhombus":
        geoms = [g for g in Geoms if ((g.intersection(G)).area / g.area) >= thresh]
    elif shape == "square":
        geoms = [g for g in Geoms if ((g.intersection(G)).area / g.area) >= thresh]
    grid = gpd.GeoDataFrame({'geometry':geoms})
    class_id_to_label = {
        0: "ann_crop",
        1: "forest",
        2: "herb_veg",
        3: "highway",
        4: "industrial",
        5: "pasture",
        6: "perm_crop",
        7: "residential",
        8: "river",
        9: "sea_lake"
    }
    class_id_to_color = {
        0: (0, 0, 255),  # Red
        1: (0, 143, 57),  # Blue
        2: (0, 255, 0),  # Green
        3: (0, 255, 255),  # Yellow
        4: (0, 165, 255),  # Orange
        5: (128, 0, 128),  # Purple
        6: (145, 176, 255),  # Cyan
        7: (255, 0, 255),  # Magenta
        8: (128, 0, 0),  # Brown
        9: (235, 206, 135)  # Lime
    }
    # Setup device agnostic code
    device = "cuda" if torch.cuda.is_available() else "cpu"
    # Load Model
    path = './models/ViT_Satellite.pth'
    # 1. Get pretrained weights for ViT-Base
    model_weights = torchvision.models.ViT_B_16_Weights.DEFAULT # requires torchvision >= 0.13, "DEFAULT" means best available


    # Get automatic transforms from pretrained ViT weights
    transform_im = model_weights.transforms()
    print(transform_im)

    # 2. Setup a ViT model instance with pretrained weights
    model = torchvision.models.vit_b_16(weights=model_weights).to(device)


    # 3. Freeze the base parameters
    for parameter in model.parameters():
        parameter.requires_grad = False

    # 4. Change the classifier head (set the seeds to ensure same initialization with linear head)
    model.heads = nn.Linear(in_features=768, out_features=10).to(device)
    model.load_state_dict(torch.load(path, map_location='cpu'))

    for i, fecha in enumerate(fechas_dict):
        model.eval()

        bboxes = []
        with rasterio.open(f'imagenes/descargas/downloaded_image_{i+1}.tif') as src:
            # Read the RGB bands
            red = src.read(1)
            green = src.read(2)
            blue = src.read(3)
            transform = src.transform
            

            full_mask = np.zeros_like(red, dtype=bool)
            forest = 0
            
            for i, polygon in enumerate(geoms):
                
                # Convert to pixel coordinates
                pixel_polygon = [~transform * (x, y) for x, y in polygon.exterior.coords]
                
                # Create a mask for the polygon
                geojson_polygon = mapping(polygon)
                mask = geometry_mask([geojson_polygon], transform=transform, invert=True, out_shape=src.shape)
                full_mask = np.logical_or(full_mask, mask)
                
                red_clip = src.read(1) * mask
                green_clip = src.read(2) * mask
                blue_clip = src.read(3) * mask

                red_patch, green_patch, blue_patch = extract_patch_from_masked_data(red_clip, green_clip, blue_clip, mask)

                pixel_shapely_polygon = Polygon(pixel_polygon)
                x1, y1, x2, y2 = pixel_shapely_polygon.bounds
                x1 = int(x1)
                y1 = int(y1)
                x2 = int(x2)
                y2 = int(y2)
                
                bands_8bit = []
                for band_name in [red_patch, green_patch, blue_patch]:
                    band_data = band_name
                    min_val = 0
                    max_val = 3200
                    band_8bit = ((band_data - min_val) / (max_val - min_val)) * 255
                    band_8bit = np.clip(band_8bit, 0, 255).round().astype(np.uint8)
                    bands_8bit.append(band_8bit)

                data_8bit = np.stack(bands_8bit, axis=-1)

                # Inference

                pil_image = Image.fromarray(data_8bit)
                tensor_im  = transform_im(pil_image).unsqueeze(0)

                with torch.no_grad():
                    outputs = model(tensor_im.to(device))
                    
                    # Convert raw output scores to probabilities
                    probabilities = F.softmax(outputs, dim=1)
                    
                    # Get the predicted class and its probability
                    _, preds = torch.max(outputs, 1)
                    pred_class = preds.item()
                    pred_prob = probabilities[0][pred_class].item()

                    bboxes.append([pred_class, pred_prob, x1, y1, x2, y2])

                    #print(f"Predicted class: {class_id_to_label[pred_class]}, clase:{pred_class} , x1: {x1}, y1: {y1}, x2:{x2}, y2:{y2}, shape image: {(x2-x1, y2-y1)}")

                    if pred_class == 1:
                        forest += 1
                
            # Save or visualize the clipped image

            # Apply the mask to the RGB bands
            red_masked = np.where(full_mask, red, 0)
            green_masked = np.where(full_mask, green, 0)
            blue_masked = np.where(full_mask, blue, 0)

            bands_8bit = []
            for band_name in [red_masked, green_masked, blue_masked]:
                band_data = band_name
                min_val = 0
                max_val = 3200 #band_data.max()
                band_8bit = ((band_data - min_val) / (max_val - min_val)) * 255
                band_8bit = np.clip(band_8bit, 0, 255).round().astype(np.uint8)
                bands_8bit.append(band_8bit)

            data_8bit = np.stack(bands_8bit, axis=-1)

            #cv2.imwrite(f'full_geom.png', cv2.cvtColor(data_8bit, cv2.COLOR_RGB2BGR))
            print(f"% de bosques en imagen: {(forest / len(geoms))* 100:.2f}%")

