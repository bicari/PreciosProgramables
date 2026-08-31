# Creación Masiva de Pedidos vía Excel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir crear pedidos de almacén subiendo un Excel (SKU + Cantidad, Categoria opcional e informativa) que resuelve los ítems contra a2 y los carga al mismo carrito que ya usan la búsqueda manual y la carga de documentos a2, sin duplicar la validación de stock que ya corre al totalizar.

**Architecture:** Un módulo nuevo (`excel_pedido.py`) con la lógica pura de lectura/validación del Excel (sin Django ni DBISAM), un método nuevo en `PedidosDBISAM` para resolver productos por código en batch, dos endpoints nuevos (descargar plantilla, cargar archivo) y un overlay más en `pedidos-crear.html` que reutiliza la función de merge al carrito ya existente (renombrada de `mezclarItemsA2` a `mezclarItemsAlCarrito` porque deja de ser específica de a2).

**Tech Stack:** Django, pandas (lectura), openpyxl (generación de plantilla), pyodbc/DBISAM.

**Spec:** `docs/superpowers/specs/2026-08-27-carga-masiva-excel-pedido-design.md`

## Global Constraints

- Columnas de la plantilla: `SKU` y `Cantidad` obligatorias; `Categoria (opcional)` nunca se lee en el backend.
- Límite: 500 filas de datos por archivo (`MAX_FILAS` en `excel_pedido.py`).
- Motivos de omisión exactos (usados por tests y frontend): `'SKU vacío'`, `'Cantidad inválida'`, `'SKU no encontrado en a2'`.
- SKU repetido dentro del archivo: se suman las cantidades, no se reporta como omitido.
- Permisos: `login_required` + `user_passes_test(is_pedidos_tienda, login_url='dashboard')` — mismos que el resto del flujo de creación de pedido.
- DBISAM no soporta placeholders `?` — escapar manualmente (`.replace("'", "''")`) antes de interpolar, mismo estilo que el resto de `PedidosAlmacen/dbisam.py`.
- Sin validación de stock/comprometido en este flujo — la reutiliza `crear_pedido` al totalizar, sin cambios.
- Tests con: `venv/Scripts/python.exe manage.py test PedidosAlmacen --settings=Programarprecios.test_settings`

---

## Task 1: `PedidosDBISAM.resolver_productos`

**Files:**
- Modify: `PedidosAlmacen/dbisam.py` (nuevo método al final de la clase, después de `obtener_items_documentos`, línea 716)
- Test: `PedidosAlmacen/tests.py` (nueva clase `ResolverProductosTest`, después de `ObtenerItemsDocumentosTest`)

**Interfaces:**
- Produces: `PedidosDBISAM.resolver_productos(codigos: list[str]) -> dict[str, dict]`. Cada valor: `{'descripcion': str, 'referencia': str, 'puesto': str, 'ref_proveedor': str, 'categoria': str}`. Códigos no encontrados en `SINVENTARIO` simplemente no aparecen como clave. Lista vacía → `{}` sin consultar DBISAM.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar en `PedidosAlmacen/tests.py`, después de la clase `ObtenerItemsDocumentosTest`:

```python
class ResolverProductosTest(TestCase):
    def _capturar_sql(self, codigos):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = (mock_connect.return_value.__enter__.return_value
                      .cursor.return_value.__enter__.return_value)
            cursor.execute.return_value.fetchall.return_value = []
            db.resolver_productos(codigos)
            return cursor.execute.call_args[0][0]

    def test_filtra_por_codigos(self):
        sql = self._capturar_sql(['SKU1', 'SKU2'])
        self.assertIn("FI_CODIGO IN ('SKU1','SKU2')", sql)

    def test_sin_codigos_no_ejecuta_query(self):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            resultado = db.resolver_productos([])
        mock_connect.assert_not_called()
        self.assertEqual(resultado, {})

    def test_escapa_comillas_simples(self):
        sql = self._capturar_sql(["O'BRIEN"])
        self.assertIn("O''BRIEN", sql)

    def test_mapea_filas_a_dict_indexado_por_codigo(self):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = (mock_connect.return_value.__enter__.return_value
                      .cursor.return_value.__enter__.return_value)
            cursor.execute.return_value.fetchall.return_value = [
                ('SKU1', 'Producto Uno', 'REF1', 'P1', 'PROV1', 'FERRETERIA'),
            ]
            resultado = db.resolver_productos(['SKU1'])
        self.assertEqual(resultado, {
            'SKU1': {
                'descripcion': 'Producto Uno', 'referencia': 'REF1',
                'puesto': 'P1', 'ref_proveedor': 'PROV1', 'categoria': 'FERRETERIA',
            },
        })

    def test_codigo_no_encontrado_no_aparece_en_resultado(self):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = (mock_connect.return_value.__enter__.return_value
                      .cursor.return_value.__enter__.return_value)
            cursor.execute.return_value.fetchall.return_value = []
            resultado = db.resolver_productos(['NOEXISTE'])
        self.assertEqual(resultado, {})
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `venv/Scripts/python.exe manage.py test PedidosAlmacen.tests.ResolverProductosTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL (`AttributeError: 'PedidosDBISAM' object has no attribute 'resolver_productos'`)

- [ ] **Step 3: Implementar**

Al final de `PedidosAlmacen/dbisam.py` (después de `obtener_items_documentos`, línea 716):

```python
    def resolver_productos(self, codigos: list[str]) -> dict[str, dict]:
        """Resuelve datos de producto (SINVENTARIO) para una lista de códigos.

        Usado por la carga masiva de pedidos vía Excel: cada fila del
        archivo trae solo el código, este método completa el resto.

        Args:
            codigos: Códigos de producto a resolver.

        Returns:
            Dict indexado por código: {codigo: {descripcion, referencia,
            puesto, ref_proveedor, categoria}}. Códigos no encontrados en
            SINVENTARIO simplemente no aparecen en el resultado.
        """
        codigos_validos = [c for c in codigos if c]
        if not codigos_validos:
            return {}

        codigos_str = ','.join("'" + c.replace("'", "''") + "'" for c in codigos_validos)

        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute(f"""SELECT
                                            FI_CODIGO,
                                            FI_DESCRIPCION,
                                            FI_REFERENCIA,
                                            FI_PUESTO,
                                            ZZCAMPO_001,
                                            FI_CATEGORIA
                                        FROM SINVENTARIO
                                        WHERE FI_CODIGO IN ({codigos_str})""").fetchall()
                    return {
                        _clean(r[0]): {
                            'descripcion': _clean(r[1]),
                            'referencia': _clean(r[2]),
                            'puesto': _clean(r[3]),
                            'ref_proveedor': _clean(r[4]),
                            'categoria': _clean(r[5]),
                        }
                        for r in rows
                    }
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `venv/Scripts/python.exe manage.py test PedidosAlmacen.tests.ResolverProductosTest --settings=Programarprecios.test_settings -v 2`
Expected: OK (5 tests)

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/dbisam.py PedidosAlmacen/tests.py
git commit -m "$(cat <<'EOF'
feat(pedidos): agrega resolucion batch de productos por codigo para carga Excel

Nuevo metodo PedidosDBISAM.resolver_productos, usado por la carga
masiva de pedidos via Excel para completar descripcion/categoria/etc
de cada SKU de la plantilla.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FmMX2cwMh94uT9DHXgE2bW
EOF
)"
```

---

## Task 2: Módulo `excel_pedido.py` (lectura y validación pura)

**Files:**
- Create: `PedidosAlmacen/excel_pedido.py`
- Test: `PedidosAlmacen/tests.py` (nuevas clases `LeerFilasPedidoTest`, `ConstruirItemsTest`, al final del archivo)

**Interfaces:**
- Consumes: nada de tareas anteriores (módulo puro, sin Django ni DBISAM).
- Produces:
  - `MAX_FILAS = 500` (constante del módulo).
  - `class ExcelPedidoError(Exception)` — error de archivo completo (columnas faltantes, exceso de filas, archivo ilegible).
  - `leer_filas_pedido(archivo) -> list[dict]` — cada dict: `{'fila': int, 'sku': cualquiera, 'cantidad': cualquiera}` (valores tal cual los lee pandas, sin validar todavía). `fila` es el número de fila real en el Excel (contando la fila de encabezado como 1).
  - `construir_items(filas: list[dict], productos: dict, categorias_map: dict) -> tuple[list[dict], list[dict]]` — `(items, omitidos)`. Cada item: `{'codigo', 'descripcion', 'referencia', 'puesto', 'ref_proveedor', 'cantidad', 'categoria', 'categoria_nombre'}`. Cada omitido: `{'fila': int, 'sku': str, 'motivo': str}` con `motivo` uno de los tres strings exactos listados en Global Constraints.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar en `PedidosAlmacen/tests.py`, al final del archivo:

```python
class LeerFilasPedidoTest(TestCase):
    def _archivo(self, filas, headers=('SKU', 'Cantidad', 'Categoria (opcional)')):
        import openpyxl
        import io
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(list(headers))
        for fila in filas:
            ws.append(fila)
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return buffer

    def test_lee_filas_validas(self):
        from .excel_pedido import leer_filas_pedido
        archivo = self._archivo([['SKU1', 5, ''], ['SKU2', 3, 'FERRETERIA']])
        filas = leer_filas_pedido(archivo)
        self.assertEqual(filas, [
            {'fila': 2, 'sku': 'SKU1', 'cantidad': 5},
            {'fila': 3, 'sku': 'SKU2', 'cantidad': 3},
        ])

    def test_columnas_faltantes_lanza_error(self):
        from .excel_pedido import leer_filas_pedido, ExcelPedidoError
        archivo = self._archivo([['SKU1', 5]], headers=('Codigo', 'Cant'))
        with self.assertRaises(ExcelPedidoError):
            leer_filas_pedido(archivo)

    def test_mas_de_limite_filas_lanza_error(self):
        from .excel_pedido import leer_filas_pedido, ExcelPedidoError, MAX_FILAS
        archivo = self._archivo([[f'SKU{i}', 1, ''] for i in range(MAX_FILAS + 1)])
        with self.assertRaises(ExcelPedidoError):
            leer_filas_pedido(archivo)


class ConstruirItemsTest(TestCase):
    def test_fila_valida_se_incluye(self):
        from .excel_pedido import construir_items
        filas = [{'fila': 2, 'sku': 'SKU1', 'cantidad': 5}]
        productos = {'SKU1': {'descripcion': 'Producto Uno', 'referencia': 'REF1',
                               'puesto': 'P1', 'ref_proveedor': 'PROV1', 'categoria': 'CAT1'}}
        categorias_map = {'CAT1': 'Ferreteria'}
        items, omitidos = construir_items(filas, productos, categorias_map)
        self.assertEqual(items, [{
            'codigo': 'SKU1', 'descripcion': 'Producto Uno', 'referencia': 'REF1',
            'puesto': 'P1', 'ref_proveedor': 'PROV1', 'cantidad': 5,
            'categoria': 'CAT1', 'categoria_nombre': 'Ferreteria',
        }])
        self.assertEqual(omitidos, [])

    def test_sku_vacio_se_omite(self):
        from .excel_pedido import construir_items
        filas = [{'fila': 2, 'sku': float('nan'), 'cantidad': 5}]
        items, omitidos = construir_items(filas, {}, {})
        self.assertEqual(items, [])
        self.assertEqual(len(omitidos), 1)
        self.assertEqual(omitidos[0]['fila'], 2)
        self.assertEqual(omitidos[0]['motivo'], 'SKU vacío')

    def test_cantidad_invalida_se_omite(self):
        from .excel_pedido import construir_items
        filas = [{'fila': 2, 'sku': 'SKU1', 'cantidad': 'abc'}]
        productos = {'SKU1': {'descripcion': '', 'referencia': '', 'puesto': '',
                               'ref_proveedor': '', 'categoria': ''}}
        items, omitidos = construir_items(filas, productos, {})
        self.assertEqual(items, [])
        self.assertEqual(omitidos[0]['motivo'], 'Cantidad inválida')

    def test_cantidad_cero_o_negativa_se_omite(self):
        from .excel_pedido import construir_items
        filas = [{'fila': 2, 'sku': 'SKU1', 'cantidad': 0}]
        productos = {'SKU1': {'descripcion': '', 'referencia': '', 'puesto': '',
                               'ref_proveedor': '', 'categoria': ''}}
        items, omitidos = construir_items(filas, productos, {})
        self.assertEqual(items, [])
        self.assertEqual(omitidos[0]['motivo'], 'Cantidad inválida')

    def test_sku_no_encontrado_se_omite(self):
        from .excel_pedido import construir_items
        filas = [{'fila': 2, 'sku': 'NOEXISTE', 'cantidad': 5}]
        items, omitidos = construir_items(filas, {}, {})
        self.assertEqual(items, [])
        self.assertEqual(omitidos[0]['motivo'], 'SKU no encontrado en a2')

    def test_sku_duplicado_suma_cantidades(self):
        from .excel_pedido import construir_items
        filas = [
            {'fila': 2, 'sku': 'SKU1', 'cantidad': 5},
            {'fila': 3, 'sku': 'SKU1', 'cantidad': 3},
        ]
        productos = {'SKU1': {'descripcion': 'Uno', 'referencia': '', 'puesto': '',
                               'ref_proveedor': '', 'categoria': ''}}
        items, omitidos = construir_items(filas, productos, {})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['cantidad'], 8)
        self.assertEqual(omitidos, [])
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `venv/Scripts/python.exe manage.py test PedidosAlmacen.tests.LeerFilasPedidoTest PedidosAlmacen.tests.ConstruirItemsTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL (`ModuleNotFoundError: No module named 'PedidosAlmacen.excel_pedido'`)

- [ ] **Step 3: Implementar**

Crear `PedidosAlmacen/excel_pedido.py`:

```python
"""Lectura y validación pura del Excel de carga masiva de pedidos.

Sin dependencias de Django ni DBISAM — recibe `productos`/`categorias_map`
ya resueltos, para que la lógica de validación por fila sea testeable sin
mocks de conexión.
"""
import pandas as pd

MAX_FILAS = 500
COLUMNAS_REQUERIDAS = ('SKU', 'Cantidad')


class ExcelPedidoError(Exception):
    """Error de archivo completo: columnas faltantes, exceso de filas, o
    archivo ilegible. No se procesa nada cuando se lanza esta excepción."""


def leer_filas_pedido(archivo) -> list[dict]:
    """Lee un .xlsx/.xls y devuelve las filas crudas de datos.

    Args:
        archivo: objeto tipo archivo (ej. UploadedFile de Django) con las
            columnas SKU, Cantidad en la fila de encabezado (fila 1).

    Returns:
        Lista de dicts {'fila': int, 'sku': valor_crudo, 'cantidad': valor_crudo},
        sin validar todavía — `construir_items` hace la validación por fila.
        `fila` es el número de fila real en el Excel (la de encabezado es 1).

    Raises:
        ExcelPedidoError: el archivo no se puede leer, faltan columnas
            requeridas, o supera MAX_FILAS filas de datos.
    """
    try:
        df = pd.read_excel(archivo, header=0, dtype={'SKU': str})
    except Exception as e:
        raise ExcelPedidoError(f'No se pudo leer el archivo: {e}')

    faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in df.columns]
    if faltantes:
        raise ExcelPedidoError(f'Faltan columnas requeridas: {", ".join(faltantes)}')

    if len(df) > MAX_FILAS:
        raise ExcelPedidoError(f'El archivo supera el máximo de {MAX_FILAS} filas')

    return [
        {'fila': idx + 2, 'sku': row['SKU'], 'cantidad': row['Cantidad']}
        for idx, row in df.iterrows()
    ]


def construir_items(filas: list[dict], productos: dict, categorias_map: dict) -> tuple[list[dict], list[dict]]:
    """Valida cada fila, resuelve contra `productos`, suma SKU repetidos.

    Args:
        filas: Salida de `leer_filas_pedido`.
        productos: Salida de `PedidosDBISAM.resolver_productos` — dict
            indexado por código con descripcion/referencia/puesto/
            ref_proveedor/categoria.
        categorias_map: Dict código→nombre de categoría (de
            `PedidosDBISAM.obtener_categorias()`), para resolver
            categoria_nombre.

    Returns:
        (items, omitidos). Cada item trae codigo/descripcion/referencia/
        puesto/ref_proveedor/cantidad/categoria/categoria_nombre. Cada
        omitido trae fila/sku/motivo.
    """
    items_por_codigo: dict[str, dict] = {}
    omitidos: list[dict] = []

    for fila in filas:
        sku = fila['sku']
        if not isinstance(sku, str) or not sku.strip():
            omitidos.append({'fila': fila['fila'], 'sku': str(sku), 'motivo': 'SKU vacío'})
            continue
        sku = sku.strip()

        try:
            cantidad = int(fila['cantidad'])
        except (TypeError, ValueError):
            cantidad = None
        if cantidad is None or cantidad <= 0:
            omitidos.append({'fila': fila['fila'], 'sku': sku, 'motivo': 'Cantidad inválida'})
            continue

        info = productos.get(sku)
        if info is None:
            omitidos.append({'fila': fila['fila'], 'sku': sku, 'motivo': 'SKU no encontrado en a2'})
            continue

        if sku in items_por_codigo:
            items_por_codigo[sku]['cantidad'] += cantidad
        else:
            items_por_codigo[sku] = {
                'codigo': sku,
                'descripcion': info['descripcion'],
                'referencia': info['referencia'],
                'puesto': info['puesto'],
                'ref_proveedor': info['ref_proveedor'],
                'cantidad': cantidad,
                'categoria': info['categoria'],
                'categoria_nombre': categorias_map.get(info['categoria'], info['categoria']),
            }

    return list(items_por_codigo.values()), omitidos
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `venv/Scripts/python.exe manage.py test PedidosAlmacen.tests.LeerFilasPedidoTest PedidosAlmacen.tests.ConstruirItemsTest --settings=Programarprecios.test_settings -v 2`
Expected: OK (9 tests)

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/excel_pedido.py PedidosAlmacen/tests.py
git commit -m "$(cat <<'EOF'
feat(pedidos): agrega lectura y validacion pura del Excel de carga masiva

Modulo PedidosAlmacen/excel_pedido.py: leer_filas_pedido (pandas) y
construir_items (validacion por fila, suma de SKU repetidos), sin
dependencias de Django ni DBISAM para que sea testeable sin mocks de
conexion.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FmMX2cwMh94uT9DHXgE2bW
EOF
)"
```

---

## Task 3: Endpoints — plantilla y carga

**Files:**
- Modify: `PedidosAlmacen/views.py` (imports + dos vistas nuevas al final del archivo)
- Modify: `PedidosAlmacen/urls.py` (dos rutas nuevas)
- Test: `PedidosAlmacen/tests.py` (nuevas clases `PlantillaExcelPedidoViewTest`, `CargarItemsExcelViewTest`)

**Interfaces:**
- Consumes: `PedidosDBISAM.resolver_productos` (Task 1), `PedidosDBISAM.obtener_categorias()` (existente), `excel_pedido.leer_filas_pedido`, `excel_pedido.construir_items`, `excel_pedido.ExcelPedidoError` (Task 2).
- Produces:
  - `GET /pedidos/plantilla-excel/` (name `pedidos-plantilla-excel`) — descarga un `.xlsx` con headers `SKU`, `Cantidad`, `Categoria (opcional)`.
  - `POST /pedidos/cargar-items-excel/` (name `pedidos-cargar-items-excel`, body `multipart/form-data` con campo `archivo`) — JSON `{"items": [...], "categorias_distintas": [str], "omitidos": [...]}` (200) o `{"error": str}` (400/405/502).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar en `PedidosAlmacen/tests.py`, al final del archivo:

```python
class PlantillaExcelPedidoViewTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        self.user = User.objects.create_user(username='tnd_plantilla', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.user.groups.add(g)
        self.client.force_login(self.user)

    def test_descarga_xlsx_con_headers_correctos(self):
        import openpyxl
        import io
        resp = self.client.get('/pedidos/plantilla-excel/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp['Content-Type'],
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        wb = openpyxl.load_workbook(io.BytesIO(resp.content))
        ws = wb.active
        headers = [c.value for c in ws[1]]
        self.assertEqual(headers, ['SKU', 'Cantidad', 'Categoria (opcional)'])

    def test_usuario_sin_permiso_redirige(self):
        from users.models import User
        otro = User.objects.create_user(username='sin_permiso_plantilla', password='x')
        self.client.force_login(otro)
        resp = self.client.get('/pedidos/plantilla-excel/')
        self.assertEqual(resp.status_code, 302)


class CargarItemsExcelViewTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        self.user = User.objects.create_user(username='tnd_excel', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.user.groups.add(g)
        self.client.force_login(self.user)

    def _archivo(self, filas, nombre='pedido.xlsx'):
        import openpyxl
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['SKU', 'Cantidad', 'Categoria (opcional)'])
        for fila in filas:
            ws.append(fila)
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return SimpleUploadedFile(
            nombre, buffer.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_carga_items_validos(self, mock_db):
        mock_db.return_value.resolver_productos.return_value = {
            'SKU1': {'descripcion': 'Uno', 'referencia': 'R1', 'puesto': 'P1',
                     'ref_proveedor': 'PR1', 'categoria': 'CAT1'},
        }
        mock_db.return_value.obtener_categorias.return_value = [('CAT1', 'Ferreteria')]
        archivo = self._archivo([['SKU1', 5, '']])
        resp = self.client.post('/pedidos/cargar-items-excel/', {'archivo': archivo})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['cantidad'], 5)
        self.assertEqual(data['items'][0]['categoria_nombre'], 'Ferreteria')
        self.assertEqual(data['omitidos'], [])

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_fila_con_sku_no_encontrado_se_reporta_en_omitidos(self, mock_db):
        mock_db.return_value.resolver_productos.return_value = {}
        mock_db.return_value.obtener_categorias.return_value = []
        archivo = self._archivo([['NOEXISTE', 5, '']])
        resp = self.client.post('/pedidos/cargar-items-excel/', {'archivo': archivo})
        data = resp.json()
        self.assertEqual(data['items'], [])
        self.assertEqual(len(data['omitidos']), 1)
        self.assertEqual(data['omitidos'][0]['motivo'], 'SKU no encontrado en a2')

    def test_extension_invalida_devuelve_400(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        archivo = SimpleUploadedFile('pedido.txt', b'no es un excel', content_type='text/plain')
        resp = self.client.post('/pedidos/cargar-items-excel/', {'archivo': archivo})
        self.assertEqual(resp.status_code, 400)

    def test_sin_archivo_devuelve_400(self):
        resp = self.client.post('/pedidos/cargar-items-excel/', {})
        self.assertEqual(resp.status_code, 400)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_error_dbisam_devuelve_502(self, mock_db):
        mock_db.return_value.resolver_productos.side_effect = pyodbc.DatabaseError('odbc down')
        archivo = self._archivo([['SKU1', 5, '']])
        resp = self.client.post('/pedidos/cargar-items-excel/', {'archivo': archivo})
        self.assertEqual(resp.status_code, 502)

    def test_get_no_permitido(self):
        resp = self.client.get('/pedidos/cargar-items-excel/')
        self.assertEqual(resp.status_code, 405)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_mas_de_limite_filas_devuelve_400(self, mock_db):
        from .excel_pedido import MAX_FILAS
        archivo = self._archivo([[f'SKU{i}', 1, ''] for i in range(MAX_FILAS + 1)])
        resp = self.client.post('/pedidos/cargar-items-excel/', {'archivo': archivo})
        self.assertEqual(resp.status_code, 400)
        mock_db.assert_not_called()
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `venv/Scripts/python.exe manage.py test PedidosAlmacen.tests.PlantillaExcelPedidoViewTest PedidosAlmacen.tests.CargarItemsExcelViewTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL (404, las URLs no existen)

- [ ] **Step 3: Implementar**

En `PedidosAlmacen/views.py`, agregar cerca de los demás imports (línea 30, después de `import pyodbc`):

```python
import openpyxl
from .excel_pedido import leer_filas_pedido, construir_items, ExcelPedidoError
```

Al final de `PedidosAlmacen/views.py`, agregar:

```python
@login_required(login_url='/login/')
@user_passes_test(is_pedidos_tienda, login_url='dashboard')
def plantilla_excel_pedido(request):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Pedido'
    ws.append(['SKU', 'Cantidad', 'Categoria (opcional)'])
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="plantilla_pedido.xlsx"'
    return response


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_tienda, login_url='dashboard')
def cargar_items_excel(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    archivo = request.FILES.get('archivo')
    if archivo is None:
        return JsonResponse({'error': 'Debe seleccionar un archivo'}, status=400)
    if not archivo.name.lower().endswith(('.xlsx', '.xls')):
        return JsonResponse({'error': 'El archivo debe ser .xlsx o .xls'}, status=400)

    try:
        filas = leer_filas_pedido(archivo)
    except ExcelPedidoError as e:
        return JsonResponse({'error': str(e)}, status=400)

    codigos = sorted({
        f['sku'].strip() for f in filas
        if isinstance(f['sku'], str) and f['sku'].strip()
    })
    try:
        productos = PedidosDBISAM().resolver_productos(codigos)
    except pyodbc.Error as e:
        logger.error(f'Error al resolver productos del Excel de pedido (codigos={codigos}): {e}')
        return JsonResponse(
            {'error': 'No se pudo consultar a2. Intenta de nuevo en unos segundos.'}, status=502
        )

    categorias_map = {}
    try:
        categorias_map = {str(c[0]): c[1] for c in PedidosDBISAM().obtener_categorias()}
    except pyodbc.Error as e:
        logger.error(f'Error al obtener categorias para carga de Excel de pedido: {e}')

    items, omitidos = construir_items(filas, productos, categorias_map)
    categorias_distintas = sorted({item['categoria'] for item in items if item['categoria']})

    return JsonResponse({'items': items, 'categorias_distintas': categorias_distintas, 'omitidos': omitidos})
```

En `PedidosAlmacen/urls.py`, agregar junto a las rutas de a2:

```python
    path('pedidos/plantilla-excel/', views.plantilla_excel_pedido, name='pedidos-plantilla-excel'),
    path('pedidos/cargar-items-excel/', views.cargar_items_excel, name='pedidos-cargar-items-excel'),
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `venv/Scripts/python.exe manage.py test PedidosAlmacen.tests.PlantillaExcelPedidoViewTest PedidosAlmacen.tests.CargarItemsExcelViewTest --settings=Programarprecios.test_settings -v 2`
Expected: OK (8 tests)

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/urls.py PedidosAlmacen/tests.py
git commit -m "$(cat <<'EOF'
feat(pedidos): agrega endpoints de plantilla y carga de Excel de pedido

GET /pedidos/plantilla-excel/ genera la plantilla .xlsx al vuelo.
POST /pedidos/cargar-items-excel/ resuelve el archivo subido contra
a2 (SKU->producto), suma cantidades de SKU repetidos y reporta filas
omitidas (SKU vacio, cantidad invalida, SKU no encontrado) sin
bloquear el resto del archivo.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FmMX2cwMh94uT9DHXgE2bW
EOF
)"
```

---

## Task 4: Overlay "Cargar desde Excel" en `pedidos-crear.html`

**Files:**
- Modify: `templates/pedidos-crear.html`

**Interfaces:**
- Consumes: URL `/pedidos/plantilla-excel/` (Task 3, link directo de descarga), URL `/pedidos/cargar-items-excel/` (Task 3, fetch POST con `FormData`, JSON `{items, categorias_distintas, omitidos}` o `{error}`), la función `mezclarItemsA2` ya existente en este archivo — **se renombra a `mezclarItemsAlCarrito`** en este mismo task, porque deja de ser específica del flujo a2 y las dos cargas (a2 y Excel) la comparten.
- Produces: nada consumido por otras tareas — es la última.

No hay test automatizado de JS en este proyecto (mismo caso que la carga a2). Este task termina con verificación manual en navegador.

- [ ] **Step 1: Renombrar `mezclarItemsA2` a `mezclarItemsAlCarrito`**

En `templates/pedidos-crear.html`, la función está definida así (buscar `function mezclarItemsA2(items) {`):

```javascript
function mezclarItemsA2(items) {
```

Cambiar la línea de la definición a:

```javascript
function mezclarItemsAlCarrito(items) {
```

Y su único call site, dentro del handler de `btn-cargar-a2` (buscar `mezclarItemsA2(data.items);`):

```javascript
            mezclarItemsA2(data.items);
```

Cambiar a:

```javascript
            mezclarItemsAlCarrito(data.items);
```

- [ ] **Step 2: Agregar el botón "Cargar desde Excel"**

Buscar este bloque (el único `<div class="d-flex justify-content-end mb-2">` del archivo, contiene el botón "Cargar de a2"):

```html
    <div class="d-flex justify-content-end mb-2">
        <button type="button" class="btn btn-outline-primary btn-sm" id="btn-abrir-a2">
            <i class="fas fa-file-import"></i> Cargar de a2
        </button>
    </div>
```

Reemplazar por:

```html
    <div class="d-flex justify-content-end gap-2 mb-2">
        <button type="button" class="btn btn-outline-primary btn-sm" id="btn-abrir-excel">
            <i class="fas fa-file-excel"></i> Cargar desde Excel
        </button>
        <button type="button" class="btn btn-outline-primary btn-sm" id="btn-abrir-a2">
            <i class="fas fa-file-import"></i> Cargar de a2
        </button>
    </div>
```

- [ ] **Step 3: Agregar el overlay**

Buscar el cierre del overlay de a2 (el `</div>` que cierra `<div id="overlay-a2" ...>`, inmediatamente antes de `<style>`):

```html
    </div>
</div>

<style>
```

Insertar el nuevo overlay entre el cierre de `overlay-a2` y `<style>`:

```html
    </div>
</div>

<!-- Overlay de carga masiva desde Excel -->
<div id="overlay-excel" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.55); z-index:9996; align-items:center; justify-content:center;">
    <div style="background:#fff; border-radius:16px; padding:28px 32px; max-width:520px; width:95%; max-height:85vh; overflow-y:auto; box-shadow:0 8px 32px rgba(0,0,0,0.25);">
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h5 class="mb-0"><i class="fas fa-file-excel"></i> Cargar desde Excel</h5>
            <button type="button" class="btn-close" id="btn-cerrar-excel" aria-label="Cerrar"></button>
        </div>

        <p class="text-muted small">Sube un archivo con las columnas SKU y Cantidad (Categoria es opcional, solo de referencia).</p>

        <div class="mb-3">
            <a href="/pedidos/plantilla-excel/" class="btn btn-outline-secondary btn-sm">
                <i class="fas fa-download"></i> Descargar plantilla
            </a>
        </div>

        <div class="mb-3">
            <label for="excel-archivo" class="form-label small">Archivo (.xlsx o .xls)</label>
            <input type="file" class="form-control" id="excel-archivo" accept=".xlsx,.xls">
        </div>

        <div id="resultados-excel" class="mb-3"></div>

        <div class="d-flex justify-content-between align-items-center">
            <button type="button" class="btn btn-secondary" id="btn-cancelar-excel">Cancelar</button>
            <button type="button" class="btn btn-primary" id="btn-cargar-excel">Cargar archivo</button>
        </div>
    </div>
</div>

<style>
```

- [ ] **Step 4: Agregar el JavaScript**

Al final del bloque `<script>` existente (después de todo el código de a2, incluyendo el handler de `btn-cargar-a2`, antes de `</script>`), agregar:

```javascript

document.getElementById('btn-abrir-excel').addEventListener('click', function() {
    document.getElementById('overlay-excel').style.display = 'flex';
});

function cerrarOverlayExcel() {
    document.getElementById('overlay-excel').style.display = 'none';
    document.getElementById('excel-archivo').value = '';
    document.getElementById('resultados-excel').innerHTML = '';
}

document.getElementById('btn-cerrar-excel').addEventListener('click', cerrarOverlayExcel);
document.getElementById('btn-cancelar-excel').addEventListener('click', cerrarOverlayExcel);

document.getElementById('overlay-excel').addEventListener('click', function(e) {
    if (e.target === this) cerrarOverlayExcel();
});

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && document.getElementById('overlay-excel').style.display === 'flex') {
        cerrarOverlayExcel();
    }
});

document.getElementById('btn-cargar-excel').addEventListener('click', function() {
    const input = document.getElementById('excel-archivo');
    if (!input.files.length) {
        document.getElementById('resultados-excel').innerHTML =
            '<p class="text-warning p-2">Selecciona un archivo primero</p>';
        return;
    }

    const btn = this;
    btn.disabled = true;

    const formData = new FormData();
    formData.append('archivo', input.files[0]);

    fetch('/pedidos/cargar-items-excel/', {
        method: 'POST',
        headers: {
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
        },
        body: formData,
    })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                document.getElementById('resultados-excel').innerHTML =
                    '<p class="text-danger p-2">' + data.error + '</p>';
                return;
            }
            if (data.items.length) {
                mezclarItemsAlCarrito(data.items);
            }
            if (data.omitidos.length) {
                const lista = data.omitidos.map(function(o) {
                    return '<li>Fila ' + o.fila + ': ' + o.sku + ' — ' + o.motivo + '</li>';
                }).join('');
                document.getElementById('resultados-excel').innerHTML =
                    '<p class="text-warning p-2 mb-1">' + data.items.length + ' ítem(s) cargados. ' +
                    data.omitidos.length + ' fila(s) omitida(s):</p>' +
                    '<ul class="small text-muted">' + lista + '</ul>';
            } else {
                cerrarOverlayExcel();
            }
        })
        .catch(function() {
            document.getElementById('resultados-excel').innerHTML =
                '<p class="text-danger p-2">No se pudo consultar a2. Intenta de nuevo en unos segundos.</p>';
        })
        .finally(function() {
            btn.disabled = false;
        });
});
```

- [ ] **Step 5: Verificación manual en navegador**

Levantar el servidor de desarrollo (`venv/Scripts/python.exe manage.py runserver`), loguearse con un usuario del grupo "Pedidos Tienda", ir a `/pedidos/crear/`, y verificar:

1. El botón "Cargar desde Excel" es visible junto a "Cargar de a2", clickeable **sin** haber seleccionado categoría/condición/depósito.
2. "Descargar plantilla" baja un `.xlsx` con las columnas SKU, Cantidad, Categoria (opcional).
3. Llenar la plantilla con 2-3 SKU reales y cantidades, subirla — los ítems aparecen en el carrito con su categoría y descripción resueltas.
4. Incluir un SKU inexistente y una cantidad inválida (ej. texto) en el Excel — el resumen de omitidos los lista con su fila y motivo, y el resto de los ítems válidos sí se cargó al carrito (el overlay no se cierra solo mientras haya omitidos).
5. Subir un Excel con el mismo SKU repetido dos veces — el carrito muestra una sola línea con la cantidad sumada.
6. Cargar un Excel con SKU de categorías distintas — el checkbox "Pedido mixto" se marca solo, igual que con la carga a2.
7. Totalizar el pedido con ítems cargados desde Excel — la validación de stock/categoría/condición existente se comporta igual que con ítems agregados a mano o desde a2.
8. Confirmar que la carga a2 (`btn-abrir-a2`, `mezclarItemsAlCarrito` renombrada) sigue funcionando exactamente igual que antes del rename.

- [ ] **Step 6: Commit**

```bash
git add templates/pedidos-crear.html
git commit -m "$(cat <<'EOF'
feat(pedidos): agrega carga masiva de pedido desde plantilla Excel

Boton "Cargar desde Excel" junto al de a2, mismo candado ignorado.
Overlay con descarga de plantilla, subida de archivo y resumen de
filas omitidas (SKU no encontrado, cantidad invalida, SKU vacio) sin
bloquear la carga de las filas validas. mezclarItemsA2 se renombra a
mezclarItemsAlCarrito, compartida ahora entre el flujo a2 y el de
Excel.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FmMX2cwMh94uT9DHXgE2bW
EOF
)"
```
