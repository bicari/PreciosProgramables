"""
Management command para detectar despachos recibidos en la app cuyo traslado
de recepción (tránsito → destino) no quedó registrado en a2 (SOPERACIONINV),
por lo que las existencias de los productos recibidos no se actualizaron.

Es de solo lectura: no modifica Postgres ni a2.

Valida únicamente el paso de RECEPCIÓN. El paso de despacho (almacén→tránsito)
ya se audita en Postgres mediante Despacho.traslado_a2_registrado, sin
necesitar consultar DBISAM.

Revisa por DESPACHO, no por pedido: un mismo pedido puede tener varios
despachos, cada uno con su propio traslado de recepción en a2 (identificado
por FTI_DOCUMENTOORIGEN = numero_despacho). Verificar solo a nivel de pedido
ocultaría un despacho huérfano cuando otro despacho del mismo pedido sí
registró el suyo.

La verificación usa el depósito de tránsito actualmente configurado en
ConfiguracionPedidos; despachos históricos recibidos con otro depósito de
tránsito pueden aparecer como falsos positivos. Lo mismo aplica a despachos
recibidos antes de que se agregara FTI_DOCUMENTOORIGEN a los traslados.

Uso:
    python manage.py validar_traslados_recepcion
    python manage.py validar_traslados_recepcion --dias 30
    python manage.py validar_traslados_recepcion --pedido 1234
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from PedidosAlmacen.dbisam import PedidosDBISAM
from PedidosAlmacen.models import ConfiguracionPedidos, Despacho


class Command(BaseCommand):
    help = (
        "Detecta despachos RECIBIDO/PARCIAL cuyo traslado de recepción "
        "(tránsito → destino) no está registrado en a2 (SOPERACIONINV). "
        "Solo lectura: no modifica Postgres ni a2."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dias",
            type=int,
            default=None,
            help="Limita la revisión a despachos con fecha_recepcion dentro de los últimos N días. Por defecto revisa todo el histórico.",
        )
        parser.add_argument(
            "--pedido",
            type=int,
            default=None,
            help="Revisa únicamente los despachos de un número de pedido (spot-check). Si se pasa junto con --dias, --dias se ignora.",
        )

    def handle(self, *args, **options) -> None:
        dias = options["dias"]
        pedido_num = options["pedido"]

        candidatos = self._obtener_candidatos(dias, pedido_num)
        if not candidatos:
            self.stdout.write(self.style.WARNING("No hay despachos candidatos para revisar."))
            return

        numeros_despacho = [c[0] for c in candidatos]
        # La verificación asume el depósito de tránsito actualmente configurado;
        # despachos históricos recibidos con otro tránsito pueden dar falso positivo.
        deposito_transito = ConfiguracionPedidos.load().deposito_transito
        try:
            existentes = PedidosDBISAM().traslados_recepcion_existentes(numeros_despacho, deposito_transito)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error al consultar a2: {e}"))
            return

        problematicos = [c for c in candidatos if c[0] not in existentes]
        self._mostrar_reporte(candidatos, problematicos)

    def _obtener_candidatos(self, dias: int | None, pedido_num: int | None) -> list[tuple]:
        """Devuelve tuplas (numero_despacho, numero_pedido, username, fecha_recepcion, deposito_codigo)."""
        qs = (
            Despacho.objects.filter(estado__in=["RECIBIDO", "PARCIAL"])
            .exclude(pedido__deposito_codigo__isnull=True)
        )
        if pedido_num is not None:
            qs = qs.filter(pedido__numero_pedido=pedido_num)
        elif dias is not None:
            desde = timezone.now() - timedelta(days=dias)
            qs = qs.filter(fecha_recepcion__gte=desde)

        return list(
            qs.values_list(
                "numero_despacho", "pedido__numero_pedido", "receptor__username",
                "fecha_recepcion", "pedido__deposito_codigo",
            ).order_by("-fecha_recepcion")
        )

    def _mostrar_reporte(self, candidatos: list[tuple], problematicos: list[tuple]) -> None:
        self.stdout.write("")
        self.stdout.write(f"Despachos revisados: {len(candidatos)}")
        self.stdout.write("")
        if problematicos:
            for numero_despacho, numero_pedido, username, fecha_recepcion, deposito in problematicos:
                self.stdout.write(
                    self.style.ERROR(
                        f"  Despacho #{numero_despacho} (Pedido #{numero_pedido}) | {username} | "
                        f"{fecha_recepcion} | depósito destino {deposito}"
                    )
                )
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(problematicos)} de {len(candidatos)} despachos sin traslado de recepción en a2."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"0 de {len(candidatos)} despachos sin traslado de recepción en a2."
                )
            )
