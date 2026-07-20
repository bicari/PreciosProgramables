from django import forms

from .models import Nivel, Rack, Ubicacion


class RackForm(forms.ModelForm):
    class Meta:
        model = Rack
        fields = ['codigo', 'descripcion', 'max_niveles']
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: RACK-01'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Descripción opcional'}),
            'max_niveles': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'placeholder': 'Vacío = sin límite'}),
        }
        labels = {
            'max_niveles': 'Máximo de niveles',
        }


class NivelForm(forms.ModelForm):
    class Meta:
        model = Nivel
        fields = ['rack', 'codigo', 'tipo', 'descripcion']
        widgets = {
            'rack': forms.Select(attrs={'class': 'form-select'}),
            'codigo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: N-01'}),
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Descripción opcional'}),
        }

    def __init__(self, *args, rack_fijo=None, **kwargs):
        super().__init__(*args, **kwargs)
        if rack_fijo:
            self.fields['rack'].initial = rack_fijo
            self.fields['rack'].widget = forms.HiddenInput()


class UbicacionForm(forms.ModelForm):
    class Meta:
        model = Ubicacion
        fields = ['nivel', 'codigo', 'descripcion']
        widgets = {
            'nivel': forms.Select(attrs={'class': 'form-select'}),
            'codigo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: U-47'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Descripción opcional'}),
        }

    def __init__(self, *args, nivel_fijo=None, **kwargs):
        super().__init__(*args, **kwargs)
        if nivel_fijo:
            self.fields['nivel'].initial = nivel_fijo
            self.fields['nivel'].widget = forms.HiddenInput()


class AsignarProductoForm(forms.Form):
    codigo_producto = forms.CharField(
        max_length=50,
        label='Código de producto',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Código DBISAM'}),
    )


class TrasladarForm(forms.Form):
    codigo_producto = forms.CharField(
        max_length=50,
        label='Código de producto',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    ubicacion_origen = forms.ModelChoiceField(
        queryset=Ubicacion.objects.filter(activo=True).select_related('nivel__rack'),
        label='Ubicación origen',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    ubicacion_destino = forms.ModelChoiceField(
        queryset=Ubicacion.objects.filter(activo=True).select_related('nivel__rack'),
        label='Ubicación destino',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    notas = forms.CharField(
        required=False,
        label='Notas',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def clean(self):
        cleaned = super().clean()
        origen = cleaned.get('ubicacion_origen')
        destino = cleaned.get('ubicacion_destino')
        if origen and destino and origen.pk == destino.pk:
            raise forms.ValidationError('La ubicación origen y destino deben ser distintas.')
        return cleaned


class FusionarForm(forms.Form):
    ubicacion_a = forms.ModelChoiceField(
        queryset=Ubicacion.objects.filter(activo=True).select_related('nivel__rack'),
        label='Ubicación A (desaparece)',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    ubicacion_b = forms.ModelChoiceField(
        queryset=Ubicacion.objects.filter(activo=True).select_related('nivel__rack'),
        label='Ubicación B (recibe)',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    notas = forms.CharField(
        required=False,
        label='Notas',
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def clean(self):
        cleaned = super().clean()
        a = cleaned.get('ubicacion_a')
        b = cleaned.get('ubicacion_b')
        if a and b and a.pk == b.pk:
            raise forms.ValidationError('Las dos ubicaciones deben ser distintas.')
        return cleaned
