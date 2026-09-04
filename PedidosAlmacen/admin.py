from typing import Any, Iterable

from django.contrib import admin, messages
from django.shortcuts import redirect
from django.urls import path
from .models import Pedido, PedidoItem, DepositoPermitido, ConfiguracionPedidos, Condicion
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
    filter_horizontal = ('receptores',)
    change_list_template = 'admin/depositopermitido_changelist.html'

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """Limita el selector de receptores a usuarios activos."""
        if db_field.name == 'receptores':
            from users.models import User
            kwargs['queryset'] = User.objects.filter(status=True).order_by('username')
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def get_urls(self):
        """Añade la URL del botón 'Sincronizar depósitos desde a2'."""
        urls = super().get_urls()
        custom = [
            path(
                'sincronizar/',
                self.admin_site.admin_view(self.sincronizar_view),
                name='pedidosalmacen_depositopermitido_sincronizar',
            ),
        ]
        return custom + urls

    def sincronizar_view(self, request):
        """Sincroniza los depósitos desde DBISAM y vuelve al listado.

        No depende de una selección de filas, por eso es una vista propia
        (un botón siempre visible) y no una acción de changelist.
        """
        try:
            rows = PedidosDBISAM().obtener_depositos()
        except Exception as e:
            self.message_user(request, f'Error al conectar con a2: {e}', level=messages.ERROR)
            return redirect('..')
        creados, actualizados = sincronizar_depositos_permitidos(rows)
        self.message_user(
            request,
            f'Sincronización completa: {creados} creados, {actualizados} actualizados.',
        )
        return redirect('..')


@admin.register(Condicion)
class CondicionAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'color_badge', 'icono', 'activo', 'orden')
    list_editable = ('activo', 'orden')
    list_filter = ('activo', 'color_badge')
    search_fields = ('codigo', 'nombre')
    ordering = ('orden', 'codigo')


@admin.register(ConfiguracionPedidos)
class ConfiguracionPedidosAdmin(admin.ModelAdmin):
    """Singleton: una sola fila, sin altas adicionales ni borrado."""
    list_display = ('deposito_transito', 'fecha_actualizacion')

    def has_add_permission(self, request):
        return not ConfiguracionPedidos.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
