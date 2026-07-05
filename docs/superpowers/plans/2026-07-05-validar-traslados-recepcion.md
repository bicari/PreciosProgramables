# Validar Traslados de Recepción en a2 — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dar al operador un `management command` de solo lectura que detecte pedidos marcados `RECIBIDO`/`PARCIAL` en la app cuyo traslado de recepción (tránsito→destino) nunca quedó registrado en a2, dejando las existencias sin actualizar.

**Architecture:** Un nuevo método `traslados_recepcion_existentes` en `PedidosAlmacen/dbisam.py` consulta `SOPERACIONINV` por lotes para saber qué documentos (números de pedido) sí tienen el traslado tránsito(10)→destino registrado. Un nuevo `management command` obtiene de Postgres los pedidos candidatos (con algún despacho `RECIBIDO`/`PARCIAL` y `deposito_codigo` no nulo), cruza contra ese método, e imprime en consola los pedidos ausentes.

**Tech Stack:** Django 5.2, `pyodbc`/DBISAM (SQL92, sin CTE/EXISTS/derived tables), PostgreSQL (prod) / SQLite (tests).

## Global Constraints

- **Solo lectura:** no modifica Postgres ni a2; es exclusivamente diagnóstico.
- **Alcance:** valida únicamente el paso de recepción (tránsito→destino). El paso de despacho (almacén→tránsito) ya se audita con `Despacho.traslado_a2_registrado` sin tocar DBISAM.
- **Precisión de existencia simple:** por pedido candidato, valida si existe AL MENOS UN traslado con ese documento en `SOPERACIONINV` — no se compara cantidad de despachos recibidos contra cantidad de traslados (a2 no distingue despacho por despacho dentro de un mismo pedido).
- **SQL DBISAM:** sin CTE, sin `EXISTS`, sin subqueries en `FROM` (derived tables) — solo `WHERE ... IN (...)`, `GROUP BY`/`DISTINCT`, consistente con `CLAUDE.md`.
- **Formato de documento:** `FTI_DOCUMENTO` es el número de pedido paddeado a 8 dígitos con ceros a la izquierda (mismo formato que `insertar_traslado_recepcion`/`existe_traslado_despacho` en `dbisam.py`).
- **Constante existente:** `DEPOSITO_TRANSITO = 10` ya está definida en `PedidosAlmacen/dbisam.py:9`.
- **Estilo:** PEP 8, type hints, docstrings estilo Google, seguir patrones de `reset_pedidos.py` (management command) y `consultar_stock_multiple`/`existe_traslado_despacho` (dbisam.py).
- **Comando de tests:** `python manage.py test PedidosAlmacen --settings=Programarprecios.test_settings -v 2`

---

### Task 1: Método `traslados_recepcion_existentes` en `dbisam.py`

**Files:**
- Modify: `PedidosAlmacen/dbisam.py` (agregar método nuevo, después de `existe_traslado_despacho`, línea ~348)
- Test: `PedidosAlmacen/tests.py` (agregar clase nueva al final)

**Interfaces:**
- Consumes: `self.connect()` (ya existente en `PedidosDBISAM`), constante `DEPOSITO_TRANSITO = 10` (`PedidosAlmacen/dbisam.py:9`).
- Produces: `PedidosDBISAM.traslados_recepcion_existentes(numeros_pedido: list[int]) -> set[int]` — usado por el management command del Task 2.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `PedidosAlmacen/tests.py` (el archivo ya importa `SimpleNamespace as NS` y `from unittest.mock import patch, MagicMock`, y `from .dbisam import PedidosDBISAM`):

```python
class TrasladosRecepcionExistentesTest(TestCase):
    def _mock_cursor(self, mock_connect):
        conn = mock_connect.return_value.__enter__.return_value
        return conn.cursor.return_value.__enter__.return_value

    def test_devuelve_documentos_encontrados_como_enteros(self):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = self._mock_cursor(mock_connect)
            cursor.execute.return_value.fetchall.return_value = [
                NS(FTI_DOCUMENTO='00001234'),
                NS(FTI_DOCUMENTO='00005678'),
            ]
            resultado = db.traslados_recepcion_existentes([1234, 5678, 9999])
        self.assertEqual(resultado, {1234, 5678})

    def test_lista_vacia_no_consulta_bd(self):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            resultado = db.traslados_recepcion_existentes([])
        self.assertEqual(resultado, set())
        mock_connect.assert_not_called()

    def test_sql_filtra_tipo_y_deposito_transito(self):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = self._mock_cursor(mock_connect)
            cursor.execute.return_value.fetchall.return_value = []
            db.traslados_recepcion_existentes([1234])
            sql = cursor.execute.call_args[0][0]
        self.assertIn('FTI_TIPO = 1', sql)
        self.assertIn('FTI_DEPOSITOSOURCE = 10', sql)
        self.assertIn("'00001234'", sql)

    def test_pagina_en_lotes_de_200(self):
        db = PedidosDBISAM()
        numeros = list(range(1, 251))  # 250 números > 1 lote de 200
        with patch.object(db, 'connect') as mock_connect:
            cursor = self._mock_cursor(mock_connect)
            cursor.execute.return_value.fetchall.return_value = []
            db.traslados_recepcion_existentes(numeros)
        self.assertEqual(cursor.execute.call_count, 2)

    def test_error_dbisam_propaga_databaseerror(self):
        import pyodbc
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            mock_connect.side_effect = Exception('odbc down')
            with self.assertRaises(pyodbc.DatabaseError):
                db.traslados_recepcion_existentes([1234])
```

- [ ] **Step 2: Ejecutar los tests para verificar que fallan**

Run: `python manage.py test PedidosAlmacen.tests.TrasladosRecepcionExistentesTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL con `AttributeError: 'PedidosDBISAM' object has no attribute 'traslados_recepcion_existentes'` en los 5 tests.

- [ ] **Step 3: Implementar el método**

En `PedidosAlmacen/dbisam.py`, agregar después del método `existe_traslado_despacho` (termina en la línea 348, justo antes de `def insertar_traslado_despacho`):

```python
    def traslados_recepcion_existentes(self, numeros_pedido: list[int]) -> set[int]:
        """
        Verifica cuáles de los pedidos dados tienen registrado el traslado de
        recepción (tránsito → destino) en a2 (SOPERACIONINV).

        Args:
            numeros_pedido: Números de pedido (PK de Pedido en Postgres) a
                verificar.

        Returns:
            Conjunto de números de pedido que SÍ tienen el traslado
            registrado en a2. Los ausentes del conjunto de entrada son los
            problemáticos (recibidos en la app sin traslado en a2).

        Raises:
            pyodbc.DatabaseError: Si falla la conexión o la consulta.
        """
        if not numeros_pedido:
            return set()

        TAMANO_LOTE = 200
        encontrados: set[int] = set()
        try:
            with self.connect() as conn:
                for i in range(0, len(numeros_pedido), TAMANO_LOTE):
                    lote = numeros_pedido[i:i + TAMANO_LOTE]
                    docs_str = ','.join(f"'{str(n).rjust(8, '0')}'" for n in lote)
                    with conn.cursor() as cursor:
                        rows = cursor.execute(f"""SELECT DISTINCT FTI_DOCUMENTO
                                                FROM SOPERACIONINV
                                                WHERE FTI_TIPO = 1
                                                  AND FTI_DEPOSITOSOURCE = {DEPOSITO_TRANSITO}
                                                  AND FTI_DOCUMENTO IN ({docs_str})""").fetchall()
                        encontrados.update(int(row.FTI_DOCUMENTO) for row in rows)
            return encontrados
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))
```

- [ ] **Step 4: Ejecutar los tests para verificar que pasan**

Run: `python manage.py test PedidosAlmacen.tests.TrasladosRecepcionExistentesTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/dbisam.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): agrega traslados_recepcion_existentes a PedidosDBISAM"
```

---

### Task 2: Management command `validar_traslados_recepcion`

**Files:**
- Create: `PedidosAlmacen/management/commands/validar_traslados_recepcion.py`
- Test: `PedidosAlmacen/tests.py` (agregar clase nueva al final)

**Interfaces:**
- Consumes: `PedidosDBISAM.traslados_recepcion_existentes(numeros_pedido: list[int]) -> set[int]` (Task 1); modelos `Pedido` (`numero_pedido`, `solicitante`, `fecha_recepcion`, `deposito_codigo`) y `Despacho` (`estado`, relación `pedido.despachos`) de `PedidosAlmacen/models.py`.
- Produces: comando de consola `python manage.py validar_traslados_recepcion [--dias N] [--pedido N]`. No expone funciones para otros módulos.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `PedidosAlmacen/tests.py`:

```python
from io import StringIO
from django.core.management import call_command


class ValidarTrasladosRecepcionCommandTest(TestCase):
    def setUp(self):
        from users.models import User
        self.user = User.objects.create_superuser(username='cmd_valtras', password='x')

    def _crear_pedido_recibido(self, deposito_codigo=2, estado_despacho='RECIBIDO'):
        from .models import Pedido, Despacho
        pedido = Pedido.objects.create(
            solicitante=self.user, estado='RECIBIDO', deposito_codigo=deposito_codigo,
        )
        Despacho.objects.create(pedido=pedido, estado=estado_despacho)
        return pedido

    @patch('PedidosAlmacen.management.commands.validar_traslados_recepcion.PedidosDBISAM')
    def test_detecta_pedido_sin_traslado(self, mock_db):
        pedido = self._crear_pedido_recibido()
        mock_db.return_value.traslados_recepcion_existentes.return_value = set()

        out = StringIO()
        call_command('validar_traslados_recepcion', stdout=out)

        salida = out.getvalue()
        self.assertIn(f'#{pedido.numero_pedido}', salida)
        self.assertIn('1 de 1 pedidos sin traslado', salida)

    @patch('PedidosAlmacen.management.commands.validar_traslados_recepcion.PedidosDBISAM')
    def test_no_reporta_pedido_con_traslado_ok(self, mock_db):
        pedido = self._crear_pedido_recibido()
        mock_db.return_value.traslados_recepcion_existentes.return_value = {pedido.numero_pedido}

        out = StringIO()
        call_command('validar_traslados_recepcion', stdout=out)

        salida = out.getvalue()
        self.assertNotIn(f'#{pedido.numero_pedido}', salida)
        self.assertIn('0 de 1 pedidos sin traslado', salida)

    @patch('PedidosAlmacen.management.commands.validar_traslados_recepcion.PedidosDBISAM')
    def test_sin_candidatos_no_consulta_dbisam(self, mock_db):
        out = StringIO()
        call_command('validar_traslados_recepcion', stdout=out)

        self.assertIn('No hay pedidos candidatos', out.getvalue())
        mock_db.assert_not_called()

    @patch('PedidosAlmacen.management.commands.validar_traslados_recepcion.PedidosDBISAM')
    def test_filtro_pedido_ignora_otros(self, mock_db):
        p1 = self._crear_pedido_recibido()
        p2 = self._crear_pedido_recibido()
        mock_db.return_value.traslados_recepcion_existentes.return_value = set()

        out = StringIO()
        call_command('validar_traslados_recepcion', '--pedido', str(p1.numero_pedido), stdout=out)

        salida = out.getvalue()
        self.assertIn(f'#{p1.numero_pedido}', salida)
        self.assertNotIn(f'#{p2.numero_pedido}', salida)
        mock_db.return_value.traslados_recepcion_existentes.assert_called_once_with([p1.numero_pedido])

    @patch('PedidosAlmacen.management.commands.validar_traslados_recepcion.PedidosDBISAM')
    def test_filtro_dias_excluye_antiguos(self, mock_db):
        from django.utils import timezone
        from datetime import timedelta

        reciente = self._crear_pedido_recibido()
        reciente.fecha_recepcion = timezone.now()
        reciente.save()

        antiguo = self._crear_pedido_recibido()
        antiguo.fecha_recepcion = timezone.now() - timedelta(days=100)
        antiguo.save()

        mock_db.return_value.traslados_recepcion_existentes.return_value = set()

        out = StringIO()
        call_command('validar_traslados_recepcion', '--dias', '30', stdout=out)

        salida = out.getvalue()
        self.assertIn(f'#{reciente.numero_pedido}', salida)
        self.assertNotIn(f'#{antiguo.numero_pedido}', salida)

    @patch('PedidosAlmacen.management.commands.validar_traslados_recepcion.PedidosDBISAM')
    def test_pedido_sin_deposito_codigo_se_excluye(self, mock_db):
        self._crear_pedido_recibido(deposito_codigo=None)

        out = StringIO()
        call_command('validar_traslados_recepcion', stdout=out)

        self.assertIn('No hay pedidos candidatos', out.getvalue())
        mock_db.assert_not_called()

    @patch('PedidosAlmacen.management.commands.validar_traslados_recepcion.PedidosDBISAM')
    def test_error_dbisam_no_rompe_comando(self, mock_db):
        self._crear_pedido_recibido()
        mock_db.return_value.traslados_recepcion_existentes.side_effect = Exception('odbc down')

        out = StringIO()
        err = StringIO()
        call_command('validar_traslados_recepcion', stdout=out, stderr=err)

        self.assertIn('Error al consultar a2', err.getvalue())
```

- [ ] **Step 2: Ejecutar los tests para verificar que fallan**

Run: `python manage.py test PedidosAlmacen.tests.ValidarTrasladosRecepcionCommandTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL con `django.core.management.base.CommandError: Unknown command: 'validar_traslados_recepcion'` en los 7 tests.

- [ ] **Step 3: Implementar el management command**

Crear `PedidosAlmacen/management/commands/validar_traslados_recepcion.py`:

```python
"""
Management command para detectar pedidos recibidos en la app cuyo traslado de
recepción (tránsito → destino) no quedó registrado en a2 (SOPERACIONINV), por
lo que las existencias de los productos recibidos no se actualizaron.

Es de solo lectura: no modifica Postgres ni a2.

Valida únicamente el paso de RECEPCIÓN. El paso de despacho (almacén→tránsito)
ya se audita en Postgres mediante Despacho.traslado_a2_registrado, sin
necesitar consultar DBISAM.

Uso:
    python manage.py validar_traslados_recepcion
    python manage.py validar_traslados_recepcion --dias 30
    python manage.py validar_traslados_recepcion --pedido 1234
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from PedidosAlmacen.dbisam import PedidosDBISAM
from PedidosAlmacen.models import Pedido


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
        try:
            existentes = PedidosDBISAM().traslados_recepcion_existentes(numeros)
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
```

- [ ] **Step 4: Ejecutar los tests para verificar que pasan**

Run: `python manage.py test PedidosAlmacen.tests.ValidarTrasladosRecepcionCommandTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (7 tests).

- [ ] **Step 5: Ejecutar toda la suite de PedidosAlmacen para verificar que no hay regresiones**

Run: `python manage.py test PedidosAlmacen --settings=Programarprecios.test_settings -v 1`
Expected: PASS (todos los tests existentes + los 12 nuevos de esta feature).

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/management/commands/validar_traslados_recepcion.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): agrega comando validar_traslados_recepcion"
```

---

## Uso manual en producción (post-implementación)

```bash
# Revisar todo el histórico
python manage.py validar_traslados_recepcion

# Solo últimos 30 días
python manage.py validar_traslados_recepcion --dias 30

# Spot-check de un pedido puntual
python manage.py validar_traslados_recepcion --pedido 1234
```
