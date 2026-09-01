"""
Management command para cerrar en bloque pedidos PARCIAL con back order en
un rango de fechas.

Aplica la misma regla de elegibilidad que el cierre manual (vista
`cerrar_pedido` en views.py): el pedido debe estar en estado PARCIAL y no
tener despachos pendientes (ENVIADO/PENDIENTE_APROBACION/PREPARANDO).
Adicionalmente, el pedido debe tener al menos un item con
cantidad_back_order > 0.

Deja cantidad_back_order = 0 en los items PARCIAL/BACK_ORDER, los marca
CERRADO y marca el pedido como CERRADO, igual que el cierre manual.

Uso:
    python manage.py cerrar_pedidos_backorder --desde 2026-07-01 --hasta 2026-07-31 --motivo "..."
    python manage.py cerrar_pedidos_backorder --desde 2026-07-01 --hasta 2026-07-31 --motivo "..." --usuario admin
    python manage.py cerrar_pedidos_backorder --desde 2026-07-01 --hasta 2026-07-31 --motivo "..." --dry-run
"""

import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from PedidosAlmacen.models import Pedido
from PedidosAlmacen.views import _puede_cerrar_pedido

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Cierra en bloque pedidos PARCIAL con back order (cantidad_back_order > 0) "
        "creados dentro de un rango de fechas. Misma regla de elegibilidad que el "
        "cierre manual de un pedido individual."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--desde", required=True, help="Fecha inicial (YYYY-MM-DD), sobre fecha_creacion.")
        parser.add_argument("--hasta", required=True, help="Fecha final (YYYY-MM-DD), sobre fecha_creacion.")
        parser.add_argument("--motivo", required=True, help="Motivo de cierre, se registra en cada pedido.")
        parser.add_argument(
            "--usuario", default=None,
            help="Username a registrar como cerrado_por. Si se omite, queda sin asignar.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Solo lista los pedidos que se cerrarían, sin modificar nada.",
        )

    def handle(self, *args, **options) -> None:
        desde = parse_date(options["desde"])
        hasta = parse_date(options["hasta"])
        if desde is None or hasta is None:
            raise CommandError("--desde y --hasta deben tener formato YYYY-MM-DD")
        if desde > hasta:
            raise CommandError("--desde no puede ser posterior a --hasta")

        motivo = options["motivo"].strip()
        if not motivo:
            raise CommandError("--motivo no puede estar vacío")

        usuario = None
        if options["usuario"]:
            User = get_user_model()
            try:
                usuario = User.objects.get(username=options["usuario"])
            except User.DoesNotExist:
                raise CommandError(f"Usuario '{options['usuario']}' no existe")

        candidatos = list(
            Pedido.objects.filter(
                estado="PARCIAL",
                fecha_creacion__date__gte=desde,
                fecha_creacion__date__lte=hasta,
                items__cantidad_back_order__gt=0,
            )
            .exclude(despachos__estado__in=("ENVIADO", "PENDIENTE_APROBACION", "PREPARANDO"))
            .distinct()
            .order_by("numero_pedido")
            .values_list("numero_pedido", flat=True)
        )

        if not candidatos:
            self.stdout.write(self.style.WARNING("No hay pedidos candidatos para cerrar en ese rango."))
            return

        if options["dry_run"]:
            self.stdout.write(f"{len(candidatos)} pedido(s) se cerrarían (dry-run, nada modificado):")
            for numero in candidatos:
                self.stdout.write(f"  #{numero}")
            return

        cerrados, omitidos = self._cerrar_pedidos(candidatos, usuario, motivo)
        self._mostrar_reporte(cerrados, omitidos)

    def _cerrar_pedidos(self, numeros: list[int], usuario, motivo: str) -> tuple[list[int], list[int]]:
        cerrados = []
        omitidos = []
        for numero in numeros:
            with transaction.atomic():
                pedido = Pedido.objects.select_for_update().get(numero_pedido=numero)
                if not _puede_cerrar_pedido(pedido) or not pedido.items.filter(cantidad_back_order__gt=0).exists():
                    omitidos.append(numero)
                    continue
                pedido.items.filter(estado__in=("PARCIAL", "BACK_ORDER")).update(
                    cantidad_back_order=0, estado="CERRADO",
                )
                pedido.estado = "CERRADO"
                pedido.cerrado_por = usuario
                pedido.fecha_cierre = timezone.now()
                pedido.motivo_cierre = motivo
                pedido.save()
                cerrados.append(numero)
                logger.info(
                    "Pedido #%s cerrado en bloque por %s. Motivo: %s",
                    numero, usuario.username if usuario else "(sin usuario)", motivo,
                )
        return cerrados, omitidos

    def _mostrar_reporte(self, cerrados: list[int], omitidos: list[int]) -> None:
        self.stdout.write("")
        if cerrados:
            self.stdout.write(self.style.SUCCESS(f"{len(cerrados)} pedido(s) cerrados:"))
            for numero in cerrados:
                self.stdout.write(f"  #{numero}")
        if omitidos:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(omitidos)} pedido(s) omitidos (dejaron de ser elegibles entre el conteo y el cierre):"
                )
            )
            for numero in omitidos:
                self.stdout.write(f"  #{numero}")
