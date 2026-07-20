from rest_framework import serializers


class OrdenItemSerializer(serializers.Serializer):
    codigo = serializers.CharField(max_length=20)
    orden = serializers.CharField(max_length=20)
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=4)
    recibido = serializers.DecimalField(max_digits=14, decimal_places=4)
    diferencia = serializers.DecimalField(max_digits=14, decimal_places=4)
    costo = serializers.DecimalField(max_digits=14, decimal_places=4)
    iva = serializers.ChoiceField(choices=[0, 16])
    moneda = serializers.ChoiceField(choices=['1', '2'])
    deposito = serializers.IntegerField()
    autoincrement = serializers.IntegerField()
    iva_16_monto = serializers.DecimalField(max_digits=14, decimal_places=4)
    descripcion = serializers.CharField(max_length=255, required=False, allow_blank=True)
    puesto = serializers.CharField(max_length=50, required=False, allow_blank=True)
    referencia = serializers.CharField(max_length=50, required=False, allow_blank=True)
    ref_proveedor = serializers.CharField(max_length=50, required=False, allow_blank=True)


class ProductoSinOcSerializer(serializers.Serializer):
    codigo = serializers.CharField(max_length=20)
    cantidad = serializers.DecimalField(max_digits=14, decimal_places=4)
    costoBS = serializers.DecimalField(max_digits=14, decimal_places=4)
    costoUS = serializers.DecimalField(max_digits=14, decimal_places=4)
    iva = serializers.ChoiceField(choices=[0, 16])
    descripcion = serializers.CharField(max_length=255, required=False, allow_blank=True)
    puesto = serializers.CharField(max_length=50, required=False, allow_blank=True)
    referencia = serializers.CharField(max_length=50, required=False, allow_blank=True)
    ref_proveedor = serializers.CharField(max_length=50, required=False, allow_blank=True)


class NotaEntregaSerializer(serializers.Serializer):
    rif = serializers.CharField(max_length=15)
    proveedor = serializers.CharField(max_length=120)
    direccion_proveedor = serializers.CharField(max_length=255, required=False, allow_blank=True)
    comentario = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    fecha_vencimiento = serializers.DateField()
    ordenes = OrdenItemSerializer(many=True)
    productoSinOc = ProductoSinOcSerializer(many=True)

    def validate(self, data):
        if not data.get('ordenes') and not data.get('productoSinOc'):
            raise serializers.ValidationError("Debe incluir al menos un ítem en 'ordenes' o 'productoSinOc'.")
        return data
