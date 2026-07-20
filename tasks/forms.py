from django import forms
from django.core.validators import FileExtensionValidator, RegexValidator
import win32print
from datetime import datetime


class UploadTaskForm(forms.Form):

    user_id = forms.IntegerField(
            label='Responsable',
            widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'id': 'floatingInput',
                'readonly': True,
                'placeholder': 'Responsable',
                }
            ),
            
    
   ) 

    # rif_proveedor = forms.CharField(
    #     label = "Rif del proveedor",
    #     max_length=10,
    #     widget=forms.TextInput(
    #         attrs={
    #             'class': 'form-control',
    #             'placeholder': 'Ingrese el RIF del proveedor',
    #             'id': 'rif_proveedor',
    #             'required': 'true'
    #         }
    #     ),
    #     validators=[
    #         RegexValidator(
    #             regex=r'^[JGVE][0-9]{9}$',
    #             message='El RIF debe comenzar con J, G, V, E seguido de 9 dígitos.',
    #             code='invalid_rif'
    #         )
    #     ]
    # )

    file = forms.FileField(
        label= 'Selecciona un archivo de excel',
        validators=[FileExtensionValidator(allowed_extensions=['xlsx', 'xls'])],
        widget=forms.FileInput(
            attrs={
                'class': 'form-control',
                'accept': '.xlsx, .xls',
                'id': 'formFile'
                    }
                            )
                        )
    date_time = forms.DateField(
        label='Fecha y hora',
        widget=forms.DateInput(
            attrs={
                'class': 'form-control',
                'type': 'date',
                'id': 'date_time',
                'required': 'true',
                'onkeydown': 'return false'
            }
        ),
        input_formats=['%Y-%m-%d'],
        initial=datetime.now().strftime('%Y-%m-%d')
        
    )
    check_process = forms.BooleanField(
        label='Procesar de inmediato',
        required=False,
        initial=False,
        widget=forms.CheckboxInput(
            attrs={
                'class': 'form-check-input',
                'type': 'checkbox',
                'role': 'switch',
                'id': 'check_process',
                'placeholder': 'Procesar archivo sin esperar fecha',
            }
        ),
    )

    validar_ofertas = forms.BooleanField(
        label='Validar ofertas',
        required=False,
        initial=False,
        help_text='Desmarcar si desea actualizar precios de productos con ofertas activas',
        widget=forms.CheckboxInput(
            attrs={
                'class': 'form-check-input',
                'type': 'checkbox',
                'role': 'switch',
                'id': 'validar_ofertas',
                'placeholder': 'Validar ofertas al procesar el archivo',
                
            }
        )
        
    )

    header = forms.IntegerField(
        label='Encabezado del archivo',
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'Ingrese el numero de fila de la tabla',
                'required': 'true',
                'id': 'header'

            }
        )
    )

    is_oferta = forms.BooleanField(
        label='Es oferta',
        required=False,
        initial=False,
        help_text='Marcar si el archivo contiene productos en oferta',
        widget=forms.CheckboxInput(
            attrs={
                'class': 'form-check-input',
                'type': 'checkbox',
                'role': 'switch',
                'id': 'is_oferta',
                'placeholder': 'Marcar si el archivo contiene productos en oferta',
            }
        )
    )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super(UploadTaskForm, self).__init__(*args, **kwargs)
        if self.user:
            self.initial['user_id'] = self.user.id


class PrintLabelTask(forms.Form):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['so_printers'].choices = self.get_system_printers()

    list_id = forms.IntegerField(label='Id lista', required=True,error_messages={'error': 'Por favor ingrese un ID de lista válido'},
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'id': 'floatingInput',
                'placeholder': 'Responsable',
                }
            )

    )

    so_printers = forms.ChoiceField(
            widget= forms.Select(
                    attrs={
                        'class': 'form-select',
                        'id': 'floatingInput',
                        'placeholder': 'Responsable'},
                       
              ),
              choices=[],
        )
    formato_label = forms.ChoiceField(
            widget= forms.Select(
                    attrs={
                        'class': 'form-select',
                        'id': 'floatingInput',
                        'placeholder': 'Responsable'},
                       
              ),
              choices=[('Ofertas', 'OfertasKsa'), ('Hablador', 'HabladorKsa')],
        )
    

    logo_etiquetas = forms.ChoiceField(
            widget= forms.Select(
                    attrs={
                        'class': 'form-select',
                        'id': 'floatingInput',
                        'placeholder': 'Responsable'},
                       
              ),
              choices=[('KsaHome', 'Ksa Home'), ('KsaConstructor', 'Ksa Constructor')],
        )
    validar_existencia = forms.BooleanField(
        label='Validar existencia',
        required=False,
        initial=True,
        help_text='Desmarcar si desea imprimir etiquetas sin validar existencia',
        widget=forms.CheckboxInput(
            attrs={
                'class': 'form-check-input',
                'type': 'checkbox',
                'role': 'switch',
                'id': 'validar_existencia',
                'placeholder': 'Validar existencia al imprimir etiquetas',
            }
        )
    )

    departamento = forms.CharField(
        label='Departamento',
        required=False,
        max_length=40,
        widget=forms.HiddenInput(),
    )

    rango_desde = forms.IntegerField(
        label='Desde',
        required=False,
        min_value=1,
        widget=forms.NumberInput(
            attrs={
                'class': 'form-control',
                'id': 'rango_desde',
                'placeholder': 'Desde',
            }
        )
    )

    rango_hasta = forms.IntegerField(
        label='Hasta',
        required=False,
        min_value=1,
        widget=forms.NumberInput(
            attrs={
                'class': 'form-control',
                'id': 'rango_hasta',
                'placeholder': 'Hasta',
            }
        )
    )

    def clean(self):
        cleaned_data = super().clean()
        departamento = cleaned_data.get('departamento') or None
        if not departamento:
            desde = cleaned_data.get('rango_desde')
            hasta = cleaned_data.get('rango_hasta')
            if (desde is None) != (hasta is None):
                raise forms.ValidationError('Debe completar ambos campos del rango (Desde y Hasta).')
            if desde is not None and hasta is not None and hasta < desde:
                raise forms.ValidationError("'Hasta' debe ser mayor o igual que 'Desde'.")
        return cleaned_data

    def get_system_printers(self):
        printer_system = win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL)
        return [(printer[2], printer[2]) for printer in printer_system]