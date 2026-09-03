"""
Management command que reconcilia la existencia por ubicación (Postgres)
contra el total real en a2 (SINVDEP, depósito almacén).

Escribe en Postgres (a diferencia de validar_traslados_recepcion, que es
de solo lectura): cuando a2 queda por debajo de lo asignado por ubicación,
ajusta la ubicación que se puede resolver sin ambigüedad (una sola
asignación, o la marcada es_principal si hay varias) y registra el
faltante como incidencia pendiente_revision. Si hay varias ubicaciones y
ninguna es principal, no ajusta nada — solo deja la incidencia para que
un supervisor la resuelva a mano.

Diseñado para ejecutarse periódicamente vía el Task Scheduler de Windows,
igual que validar_traslados_recepcion.

Uso:
    python manage.py reconciliar_existencias
"""

from django.core.management.base import BaseCommand

from PedidosAlmacen.dbisam import DEPOSITO_ALMACEN, PedidosDBISAM
from ubicaciones.models import ProductoUbicacion
from ubicaciones.services import UbicacionesService


class Command(BaseCommand):
    help = (
        "Reconcilia la existencia por ubicación contra el total real en a2. "
        "Ajusta automáticamente cuando puede resolver sin ambigüedad la "
        "ubicación afectada; si no, solo registra la incidencia."
    )

    def handle(self, *args, **options) -> None:
        codigos = list(
            ProductoUbicacion.objects.values_list('codigo_producto', flat=True).distinct()
        )
        if not codigos:
            self.stdout.write(self.style.WARNING('No hay productos con ubicación asignada.'))
            return

        TAMANO_LOTE = 200
        existencias = {}
        try:
            dbisam = PedidosDBISAM()
            for i in range(0, len(codigos), TAMANO_LOTE):
                lote = codigos[i:i + TAMANO_LOTE]
                existencias.update(dbisam.consultar_stock_multiple(lote, deposito=DEPOSITO_ALMACEN))
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Error al consultar a2: {e}'))
            return

        ajustados, sin_resolver = 0, 0
        for codigo in codigos:
            resultado = UbicacionesService.ajustar_por_reconciliacion_a2(
                codigo, existencias.get(codigo, 0),
            )
            if resultado['faltante'] <= 0:
                continue
            if resultado['ajustado']:
                ajustados += 1
                self.stdout.write(self.style.WARNING(
                    f"{codigo}: faltante {resultado['faltante']} — ajustado en nivel {resultado['nivel_id']}"
                ))
            else:
                sin_resolver += 1
                self.stdout.write(self.style.ERROR(
                    f"{codigo}: faltante {resultado['faltante']} — ambigüedad, requiere revisión manual"
                ))

        self.stdout.write('')
        self.stdout.write(f'Productos revisados: {len(codigos)}')
        self.stdout.write(f'Ajustados automáticamente: {ajustados}')
        self.stdout.write(f'Con incidencia sin resolver: {sin_resolver}')
