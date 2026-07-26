import os

def mapbox_token(request):
    """
    Inyecta el token de Mapbox desde las variables de entorno (.env)
    a todas las plantillas HTML del sistema de forma global.
    """
    return {
        'MAPBOX_ACCESS_TOKEN': os.getenv('MAPBOX_ACCESS_TOKEN', '')
    }
