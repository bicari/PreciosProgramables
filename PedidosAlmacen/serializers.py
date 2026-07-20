from rest_framework import serializers
from .models import Pedido, PedidoItem, Despacho, DespachoItem
from users.serializers import UserMinSerializer


class PedidoItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PedidoItem
        fields = [
            'id', 'codigo', 'descripcion', 'referencia', 'puesto',
            'ref_proveedor', 'cantidad_solicitada', 'cantidad_preparada',
            'cantidad_despachada', 'cantidad_back_order', 'cantidad_recibida',
            'estado', 'observacion',
        ]


class PedidoListSerializer(serializers.ModelSerializer):
    solicitante = UserMinSerializer(read_only=True)
    despachador = UserMinSerializer(read_only=True)
    total_items = serializers.SerializerMethodField()
    items_listos = serializers.SerializerMethodField()

    class Meta:
        model = Pedido
        fields = [
            'numero_pedido', 'solicitante', 'despachador', 'estado',
            'condicion', 'deposito', 'observaciones', 'fecha_creacion',
            'fecha_despacho', 'categoria', 'categoria_nombre',
            'deposito_codigo', 'total_items', 'items_listos',
        ]

    def get_total_items(self, obj):
        return obj.items.count()

    def get_items_listos(self, obj):
        return obj.items.filter(cantidad_preparada__isnull=False).count()


class PedidoDetailSerializer(PedidoListSerializer):
    items = PedidoItemSerializer(many=True, read_only=True)

    class Meta(PedidoListSerializer.Meta):
        fields = PedidoListSerializer.Meta.fields + ['items']


class DespachoItemMinSerializer(serializers.ModelSerializer):
    codigo = serializers.SerializerMethodField()
    descripcion = serializers.SerializerMethodField()

    class Meta:
        model = DespachoItem
        fields = [
            'id', 'codigo', 'descripcion',
            'cantidad_despachada', 'cantidad_recibida',
            'observacion', 'tipo_incidencia',
        ]

    def get_codigo(self, obj):
        if obj.tipo_incidencia == 'PRODUCTO_ERRONEO' and obj.codigo_real:
            return obj.codigo_real
        return obj.pedido_item.codigo if obj.pedido_item else ''

    def get_descripcion(self, obj):
        if obj.tipo_incidencia == 'PRODUCTO_ERRONEO' and obj.descripcion_real:
            return obj.descripcion_real
        return obj.pedido_item.descripcion if obj.pedido_item else ''


class DespachoSerializer(serializers.ModelSerializer):
    pedido_info = serializers.SerializerMethodField()
    despachador = UserMinSerializer(read_only=True)
    picker = UserMinSerializer(read_only=True)
    receptor = UserMinSerializer(read_only=True)
    items = DespachoItemMinSerializer(many=True, read_only=True)

    class Meta:
        model = Despacho
        fields = [
            'numero_despacho', 'pedido_info', 'despachador', 'picker', 'receptor',
            'estado', 'observaciones', 'fecha_despacho', 'fecha_recepcion',
            'items',
        ]

    def get_pedido_info(self, obj):
        p = obj.pedido
        return {
            'numero_pedido': p.numero_pedido,
            'deposito': p.deposito,
            'deposito_codigo': p.deposito_codigo,
            'categoria_nombre': p.categoria_nombre,
            'condicion': p.condicion,
        }


class DespachoItemCreateSerializer(serializers.Serializer):
    pedido_item_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    cantidad_despachada = serializers.IntegerField(min_value=1)
    observacion = serializers.CharField(max_length=255, required=False, default='')
    tipo_incidencia = serializers.ChoiceField(
        choices=['', 'PRODUCTO_ERRONEO', 'SKU_NO_CONTEMPLADO', 'CANTIDAD_MENOR', 'CANTIDAD_MAYOR'],
        required=False,
        default='',
    )
    codigo_real = serializers.CharField(max_length=50, required=False, default='')
    descripcion_real = serializers.CharField(max_length=255, required=False, default='')


class DespachoCreateSerializer(serializers.Serializer):
    pedido_id = serializers.IntegerField()
    observaciones = serializers.CharField(required=False, default='')
    items = DespachoItemCreateSerializer(many=True)
