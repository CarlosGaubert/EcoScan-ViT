import ee

def descargar_imagen_landsat8(geometry, fecha_inicio, fecha_fin, tipoImagen):
  band = ['B4', 'B3', 'B2']

  # Inicializar la API de Google Earth Engine
  ee.Initialize()

  # Definir la geometría
  geometry = ee.Geometry.Polygon(
    [geometry], None, False);
  
  IMGLandsat8 = ee.ImageCollection('LANDSAT/LC08/C02/T1_RT_TOA') \
      .filterDate(fecha_inicio, fecha_fin) \
      .filterBounds(geometry) \
      .filterMetadata('CLOUD_COVER', 'less_than', 20)

  # Obtener la imagen mediana
  Landsat8Filtro = IMGLandsat8.median()

  # Recortar la imagen con la geometría
  Landsat8Clip = Landsat8Filtro.clip(geometry)



  imagenRGB = Landsat8Clip.visualize(**{'min': 0,'max': 0.5, 'bands': band})
  extension = 'jpg'

  url = imagenRGB.getThumbURL({ 'region': geometry, 'dimensions': 500, 'format': extension })
  
  print(url)
  return url

geometria = [(-73.0368104858098, -36.7745272641162),
 (-73.13105258175706, -36.7745272641162),
 (-73.13105258175706, -36.705746266993266),
 (-73.0368104858098, -36.705746266993266),
 (-73.0368104858098, -36.7745272641162)]


geometria2 = [[-73.0368104858098 ,-36.7745272641162],
             [-73.13105258175706,-36.7745272641162],
             [-73.13105258175706,-36.705746266993266],
             [-73.0368104858098,-36.705746266993266],
             [ -73.0368104858098 ,-36.7745272641162]]

print(type(geometria))

descargar_imagen_landsat8(geometria, "2018-01-01", '2019-01-01', "True Color")