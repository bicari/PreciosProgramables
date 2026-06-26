from typing import Any, Iterable

from django.contrib import admin
from .models import Pedido, PedidoItem, DepositoPermitido
from .dbisam import PedidosDBISAM


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


def sincronizar_depositos_permitidos(rows: Iterable[Any]) -> tuple[int, int]:
    """Upsert de depósitos desde filas de SDEPOSITOS, preservando `activo`.

    Args:
        rows: iterable de filas con atributos FDP_CODIGO y FDP_DESCRIPCION.

    Returns:
        Tupla (creados, actualizados).
    """
    creados = 0
    actualizados = 0
    for row in rows:
        _, created = DepositoPermitido.objects.update_or_create(
            codigo=int(row.FDP_CODIGO),
            defaults={'nombre': (row.FDP_DESCRIPCION or '').strip()},
        )
        if created:
            creados += 1
        else:
            actualizados += 1
    return creados, actualizados


@admin.register(DepositoPermitido)
class DepositoPermitidoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'activo', 'fecha_sync')
    list_editable = ('activo',)
    list_filter = ('activo',)
    search_fields = ('codigo', 'nombre')
    ordering = ('nombre',)

    actions = ['accion_sincronizar']

    @admin.action(description='Sincronizar depósitos desde a2')
    def accion_sincronizar(self, request, queryset):
        try:
            rows = PedidosDBISAM().obtener_depositos()
        except Exception as e:
            self.message_user(request, f'Error al conectar con a2: {e}', level='error')
            return
        creados, actualizados = sincronizar_depositos_permitidos(rows)
        self.message_user(
            request,
            f'Sincronización completa: {creados} creados, {actualizados} actualizados.',
        )
