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

class DescargaImagenForm(forms.Form):
    titulo = forms.FloatField(label="Título área de estudio", widget=forms.TextInput(attrs={'class': 'form-control Rent',}))
    geometria = forms.FloatField(label="Geometria", widget=forms.TextInput(attrs={'class': 'form-control'}))
    shapefiles = MultiFileField(min_num=1, max_num=20, max_file_size=1024*1024*5, required=False)  # Hasta 5 MB por archivo y hasta 20 archivos

    metros_cuadrados = forms.FloatField(
        label="Metros cuadrados",
        widget=forms.TextInput(attrs={'class': 'form-control Rent','readonly': 'readonly'})
    )

class ImagenesDescargadasForm(forms.Form):
    imagenes = forms.ModelChoiceField(label="Area de estudio", queryset=models.ImagenSatelital.objects.all(), widget=forms.Select(attrs={'class': 'form-control Rent'}))