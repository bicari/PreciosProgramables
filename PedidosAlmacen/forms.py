from django import forms


class PedidoForm(forms.Form):
    observaciones = forms.CharField(
        label='Observaciones',
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Observaciones del pedido (opcional)',
        })
    )
