from django import forms

from .models import Galpon, Rack


class GalponForm(forms.ModelForm):
    class Meta:
        model = Galpon
        fields = ['codigo', 'nombre', 'grid_filas', 'grid_columnas']
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 1'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Galpón 1'}),
            'grid_filas': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'grid_columnas': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }


class RackForm(forms.ModelForm):
    class Meta:
        model = Rack
        fields = ['codigo', 'descripcion', 'grid_fila', 'grid_columna', 'ancho', 'alto', 'max_niveles']
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: A'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Descripción opcional'}),
            'grid_fila': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'grid_columna': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'ancho': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'alto': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'max_niveles': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }
        labels = {'max_niveles': 'Máximo de niveles'}

    def __init__(self, *args, bloquear_max_niveles=False, **kwargs):
        super().__init__(*args, **kwargs)
        if bloquear_max_niveles:
            self.fields['max_niveles'].disabled = True
            self.fields['max_niveles'].help_text = 'No editable: el rack ya tiene cuerpos creados.'
