from . import models
from django.forms import ModelForm
from django import forms
from multiupload.fields import MultiFileField

class SateliteForm(ModelForm):
    class Meta:
        model = models.Satelite
        fields = ['name']


class TipoImagenForm(ModelForm):
    class Meta:
        model = models.Tipo_Imagen
        fields = ['name']

class MultipleFileInput(forms.FileInput):
    allow_multiple_selected = True

class DescargaImagenForm(forms.Form):
    titulo = forms.CharField(
        label="Título área de estudio", 
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control Rent', 'placeholder': 'Ej. Área de Estudio'})
    )
    geometria = forms.CharField(
        label="Geometría", 
        required=False, 
        widget=forms.TextInput(attrs={'class': 'form-control', 'id': 'id_geometria', 'placeholder': 'Traza un polígono o sube un shapefile'})
    )
    shapefiles = forms.FileField(
        label="Archivo Shapefile", 
        required=False,
        widget=MultipleFileInput(attrs={
            'class': 'form-control',
            'id': 'id_shapefiles',
            'accept': '.zip,.shp,.shx,.dbf,.prj,.cpg,.qpj',
            'multiple': True
        })
    )
    metros_cuadrados = forms.CharField(
        label="Metros cuadrados",
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control Rent', 'readonly': 'readonly', 'id': 'id_metros_cuadrados', 'placeholder': '0.00 m²'})
    )

class ImagenesDescargadasForm(forms.Form):
    imagenes = forms.ModelChoiceField(label="Area de estudio", queryset=models.ImagenSatelital.objects.all(), widget=forms.Select(attrs={'class': 'form-control Rent'}))