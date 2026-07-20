from django.contrib import admin

from .models import MovimientoUbicacion, Nivel, ProductoUbicacion, Rack, Ubicacion


@admin.register(Rack)
class RackAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'descripcion', 'max_niveles', 'total_niveles', 'activo', 'fecha_creacion']
    list_filter = ['activo']
    search_fields = ['codigo', 'descripcion']
    readonly_fields = ['fecha_creacion', 'fecha_modificacion', 'creado_por']


@admin.register(Nivel)
class NivelAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'rack', 'tipo', 'activo', 'fecha_creacion']
    list_filter = ['tipo', 'activo', 'rack']
    search_fields = ['codigo', 'rack__codigo']
    readonly_fields = ['fecha_creacion', 'fecha_modificacion', 'creado_por']


@admin.register(Ubicacion)
class UbicacionAdmin(admin.ModelAdmin):
    list_display = ['codigo_completo', 'activo', 'fecha_creacion']
    list_filter = ['activo', 'nivel__rack']
    search_fields = ['codigo', 'nivel__codigo', 'nivel__rack__codigo']
    readonly_fields = ['fecha_creacion', 'fecha_modificacion', 'creado_por']


@admin.register(ProductoUbicacion)
class ProductoUbicacionAdmin(admin.ModelAdmin):
    list_display = ['codigo_producto', 'ubicacion', 'fecha_asignacion']
    search_fields = ['codigo_producto']
    list_filter = ['ubicacion__nivel__rack']
    readonly_fields = ['fecha_asignacion', 'asignado_por']


@admin.register(MovimientoUbicacion)
class MovimientoUbicacionAdmin(admin.ModelAdmin):
    list_display = ['tipo', 'codigo_producto', 'rack', 'nivel',
                    'ubicacion_origen', 'ubicacion_destino', 'usuario', 'fecha']
    list_filter = ['tipo']
    search_fields = ['codigo_producto']
    date_hierarchy = 'fecha'
    readonly_fields = [
        'tipo', 'rack', 'nivel', 'ubicacion_origen', 'ubicacion_destino',
        'codigo_producto', 'usuario', 'fecha', 'notas',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
