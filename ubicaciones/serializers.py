from rest_framework import serializers

from .models import Cuerpo, Galpon, MovimientoUbicacion, Nivel, ProductoUbicacion, Rack, Ubicacion


class GalponSerializer(serializers.ModelSerializer):
    class Meta:
        model = Galpon
        fields = ['id', 'codigo', 'nombre', 'grid_filas', 'grid_columnas', 'activo']


class RackSerializer(serializers.ModelSerializer):
    galpon_codigo = serializers.CharField(source='galpon.codigo', read_only=True)
    total_cuerpos = serializers.IntegerField(read_only=True)

    class Meta:
        model = Rack
        fields = [
            'id', 'galpon', 'galpon_codigo', 'codigo', 'descripcion',
            'grid_fila', 'grid_columna', 'ancho', 'alto', 'max_niveles',
            'total_cuerpos', 'activo',
        ]


class CuerpoSerializer(serializers.ModelSerializer):
    rack_codigo = serializers.CharField(source='rack.codigo', read_only=True)
    total_ubicaciones = serializers.SerializerMethodField()

    class Meta:
        model = Cuerpo
        fields = ['id', 'rack', 'rack_codigo', 'codigo', 'descripcion', 'activo', 'total_ubicaciones']

    def get_total_ubicaciones(self, obj) -> int:
        return obj.ubicaciones.count()


class NivelSerializer(serializers.ModelSerializer):
    codigo_completo = serializers.CharField(read_only=True)
    esta_fusionado = serializers.BooleanField(read_only=True)
    fusionado_en_codigo = serializers.CharField(source='fusionado_en.codigo_completo', read_only=True, default=None)
    total_productos = serializers.SerializerMethodField()

    class Meta:
        model = Nivel
        fields = [
            'id', 'ubicacion', 'numero', 'codigo_completo', 'tipo',
            'esta_fusionado', 'fusionado_en_codigo', 'activo', 'total_productos',
        ]

    def get_total_productos(self, obj) -> int:
        return obj.productos.count()


class ProductoUbicacionSerializer(serializers.ModelSerializer):
    nivel_codigo = serializers.CharField(source='nivel.codigo_completo', read_only=True)
    tipo_nivel = serializers.CharField(source='nivel.tipo', read_only=True)

    class Meta:
        model = ProductoUbicacion
        fields = ['id', 'codigo_producto', 'nivel', 'nivel_codigo', 'tipo_nivel', 'cantidad', 'stock_minimo']


class MovimientoSerializer(serializers.ModelSerializer):
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    usuario_nombre = serializers.SerializerMethodField()
    rack_codigo = serializers.CharField(source='rack.codigo', read_only=True, default=None)
    nivel_origen_str = serializers.CharField(source='nivel_origen.codigo_completo', read_only=True, default=None)
    nivel_destino_str = serializers.CharField(source='nivel_destino.codigo_completo', read_only=True, default=None)

    class Meta:
        model = MovimientoUbicacion
        fields = [
            'id', 'tipo', 'tipo_display', 'rack_codigo',
            'nivel_origen_str', 'nivel_destino_str',
            'codigo_producto', 'usuario_nombre', 'fecha', 'notas',
        ]

    def get_usuario_nombre(self, obj) -> str:
        return obj.usuario.username if obj.usuario else ''
