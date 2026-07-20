from rest_framework import serializers

from .models import MovimientoUbicacion, Nivel, ProductoUbicacion, Rack, Ubicacion


class RackSerializer(serializers.ModelSerializer):
    total_niveles = serializers.IntegerField(source='total_niveles', read_only=True)
    tope_alcanzado = serializers.BooleanField(source='tope_alcanzado', read_only=True)

    class Meta:
        model = Rack
        fields = ['id', 'codigo', 'descripcion', 'max_niveles',
                  'activo', 'total_niveles', 'tope_alcanzado']


class NivelSerializer(serializers.ModelSerializer):
    rack_codigo = serializers.CharField(source='rack.codigo', read_only=True)

    class Meta:
        model = Nivel
        fields = ['id', 'rack', 'rack_codigo', 'codigo', 'tipo', 'descripcion', 'activo']


class UbicacionListSerializer(serializers.ModelSerializer):
    codigo_completo = serializers.CharField(read_only=True)
    rack_codigo = serializers.CharField(source='nivel.rack.codigo', read_only=True)
    nivel_codigo = serializers.CharField(source='nivel.codigo', read_only=True)
    tipo_nivel = serializers.CharField(source='nivel.tipo', read_only=True)
    total_productos = serializers.SerializerMethodField()

    class Meta:
        model = Ubicacion
        fields = ['id', 'codigo', 'codigo_completo', 'rack_codigo', 'nivel_codigo',
                  'tipo_nivel', 'descripcion', 'activo', 'total_productos']

    def get_total_productos(self, obj) -> int:
        return obj.productos.count()


class UbicacionDetailSerializer(UbicacionListSerializer):
    productos = serializers.SerializerMethodField()

    class Meta(UbicacionListSerializer.Meta):
        fields = UbicacionListSerializer.Meta.fields + ['productos']

    def get_productos(self, obj) -> list:
        return list(
            obj.productos.values('id', 'codigo_producto', 'fecha_asignacion')
        )


class ProductoUbicacionesSerializer(serializers.Serializer):
    """Vista plana: para dado un código, todas sus ubicaciones + existencia DBISAM."""
    codigo = serializers.CharField()
    existencia_dbisam = serializers.IntegerField()
    ubicaciones = serializers.ListField(child=serializers.DictField())


class MovimientoSerializer(serializers.ModelSerializer):
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    usuario_nombre = serializers.SerializerMethodField()
    rack_codigo = serializers.CharField(source='rack.codigo', read_only=True, default=None)
    nivel_codigo = serializers.CharField(source='nivel.codigo', read_only=True, default=None)
    ubicacion_origen_str = serializers.CharField(
        source='ubicacion_origen.codigo_completo', read_only=True, default=None,
    )
    ubicacion_destino_str = serializers.CharField(
        source='ubicacion_destino.codigo_completo', read_only=True, default=None,
    )

    class Meta:
        model = MovimientoUbicacion
        fields = [
            'id', 'tipo', 'tipo_display',
            'rack_codigo', 'nivel_codigo',
            'ubicacion_origen_str', 'ubicacion_destino_str',
            'codigo_producto', 'usuario_nombre', 'fecha', 'notas',
        ]

    def get_usuario_nombre(self, obj) -> str:
        return obj.usuario.get_full_name() or obj.usuario.username if obj.usuario else ''
