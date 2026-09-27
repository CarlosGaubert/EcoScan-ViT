
import base64
import io
import os
import time
import json
import shutil
import uuid
import threading
from datetime import datetime, timedelta
from io import BytesIO

from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseRedirect
from django.contrib import messages
from django.db import connection
from django.core.files.base import ContentFile
from django.conf import settings

import requests
import numpy as np  
import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon, LineString, mapping
from shapely.ops import split
import rasterio
from rasterio.features import geometry_mask
from PIL import Image
import cv2
import torch
from torch import nn
import torch.nn.functional as F
import torchvision
from torchvision import models, transforms
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import ee
from mapas.forms import DescargaImagenForm, ImagenesDescargadasForm
from .models import ImagenSatelital, Satelite, Tipo_Imagen, SubImagenSatelital

# Diccionario thread-safe para rastreo de progreso de evaluación
PROGRESS_LOCK = threading.Lock()
EVAL_PROGRESS = {}

def update_progress(task_id, progress, step, detail="", status="running", id_imagen=None, error_message=None):
    """Actualiza de forma atómica el estado y progreso porcentual de una tarea de evaluación."""
    with PROGRESS_LOCK:
        if task_id not in EVAL_PROGRESS:
            EVAL_PROGRESS[task_id] = {}
        EVAL_PROGRESS[task_id].update({
            'progress': progress,
            'current_step': step,
            'detail': detail,
            'status': status,
            'id_imagen': id_imagen,
            'error_message': error_message,
            'updated_at': time.time()
        })



def inicializar_earth_engine():
  """
  Inicializa la conexión con Google Earth Engine usando el proyecto activo.
  Si las credenciales OAuth expiraron (RefreshError / invalid_grant), lanza un error amigable.
  """
  try:
    project_id = os.getenv('EE_PROJECT_ID', 'proyecto-forest-2026')
    try:
      ee.Initialize(project=project_id)
    except Exception:
      ee.Initialize()
  except Exception as e:
    err_str = str(e)
    if 'invalid_grant' in err_str or 'RefreshError' in err_str or 'credentials' in err_str.lower():
      raise RuntimeError(
        'Las credenciales de Google Earth Engine han expirado (invalid_grant). '
        'Por favor abre una terminal en el servidor y ejecuta "./venv/bin/earthengine authenticate" '
        'para renovar tu sesión con Google.'
      ) from e
    raise


def maps(request):
  if request.method == 'POST':
    print(request.POST)

    # CASO 1: Evaluar área de estudio existente (Formulario 2)
    id_imagen = request.POST.get('imagenes')
    if id_imagen and id_imagen.strip():
      return redirect('vista_evaluacion', id_imagen=id_imagen)

    # CASO 2: Confirmar o Cancelar el guardado tras previsualizar imagen
    if request.POST.get('guardar') == '1':
      tipo_imagen, _ = Tipo_Imagen.objects.get_or_create(name='True color')
      satelite, _ = Satelite.objects.get_or_create(name='Sentinel-2')
      titulo = request.POST.get('titulo') or 'Área de Estudio'

      imagen = ImagenSatelital.objects.create(
        name=titulo,
        coordenadas=request.POST.get('geometria'),
        satelite=satelite,
        tipo_imagen=tipo_imagen,
      )
      imagen.save()

      try:
        calcular_porcentaje_bosques(request, imagen.pk)
      except Exception as eval_error:
        imagen.delete()
        print(f"ERROR durante la evaluación multitemporal: {eval_error}")
        form = DescargaImagenForm()
        form_imagenes = ImagenesDescargadasForm()
        return render(
          request, 
          'maps.html',
          {
            'form': form,
            'form_imagenes': form_imagenes,
            'error_message': f'La evaluación satelital multitemporal falló: {eval_error}. Se canceló el guardado del área.'
          }
        )

      return redirect('vista_evaluacion', id_imagen=imagen.pk)

    elif request.POST.get('guardar') == '0':
      return redirect('main')

    # CASO 3: Descarga y Procesamiento Inicial de Imagen Satelital (Formulario 1)
    else:
      form = DescargaImagenForm(request.POST, request.FILES)
      form_imagenes = ImagenesDescargadasForm()

      raw_geom = request.POST.get('geometria')
      if not raw_geom or not raw_geom.strip():
        return render(
          request, 
          'maps.html',
          {
            'form': form,
            'form_imagenes': form_imagenes,
            'error_message': 'No has seleccionado un área de estudio. Por favor dibuja un rectángulo o polígono en el mapa (esquina superior izquierda) o sube un archivo Shapefile (.zip).'
          }
        )

      geometria = None
      if raw_geom == 'Shapefile cargado.':
        try:
          for uploaded_file in request.FILES.getlist('shapefiles'):
            handle_uploaded_file(uploaded_file)
          shp_file = get_shp_file(request.FILES.getlist('shapefiles'))
          if not shp_file:
            raise ValueError('No se encontró un archivo con extensión .shp dentro del archivo comprimido subido.')
          geoms = process_shapefile("./shapefiles/temp/" + str(shp_file))
          for sq in geoms:
            xx, yy = sq.exterior.coords.xy
            x = xx.tolist()
            y = yy.tolist()
          geometria = list(zip(x, y))
        except Exception as shp_err:
          print(f"Error procesando shapefile: {shp_err}")
          return render(
            request, 
            'maps.html',
            {
              'form': form,
              'form_imagenes': form_imagenes,
              'error_message': f'Error al procesar el archivo Shapefile: {shp_err}'
            }
          )
      else:
        try:
          geometria = json.loads(raw_geom)
        except Exception as json_err:
          print(f"Error decodificando geometría: {json_err}")
          return render(
            request, 
            'maps.html',
            {
              'form': form,
              'form_imagenes': form_imagenes,
              'error_message': 'El formato de las coordenadas recibidas no es válido. Vuelve a trazar el polígono en el mapa.'
            }
          )

      if not geometria or len(geometria) < 3:
        return render(
          request, 
          'maps.html',
          {
            'form': form,
            'form_imagenes': form_imagenes,
            'error_message': 'El polígono trazado debe tener al menos 3 vértices para delimitar una región geográfica.'
          }
        )

      satelite, _ = Satelite.objects.get_or_create(name='Sentinel-2')
      tipoImagen, _ = Tipo_Imagen.objects.get_or_create(name='True color')

      try:
        geo_path = crear_archivo_shapefile(geometria)
        print(f"Generando archivo shapefile en {geo_path}")

        url, capture_date, cloud_pct = descargar_imagen_sentinel(geometria, None, None, tipoImagen, 1500)
        porcentaje = calcular_porcentaje_bosque(geometria)

      except Exception as gee_err:
        print(f"ERROR durante la descarga satelital Sentinel: {gee_err}")
        err_str = str(gee_err)
        if 'invalid_grant' in err_str or 'RefreshError' in err_str or 'credentials' in err_str.lower():
          err_msg = (
            'Error de autenticación con Google Earth Engine (sesión expirada). '
            'Por favor ejecuta "./venv/bin/earthengine authenticate" en tu terminal para reconectar tu cuenta de Google.'
          )
        elif 'Collection is empty' in err_str or 'image is empty' in err_str:
          err_msg = 'No se encontraron capturas satelitales Sentinel-2 sin nubes para el polígono seleccionado.'
        else:
          err_msg = f'No fue posible obtener la imagen desde Google Earth Engine: {gee_err}'

        return render(
          request, 
          'maps.html',
          {
            'form': form,
            'form_imagenes': form_imagenes,
            'error_message': err_msg
          }
        )

      return render(
        request, 
        'visualizar_imagen.html',
        {
          'url': url, 
          'geometria': request.POST.get('geometria'),
          'satelite': satelite.name,
          'tipoImagen_name': tipoImagen.name,
          'tipoImagen_id': tipoImagen.id,
          'fecha_inicio': capture_date,
          'fecha_fin': capture_date,
          'metros_cuadrados': request.POST.get('metros_cuadrados'),
          'titulo': request.POST.get('titulo'),
          'porcentaje': porcentaje,
          'cloud_pct': cloud_pct
        }
      )

  else:
    form = DescargaImagenForm()
    form_imagenes = ImagenesDescargadasForm()
    return render(
      request, 
      'maps.html',
      {'form': form, 'form_imagenes': form_imagenes}
    )
  

def vista_satelite(request, url):
  return render(
        request, 
        'visualizar_imagen.html',
        {'url': url}
  )

def evaluacion(request):
    return redirect('main')

def vista_evaluacion(request, id_imagen):
    """
    Renderiza la vista detallada de evaluación multitemporal para un área de estudio específica.
    Genera el gráfico Matplotlib de decrecimiento forestal y prepara el carrusel de imágenes.
    """
    imagen = get_object_or_404(ImagenSatelital, pk=id_imagen)
    subimagenes = SubImagenSatelital.objects.filter(imagen=imagen).order_by('anio_imagen')
    decrecimiento_forestal = []
    años = []
    for subimagen in subimagenes:
        try:
            decrecimiento_forestal.append(float(subimagen.porcentaje))
            años.append(int(subimagen.anio_imagen))
        except (ValueError, TypeError):
            continue

    if len(decrecimiento_forestal) == 0:
        try:
            messages.error(request, f"El área de estudio '{imagen.name}' no posee análisis anuales válidos en la base de datos.")
        except Exception:
            pass
        return redirect('main')

    plt.figure(figsize=(8, 6))
    plt.plot(años, decrecimiento_forestal, marker='o', color='b', linestyle='-', linewidth=2, markersize=8)
    plt.title('Decrecimiento Forestal por Año')
    plt.xlabel('Año')
    plt.ylabel('Porcentaje de Decrecimiento')
    plt.grid(True)
    plt.xticks(años, rotation=45)

    buffer = io.BytesIO()
    plt.savefig(buffer, format='png')
    buffer.seek(0)
    plt.close()

    imagen_base64 = base64.b64encode(buffer.read()).decode()
    min_year = subimagenes.first().anio_imagen if subimagenes.exists() else ""
    max_year = subimagenes.last().anio_imagen if subimagenes.exists() else ""

    contexto = {
        'imagen_base64': imagen_base64,
        'subimagenes': subimagenes,
        'imagen_satelital': imagen,
        'min_year': min_year,
        'max_year': max_year,
    }
    return render(request, 'evaluacion.html', contexto)

def ejecutar_evaluacion_async(task_id, pk_imagen):
    """Ejecuta la evaluación en un hilo en segundo plano y maneja la sesión de base de datos."""
    try:
        calcular_porcentaje_bosques(None, pk_imagen, task_id=task_id)
    except Exception as err:
        print(f"Error en ejecución asíncrona: {err}")
        try:
            ImagenSatelital.objects.filter(pk=pk_imagen).delete()
        except Exception:
            pass
        update_progress(
            task_id, 0,
            "Error en la evaluación multitemporal",
            str(err),
            status="error",
            error_message=str(err)
        )
    finally:
        connection.close()

def iniciar_evaluacion(request):
    """
    Endpoint AJAX para iniciar la evaluación multitemporal con barra de progreso en tiempo real.
    Crea el registro de ImagenSatelital e inicia el hilo de procesamiento con ViT.
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    titulo = request.POST.get('titulo') or 'Área Sin Título'
    geometria = request.POST.get('geometria')

    if not geometria:
        return JsonResponse({'error': 'No se recibieron coordenadas de geometría.'}, status=400)

    try:
        tipo_imagen, _ = Tipo_Imagen.objects.get_or_create(name='True color')
        satelite, _ = Satelite.objects.get_or_create(name='Sentinel-2')

        imagen = ImagenSatelital.objects.create(
            name=titulo,
            coordenadas=geometria,
            satelite=satelite,
            tipo_imagen=tipo_imagen,
        )

        task_id = uuid.uuid4().hex
        update_progress(
            task_id, 1, 
            "Iniciando evaluación multitemporal...", 
            "Conectando servicios de Google Drive y Earth Engine...", 
            id_imagen=imagen.pk
        )

        thread = threading.Thread(
            target=ejecutar_evaluacion_async,
            args=(task_id, imagen.pk),
            daemon=True
        )
        thread.start()

        return JsonResponse({'task_id': task_id, 'id_imagen': imagen.pk})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

def progreso_evaluacion(request, task_id):
    """Endpoint AJAX para consultar el porcentaje y estado actual de la evaluación."""
    with PROGRESS_LOCK:
        info = EVAL_PROGRESS.get(task_id)
    if not info:
        return JsonResponse({'status': 'unknown', 'progress': 0, 'current_step': 'Buscando tarea...'}, status=404)
    return JsonResponse(info)

def eliminar_area(request, id_imagen):
    """
    Elimina permanentemente un área de estudio y sus subimágenes asociadas de la base de datos y disco.
    """
    if request.method != 'POST':
        return redirect('main')

    imagen = get_object_or_404(ImagenSatelital, pk=id_imagen)
    nombre = imagen.name
    try:
        subimagenes = SubImagenSatelital.objects.filter(imagen=imagen)
        for sub in subimagenes:
            if sub.subImagen:
                try:
                    if os.path.isfile(sub.subImagen.path):
                        os.remove(sub.subImagen.path)
                except Exception:
                    pass
        imagen.delete()
        try:
            messages.success(request, f"El área de estudio '{nombre}' fue eliminada permanentemente.")
        except Exception:
            pass
    except Exception as err:
        try:
            messages.error(request, f"Error al eliminar el área de estudio '{nombre}': {err}")
        except Exception:
            pass

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({'success': True, 'message': f"Área '{nombre}' eliminada con éxito."})

    return redirect('main')

def descargar_imagen_landsat8(geometry, fecha_inicio, fecha_fin, tipoImagen):
  band = ['B4', 'B3', 'B2']

  if tipoImagen.name == 'True color':
    band = ['B4', 'B3', 'B2']
  elif tipoImagen.name == 'False color':
    band = ['B10', 'B4', 'B3']
  elif tipoImagen.name == 'Agriculture':
    band = ['B6', 'B5', 'B2']
  elif tipoImagen.name == 'Urban':
    band = ['B7', 'B6', 'B4']
  # Inicializar la API de Google Earth Engine
  inicializar_earth_engine()

  # Definir la geometría
  geometry = ee.Geometry.Polygon(
    [geometry], None, False);
  
  IMGLandsat8 = ee.ImageCollection('LANDSAT/LC08/C02/T1_RT_TOA') \
      .filterDate(fecha_inicio, fecha_fin) \
      .filterBounds(geometry) \
      .sort('CLOUD_COVER', True)

  # Obtener la imagen con menor nubosidad (compuesto de las escenas más despejadas)
  Landsat8Filtro = IMGLandsat8.limit(5).median()

  # Recortar la imagen con la geometría
  Landsat8Clip = Landsat8Filtro.clip(geometry)



  imagenRGB = Landsat8Clip.visualize(**{'min': 0,'max': 0.5, 'bands': band})
  extension = 'png'

  url = imagenRGB.getThumbURL({ 'region': geometry, 'dimensions': 500, 'format': extension })
  
  #print(url)
  return url
  
def descargar_imagen_landsat7(geometry, fecha_inicio, fecha_fin, tipoImagen):
  band = ['B3', 'B2', 'B1']

  if tipoImagen.name == 'True color':
    band = ['B3', 'B2', 'B1']
  elif tipoImagen.name == 'False color':
    band = ['B4', 'B3', 'B2']
  elif tipoImagen.name == 'Agriculture':
    band = ['B5', 'B4', 'B3']
  elif tipoImagen.name == 'Urban':
    band = ['B7', 'B5', 'B3']
  # Inicializar la API de Google Earth Engine
  inicializar_earth_engine()

  # Definir la geometría
  geometry = ee.Geometry.Polygon(
    [geometry], None, False);
  
  # Filtra la colección de imágenes Landsat 7
  l7 = (ee.ImageCollection("LANDSAT/LE07/C01/T1_TOA")
        .filterDate(fecha_inicio, fecha_fin)
        .filterBounds(geometry)
        .sort('CLOUD_COVER', True)
        .first())

  # Calcula el promedio focal
  img_fill = l7.focal_mean(1, 'square', 'pixels', 8)

  # Combina la imagen promedio con la imagen Landsat 7 original
  final_image = img_fill.blend(l7)

  
  url = final_image.clip(geometry).getThumbUrl({'min': 0, 'max': 0.3, 'gamma': 1.4, 'bands': band, 'format': 'png'})
  
  
  return url
  

def descargar_imagen_sentinel(geometry, fecha_inicio=None, fecha_fin=None, tipoImagen=None, dimension=1500):
  
  band = ['B4', 'B3', 'B2']

  if tipoImagen.name == 'True color':
    band = ['B4', 'B3', 'B2']
  elif tipoImagen.name == 'False color':
    band = ['B8', 'B4', 'B3']
  elif tipoImagen.name == 'Agriculture':
    band = ['B11', 'B8', 'B2']
  elif tipoImagen.name == 'Urban':
    band = ['B12', 'B11', 'B4']
  
  # Inicializar la API de Google Earth Engine con manejo de sesión
  inicializar_earth_engine()

  # Definir la geometría
  geometry = ee.Geometry.Polygon([geometry], None, False)

  collection = ee.ImageCollection('COPERNICUS/S2_HARMONIZED') \
      .filterBounds(geometry)

  # Filtrar por fecha si se especificó un rango
  if fecha_inicio and fecha_fin and fecha_inicio != fecha_fin:
    collection = collection.filterDate(fecha_inicio, fecha_fin)
  else:
    # Priorizar imágenes de los últimos 180 días para mantener actualidad
    now = datetime.now()
    hace_180_dias = (now - timedelta(days=180)).strftime('%Y-%m-%d')
    hoy = now.strftime('%Y-%m-%d')
    recent_col = collection.filterDate(hace_180_dias, hoy)
    try:
      if recent_col.size().getInfo() > 0:
        collection = recent_col
    except Exception:
      pass

  # Ordenar de menor a mayor porcentaje de nubes para obtener la escena con menor nubosidad
  collection = collection.sort('CLOUDY_PIXEL_PERCENTAGE', True)

  image = collection.first()

  try:
    date_str = ee.Date(image.get('system:time_start')).format('YYYY-MM-DD').getInfo()
  except Exception as e:
    print(f"Error getting image date: {e}")
    date_str = datetime.now().strftime('%Y-%m-%d')

  try:
    cloud_pct = image.get('CLOUDY_PIXEL_PERCENTAGE').getInfo()
    cloud_pct_str = f"{cloud_pct:.2f}" if cloud_pct is not None else "0.00"
  except Exception:
    cloud_pct_str = "0.00"

  datasetClip = image.clip(geometry)
  imagenRGB = datasetClip.visualize(**{'min': 0, 'max': 3200, 'bands': band})
  extension = 'png'

  url = imagenRGB.getThumbURL({'region': geometry, 'dimensions': dimension, 'format': extension})
  
  return url, date_str, cloud_pct_str
   
def calcular_porcentaje_bosque(geometry, fecha_inicio=None, fecha_fin=None):
    # Inicializar la API de Google Earth Engine con manejo de sesión
    inicializar_earth_engine()

    geometry = ee.Geometry.Polygon([geometry], None, False)

    # Filtrar la colección Sentinel-2 Harmonized
    collection = ee.ImageCollection('COPERNICUS/S2_HARMONIZED') \
        .filterBounds(geometry)

    if fecha_inicio and fecha_fin and fecha_inicio != fecha_fin:
        collection = collection.filterDate(fecha_inicio, fecha_fin)
    else:
        # Priorizar imágenes de los últimos 180 días
        now = datetime.now()
        hace_180_dias = (now - timedelta(days=180)).strftime('%Y-%m-%d')
        hoy = now.strftime('%Y-%m-%d')
        recent_col = collection.filterDate(hace_180_dias, hoy)
        try:
            if recent_col.size().getInfo() > 0:
                collection = recent_col
        except Exception:
            pass

    # Ordenar por menor porcentaje de nubes (ascendente) para usar la imagen más despejada
    collection = collection.sort('CLOUDY_PIXEL_PERCENTAGE', True)

    # Obtener la imagen con menor nubosidad de la colección
    sentinel_image = collection.first()

    # Calcular el NDVI usando las bandas B8 y B4 de Sentinel-2
    ndvi = sentinel_image.normalizedDifference(['B8', 'B4'])

    # Aplicar umbral para identificar bosques
    threshold = 0.2
    bosque = ndvi.gt(threshold)

    # Calcular el porcentaje de bosque en la región de interés
    area_bosque = bosque.multiply(ee.Image.pixelArea()).reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=geometry,
        scale=10  # Resolución espacial de Sentinel-2
    )

    total_area = geometry.area(1)
    info_area = area_bosque.getInfo()
    val_bosque = info_area.get('nd', 0) if info_area else 0
    total_val = total_area.getInfo()
    porcentaje_bosque = (val_bosque / total_val) if total_val and total_val > 0 else 0
    resultado = round(porcentaje_bosque * 100, 2)
    return "{:.2f}".format(resultado)

def crear_archivo_shapefile(geometry):
    polygon = Polygon(tuple(geometry))
    gdf = gpd.GeoDataFrame({'geometry': [polygon]})
    ruta_guardar = 'shapefiles/generated/nombre_shapefile.shp'
    os.makedirs(os.path.dirname(ruta_guardar), exist_ok=True)
    gdf.to_file(ruta_guardar)
    return ruta_guardar




def get_shp_file(files):
    for uploaded_file in files:
        if uploaded_file.name.endswith('.shp'):
            return uploaded_file
    return None

def handle_uploaded_file(f):
    temp_folder = os.path.join(settings.MEDIA_ROOT, 'shapefiles/temp')
    os.makedirs(temp_folder, exist_ok=True)  # Crea la carpeta temporal si no existe
    file_path = os.path.join(temp_folder, f.name)  # Conserva el nombre original del archivo
    with open(file_path, 'wb+') as destination:
        for chunk in f.chunks():
            destination.write(chunk)
    return file_path

def process_shapefile(file):
    print(file)
    gdf = gpd.read_file(file)
    geometries = gdf.geometry  
    return geometries
  
def eliminar_contenido_carpeta(carpeta_a_eliminar ):
    if os.path.exists(carpeta_a_eliminar):
        for contenido in os.listdir(carpeta_a_eliminar):
            contenido_ruta = os.path.join(carpeta_a_eliminar, contenido)
            if os.path.isfile(contenido_ruta):
                os.remove(contenido_ruta)      
            elif os.path.isdir(contenido_ruta):
                shutil.rmtree(contenido_ruta)
        os.rmdir(carpeta_a_eliminar)
    else:
        print(f"La carpeta '{carpeta_a_eliminar}' no existe.")



#################################################################################################
#################################################################################################
#################################################################################################
#################################################################################################
#################################################################################################
#################################################################################################
#################################################################################################
#################################################################################################
#################################################################################################




def export_rectangle_to_drive(Rectangle, name_file, start_date, end_date):
    inicializar_earth_engine()
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

def calcular_porcentaje_bosques(request, pk_imagen, task_id=None):
    if task_id:
        update_progress(task_id, 2, "Iniciando autenticación y servicios...", "Verificando conexión con Google Drive y Earth Engine...")

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

    if task_id:
        update_progress(task_id, 6, "Sincronizando almacenamiento temporal...", "Limpiando directorio en Google Drive...")

    id_carpeta = '1TvcWff-3Qt-U7WFuzRDRRbnP3UHHezVB'

    try:
        archivos_en_carpeta = drive.ListFile({'q': f"'{id_carpeta}' in parents and trashed=false"}).GetList()
        for archivo in archivos_en_carpeta:
            try:
                archivo.Delete()
                print(f"Archivo '{archivo['title']}' eliminado correctamente.")
            except Exception:
                pass
    except Exception as clean_err:
        print(f"Aviso al limpiar carpeta en Drive: {clean_err}")

    # Obtener geometría
    geo_filepath = "./shapefiles/generated/nombre_shapefile.shp"
    GeoDF = gpd.read_file(geo_filepath)
    G = np.random.choice(GeoDF.geometry.values)
    Rectangle = G.envelope
    
    fechas_dict = [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]
    total_anios = len(fechas_dict)

    if task_id:
        update_progress(task_id, 12, f"Enviando {total_anios} tareas a Google Earth Engine...", "Iniciando exportación multitemporal (2018-2026)...")

    tasks = []
    for i, fecha in enumerate(fechas_dict):
        start_date = str(fecha) + "-01-01" 
        end_date = str(fecha + 1) + "-01-01" 
        name_file = f"RectangleExport_{i+1}"
        task = export_rectangle_to_drive(Rectangle, name_file=name_file, start_date=start_date, end_date=end_date)
        tasks.append(task)

    # Monitorear tareas en Google Earth Engine (Progreso: 15% a 40%)
    while True:
        completed_tasks = sum(1 for t in tasks if not t.active())
        if task_id:
            pct_gee = 15 + int((completed_tasks / total_anios) * 25)
            update_progress(
                task_id, pct_gee,
                f"Procesando en Google Earth Engine ({completed_tasks}/{total_anios} años listos)...",
                "Componiendo escenas satelitales Sentinel-2 con mínima nubosidad..."
            )
        if completed_tasks == total_anios:
            break
        time.sleep(5)

    # Calcular división de geometrías
    if task_id:
        update_progress(task_id, 40, "Dividiendo área en parches espaciales...", "Generando cuadrícula de muestreo para IA...")

    rect_coords = np.array(Rectangle.boundary.coords.xy)
    y_list = rect_coords[1]
    x_list = rect_coords[0]
    y1, y2 = min(y_list), max(y_list)
    x1, x2 = min(x_list), max(x_list)
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
    SquareGeoDF = gpd.GeoDataFrame(square_polygons)
    SquareGeoDF = SquareGeoDF.set_geometry(0)

    Geoms = SquareGeoDF[SquareGeoDF.intersects(G)].geometry.values
    thresh = 0.9

    geoms = [g for g in Geoms if ((g.intersection(G)).area / g.area) >= thresh]
    if len(geoms) == 0:
        geoms = Geoms

    # Configuración del modelo ViT
    device = "cuda" if torch.cuda.is_available() else "cpu"
    path = './models/ViT_Satellite.pth'
    model_weights = torchvision.models.ViT_B_16_Weights.DEFAULT
    transform_im = model_weights.transforms()
    model = torchvision.models.vit_b_16(weights=model_weights).to(device)
    for parameter in model.parameters():
        parameter.requires_grad = False
    model.heads = nn.Linear(in_features=768, out_features=10).to(device)
    model.load_state_dict(torch.load(path, map_location='cpu'))

    # Descarga de rasters desde Drive (Progreso: 40% a 50%)
    os.makedirs('imagenes/descargas', exist_ok=True)
    for i, fecha in enumerate(fechas_dict):
        if task_id:
            pct_dl = 40 + int(((i + 1) / total_anios) * 10)
            update_progress(
                task_id, pct_dl,
                f"Descargando imágenes satelitales ({i+1}/{total_anios})...",
                f"Descargando GeoTIFF del año {fecha}..."
            )
        file_id = get_file_id_by_name(f'RectangleExport_{i+1}.tif', drive)
        if file_id:
            downloaded = drive.CreateFile({'id': file_id})
            downloaded.GetContentFile(f'imagenes/descargas/downloaded_image_{i+1}.tif')

    # Inferencia con IA Parche por Parche (Progreso: 50% a 95%)
    total_parches = len(geoms)
    total_evaluaciones = total_anios * total_parches
    evaluacion_idx = 0

    imagen = ImagenSatelital.objects.get(pk=pk_imagen)
    satelite, _ = Satelite.objects.get_or_create(name='Sentinel-2')
    titulo = request.POST.get('titulo') if request else imagen.name

    for year_idx, fecha in enumerate(fechas_dict):
        model.eval()
        bboxes = []
        tif_path = f'imagenes/descargas/downloaded_image_{year_idx+1}.tif'
        if not os.path.exists(tif_path):
            continue

        with rasterio.open(tif_path) as src:
            red = src.read(1)
            green = src.read(2)
            blue = src.read(3)
            transform = src.transform
            full_mask = np.zeros_like(red, dtype=bool)
            forest = 0

            for patch_idx, polygon in enumerate(geoms):
                evaluacion_idx += 1
                if task_id:
                    pct_ia = 50 + int((evaluacion_idx / total_evaluaciones) * 45)
                    patch_pct_year = int(((patch_idx + 1) / total_parches) * 100)
                    update_progress(
                        task_id, pct_ia,
                        f"Analizando con IA (ViT): Año {fecha} - Parche {patch_idx + 1}/{total_parches} ({patch_pct_year}%)",
                        f"Inferencia neuronal ({evaluacion_idx}/{total_evaluaciones} parches clasificados)..."
                    )

                pixel_polygon = [~transform * (x, y) for x, y in polygon.exterior.coords]
                geojson_polygon = mapping(polygon)
                mask = geometry_mask([geojson_polygon], transform=transform, invert=True, out_shape=src.shape)
                full_mask = np.logical_or(full_mask, mask)

                red_clip = src.read(1) * mask
                green_clip = src.read(2) * mask
                blue_clip = src.read(3) * mask

                red_patch, green_patch, blue_patch = extract_patch_from_masked_data(red_clip, green_clip, blue_clip, mask)
                pixel_shapely_polygon = Polygon(pixel_polygon)
                x1, y1, x2, y2 = pixel_shapely_polygon.bounds
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

                bands_8bit = []
                for band_data in [red_patch, green_patch, blue_patch]:
                    band_data = band_data
                    min_val, max_val = 0, 3200
                    band_8bit = ((band_data - min_val) / (max_val - min_val)) * 255
                    band_8bit = np.clip(band_8bit, 0, 255).round().astype(np.uint8)
                    bands_8bit.append(band_8bit)
                data_8bit = np.stack(bands_8bit, axis=-1)

                pil_image = Image.fromarray(data_8bit)
                tensor_im = transform_im(pil_image).unsqueeze(0)

                with torch.no_grad():
                    outputs = model(tensor_im.to(device))
                    probabilities = F.softmax(outputs, dim=1)
                    _, preds = torch.max(outputs, 1)
                    pred_class = preds.item()
                    pred_prob = probabilities[0][pred_class].item()
                    bboxes.append([pred_class, pred_prob, x1, y1, x2, y2])
                    if pred_class == 1:
                        forest += 1

            # Generar y guardar subimagen del año
            red_masked = np.where(full_mask, red, 0)
            green_masked = np.where(full_mask, green, 0)
            blue_masked = np.where(full_mask, blue, 0)

            bands_8bit = []
            for band_name in [red_masked, green_masked, blue_masked]:
                band_data = band_name
                min_val, max_val = 0, 3200
                band_8bit = ((band_data - min_val) / (max_val - min_val)) * 255
                band_8bit = np.clip(band_8bit, 0, 255).round().astype(np.uint8)
                bands_8bit.append(band_8bit)
            data_8bit = np.stack(bands_8bit, axis=-1)

            start_date = f"{fecha}-01-01"
            end_date = f"{fecha + 1}-01-01"
            nombre_imagen = f"{titulo}_{satelite.name}_{start_date}_{end_date}.png"

            pct_forestal = (forest / len(geoms)) * 100 if len(geoms) > 0 else 0
            subimg_obj = SubImagenSatelital.objects.create(
                imagen=imagen,
                porcentaje=f"{pct_forestal:.2f}",
                anio_imagen=str(fecha)
            )

            success, encoded_img = cv2.imencode('.png', cv2.cvtColor(data_8bit, cv2.COLOR_RGB2BGR))
            if success:
                subimg_obj.subImagen.save(nombre_imagen, ContentFile(encoded_img.tobytes()), save=False)
            subimg_obj.save()

            print(f"Porcentaje de bosques para el año {fecha}: {pct_forestal:.2f}%")

    if task_id:
        update_progress(
            task_id, 100, 
            "¡Evaluación completada con éxito!", 
            "Redirigiendo a la pantalla de resultados...", 
            status="completed", 
            id_imagen=pk_imagen
        )

