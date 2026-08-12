# Ficha completa de item al escanear — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Endpoint nuevo `GET /api/productos/<codigo>/ficha/` que, bajo demanda (botón "ojito" en la app móvil), devuelve la ficha completa de un producto escaneado: datos básicos + ubicaciones internas (ya existentes), existencia del almacén principal en a2, y los pedidos donde ese código está pendiente, parcial o en backorder.

**Architecture:** Una vista DRF nueva en `PedidosAlmacen/api_views.py` que reutiliza `PedidosDBISAM.buscar_producto_por_campo` y el bloque de `ubicaciones_internas` ya escritos para `api_buscar_producto`, agrega `PedidosDBISAM.consultar_stock(codigo, deposito=DEPOSITO_ALMACEN)` (método ya existente, sin cambios), y una query nueva a Postgres sobre `PedidoItem` para armar tres listas agrupadas por estado. El endpoint existente `api_buscar_producto` no se toca — es una ruta nueva e independiente para no penalizar el flujo de escaneo rápido.

**Tech Stack:** Django REST Framework (`@api_view`, `Response`), `pyodbc.DatabaseError` para errores de DBISAM, `django.test.TestCase` + `rest_framework.test.APIClient` para tests.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-08-11-ficha-item-escaneo-design.md`.
- Ruta exacta: `GET /api/productos/<codigo>/ficha/`, nombre de URL `api-producto-ficha`.
- Nombre de la vista: `api_ficha_producto` (sigue el patrón `api_<verbo>_<recurso>` del archivo).
- NO modificar `api_buscar_producto` ni su ruta `productos/<str:codigo>/` existente.
- `existencia_almacen` se consulta SOLO para `DEPOSITO_ALMACEN` (constante ya existente en `PedidosAlmacen/dbisam.py`, importada en `api_views.py`) — no desglosar por depósito.
- Pedidos relacionados: alcance TODOS los depósitos del sistema; excluir explícitamente `pedido__estado__in=['ANULADO', 'CERRADO']` (anular un pedido no cambia `PedidoItem.estado`, así que sin este filtro aparecerían pedidos ya anulados).
- Tests se corren desde la raíz del repo con: `.\venv\Scripts\python.exe manage.py test ... --settings=Programarprecios.test_settings`.
- Mensajes de commit en español, estilo convencional del repo (`feat(pedidos): ...`), con la línea `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.

---

### Task 1: Endpoint base — ficha del producto + existencia del almacén principal

**Files:**
- Modify: `PedidosAlmacen/api_views.py` (nueva función al final del archivo, después de `api_buscar_producto` en la línea 384)
- Modify: `PedidosAlmacen/api_urls.py` (nueva ruta, línea 13)
- Test: `PedidosAlmacen/tests.py` (clase nueva al final del archivo, línea 3885)

**Interfaces:**
- Consumes: `PedidosDBISAM.buscar_producto_por_campo(codigo: str, campo: str) -> tuple | None` (existe, `dbisam.py:48`); `PedidosDBISAM.consultar_stock(codigo, deposito=None) -> int` (existe, `dbisam.py:105`); `DEPOSITO_ALMACEN` (constante `= 1`, ya importada en `api_views.py:13`); `_CAMPOS_VALIDOS` (ya definida en `api_views.py:18`).
- Produces: ruta `api-producto-ficha` → `/api/productos/<codigo>/ficha/`; vista `api_ficha_producto(request, codigo)` que devuelve `Response` con claves `codigo, descripcion, referencia, puesto, ref_proveedor, ubicaciones_internas, existencia_almacen`. Esta vista es la que la Task 2 extiende in-place agregando las claves de pedidos relacionados — no cambia de nombre ni de firma.

- [ ] **Step 1: Escribir los tests que fallan**

Al final de `PedidosAlmacen/tests.py` agregar:

```python
class ApiFichaProductoTest(TestCase):
    """GET /api/productos/<codigo>/ficha/ — ficha completa bajo demanda (botón ojito)."""

    def setUp(self):
        from rest_framework.test import APIClient
        from users.models import User
        self.user = User.objects.create_user(username='ficha_user', password='x')
        self.api = APIClient()
        self.api.force_authenticate(user=self.user)

    @patch('PedidosAlmacen.api_views.PedidosDBISAM')
    def test_devuelve_ficha_y_existencia_del_almacen_principal(self, mock_db):
        from .dbisam import DEPOSITO_ALMACEN
        mock_db.return_value.buscar_producto_por_campo.return_value = (
            'SKU1', 'Producto Uno', 'REF1', 'P1', 'PROV1',
        )
        mock_db.return_value.consultar_stock.return_value = 42

        resp = self.api.get('/api/productos/SKU1/ficha/', HTTP_X_CAMPO='sku')

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['codigo'], 'SKU1')
        self.assertEqual(resp.data['descripcion'], 'Producto Uno')
        self.assertEqual(resp.data['ref_proveedor'], 'PROV1')
        self.assertEqual(resp.data['ubicaciones_internas'], [])
        self.assertEqual(resp.data['existencia_almacen'], 42)
        mock_db.return_value.consultar_stock.assert_called_once_with(
            'SKU1', deposito=DEPOSITO_ALMACEN,
        )

    def test_sin_header_x_campo_devuelve_400(self):
        resp = self.api.get('/api/productos/SKU1/ficha/')
        self.assertEqual(resp.status_code, 400)

    def test_header_invalido_devuelve_400(self):
        resp = self.api.get('/api/productos/SKU1/ficha/', HTTP_X_CAMPO='otro')
        self.assertEqual(resp.status_code, 400)

    @patch('PedidosAlmacen.api_views.PedidosDBISAM')
    def test_producto_no_encontrado_devuelve_404(self, mock_db):
        mock_db.return_value.buscar_producto_por_campo.return_value = None
        resp = self.api.get('/api/productos/NOEXISTE/ficha/', HTTP_X_CAMPO='sku')
        self.assertEqual(resp.status_code, 404)

    @patch('PedidosAlmacen.api_views.PedidosDBISAM')
    def test_error_dbisam_al_buscar_producto_devuelve_502(self, mock_db):
        import pyodbc
        mock_db.return_value.buscar_producto_por_campo.side_effect = pyodbc.DatabaseError('odbc down')
        resp = self.api.get('/api/productos/SKU1/ficha/', HTTP_X_CAMPO='sku')
        self.assertEqual(resp.status_code, 502)

    @patch('PedidosAlmacen.api_views.PedidosDBISAM')
    def test_error_dbisam_al_consultar_stock_devuelve_502(self, mock_db):
        import pyodbc
        mock_db.return_value.buscar_producto_por_campo.return_value = (
            'SKU1', 'Producto Uno', 'REF1', 'P1', 'PROV1',
        )
        mock_db.return_value.consultar_stock.side_effect = pyodbc.DatabaseError('odbc down')
        resp = self.api.get('/api/productos/SKU1/ficha/', HTTP_X_CAMPO='sku')
        self.assertEqual(resp.status_code, 502)
```

Notas para el implementador:
- `mock_db` reemplaza la clase `PedidosDBISAM` completa dentro de `PedidosAlmacen.api_views`, por eso `mock_db.return_value.<metodo>` configura el mock de la instancia (`PedidosDBISAM()`).
- No hace falta crear `ProductoUbicacion` en este test — sin ninguno creado, `ubicaciones_internas` debe ser `[]` (mismo comportamiento que `api_buscar_producto`, ya cubierto por `BuscarProductoUbicacionesInternasTest`).

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `.\venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ApiFichaProductoTest --settings=Programarprecios.test_settings`
Expected: FAIL — `404` en todos (la ruta `/api/productos/SKU1/ficha/` no existe todavía).

- [ ] **Step 3: Agregar la ruta**

En `PedidosAlmacen/api_urls.py`, después de la línea 13 (`path('productos/<str:codigo>/', ...)`):

```python
    path('productos/<str:codigo>/ficha/', api_views.api_ficha_producto, name='api-producto-ficha'),
```

- [ ] **Step 4: Agregar la vista**

En `PedidosAlmacen/api_views.py`, al final del archivo (después de la línea 384, que cierra `api_buscar_producto`):

```python


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def api_ficha_producto(request, codigo):
    """GET /api/productos/<codigo>/ficha/ — ficha completa bajo demanda (botón "ojito").

    A diferencia de api_buscar_producto (llamado en cada escaneo), este
    endpoint solo se llama cuando el usuario pide ver el detalle: agrega
    existencia del almacén principal y pedidos relacionados en otros pedidos.
    Requiere header X-Campo: sku | codBarra | refProveedor.
    """
    campo = request.headers.get('X-Campo')
    if not campo:
        return Response({'error': 'Header X-Campo requerido'}, status=400)
    if campo not in _CAMPOS_VALIDOS:
        return Response(
            {'error': 'X-Campo inválido. Use: sku, codBarra, refProveedor'},
            status=400,
        )

    try:
        row = PedidosDBISAM().buscar_producto_por_campo(codigo, campo)
    except pyodbc.DatabaseError as e:
        return Response({'error': f'Error consultando DBISAM: {e}'}, status=502)

    if row is None:
        return Response({'error': 'Producto no encontrado'}, status=404)

    codigo_prod, descripcion, referencia, puesto, ref_proveedor = row

    from ubicaciones.models import ProductoUbicacion
    ubicaciones_internas = []
    try:
        qs = (
            ProductoUbicacion.objects
            .filter(
                codigo_producto=codigo_prod,
                nivel__activo=True,
                nivel__ubicacion__activo=True,
                nivel__ubicacion__cuerpo__activo=True,
                nivel__ubicacion__cuerpo__rack__activo=True,
            )
            .select_related('nivel__ubicacion__cuerpo__rack__galpon')
        )
        ubicaciones_internas = [
            {
                'codigo': pu.nivel.codigo_completo,
                'tipo_nivel': pu.nivel.tipo,
                'tipo_nivel_display': pu.nivel.get_tipo_display(),
            }
            for pu in qs
        ]
    except Exception:
        logger.exception("Error al consultar ubicaciones internas en api_ficha_producto")

    try:
        existencia_almacen = PedidosDBISAM().consultar_stock(codigo_prod, deposito=DEPOSITO_ALMACEN)
    except pyodbc.DatabaseError as e:
        return Response({'error': f'Error consultando DBISAM: {e}'}, status=502)

    return Response({
        'codigo': codigo_prod,
        'descripcion': descripcion,
        'referencia': referencia,
        'puesto': puesto,
        'ref_proveedor': ref_proveedor,
        'ubicaciones_internas': ubicaciones_internas,
        'existencia_almacen': existencia_almacen,
    })
```

- [ ] **Step 5: Correr los tests de la clase y verificar que pasan**

Run: `.\venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ApiFichaProductoTest --settings=Programarprecios.test_settings`
Expected: PASS — `Ran 6 tests ... OK`.

- [ ] **Step 6: Commit**

```powershell
git add PedidosAlmacen/api_views.py PedidosAlmacen/api_urls.py PedidosAlmacen/tests.py
git commit -m @'
feat(pedidos): endpoint de ficha completa de producto para escaneo

GET /api/productos/<codigo>/ficha/ — bajo demanda (botón ojito en la
app móvil), devuelve ficha + ubicaciones internas + existencia del
almacén principal en a2. No toca api_buscar_producto (flujo de
escaneo rápido).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
'@
```

---

### Task 2: Pedidos relacionados (pendientes / parciales / backorder)

**Files:**
- Modify: `PedidosAlmacen/api_views.py` (extender `api_ficha_producto`, agregada en Task 1)
- Test: `PedidosAlmacen/tests.py` (clase nueva al final del archivo)

**Interfaces:**
- Consumes: `api_ficha_producto` de la Task 1 (misma función, mismo nombre — se extiende in-place); modelos `Pedido` y `PedidoItem` (ya importados en `api_views.py:8`), campos `PedidoItem.codigo/estado/cantidad_solicitada/cantidad_despachada/cantidad_back_order` y `Pedido.numero_pedido/deposito/estado/condicion/fecha_creacion` (todos ya existentes, sin migraciones).
- Produces: la `Response` de `api_ficha_producto` gana tres claves nuevas: `pedidos_pendientes`, `pedidos_parciales`, `pedidos_backorder` (listas de dicts). No hay otros consumidores dentro del repo — es el final de la cadena.

- [ ] **Step 1: Escribir los tests que fallan**

Al final de `PedidosAlmacen/tests.py` agregar:

```python
class ApiFichaProductoPedidosRelacionadosTest(TestCase):
    """La ficha agrupa PedidoItem del mismo código en 3 listas por estado,
    excluyendo pedidos ANULADO/CERRADO aunque el item no haya cambiado de estado."""

    def setUp(self):
        from rest_framework.test import APIClient
        from users.models import User
        from .models import Pedido, PedidoItem

        self.user = User.objects.create_user(username='ficha_rel_user', password='x')
        self.solicitante = User.objects.create_user(username='ficha_rel_sol', password='x')
        self.api = APIClient()
        self.api.force_authenticate(user=self.user)

        self.pedido_pendiente = Pedido.objects.create(
            solicitante=self.solicitante, estado='ASIGNADO',
            deposito='CENTRO CERAMICO', condicion='URGENTE',
        )
        PedidoItem.objects.create(
            pedido=self.pedido_pendiente, codigo='SKU1', descripcion='Producto Uno',
            cantidad_solicitada=5, estado='PENDIENTE',
        )

        self.pedido_parcial = Pedido.objects.create(
            solicitante=self.solicitante, estado='PARCIAL', deposito='ALMACEN NORTE',
        )
        PedidoItem.objects.create(
            pedido=self.pedido_parcial, codigo='SKU1', descripcion='Producto Uno',
            cantidad_solicitada=10, cantidad_despachada=6, cantidad_back_order=4,
            estado='PARCIAL',
        )

        self.pedido_backorder = Pedido.objects.create(
            solicitante=self.solicitante, estado='PARCIAL', deposito='TIENDA SUR',
        )
        PedidoItem.objects.create(
            pedido=self.pedido_backorder, codigo='SKU1', descripcion='Producto Uno',
            cantidad_solicitada=8, cantidad_back_order=3, estado='BACK_ORDER',
        )

        # Pedido anulado: anular_pedido() NO cambia PedidoItem.estado, así que
        # el item queda PENDIENTE aunque el pedido ya no esté vigente.
        self.pedido_anulado = Pedido.objects.create(
            solicitante=self.solicitante, estado='ANULADO', deposito='TIENDA SUR',
        )
        PedidoItem.objects.create(
            pedido=self.pedido_anulado, codigo='SKU1', descripcion='Producto Uno',
            cantidad_solicitada=2, estado='PENDIENTE',
        )

        # Pedido cerrado con un item que quedó PARCIAL (caso borde: cerrar_pedido
        # marca CERRADO a los items en la mayoría de los casos, pero el filtro
        # por pedido.estado debe excluirlo igual si no fue así).
        self.pedido_cerrado = Pedido.objects.create(
            solicitante=self.solicitante, estado='CERRADO', deposito='TIENDA SUR',
        )
        PedidoItem.objects.create(
            pedido=self.pedido_cerrado, codigo='SKU1', descripcion='Producto Uno',
            cantidad_solicitada=1, cantidad_back_order=1, estado='PARCIAL',
        )

    def _get_ficha(self, codigo='SKU1'):
        with patch('PedidosAlmacen.api_views.PedidosDBISAM') as mock_db:
            mock_db.return_value.buscar_producto_por_campo.return_value = (
                codigo, 'Producto Uno', 'REF1', 'P1', 'PROV1',
            )
            mock_db.return_value.consultar_stock.return_value = 20
            resp = self.api.get(f'/api/productos/{codigo}/ficha/', HTTP_X_CAMPO='sku')
        return resp

    def test_item_pendiente_aparece_en_pendientes(self):
        resp = self._get_ficha()
        self.assertEqual(resp.status_code, 200)
        numeros = [p['numero_pedido'] for p in resp.data['pedidos_pendientes']]
        self.assertEqual(numeros, [self.pedido_pendiente.numero_pedido])
        fila = resp.data['pedidos_pendientes'][0]
        self.assertEqual(fila['deposito'], 'CENTRO CERAMICO')
        self.assertEqual(fila['estado_pedido'], 'ASIGNADO')
        self.assertEqual(fila['condicion'], 'URGENTE')
        self.assertEqual(fila['cantidad_solicitada'], 5)

    def test_item_parcial_aparece_en_parciales_con_cantidades(self):
        resp = self._get_ficha()
        numeros = [p['numero_pedido'] for p in resp.data['pedidos_parciales']]
        self.assertEqual(numeros, [self.pedido_parcial.numero_pedido])
        fila = resp.data['pedidos_parciales'][0]
        self.assertEqual(fila['cantidad_despachada'], 6)
        self.assertEqual(fila['cantidad_back_order'], 4)

    def test_item_backorder_aparece_en_backorder(self):
        resp = self._get_ficha()
        numeros = [p['numero_pedido'] for p in resp.data['pedidos_backorder']]
        self.assertEqual(numeros, [self.pedido_backorder.numero_pedido])
        self.assertEqual(resp.data['pedidos_backorder'][0]['cantidad_back_order'], 3)

    def test_pedido_anulado_no_aparece(self):
        resp = self._get_ficha()
        todos = (
            resp.data['pedidos_pendientes']
            + resp.data['pedidos_parciales']
            + resp.data['pedidos_backorder']
        )
        numeros = [p['numero_pedido'] for p in todos]
        self.assertNotIn(self.pedido_anulado.numero_pedido, numeros)

    def test_pedido_cerrado_no_aparece(self):
        resp = self._get_ficha()
        todos = (
            resp.data['pedidos_pendientes']
            + resp.data['pedidos_parciales']
            + resp.data['pedidos_backorder']
        )
        numeros = [p['numero_pedido'] for p in todos]
        self.assertNotIn(self.pedido_cerrado.numero_pedido, numeros)

    def test_incluye_pedidos_de_todos_los_depositos(self):
        from .models import Pedido, PedidoItem
        otro_pedido = Pedido.objects.create(
            solicitante=self.solicitante, estado='ASIGNADO', deposito='DEPOSITO OTRO',
        )
        PedidoItem.objects.create(
            pedido=otro_pedido, codigo='SKU1', descripcion='Producto Uno',
            cantidad_solicitada=3, estado='PENDIENTE',
        )
        resp = self._get_ficha()
        numeros = {p['numero_pedido'] for p in resp.data['pedidos_pendientes']}
        self.assertEqual(
            numeros,
            {self.pedido_pendiente.numero_pedido, otro_pedido.numero_pedido},
        )

    def test_producto_sin_pedidos_relacionados_devuelve_listas_vacias(self):
        resp = self._get_ficha(codigo='SKU_SIN_PEDIDOS')
        self.assertEqual(resp.data['pedidos_pendientes'], [])
        self.assertEqual(resp.data['pedidos_parciales'], [])
        self.assertEqual(resp.data['pedidos_backorder'], [])
```

Notas para el implementador:
- `_get_ficha` mockea DBISAM en cada llamada para no repetir el `with patch(...)` en cada test.
- El caso `test_pedido_cerrado_no_aparece` es el que valida la "higiene" del filtro: aunque el item quedó `PARCIAL` (no `CERRADO`), el pedido padre está `CERRADO` y debe excluirse por el `exclude(pedido__estado__in=...)`, no por el estado del item.

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `.\venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ApiFichaProductoPedidosRelacionadosTest --settings=Programarprecios.test_settings`
Expected: FAIL — `KeyError: 'pedidos_pendientes'` (la respuesta de la Task 1 todavía no incluye esas claves).

- [ ] **Step 3: Extender la vista con la query de pedidos relacionados**

En `PedidosAlmacen/api_views.py`, dentro de `api_ficha_producto` (agregada en Task 1), reemplazar el bloque final:

```python
    try:
        existencia_almacen = PedidosDBISAM().consultar_stock(codigo_prod, deposito=DEPOSITO_ALMACEN)
    except pyodbc.DatabaseError as e:
        return Response({'error': f'Error consultando DBISAM: {e}'}, status=502)

    return Response({
        'codigo': codigo_prod,
        'descripcion': descripcion,
        'referencia': referencia,
        'puesto': puesto,
        'ref_proveedor': ref_proveedor,
        'ubicaciones_internas': ubicaciones_internas,
        'existencia_almacen': existencia_almacen,
    })
```

por:

```python
    try:
        existencia_almacen = PedidosDBISAM().consultar_stock(codigo_prod, deposito=DEPOSITO_ALMACEN)
    except pyodbc.DatabaseError as e:
        return Response({'error': f'Error consultando DBISAM: {e}'}, status=502)

    items_relacionados = (
        PedidoItem.objects
        .filter(codigo=codigo_prod, estado__in=['PENDIENTE', 'PARCIAL', 'BACK_ORDER'])
        .exclude(pedido__estado__in=['ANULADO', 'CERRADO'])
        .select_related('pedido')
        .order_by('pedido__fecha_creacion')
    )

    pedidos_pendientes, pedidos_parciales, pedidos_backorder = [], [], []
    for item in items_relacionados:
        p = item.pedido
        fila = {
            'numero_pedido': p.numero_pedido,
            'deposito': p.deposito,
            'estado_pedido': p.estado,
            'condicion': p.condicion,
            'cantidad_solicitada': item.cantidad_solicitada,
            'fecha_creacion': p.fecha_creacion,
        }
        if item.estado == 'PENDIENTE':
            pedidos_pendientes.append(fila)
        elif item.estado == 'PARCIAL':
            pedidos_parciales.append({
                **fila,
                'cantidad_despachada': item.cantidad_despachada,
                'cantidad_back_order': item.cantidad_back_order,
            })
        else:  # BACK_ORDER
            pedidos_backorder.append({
                **fila,
                'cantidad_back_order': item.cantidad_back_order,
            })

    return Response({
        'codigo': codigo_prod,
        'descripcion': descripcion,
        'referencia': referencia,
        'puesto': puesto,
        'ref_proveedor': ref_proveedor,
        'ubicaciones_internas': ubicaciones_internas,
        'existencia_almacen': existencia_almacen,
        'pedidos_pendientes': pedidos_pendientes,
        'pedidos_parciales': pedidos_parciales,
        'pedidos_backorder': pedidos_backorder,
    })
```

- [ ] **Step 4: Correr los tests de la clase y verificar que pasan**

Run: `.\venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ApiFichaProductoPedidosRelacionadosTest --settings=Programarprecios.test_settings`
Expected: PASS — `Ran 7 tests ... OK`.

- [ ] **Step 5: Correr la suite completa de la app (regresión)**

Run: `.\venv\Scripts\python.exe manage.py test PedidosAlmacen --settings=Programarprecios.test_settings`
Expected: PASS (256 tests existentes + 13 nuevos = 269, OK).

- [ ] **Step 6: Commit**

```powershell
git add PedidosAlmacen/api_views.py PedidosAlmacen/tests.py
git commit -m @'
feat(pedidos): agrega pedidos relacionados a la ficha de producto

api_ficha_producto ahora agrupa PedidoItem del mismo código en
pedidos_pendientes/parciales/backorder, en todos los depósitos,
excluyendo pedidos ANULADO/CERRADO (anular no cambia el estado del
item, así que el filtro va por pedido.estado, no por item.estado).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
'@
```
