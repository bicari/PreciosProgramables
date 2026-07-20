"""
Management command para detectar pedidos recibidos en la app cuyo traslado de
recepción (tránsito → destino) no quedó registrado en a2 (SOPERACIONINV), por
lo que las existencias de los productos recibidos no se actualizaron.

Es de solo lectura: no modifica Postgres ni a2.

Valida únicamente el paso de RECEPCIÓN. El paso de despacho (almacén→tránsito)
ya se audita en Postgres mediante Despacho.traslado_a2_registrado, sin
necesitar consultar DBISAM.

La verificación usa el depósito de tránsito actualmente configurado en
ConfiguracionPedidos; pedidos históricos despachados con otro depósito de
tránsito pueden aparecer como falsos positivos.

Uso:
    python manage.py validar_traslados_recepcion
    python manage.py validar_traslados_recepcion --dias 30
    python manage.py validar_traslados_recepcion --pedido 1234
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from PedidosAlmacen.dbisam import PedidosDBISAM
from PedidosAlmacen.models import ConfiguracionPedidos, Pedido


class Command(BaseCommand):
    help = (
        "Detecta pedidos RECIBIDO/PARCIAL cuyo traslado de recepción "
        "(tránsito → destino) no está registrado en a2 (SOPERACIONINV). "
        "Solo lectura: no modifica Postgres ni a2."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dias",
            type=int,
            default=None,
            help="Limita la revisión a pedidos con fecha_recepcion dentro de los últimos N días. Por defecto revisa todo el histórico.",
        )
        parser.add_argument(
            "--pedido",
            type=int,
            default=None,
            help="Revisa un único número de pedido (spot-check). Si se pasa junto con --dias, --dias se ignora.",
        )

    def handle(self, *args, **options) -> None:
        dias = options["dias"]
        pedido_num = options["pedido"]

        candidatos = self._obtener_candidatos(dias, pedido_num)
        if not candidatos:
            self.stdout.write(self.style.WARNING("No hay pedidos candidatos para revisar."))
            return

        numeros = [c[0] for c in candidatos]
        # La verificación asume el depósito de tránsito actualmente configurado;
        # pedidos históricos despachados con otro tránsito pueden dar falso positivo.
        deposito_transito = ConfiguracionPedidos.load().deposito_transito
        try:
            existentes = PedidosDBISAM().traslados_recepcion_existentes(numeros, deposito_transito)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error al consultar a2: {e}"))
            return

        problematicos = [c for c in candidatos if c[0] not in existentes]
        self._mostrar_reporte(candidatos, problematicos)

    def _obtener_candidatos(self, dias: int | None, pedido_num: int | None) -> list[tuple]:
        """Devuelve tuplas (numero_pedido, username, fecha_recepcion, deposito_codigo)."""
        qs = (
            Pedido.objects.filter(despachos__estado__in=["RECIBIDO", "PARCIAL"])
            .exclude(deposito_codigo__isnull=True)
            .distinct()
        )
        if pedido_num is not None:
            qs = qs.filter(numero_pedido=pedido_num)
        elif dias is not None:
            desde = timezone.now() - timedelta(days=dias)
            qs = qs.filter(fecha_recepcion__gte=desde)

        return list(
            qs.values_list(
                "numero_pedido", "solicitante__username", "fecha_recepcion", "deposito_codigo"
            ).order_by("-fecha_recepcion")
        )

    def _mostrar_reporte(self, candidatos: list[tuple], problematicos: list[tuple]) -> None:
        self.stdout.write("")
        self.stdout.write(f"Pedidos revisados: {len(candidatos)}")
        self.stdout.write("")
        if problematicos:
            for numero, username, fecha_recepcion, deposito in problematicos:
                self.stdout.write(
                    self.style.ERROR(
                        f"  #{numero} | {username} | {fecha_recepcion} | depósito destino {deposito}"
                    )
                )
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(problematicos)} de {len(candidatos)} pedidos sin traslado de recepción en a2."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"0 de {len(candidatos)} pedidos sin traslado de recepción en a2."
                )
            )
