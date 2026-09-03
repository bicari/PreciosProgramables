from django.contrib import admin

from .models import Cuerpo, Galpon, MovimientoUbicacion, Nivel, ProductoUbicacion, Rack, Ubicacion


@admin.register(Galpon)
class GalponAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'nombre', 'grid_filas', 'grid_columnas', 'activo', 'fecha_creacion']
    list_filter = ['activo']
    search_fields = ['codigo', 'nombre']
    readonly_fields = ['fecha_creacion', 'fecha_modificacion', 'creado_por']


@admin.register(Rack)
class RackAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'galpon', 'descripcion', 'max_niveles', 'total_cuerpos', 'activo', 'fecha_creacion']
    list_filter = ['activo', 'galpon']
    search_fields = ['codigo', 'descripcion']
    readonly_fields = ['fecha_creacion', 'fecha_modificacion', 'creado_por']


@admin.register(Cuerpo)
class CuerpoAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'rack', 'activo', 'fecha_creacion']
    list_filter = ['activo', 'rack']
    search_fields = ['codigo', 'rack__codigo']
    readonly_fields = ['fecha_creacion', 'fecha_modificacion', 'creado_por']


@admin.register(Ubicacion)
class UbicacionAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'cuerpo', 'activo', 'fecha_creacion']
    list_filter = ['activo', 'cuerpo__rack']
    search_fields = ['codigo', 'cuerpo__codigo', 'cuerpo__rack__codigo']
    readonly_fields = ['fecha_creacion', 'fecha_modificacion', 'creado_por']


@admin.register(Nivel)
class NivelAdmin(admin.ModelAdmin):
    list_display = ['codigo_completo', 'tipo', 'fusionado_en', 'activo', 'fecha_creacion']
    list_filter = ['tipo', 'activo', 'ubicacion__cuerpo__rack']
    search_fields = ['ubicacion__cuerpo__rack__codigo']
    readonly_fields = ['fecha_creacion', 'fecha_modificacion', 'creado_por']


@admin.register(ProductoUbicacion)
class ProductoUbicacionAdmin(admin.ModelAdmin):
    list_display = ['codigo_producto', 'nivel', 'cantidad', 'stock_minimo', 'es_principal', 'fecha_asignacion']
    search_fields = ['codigo_producto']
    list_filter = ['nivel__ubicacion__cuerpo__rack', 'es_principal']
    readonly_fields = ['fecha_asignacion', 'asignado_por']


@admin.register(MovimientoUbicacion)
class MovimientoUbicacionAdmin(admin.ModelAdmin):
    list_display = [
        'tipo', 'codigo_producto', 'cantidad', 'pendiente_revision', 'rack',
        'nivel_origen', 'nivel_destino', 'usuario', 'fecha',
    ]
    list_filter = ['tipo', 'pendiente_revision']
    search_fields = ['codigo_producto']
    date_hierarchy = 'fecha'
    readonly_fields = [
        'tipo', 'galpon', 'rack', 'cuerpo', 'ubicacion', 'nivel',
        'nivel_origen', 'nivel_destino', 'codigo_producto', 'cantidad',
        'pendiente_revision', 'revisado_por', 'fecha_revision', 'pedido_item',
        'activo', 'usuario', 'fecha', 'notas',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
