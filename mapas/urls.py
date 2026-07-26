from django.urls import path

from mapas.views import maps, vista_satelite, evaluacion

urlpatterns = [
   path('', maps, name='main'),
   path('vista_satelite/<str:url>/', vista_satelite, name='vista_satelite'),
   path('evaluacion/', evaluacion, name='evaluacion'),
]