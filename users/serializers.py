from rest_framework import serializers
from .models import User

GROUP_SUPERVISOR = 'Pedidos Supervisor'
GROUP_ALMACEN = 'Pedidos Almacen'
GROUP_TIENDA = 'Pedidos Tienda'
GROUP_PICKER = 'Pedidos Picker'

def get_rol(user):
    if user.is_superuser:
        return 'admin'
    if user.groups.filter(name=GROUP_SUPERVISOR).exists():
        return 'supervisor'
    if user.groups.filter(name=GROUP_ALMACEN).exists():
        return 'almacen'
    if user.groups.filter(name=GROUP_PICKER).exists():
        return 'picker'
    if user.groups.filter(name=GROUP_TIENDA).exists():
        return 'operario'
    # 'Pedidos Receptor' cae en 'operario' a propósito: no opera por la API móvil.
    return 'operario'


class UserSerializer(serializers.ModelSerializer):
    rol = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'rol', 'status']

    def get_rol(self, obj):
        return get_rol(obj)


class UserMinSerializer(serializers.ModelSerializer):
    rol = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'rol']

    def get_rol(self, obj):
        return get_rol(obj)
