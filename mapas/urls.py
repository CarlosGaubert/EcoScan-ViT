from django.urls import path

from mapas.views import (
    maps, 
    vista_satelite, 
    evaluacion, 
    vista_evaluacion, 
    iniciar_evaluacion, 
    progreso_evaluacion, 
    eliminar_area
)

urlpatterns = [
    path('', maps, name='main'),
    path('vista_satelite/<str:url>/', vista_satelite, name='vista_satelite'),
    path('evaluacion/', evaluacion, name='evaluacion'),
    path('evaluacion/<int:id_imagen>/', vista_evaluacion, name='vista_evaluacion'),
    path('iniciar_evaluacion/', iniciar_evaluacion, name='iniciar_evaluacion'),
    path('progreso_evaluacion/<str:task_id>/', progreso_evaluacion, name='progreso_evaluacion'),
    path('eliminar_area/<int:id_imagen>/', eliminar_area, name='eliminar_area'),
]