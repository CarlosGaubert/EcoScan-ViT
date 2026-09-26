import os

def google_maps_api_key(request):
    """
    Inyecta la clave de Google Maps API desde las variables de entorno (.env)
    a todas las plantillas HTML del sistema de forma global.
    """
    return {
        'GOOGLE_MAPS_API_KEY': os.getenv('GOOGLE_MAPS_API_KEY', '')
    }
