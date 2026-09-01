"""
Management command para corregir PedidoItem.categoria='' heredando la
categoría del Pedido al que pertenecen.

Causa: crear_pedido (views.py) usaba `item.get('categoria', categoria_codigo)`
para armar cada PedidoItem. Ese patrón solo aplica el valor por defecto
cuando la clave 'categoria' no existe en el dict — pero el formulario
siempre la manda (aunque venga vacía), así que el fallback nunca se
disparaba y el item quedaba con categoria=''. Ya corregido en crear_pedido
(ahora usa `item.get('categoria') or categoria_codigo`, igual que Pedido).
Este comando repara los registros ya creados con el bug.

Solo se puede recuperar cuando el Pedido sí tiene categoria (siempre es
el caso, porque Pedido.categoria nunca tuvo este bug). Los items cuyo
propio pedido también tiene categoria='' no son recuperables y se
reportan aparte.

Uso:
    python manage.py backfill_categoria_pedidoitem --dry-run
    python manage.py backfill_categoria_pedidoitem
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from PedidosAlmacen.models import PedidoItem


class Command(BaseCommand):
    help = (
        "Corrige PedidoItem.categoria='' heredando pedido.categoria/categoria_nombre "
        "cuando el pedido sí los tiene."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Solo muestra cuántos items se corregirían, sin modificar nada.",
        )

    def handle(self, *args, **options) -> None:
        dry_run = options["dry_run"]

        items_vacios = PedidoItem.objects.filter(categoria='').select_related('pedido')
        recuperables = []
        no_recuperables = 0
        for item in items_vacios:
            if item.pedido.categoria:
                recuperables.append(item)
            else:
                no_recuperables += 1

        if dry_run:
            self.stdout.write(f"(dry-run) {len(recuperables)} item(s) se corregirían.")
            if no_recuperables:
                self.stdout.write(
                    self.style.WARNING(
                        f"(dry-run) {no_recuperables} item(s) no son recuperables "
                        "(su pedido tampoco tiene categoria)."
                    )
                )
            return

        with transaction.atomic():
            for item in recuperables:
                item.categoria = item.pedido.categoria
                item.categoria_nombre = item.pedido.categoria_nombre
                item.save(update_fields=['categoria', 'categoria_nombre'])

        self.stdout.write(self.style.SUCCESS(f"{len(recuperables)} item(s) corregidos."))
        if no_recuperables:
            self.stdout.write(
                self.style.WARNING(
                    f"{no_recuperables} item(s) no son recuperables "
                    "(su pedido tampoco tiene categoria)."
                )
            )
