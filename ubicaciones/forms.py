from django import forms

from .models import Cuerpo, Galpon, Nivel, Rack, Ubicacion


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


class CuerpoForm(forms.ModelForm):
    class Meta:
        model = Cuerpo
        fields = ['descripcion']
        widgets = {
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Descripción opcional'}),
        }


class UbicacionForm(forms.ModelForm):
    class Meta:
        model = Ubicacion
        fields = ['descripcion']
        widgets = {
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Descripción opcional'}),
        }


class NivelForm(forms.ModelForm):
    class Meta:
        model = Nivel
        fields = ['tipo', 'descripcion']
        widgets = {
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Descripción opcional'}),
        }


class AsignarProductoAccionForm(forms.Form):
    codigo_producto = forms.CharField(
        max_length=50, label='Código de producto',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    cantidad = forms.IntegerField(
        min_value=0, label='Cantidad',
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    stock_minimo = forms.IntegerField(
        min_value=0, required=False, label='Stock mínimo (solo picking)',
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )

    def clean_codigo_producto(self):
        return self.cleaned_data['codigo_producto'].strip().upper()


class EditarCantidadForm(forms.Form):
    cantidad = forms.IntegerField(
        min_value=0, label='Cantidad',
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    stock_minimo = forms.IntegerField(
        min_value=0, required=False, label='Stock mínimo (solo picking)',
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )


class TrasladarForm(forms.Form):
    codigo_producto = forms.CharField(
        max_length=50, label='Código de producto',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    nivel_origen = forms.ModelChoiceField(
        queryset=Nivel.objects.filter(activo=True, fusionado_en__isnull=True).select_related('ubicacion__cuerpo__rack'),
        label='Nivel origen', widget=forms.Select(attrs={'class': 'form-select'}),
    )
    nivel_destino = forms.ModelChoiceField(
        queryset=Nivel.objects.filter(activo=True, fusionado_en__isnull=True).select_related('ubicacion__cuerpo__rack'),
        label='Nivel destino', widget=forms.Select(attrs={'class': 'form-select'}),
    )
    notas = forms.CharField(
        required=False, label='Notas', widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def clean(self):
        cleaned = super().clean()
        origen = cleaned.get('nivel_origen')
        destino = cleaned.get('nivel_destino')
        if origen and destino and origen.pk == destino.pk:
            raise forms.ValidationError('El nivel origen y destino deben ser distintos.')
        return cleaned


class FusionarForm(forms.Form):
    niveles = forms.ModelMultipleChoiceField(
        queryset=Nivel.objects.filter(activo=True, fusionado_en__isnull=True).select_related('ubicacion__cuerpo__rack'),
        label='Niveles a fusionar', widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': 8}),
    )
    maestro = forms.ModelChoiceField(
        queryset=Nivel.objects.filter(activo=True, fusionado_en__isnull=True).select_related('ubicacion__cuerpo__rack'),
        label='Nivel maestro (recibe el stock)', widget=forms.Select(attrs={'class': 'form-select'}),
    )
    notas = forms.CharField(
        required=False, label='Notas', widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def clean(self):
        cleaned = super().clean()
        niveles = cleaned.get('niveles')
        maestro = cleaned.get('maestro')
        if niveles and len(niveles) < 2:
            raise forms.ValidationError('Selecciona al menos 2 niveles para fusionar.')
        if niveles and maestro and maestro not in niveles:
            raise forms.ValidationError('El maestro debe estar entre los niveles seleccionados.')
        return cleaned
