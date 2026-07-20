"""
Management command para reiniciar la base de datos de PedidosAlmacen desde cero.

Borra todos los pedidos y despachos en el orden correcto (respetando las
restricciones PROTECT), reinicia los contadores AutoField a 1 y elimina
las fotos de incidencias del disco.

Uso:
    python manage.py reset_pedidos              # pide confirmación
    python manage.py reset_pedidos --dry-run    # solo muestra qué se borraría
    python manage.py reset_pedidos --yes        # sin confirmación interactiva
    python manage.py reset_pedidos --keep-counters  # no reinicia numeración
    python manage.py reset_pedidos --keep-files     # no borra fotos de disco
"""

import logging
import os
import shutil

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from PedidosAlmacen.models import Despacho, DespachoItem, Pedido, PedidoItem

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Reinicia la BD de PedidosAlmacen: borra pedidos, ítems, despachos "
        "y sus ítems. Reinicia los contadores AutoField y elimina fotos de "
        "incidencias. NO afecta usuarios ni otras apps."
    )

    # ------------------------------------------------------------------
    # Argumentos
    # ------------------------------------------------------------------
    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Simula el reset: muestra los conteos sin modificar nada.",
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            default=False,
            help="Omite la confirmación interactiva (apto para scripts).",
        )
        parser.add_argument(
            "--keep-counters",
            action="store_true",
            default=False,
            help=(
                "No reinicia los contadores AutoField. Por defecto los "
                "reinicia a 1 mediante TRUNCATE … RESTART IDENTITY."
            ),
        )
        parser.add_argument(
            "--keep-files",
            action="store_true",
            default=False,
            help=(
                "No borra las fotos de incidencias del disco. "
                "Por defecto las elimina para evitar archivos huérfanos."
            ),
        )

    # ------------------------------------------------------------------
    # Punto de entrada principal
    # ------------------------------------------------------------------
    def handle(self, *args, **options) -> None:
        dry_run: bool = options["dry_run"]
        yes: bool = options["yes"]
        keep_counters: bool = options["keep_counters"]
        keep_files: bool = options["keep_files"]

        # --- Conteo previo ---
        conteos = self._obtener_conteos()
        fotos = self._obtener_rutas_fotos()

        self._mostrar_resumen_previo(conteos, fotos, dry_run)

        if dry_run:
            self.stdout.write(self.style.WARNING("Modo --dry-run: no se realizó ningún cambio."))
            return

        # --- Confirmación ---
        if not yes and not self._confirmar():
            self.stdout.write(self.style.WARNING("Reset cancelado por el usuario."))
            return

        # --- Borrado de fotos ---
        fotos_borradas = 0
        fotos_errores = 0
        if not keep_files:
            fotos_borradas, fotos_errores = self._borrar_fotos(fotos)

        # --- Borrado de registros ---
        if keep_counters:
            registros_borrados = self._borrar_con_orm(conteos)
        else:
            registros_borrados = self._borrar_con_truncate()

        # --- Limpiar subcarpetas vacías ---
        if not keep_files:
            self._limpiar_directorio_incidencias()

        # --- Resumen final ---
        self._mostrar_resumen_final(registros_borrados, fotos_borradas, fotos_errores, keep_counters)

        logger.info(
            "reset_pedidos ejecutado: %d registros borrados, %d fotos borradas, "
            "%d errores en fotos. keep_counters=%s keep_files=%s",
            registros_borrados,
            fotos_borradas,
            fotos_errores,
            keep_counters,
            keep_files,
        )

    # ------------------------------------------------------------------
    # Conteos previos
    # ------------------------------------------------------------------
    def _obtener_conteos(self) -> dict[str, int]:
        """Devuelve el número de filas actuales en cada tabla."""
        return {
            "pedidos": Pedido.objects.count(),
            "pedido_items": PedidoItem.objects.count(),
            "despachos": Despacho.objects.count(),
            "despacho_items": DespachoItem.objects.count(),
        }

    def _obtener_rutas_fotos(self) -> list[str]:
        """Devuelve las rutas relativas (campo foto_incidencia) con archivo asignado."""
        return list(
            DespachoItem.objects.exclude(foto_incidencia="")
            .exclude(foto_incidencia__isnull=True)
            .values_list("foto_incidencia", flat=True)
        )

    # ------------------------------------------------------------------
    # Presentación
    # ------------------------------------------------------------------
    def _mostrar_resumen_previo(
        self, conteos: dict[str, int], fotos: list[str], dry_run: bool
    ) -> None:
        prefijo = "[DRY-RUN] " if dry_run else ""
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("=" * 50))
        self.stdout.write(self.style.WARNING(f"  {prefijo}RESET PEDIDOS ALMACEN"))
        self.stdout.write(self.style.WARNING("=" * 50))
        self.stdout.write(f"  Pedidos        : {conteos['pedidos']}")
        self.stdout.write(f"  Ítems pedido   : {conteos['pedido_items']}")
        self.stdout.write(f"  Despachos      : {conteos['despachos']}")
        self.stdout.write(f"  Ítems despacho : {conteos['despacho_items']}")
        self.stdout.write(f"  Fotos en BD    : {len(fotos)}")
        self.stdout.write(self.style.WARNING("=" * 50))
        self.stdout.write("")

    def _mostrar_resumen_final(
        self,
        registros: int,
        fotos_borradas: int,
        fotos_errores: int,
        keep_counters: bool,
    ) -> None:
        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(f"✓ {registros} registros eliminados de la BD.")
        )
        self.stdout.write(
            self.style.SUCCESS(f"✓ {fotos_borradas} fotos eliminadas del disco.")
        )
        if fotos_errores:
            self.stdout.write(
                self.style.WARNING(f"⚠ {fotos_errores} fotos con error al borrar (ver logs).")
            )
        if not keep_counters:
            self.stdout.write(
                self.style.SUCCESS(
                    "✓ Contadores reiniciados a 1 (próximo pedido será #1)."
                )
            )
        self.stdout.write("")

    # ------------------------------------------------------------------
    # Confirmación interactiva
    # ------------------------------------------------------------------
    def _confirmar(self) -> bool:
        """Solicita confirmación al usuario. Devuelve True si confirma."""
        self.stdout.write(
            self.style.ERROR(
                "ADVERTENCIA: Esta operación borrará TODOS los pedidos y "
                "despachos de forma IRREVERSIBLE."
            )
        )
        respuesta = input("Escribe 'SI' en mayúsculas para continuar: ").strip()
        return respuesta == "SI"

    # ------------------------------------------------------------------
    # Borrado mediante TRUNCATE (reinicia contadores)
    # ------------------------------------------------------------------
    def _borrar_con_truncate(self) -> int:
        """
        Vacía las 4 tablas con TRUNCATE … RESTART IDENTITY CASCADE.

        Returns:
            Total de filas eliminadas (suma de las 4 tablas).
        """
        tablas = [
            DespachoItem._meta.db_table,
            Despacho._meta.db_table,
            PedidoItem._meta.db_table,
            Pedido._meta.db_table,
        ]
        lista_tablas = ", ".join(f'"{t}"' for t in tablas)

        # Contar antes de truncar para el resumen
        total = sum(
            [
                DespachoItem.objects.count(),
                Despacho.objects.count(),
                PedidoItem.objects.count(),
                Pedido.objects.count(),
            ]
        )

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"TRUNCATE TABLE {lista_tablas} RESTART IDENTITY CASCADE"
                )

        return total

    # ------------------------------------------------------------------
    # Borrado mediante ORM (conserva contadores)
    # ------------------------------------------------------------------
    def _borrar_con_orm(self, conteos: dict[str, int]) -> int:
        """
        Borra registros respetando el orden requerido por los PROTECT:
        1. Despacho (arrastra DespachoItem por CASCADE)
        2. PedidoItem
        3. Pedido

        Returns:
            Total de filas eliminadas.
        """
        with transaction.atomic():
            Despacho.objects.all().delete()   # CASCADE → borra DespachoItem también
            PedidoItem.objects.all().delete()
            Pedido.objects.all().delete()

        return sum(conteos.values())

    # ------------------------------------------------------------------
    # Borrado de fotos físicas
    # ------------------------------------------------------------------
    def _borrar_fotos(self, rutas: list[str]) -> tuple[int, int]:
        """
        Elimina los archivos físicos de fotos de incidencias usando el
        storage configurado en Django.

        Args:
            rutas: Lista de rutas relativas almacenadas en el campo foto_incidencia.

        Returns:
            Tupla (borradas, errores).
        """
        borradas = 0
        errores = 0
        for ruta in rutas:
            try:
                if default_storage.exists(ruta):
                    default_storage.delete(ruta)
                    borradas += 1
                    logger.debug("Foto eliminada: %s", ruta)
                else:
                    logger.warning("Foto no encontrada en storage: %s", ruta)
            except Exception as exc:
                errores += 1
                logger.warning("Error al borrar foto '%s': %s", ruta, exc)
        return borradas, errores

    # ------------------------------------------------------------------
    # Limpieza de subcarpetas vacías
    # ------------------------------------------------------------------
    def _limpiar_directorio_incidencias(self) -> None:
        """
        Elimina subdirectorios vacíos bajo media/incidencias/ para no
        dejar estructura de carpetas huérfana tras borrar las fotos.
        """
        from django.conf import settings

        directorio_incidencias = os.path.join(settings.MEDIA_ROOT, "incidencias")
        if not os.path.isdir(directorio_incidencias):
            return

        try:
            for root, dirs, files in os.walk(directorio_incidencias, topdown=False):
                if root == directorio_incidencias:
                    continue  # No borrar la carpeta raíz de incidencias
                if not os.listdir(root):
                    os.rmdir(root)
                    logger.debug("Directorio vacío eliminado: %s", root)
        except Exception as exc:
            logger.warning("Error al limpiar directorio de incidencias: %s", exc)
