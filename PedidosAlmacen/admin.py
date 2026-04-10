from django.contrib import admin
from .models import Pedido, PedidoItem


class PedidoItemInline(admin.TabularInline):
    model = PedidoItem
    extra = 0
    readonly_fields = ('codigo', 'descripcion', 'cantidad_solicitada', 'cantidad_despachada', 'cantidad_recibida', 'estado')


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('numero_pedido', 'solicitante', 'estado', 'fecha_creacion', 'fecha_despacho', 'fecha_recepcion')
    list_filter = ('estado', 'fecha_creacion')
    search_fields = ('numero_pedido', 'solicitante__username')
    list_per_page = 20
    ordering = ('-fecha_creacion',)
    inlines = [PedidoItemInline]


@admin.register(PedidoItem)
class PedidoItemAdmin(admin.ModelAdmin):
    list_display = ('pedido', 'codigo', 'descripcion', 'cantidad_solicitada', 'cantidad_despachada', 'cantidad_recibida', 'estado')
    list_filter = ('estado',)
    search_fields = ('codigo', 'descripcion')
    list_per_page = 30
