import ee

# Inicializa Earth Engine
ee.Initialize()

# Crea una geometría (en este caso, un polígono)
geometry = ee.Geometry.Polygon(
    [[[-73.16234292091593,-36.703380153242165],[-73.08399389414916,-36.70289854269347],[-73.08407970907516,-36.737910640272],[-73.14114663437554,-36.744374782690635],[-73.16654785225397,-36.73158350565598],[-73.16234292091593,-36.703380153242165]]])

# Exporta la geometría a un shapefile
task = ee.batch.Export.table.toDrive(
    collection=ee.FeatureCollection(geometry),
    description='nombre_del_shapefile',
    folder='./TesisGaubert/',
    fileFormat='SHP')

# Inicia la tarea de exportación
task.start()