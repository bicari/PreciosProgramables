# Carga de Documentos a2 en Pedidos de Almacén Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir, desde `pedidos-crear.html`, buscar presupuestos/pedidos/notas de entrega abiertos en a2 por número de documento o cliente, seleccionar varios (de tipos y categorías distintas) y cargar sus ítems al carrito del pedido en curso, sin tocar la validación existente al totalizar.

**Architecture:** Dos métodos nuevos en `PedidosDBISAM` (búsqueda de cabeceras + resolución de ítems por IDs), dos endpoints nuevos en `PedidosAlmacen/views.py` (uno htmx GET para buscar, uno JSON POST para cargar), un overlay nuevo en `pedidos-crear.html` que reutiliza el array `itemsPedido` y las funciones `renderItems`/`sincronizarMixto`/`seleccionarCategoria` ya existentes.

**Tech Stack:** Django, pyodbc/DBISAM, htmx, Bootstrap 5, JavaScript vanilla.

**Spec:** `docs/superpowers/specs/2026-08-26-carga-documentos-a2-design.md`

## Global Constraints

- DBISAM no soporta placeholders `?` — toda entrada del usuario que llegue a un query se escapa manualmente (`.replace("'", "''")`) antes de interpolar, igual que el resto de `PedidosAlmacen/dbisam.py`.
- Tipos de documento soportados: `9` (Presupuesto), `10` (Pedido), `13` (Nota de Entrega). Cualquier otro valor se descarta silenciosamente en el backend.
- Estados "abiertos" (los únicos que se muestran/cargan): cabecera `FTI_STATUS IN (1, 4)`, línea `FDI_STATUS IN (1, 4)`.
- `obtener_items_documentos` NUNCA confía en los `operacion_ids` recibidos del cliente: siempre revalida `FTI_TIPO` y ambos estados en el propio query.
- Los ítems cargados desde a2 no llevan marca de origen — mismos campos (`codigo`, `descripcion`, `referencia`, `puesto`, `ref_proveedor`, `cantidad`, `categoria`, `categoria_nombre`) que un ítem agregado a mano vía `agregarItem()`.
- Permisos: mismos que `crear_pedido` hoy (`login_required` + `user_passes_test(is_pedidos_tienda, ...)`), sin restricción nueva.
- Tests con: `venv\Scripts\python.exe manage.py test PedidosAlmacen --settings=Programarprecios.test_settings`

---

## Task 1: `PedidosDBISAM.buscar_documentos_venta`

**Files:**
- Modify: `PedidosAlmacen/dbisam.py` (agregar constantes cerca de la línea 14, y el método al final de la clase, después de `buscar_en_categoria` — línea 566)
- Test: `PedidosAlmacen/tests.py` (agregar clase `BuscarDocumentosVentaTest` cerca de `BuscarEnCategoriaFiltroTest`, línea 75)

**Interfaces:**
- Produces: `PedidosDBISAM.buscar_documentos_venta(tipos: list[int], documento: str = '', cliente: str = '', limit: int = 50) -> list[dict]`. Cada dict: `{'operacion_id': int, 'tipo': int, 'documento': str, 'fecha': date|None, 'cliente': str}`. Devuelve `[]` sin consultar DBISAM si `tipos` queda vacío tras filtrar valores no permitidos, o si tanto `documento` como `cliente` están vacíos.
- Produces (módulo): constantes `TIPOS_DOCUMENTO_VENTA = {9, 10, 13}` y `ESTADOS_ABIERTOS = (1, 4)` en `PedidosAlmacen/dbisam.py`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar en `PedidosAlmacen/tests.py`, después de la clase `BuscarEnCategoriaFiltroTest` (que termina alrededor de la línea 95, antes de la siguiente clase):

```python
class BuscarDocumentosVentaTest(TestCase):
    def _capturar_sql(self, tipos, documento='', cliente=''):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = (mock_connect.return_value.__enter__.return_value
                      .cursor.return_value.__enter__.return_value)
            cursor.execute.return_value.fetchmany.return_value = []
            db.buscar_documentos_venta(tipos, documento=documento, cliente=cliente)
            return cursor.execute.call_args[0][0]

    def test_filtra_por_tipos_y_estados_abiertos(self):
        sql = self._capturar_sql([9, 10], documento='1234')
        self.assertIn('FTI_TIPO IN (9,10)', sql)
        self.assertIn('FTI_STATUS IN (1,4)', sql)

    def test_busca_por_documento_con_like(self):
        sql = self._capturar_sql([9], documento='1234')
        self.assertIn("FTI_DOCUMENTO LIKE '%1234%'", sql)

    def test_busca_por_cliente_con_like_case_insensitive(self):
        sql = self._capturar_sql([9], cliente='Perez')
        self.assertIn("UPPER(FTI_PERSONACONTACTO) LIKE UPPER('%Perez%')", sql)

    def test_escapa_comillas_simples_en_cliente(self):
        sql = self._capturar_sql([9], cliente="O'Brien")
        self.assertIn("O''Brien", sql)

    def test_sin_tipos_no_ejecuta_query(self):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            resultado = db.buscar_documentos_venta([], documento='1234')
        mock_connect.assert_not_called()
        self.assertEqual(resultado, [])

    def test_sin_documento_ni_cliente_no_ejecuta_query(self):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            resultado = db.buscar_documentos_venta([9])
        mock_connect.assert_not_called()
        self.assertEqual(resultado, [])

    def test_ignora_tipos_no_permitidos(self):
        sql = self._capturar_sql([9, 99], documento='1234')
        self.assertIn('FTI_TIPO IN (9)', sql)
        self.assertNotIn('99', sql)

    def test_mapea_filas_a_dicts(self):
        from datetime import date
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = (mock_connect.return_value.__enter__.return_value
                      .cursor.return_value.__enter__.return_value)
            cursor.execute.return_value.fetchmany.return_value = [
                (100, 9, '00001234', date(2026, 8, 20), 'Cliente Uno'),
            ]
            resultado = db.buscar_documentos_venta([9], documento='1234')
        self.assertEqual(resultado, [{
            'operacion_id': 100, 'tipo': 9, 'documento': '00001234',
            'fecha': date(2026, 8, 20), 'cliente': 'Cliente Uno',
        }])
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.BuscarDocumentosVentaTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL (`AttributeError: 'PedidosDBISAM' object has no attribute 'buscar_documentos_venta'`)

- [ ] **Step 3: Implementar**

En `PedidosAlmacen/dbisam.py`, agregar cerca de la línea 14 (después de `CLASIFICACION_RECEPCION_TIENDA`):

```python
TIPOS_DOCUMENTO_VENTA = {9, 10, 13}  # Presupuesto, Pedido, Nota de Entrega
ESTADOS_ABIERTOS = (1, 4)            # Procesado, Transito
```

Al final de la clase `PedidosDBISAM`, después de `buscar_en_categoria` (línea 566):

```python
    def buscar_documentos_venta(self, tipos: list[int], documento: str = '', cliente: str = '', limit: int = 50) -> list[dict]:
        """Busca cabeceras de presupuestos/pedidos/notas de entrega abiertos en a2.

        Args:
            tipos: Subconjunto de TIPOS_DOCUMENTO_VENTA a incluir; valores no
                permitidos se descartan.
            documento: Coincidencia parcial contra FTI_DOCUMENTO.
            cliente: Coincidencia parcial (case-insensitive) contra FTI_PERSONACONTACTO.
            limit: Máximo de filas a traer.

        Returns:
            Lista de dicts: operacion_id, tipo, documento, fecha, cliente.
            Lista vacía si no hay tipos válidos o si documento/cliente vienen
            ambos vacíos (no se ejecuta ningún query en ese caso).
        """
        tipos_validos = sorted({t for t in tipos if t in TIPOS_DOCUMENTO_VENTA})
        documento = (documento or '').strip()
        cliente = (cliente or '').strip()
        if not tipos_validos or (not documento and not cliente):
            return []

        tipos_str = ','.join(str(t) for t in tipos_validos)
        estados_str = ','.join(str(e) for e in ESTADOS_ABIERTOS)

        condiciones = []
        if documento:
            doc_esc = documento[:20].replace("'", "''")
            condiciones.append(f"FTI_DOCUMENTO LIKE '%{doc_esc}%'")
        if cliente:
            cli_esc = cliente[:100].replace("'", "''")
            condiciones.append(f"UPPER(FTI_PERSONACONTACTO) LIKE UPPER('%{cli_esc}%')")
        filtro_busqueda = ' OR '.join(condiciones)

        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute(f"""SELECT
                                            FTI_AUTOINCREMENT,
                                            FTI_TIPO,
                                            FTI_DOCUMENTO,
                                            FTI_FECHAEMISION,
                                            FTI_PERSONACONTACTO
                                        FROM SOPERACIONINV
                                        WHERE FTI_TIPO IN ({tipos_str})
                                        AND FTI_STATUS IN ({estados_str})
                                        AND ({filtro_busqueda})
                                        ORDER BY FTI_FECHAEMISION DESC""").fetchmany(limit)
                    return [
                        {
                            'operacion_id': int(r[0]),
                            'tipo': int(r[1]),
                            'documento': _clean(r[2]),
                            'fecha': r[3],
                            'cliente': _clean(r[4]),
                        }
                        for r in rows
                    ]
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.BuscarDocumentosVentaTest --settings=Programarprecios.test_settings -v 2`
Expected: OK (8 tests)

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/dbisam.py PedidosAlmacen/tests.py
git commit -m "$(cat <<'EOF'
feat(pedidos): agrega busqueda de cabeceras de documentos de venta a2

Nuevo metodo PedidosDBISAM.buscar_documentos_venta para el modal de
carga de presupuestos/pedidos/notas de entrega abiertos en a2.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FmMX2cwMh94uT9DHXgE2bW
EOF
)"
```

---

## Task 2: `PedidosDBISAM.obtener_items_documentos`

**Files:**
- Modify: `PedidosAlmacen/dbisam.py` (agregar método al final de la clase, después del de Task 1)
- Test: `PedidosAlmacen/tests.py` (agregar clase `ObtenerItemsDocumentosTest`)

**Interfaces:**
- Consumes: `TIPOS_DOCUMENTO_VENTA`, `ESTADOS_ABIERTOS` (Task 1).
- Produces: `PedidosDBISAM.obtener_items_documentos(operacion_ids: list[int]) -> list[dict]`. Cada dict: `{'codigo': str, 'cantidad': int|float, 'descripcion': str, 'puesto': str, 'referencia': str, 'ref_proveedor': str, 'categoria': str}`. Devuelve `[]` sin consultar si no hay ids numéricos válidos.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar en `PedidosAlmacen/tests.py`, justo después de `BuscarDocumentosVentaTest`:

```python
class ObtenerItemsDocumentosTest(TestCase):
    def _capturar_sql(self, ids):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = (mock_connect.return_value.__enter__.return_value
                      .cursor.return_value.__enter__.return_value)
            cursor.execute.return_value.fetchall.return_value = []
            db.obtener_items_documentos(ids)
            return cursor.execute.call_args[0][0]

    def test_revalida_tipo_y_estado_siempre(self):
        sql = self._capturar_sql([100, 200])
        self.assertIn('FTI_AUTOINCREMENT IN (100,200)', sql)
        self.assertIn('FTI_TIPO IN (9,10,13)', sql)
        self.assertIn('FTI_STATUS IN (1,4)', sql)
        self.assertIn('FDI_STATUS IN (1,4)', sql)

    def test_join_correcto(self):
        sql = self._capturar_sql([100])
        self.assertIn('INNER JOIN SDETALLEVENTA ON FTI_AUTOINCREMENT = FDI_OPERACION_AUTOINCREMENT', sql)
        self.assertIn('INNER JOIN SINVENTARIO ON FDI_CODIGO = FI_CODIGO', sql)

    def test_sin_ids_no_ejecuta_query(self):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            resultado = db.obtener_items_documentos([])
        mock_connect.assert_not_called()
        self.assertEqual(resultado, [])

    def test_ignora_ids_no_numericos(self):
        sql = self._capturar_sql([100, 'abc', 200])
        self.assertIn('FTI_AUTOINCREMENT IN (100,200)', sql)

    def test_mapea_filas_a_dicts(self):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = (mock_connect.return_value.__enter__.return_value
                      .cursor.return_value.__enter__.return_value)
            cursor.execute.return_value.fetchall.return_value = [
                ('SKU1', 5, 'Producto Uno', 'P1', 'REF1', 'PROV1', 'FERRETERIA'),
            ]
            resultado = db.obtener_items_documentos([100])
        self.assertEqual(resultado, [{
            'codigo': 'SKU1', 'cantidad': 5, 'descripcion': 'Producto Uno',
            'puesto': 'P1', 'referencia': 'REF1', 'ref_proveedor': 'PROV1',
            'categoria': 'FERRETERIA',
        }])
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ObtenerItemsDocumentosTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL (`AttributeError: 'PedidosDBISAM' object has no attribute 'obtener_items_documentos'`)

- [ ] **Step 3: Implementar**

En `PedidosAlmacen/dbisam.py`, al final de la clase, después de `buscar_documentos_venta`:

```python
    def obtener_items_documentos(self, operacion_ids: list[int]) -> list[dict]:
        """Trae las líneas de los documentos de venta seleccionados.

        Revalida FTI_TIPO y ambos estados (cabecera y línea) sin importar
        qué operacion_ids se reciban, para no confiar en datos manipulados
        del cliente.

        Args:
            operacion_ids: FTI_AUTOINCREMENT de los documentos marcados.

        Returns:
            Lista de dicts: codigo, cantidad, descripcion, puesto,
            referencia, ref_proveedor, categoria (código de SINVENTARIO.FI_CATEGORIA).
        """
        ids_validos = []
        for oid in operacion_ids:
            try:
                ids_validos.append(int(oid))
            except (TypeError, ValueError):
                continue
        if not ids_validos:
            return []

        ids_str = ','.join(str(i) for i in ids_validos)
        tipos_str = ','.join(str(t) for t in sorted(TIPOS_DOCUMENTO_VENTA))
        estados_str = ','.join(str(e) for e in ESTADOS_ABIERTOS)

        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute(f"""SELECT
                                            FDI_CODIGO,
                                            FDI_CANTIDAD,
                                            FI_DESCRIPCION,
                                            FI_PUESTO,
                                            FI_REFERENCIA,
                                            ZZCAMPO_001,
                                            FI_CATEGORIA
                                        FROM SOPERACIONINV
                                        INNER JOIN SDETALLEVENTA ON FTI_AUTOINCREMENT = FDI_OPERACION_AUTOINCREMENT
                                        INNER JOIN SINVENTARIO ON FDI_CODIGO = FI_CODIGO
                                        WHERE FTI_AUTOINCREMENT IN ({ids_str})
                                        AND FTI_TIPO IN ({tipos_str})
                                        AND FTI_STATUS IN ({estados_str})
                                        AND FDI_STATUS IN ({estados_str})""").fetchall()
                    return [
                        {
                            'codigo': _clean(r[0]),
                            'cantidad': r[1] or 0,
                            'descripcion': _clean(r[2]),
                            'puesto': _clean(r[3]),
                            'referencia': _clean(r[4]),
                            'ref_proveedor': _clean(r[5]),
                            'categoria': _clean(r[6]),
                        }
                        for r in rows
                    ]
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ObtenerItemsDocumentosTest --settings=Programarprecios.test_settings -v 2`
Expected: OK (5 tests)

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/dbisam.py PedidosAlmacen/tests.py
git commit -m "$(cat <<'EOF'
feat(pedidos): agrega resolucion de items de documentos a2 seleccionados

Nuevo metodo PedidosDBISAM.obtener_items_documentos, revalida tipo y
estado en el propio query en vez de confiar en los IDs del cliente.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FmMX2cwMh94uT9DHXgE2bW
EOF
)"
```

---

## Task 3: Endpoint de búsqueda `buscar_documentos_a2`

**Files:**
- Modify: `PedidosAlmacen/views.py` (nueva constante `TIPOS_DOCUMENTO_A2` cerca de la línea 82, nueva vista al final del archivo)
- Modify: `PedidosAlmacen/urls.py` (nueva ruta después de la línea 15)
- Create: `templates/pedidos-buscar-documentos-a2.html`
- Test: `PedidosAlmacen/tests.py` (nueva clase `BuscarDocumentosA2ViewTest`)

**Interfaces:**
- Consumes: `PedidosDBISAM.buscar_documentos_venta` (Task 1), decorador `is_pedidos_tienda` (existente, `views.py:89`).
- Produces: vista `views.buscar_documentos_a2`, URL name `pedidos-buscar-documentos-a2` (`GET /pedidos/buscar-documentos-a2/`, params `tipos` (repetido), `documento`, `cliente`), template `templates/pedidos-buscar-documentos-a2.html`, constante `TIPOS_DOCUMENTO_A2: dict[int, dict]` con claves `label`, `icon`, `badge`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar en `PedidosAlmacen/tests.py`, al final del archivo:

```python
class BuscarDocumentosA2ViewTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        self.user = User.objects.create_user(username='tnd_a2', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.user.groups.add(g)
        self.client.force_login(self.user)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_devuelve_resultados_con_tipos_y_documento(self, mock_db):
        mock_db.return_value.buscar_documentos_venta.return_value = [
            {'operacion_id': 100, 'tipo': 9, 'documento': '00001234',
             'fecha': None, 'cliente': 'Cliente Uno'},
        ]
        resp = self.client.get('/pedidos/buscar-documentos-a2/', {
            'tipos': ['9'], 'documento': '1234',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '00001234')
        self.assertContains(resp, 'Cliente Uno')

    def test_sin_tipos_no_consulta_dbisam(self):
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            resp = self.client.get('/pedidos/buscar-documentos-a2/', {'documento': '1234'})
        self.assertEqual(resp.status_code, 200)
        mock_db.assert_not_called()

    def test_sin_documento_ni_cliente_no_consulta_dbisam(self):
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            resp = self.client.get('/pedidos/buscar-documentos-a2/', {'tipos': ['9']})
        self.assertEqual(resp.status_code, 200)
        mock_db.assert_not_called()

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_error_dbisam_muestra_mensaje_sin_romper(self, mock_db):
        mock_db.return_value.buscar_documentos_venta.side_effect = Exception('odbc down')
        resp = self.client.get('/pedidos/buscar-documentos-a2/', {
            'tipos': ['9'], 'documento': '1234',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No se pudo consultar a2')

    def test_usuario_sin_permiso_redirige(self):
        from users.models import User
        otro = User.objects.create_user(username='sin_permiso_a2', password='x')
        self.client.force_login(otro)
        resp = self.client.get('/pedidos/buscar-documentos-a2/', {'tipos': ['9'], 'documento': '1234'})
        self.assertEqual(resp.status_code, 302)
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.BuscarDocumentosA2ViewTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL (404, la URL no existe)

- [ ] **Step 3: Implementar**

En `PedidosAlmacen/views.py`, agregar cerca de la línea 82 (junto a `GROUP_TIENDA`, etc.):

```python
TIPOS_DOCUMENTO_A2 = {
    9: {'label': 'Presupuesto', 'icon': 'fa-file-invoice-dollar', 'badge': 'bg-info text-dark'},
    10: {'label': 'Pedido', 'icon': 'fa-file-invoice', 'badge': 'bg-primary'},
    13: {'label': 'Nota de Entrega', 'icon': 'fa-truck', 'badge': 'bg-success'},
}
```

Al final de `PedidosAlmacen/views.py`, agregar:

```python
@login_required(login_url='/login/')
@user_passes_test(is_pedidos_tienda, login_url='dashboard')
def buscar_documentos_a2(request):
    tipos_raw = request.GET.getlist('tipos')
    documento = request.GET.get('documento', '').strip()
    cliente = request.GET.get('cliente', '').strip()

    tipos = [int(t) for t in tipos_raw if t.isdigit()]

    if not tipos:
        return HttpResponse('<p class="text-warning p-2">Seleccione al menos un tipo de documento</p>')
    if not documento and not cliente:
        return HttpResponse('<p class="text-muted p-2">Ingrese un número de documento o un nombre de cliente</p>')

    try:
        documentos = PedidosDBISAM().buscar_documentos_venta(tipos, documento=documento, cliente=cliente)
    except Exception:
        return HttpResponse(
            '<p class="text-danger p-2">No se pudo consultar a2. Intenta de nuevo en unos segundos.</p>'
        )

    for doc in documentos:
        info = TIPOS_DOCUMENTO_A2.get(doc['tipo'], {})
        doc['tipo_label'] = info.get('label', 'Documento')
        doc['tipo_icon'] = info.get('icon', 'fa-file')
        doc['tipo_badge_class'] = info.get('badge', 'bg-secondary')

    return render(request, 'pedidos-buscar-documentos-a2.html', {'documentos': documentos})
```

Crear `templates/pedidos-buscar-documentos-a2.html`:

```html
{% if documentos %}
<div class="table-responsive">
<table class="table table-sm table-hover mb-0">
    <thead>
        <tr>
            <th></th>
            <th>Tipo</th>
            <th>Documento</th>
            <th>Fecha</th>
            <th>Cliente</th>
        </tr>
    </thead>
    <tbody>
        {% for doc in documentos %}
        <tr>
            <td>
                <input type="checkbox" class="form-check-input chk-doc-a2"
                    value="{{ doc.operacion_id }}"
                    aria-label="Seleccionar documento {{ doc.tipo_label }} {{ doc.documento }}">
            </td>
            <td>
                <span class="badge {{ doc.tipo_badge_class }}">
                    <i class="fas {{ doc.tipo_icon }}"></i> {{ doc.tipo_label }}
                </span>
            </td>
            <td>{{ doc.documento }}</td>
            <td>{{ doc.fecha|date:"d/m/Y"|default:"—" }}</td>
            <td>{{ doc.cliente|default:"—" }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>
{% else %}
<p class="text-muted p-2">No se encontraron documentos abiertos con esos datos. Prueba con otro número o nombre de cliente.</p>
{% endif %}
```

En `PedidosAlmacen/urls.py`, agregar después de la línea 15 (`pedidos-buscar-producto`):

```python
    path('pedidos/buscar-documentos-a2/', views.buscar_documentos_a2, name='pedidos-buscar-documentos-a2'),
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.BuscarDocumentosA2ViewTest --settings=Programarprecios.test_settings -v 2`
Expected: OK (5 tests)

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/urls.py PedidosAlmacen/tests.py templates/pedidos-buscar-documentos-a2.html
git commit -m "$(cat <<'EOF'
feat(pedidos): agrega endpoint de busqueda de documentos a2

GET /pedidos/buscar-documentos-a2/ devuelve el fragmento htmx con las
cabeceras de presupuestos/pedidos/notas de entrega abiertos que
calzan con el tipo, numero de documento o cliente buscado.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FmMX2cwMh94uT9DHXgE2bW
EOF
)"
```

---

## Task 4: Endpoint de carga `cargar_items_documentos_a2`

**Files:**
- Modify: `PedidosAlmacen/views.py` (nueva vista al final del archivo)
- Modify: `PedidosAlmacen/urls.py` (nueva ruta)
- Test: `PedidosAlmacen/tests.py` (nueva clase `CargarItemsDocumentosA2ViewTest`)

**Interfaces:**
- Consumes: `PedidosDBISAM.obtener_items_documentos` (Task 2), `PedidosDBISAM.obtener_categorias()` (existente, `dbisam.py:151-162`, devuelve filas indexables `row[0]`=código, `row[1]`=nombre).
- Produces: vista `views.cargar_items_documentos_a2`, URL name `pedidos-cargar-items-a2` (`POST /pedidos/cargar-items-a2/`, body `operacion_ids` repetido). Respuesta JSON `{"items": [{"codigo","descripcion","referencia","puesto","ref_proveedor","cantidad","categoria","categoria_nombre"}], "categorias_distintas": [str]}` (200) o `{"error": str}` (400/405/502).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar en `PedidosAlmacen/tests.py`, al final del archivo:

```python
class CargarItemsDocumentosA2ViewTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        self.user = User.objects.create_user(username='tnd_a2b', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.user.groups.add(g)
        self.client.force_login(self.user)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_suma_cantidades_de_codigos_repetidos(self, mock_db):
        mock_db.return_value.obtener_items_documentos.return_value = [
            {'codigo': 'SKU1', 'cantidad': 5, 'descripcion': 'Uno', 'puesto': 'P1',
             'referencia': 'R1', 'ref_proveedor': 'PR1', 'categoria': 'FERRETERIA'},
            {'codigo': 'SKU1', 'cantidad': 3, 'descripcion': 'Uno', 'puesto': 'P1',
             'referencia': 'R1', 'ref_proveedor': 'PR1', 'categoria': 'FERRETERIA'},
        ]
        mock_db.return_value.obtener_categorias.return_value = [('FERRETERIA', 'Ferreteria')]

        resp = self.client.post('/pedidos/cargar-items-a2/', {'operacion_ids': ['100', '200']})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['cantidad'], 8)
        self.assertEqual(data['items'][0]['categoria_nombre'], 'Ferreteria')
        self.assertEqual(data['categorias_distintas'], ['FERRETERIA'])

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_detecta_multiples_categorias(self, mock_db):
        mock_db.return_value.obtener_items_documentos.return_value = [
            {'codigo': 'SKU1', 'cantidad': 1, 'descripcion': 'Uno', 'puesto': '',
             'referencia': '', 'ref_proveedor': '', 'categoria': 'FERRETERIA'},
            {'codigo': 'SKU2', 'cantidad': 1, 'descripcion': 'Dos', 'puesto': '',
             'referencia': '', 'ref_proveedor': '', 'categoria': 'PLOMERIA'},
        ]
        mock_db.return_value.obtener_categorias.return_value = []

        resp = self.client.post('/pedidos/cargar-items-a2/', {'operacion_ids': ['100']})

        data = resp.json()
        self.assertEqual(sorted(data['categorias_distintas']), ['FERRETERIA', 'PLOMERIA'])

    def test_sin_operacion_ids_devuelve_400(self):
        resp = self.client.post('/pedidos/cargar-items-a2/', {})
        self.assertEqual(resp.status_code, 400)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_error_dbisam_devuelve_502(self, mock_db):
        mock_db.return_value.obtener_items_documentos.side_effect = Exception('odbc down')
        resp = self.client.post('/pedidos/cargar-items-a2/', {'operacion_ids': ['100']})
        self.assertEqual(resp.status_code, 502)

    def test_get_no_permitido(self):
        resp = self.client.get('/pedidos/cargar-items-a2/')
        self.assertEqual(resp.status_code, 405)
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CargarItemsDocumentosA2ViewTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL (404, la URL no existe)

- [ ] **Step 3: Implementar**

Al final de `PedidosAlmacen/views.py`, agregar:

```python
@login_required(login_url='/login/')
@user_passes_test(is_pedidos_tienda, login_url='dashboard')
def cargar_items_documentos_a2(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    operacion_ids_raw = request.POST.getlist('operacion_ids')
    operacion_ids = [int(i) for i in operacion_ids_raw if i.isdigit()]

    if not operacion_ids:
        return JsonResponse({'error': 'Debe seleccionar al menos un documento'}, status=400)

    try:
        items_raw = PedidosDBISAM().obtener_items_documentos(operacion_ids)
    except Exception:
        return JsonResponse(
            {'error': 'No se pudo consultar a2. Intenta de nuevo en unos segundos.'}, status=502
        )

    categorias_map = {}
    try:
        categorias_map = {str(c[0]): c[1] for c in PedidosDBISAM().obtener_categorias()}
    except Exception:
        pass

    items_por_codigo = {}
    for item in items_raw:
        codigo = item['codigo']
        if codigo in items_por_codigo:
            items_por_codigo[codigo]['cantidad'] += item['cantidad']
        else:
            items_por_codigo[codigo] = {
                'codigo': codigo,
                'descripcion': item['descripcion'],
                'referencia': item['referencia'],
                'puesto': item['puesto'],
                'ref_proveedor': item['ref_proveedor'],
                'cantidad': item['cantidad'],
                'categoria': item['categoria'],
                'categoria_nombre': categorias_map.get(item['categoria'], item['categoria']),
            }

    items = list(items_por_codigo.values())
    categorias_distintas = sorted({item['categoria'] for item in items if item['categoria']})

    return JsonResponse({'items': items, 'categorias_distintas': categorias_distintas})
```

En `PedidosAlmacen/urls.py`, agregar junto a la ruta de Task 3:

```python
    path('pedidos/cargar-items-a2/', views.cargar_items_documentos_a2, name='pedidos-cargar-items-a2'),
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CargarItemsDocumentosA2ViewTest --settings=Programarprecios.test_settings -v 2`
Expected: OK (5 tests)

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/urls.py PedidosAlmacen/tests.py
git commit -m "$(cat <<'EOF'
feat(pedidos): agrega endpoint de carga de items desde documentos a2

POST /pedidos/cargar-items-a2/ resuelve items de los documentos
marcados, suma cantidades de codigos repetidos entre documentos y
reporta las categorias distintas para que el frontend marque el
pedido como mixto automaticamente.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FmMX2cwMh94uT9DHXgE2bW
EOF
)"
```

---

## Task 5: Overlay "Cargar de a2" en `pedidos-crear.html`

**Files:**
- Modify: `templates/pedidos-crear.html`

**Interfaces:**
- Consumes: URL `pedidos-buscar-documentos-a2` (Task 3, htmx GET, fragmento con filas `.chk-doc-a2`), URL `/pedidos/cargar-items-a2/` (Task 4, fetch POST, JSON `{items, categorias_distintas}` o `{error}`), funciones/JS ya existentes en este mismo archivo: `itemsPedido` (array global), `renderItems()`, `sincronizarMixto()`, `seleccionarCategoria(select)`.
- Produces: nada consumido por otras tareas — es la última.

No hay test automatizado de JS en este proyecto (confirmado en el spec); este task termina con una verificación manual en navegador en vez de un test unitario.

- [ ] **Step 1: Agregar el botón "Cargar de a2"**

En `templates/pedidos-crear.html`, insertar justo antes del `<div class="card mb-3" id="card-busqueda" ...>` (línea 69):

```html
    <div class="d-flex justify-content-end mb-2">
        <button type="button" class="btn btn-outline-primary btn-sm" id="btn-abrir-a2">
            <i class="fas fa-file-import"></i> Cargar de a2
        </button>
    </div>

```

- [ ] **Step 2: Agregar el overlay**

Insertar después del cierre del `<div id="overlay-carga" ...>` (línea 237, antes de `<style>`):

```html

<!-- Overlay de carga de documentos a2 -->
<div id="overlay-a2" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.55); z-index:9997; align-items:center; justify-content:center;">
    <div style="background:#fff; border-radius:16px; padding:28px 32px; max-width:760px; width:95%; max-height:85vh; overflow-y:auto; box-shadow:0 8px 32px rgba(0,0,0,0.25);">
        <div class="d-flex justify-content-between align-items-center mb-3">
            <h5 class="mb-0"><i class="fas fa-file-import"></i> Cargar de a2</h5>
            <button type="button" class="btn-close" id="btn-cerrar-a2" aria-label="Cerrar"></button>
        </div>

        <div class="mb-3">
            <label class="form-label fw-bold d-block">Tipo de documento</label>
            <div class="d-flex flex-wrap gap-3">
                <div class="form-check">
                    <input class="form-check-input chk-tipo-a2" type="checkbox" value="9" id="tipo-a2-9" name="tipos">
                    <label class="form-check-label" for="tipo-a2-9"><i class="fas fa-file-invoice-dollar"></i> Presupuesto</label>
                </div>
                <div class="form-check">
                    <input class="form-check-input chk-tipo-a2" type="checkbox" value="10" id="tipo-a2-10" name="tipos">
                    <label class="form-check-label" for="tipo-a2-10"><i class="fas fa-file-invoice"></i> Pedido</label>
                </div>
                <div class="form-check">
                    <input class="form-check-input chk-tipo-a2" type="checkbox" value="13" id="tipo-a2-13" name="tipos">
                    <label class="form-check-label" for="tipo-a2-13"><i class="fas fa-truck"></i> Nota de Entrega</label>
                </div>
            </div>
        </div>

        <div class="row g-2 mb-3">
            <div class="col-md-6">
                <label for="a2-documento" class="form-label small">N° de documento</label>
                <input type="text" class="form-control" id="a2-documento" name="documento"
                    placeholder="Ej. 00001234" autocomplete="off"
                    hx-get="/pedidos/buscar-documentos-a2/"
                    hx-trigger="input changed delay:500ms, keyup[key=='Enter'], cambioFiltroA2"
                    hx-target="#resultados-a2"
                    hx-swap="innerHTML"
                    hx-include="#a2-cliente, .chk-tipo-a2">
            </div>
            <div class="col-md-6">
                <label for="a2-cliente" class="form-label small">Cliente</label>
                <input type="text" class="form-control" id="a2-cliente" name="cliente"
                    placeholder="Nombre del cliente" autocomplete="off"
                    hx-get="/pedidos/buscar-documentos-a2/"
                    hx-trigger="input changed delay:500ms, keyup[key=='Enter'], cambioFiltroA2"
                    hx-target="#resultados-a2"
                    hx-swap="innerHTML"
                    hx-include="#a2-documento, .chk-tipo-a2">
            </div>
        </div>

        <div id="resultados-a2" class="mb-3">
            <p class="text-muted p-2">Seleccione el tipo de documento e ingrese un número o cliente para buscar</p>
        </div>

        <div class="d-flex justify-content-between align-items-center">
            <button type="button" class="btn btn-secondary" id="btn-cancelar-a2">Cancelar</button>
            <button type="button" class="btn btn-primary" id="btn-cargar-a2" disabled>Cargar seleccionados (0)</button>
        </div>
    </div>
</div>
```

- [ ] **Step 3: Agregar el JavaScript**

Al final del bloque `<script>` existente (después del `document.addEventListener('DOMContentLoaded', ...)` que termina en la línea 632, antes de `</script>`), agregar:

```javascript

document.getElementById('btn-abrir-a2').addEventListener('click', function() {
    document.getElementById('overlay-a2').style.display = 'flex';
    document.getElementById('a2-documento').focus();
});

function cerrarOverlayA2() {
    document.getElementById('overlay-a2').style.display = 'none';
    document.getElementById('a2-documento').value = '';
    document.getElementById('a2-cliente').value = '';
    document.querySelectorAll('.chk-tipo-a2').forEach(function(c) { c.checked = false; });
    document.getElementById('resultados-a2').innerHTML =
        '<p class="text-muted p-2">Seleccione el tipo de documento e ingrese un número o cliente para buscar</p>';
    actualizarContadorA2();
}

document.getElementById('btn-cerrar-a2').addEventListener('click', cerrarOverlayA2);
document.getElementById('btn-cancelar-a2').addEventListener('click', cerrarOverlayA2);

document.getElementById('overlay-a2').addEventListener('click', function(e) {
    if (e.target === this) cerrarOverlayA2();
});

document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && document.getElementById('overlay-a2').style.display === 'flex') {
        cerrarOverlayA2();
    }
});

document.querySelectorAll('.chk-tipo-a2').forEach(function(chk) {
    chk.addEventListener('change', function() {
        const doc = document.getElementById('a2-documento');
        const cliente = document.getElementById('a2-cliente');
        if (doc.value.trim() || cliente.value.trim()) {
            htmx.trigger(doc, 'cambioFiltroA2');
        }
    });
});

function actualizarContadorA2() {
    const seleccionados = document.querySelectorAll('.chk-doc-a2:checked').length;
    const btn = document.getElementById('btn-cargar-a2');
    btn.textContent = 'Cargar seleccionados (' + seleccionados + ')';
    btn.disabled = seleccionados === 0;
}

document.getElementById('resultados-a2').addEventListener('change', function(e) {
    if (e.target.classList.contains('chk-doc-a2')) {
        actualizarContadorA2();
    }
});

function mezclarItemsA2(items) {
    items.forEach(function(item) {
        const existe = itemsPedido.find(function(i) { return i.codigo === item.codigo; });
        if (existe) {
            existe.cantidad += item.cantidad;
        } else {
            itemsPedido.push({
                codigo: item.codigo,
                descripcion: item.descripcion,
                referencia: item.referencia || '',
                puesto: item.puesto || '',
                ref_proveedor: item.ref_proveedor || '',
                cantidad: item.cantidad,
                categoria: item.categoria,
                categoria_nombre: item.categoria_nombre,
            });
        }
    });

    const categoriasEnCarrito = Array.from(new Set(itemsPedido.map(function(i) { return i.categoria; }).filter(Boolean)));
    if (categoriasEnCarrito.length > 1) {
        document.getElementById('checkbox-mixto').checked = true;
        sincronizarMixto();
    } else if (categoriasEnCarrito.length === 1) {
        const sel = document.getElementById('selector-categoria');
        sel.value = categoriasEnCarrito[0];
        seleccionarCategoria(sel);
    }

    renderItems();
}

document.getElementById('btn-cargar-a2').addEventListener('click', function() {
    const ids = Array.from(document.querySelectorAll('.chk-doc-a2:checked')).map(function(c) { return c.value; });
    if (ids.length === 0) return;

    const btn = this;
    btn.disabled = true;

    const params = new URLSearchParams();
    ids.forEach(function(id) { params.append('operacion_ids', id); });

    fetch('/pedidos/cargar-items-a2/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
        },
        body: params.toString(),
    })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) {
                document.getElementById('resultados-a2').innerHTML =
                    '<p class="text-danger p-2">' + data.error + '</p>';
                return;
            }
            mezclarItemsA2(data.items);
            cerrarOverlayA2();
        })
        .catch(function() {
            document.getElementById('resultados-a2').innerHTML =
                '<p class="text-danger p-2">No se pudo consultar a2. Intenta de nuevo en unos segundos.</p>';
        })
        .finally(function() {
            actualizarContadorA2();
        });
});
```

- [ ] **Step 4: Verificación manual en navegador**

Levantar el servidor de desarrollo (`venv\Scripts\python.exe manage.py runserver`), loguearse con un usuario del grupo "Pedidos Tienda", ir a `/pedidos/crear/`, y verificar:

1. El botón "Cargar de a2" es visible y clickeable **sin** haber seleccionado categoría/condición/depósito todavía (no debe estar bloqueado por el candado del formulario).
2. Al abrir el overlay, marcar dos tipos de documento (ej. Presupuesto y Nota de Entrega) y buscar por un número de documento real que exista en a2 con estado abierto — deben aparecer filas con badge de tipo distinto por cada uno.
3. Buscar por nombre de cliente (parcial, minúsculas) también trae resultados.
4. Marcar 2+ documentos con productos de categorías distintas, click "Cargar seleccionados" — el checkbox "Pedido mixto" queda marcado automáticamente y el candado de categoría se cierra igual que al agregar un producto manual.
5. Repetir con documentos de una sola categoría — la categoría del pedido queda fijada a esa, sin marcar mixto.
6. Cargar dos documentos que comparten un código de producto — el carrito muestra una sola línea con la cantidad sumada.
7. Tecla `Escape` y click fuera de la tarjeta cierran el overlay y limpian la búsqueda.
8. Totalizar el pedido con ítems mixtos de origen a2 — la validación de stock/categoría/condición existente se comporta igual que con ítems agregados a mano.

- [ ] **Step 5: Commit**

```bash
git add templates/pedidos-crear.html
git commit -m "$(cat <<'EOF'
feat(pedidos): agrega modal de carga de documentos a2 al crear pedido

Boton "Cargar de a2" abre un overlay para buscar presupuestos,
pedidos y notas de entrega abiertos por numero o cliente, seleccionar
varios de tipos/categorias distintas, y cargarlos al carrito
reutilizando itemsPedido/renderItems existentes. Marca "Pedido mixto"
automaticamente cuando los items abarcan mas de una categoria.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FmMX2cwMh94uT9DHXgE2bW
EOF
)"
```
