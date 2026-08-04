# Exportación CSV/PDF del Reporte de Items — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar exportación CSV y PDF del Reporte de Items por Estado (`/pedidos/reporte/items/`), solo cabecera agrupada por código (sin el detalle por pedido), respetando los mismos filtros que la pantalla.

**Architecture:** Se extrae la lógica de filtrado/agregación de la vista `reporte_items` a una función compartida `_construir_grupos_reporte_items(request)` en `PedidosAlmacen/views.py`, reutilizada por la vista de pantalla y dos vistas de exportación nuevas (`exportar_reporte_items_csv`, `exportar_reporte_items_pdf`). El PDF usa una nueva función `generar_reporte_items_pdf` en `PedidosAlmacen/pdf.py` siguiendo el estilo ya existente (`reportlab`). El CSV se arma con el módulo estándar `csv`. Dos botones nuevos en el header del template arman su href con un querystring pre-calculado (`querystring_filtros`) que omite parámetros vacíos, para no romper el filtro por defecto de back order.

**Tech Stack:** Django (views, urls, templates), `reportlab` (ya usado en `PedidosAlmacen/pdf.py`), `csv`/`io`/`urllib.parse` (stdlib).

## Global Constraints

- No se agregan dependencias nuevas: `csv`, `io`, `urllib.parse` son stdlib; `reportlab` ya está en `PedidosAlmacen/pdf.py`.
- Mismo gate de permisos que el reporte: `@login_required(login_url='/login/')` + `@user_passes_test(is_pedidos_supervisor, login_url='dashboard')`.
- CSV: encoding `utf-8-sig` (BOM), delimitador coma (`csv.writer` default), `content_type='text/csv'`.
- PDF: `content_type='application/pdf'`.
- Nombre de archivo en ambos: `reporte_items_YYYYMMDD_HHMM.<ext>` (mismo formato de timestamp que `exportar_reporte_pdf`: `datetime.now().strftime('%Y%m%d_%H%M')`).
- El refactor de `reporte_items` a `_construir_grupos_reporte_items` NO debe cambiar el comportamiento observable de la vista de pantalla — todos los tests existentes de `ReporteItemsTest` deben seguir pasando sin modificación.
- Columnas exportadas (mismo orden en CSV y PDF): Código, Descripción, Pedido(s), Estado, Solicit., Preparada, Despach., Recibida, Back Order, Existencia.
  - Pedido(s): `f"#{pedido_id}"` si `num_pedidos == 1`, si no `f"{num_pedidos} pedidos"`.
  - Estado: labels de `estados_badges` unidos con `", "`.
  - Existencia: entero, o `"N/D"` si `grupo['existencia'] is None`.

---

### Task 1: Refactor a helper compartido + querystring de filtros

**Files:**
- Modify: `PedidosAlmacen/views.py:1-22` (imports), `PedidosAlmacen/views.py:1832-1931` (función `reporte_items`)
- Test: `PedidosAlmacen/tests.py` (clase `ReporteItemsTest`, ~línea 3013)

**Interfaces:**
- Produces: `_construir_grupos_reporte_items(request) -> tuple[list[dict], dict]`. El segundo elemento (`filtros`) tiene las claves: `codigos_filtro`, `categoria_filtro`, `estado_filtro`, `fecha_inicio`, `fecha_fin`, `sin_filtros_aplicados`, `querystring_filtros` (string ya urlencodeado, sin parámetros vacíos, ej. `"categoria=PLOM"` o `""` si no hay filtros). Cada dict en `grupos` conserva las claves ya existentes: `codigo`, `descripcion`, `total_solicitada`, `total_preparada`, `total_despachada`, `total_recibida`, `total_back_order`, `num_pedidos`, `detalle` (lista de instancias `PedidoItem`), `estados_badges` (lista ordenada de tuplas `(estado_code, estado_label)`), `detalle_json`, `existencia` (int o `None`).
- Usado por: Task 2 (`exportar_reporte_items_csv`) y Task 3 (`exportar_reporte_items_pdf`).

- [ ] **Step 1: Escribir los tests que fallan para `querystring_filtros`**

Agregar al final de la clase `ReporteItemsTest` en `PedidosAlmacen/tests.py` (antes del cierre de la clase, después de `test_filtro_por_fecha`):

```python
    def test_querystring_filtros_vacio_sin_filtros(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'))
        self.assertEqual(resp.context['querystring_filtros'], '')

    def test_querystring_filtros_incluye_solo_valores_no_vacios(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'), {'categoria': 'PLOM', 'estado': ''})
        qs = resp.context['querystring_filtros']
        self.assertIn('categoria=PLOM', qs)
        self.assertNotIn('estado=', qs)
        self.assertNotIn('codigos=', qs)
```

- [ ] **Step 2: Correr los tests nuevos y confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ReporteItemsTest.test_querystring_filtros_vacio_sin_filtros PedidosAlmacen.tests.ReporteItemsTest.test_querystring_filtros_incluye_solo_valores_no_vacios --settings=Programarprecios.test_settings -v 2`

Expected: FAIL con `KeyError: 'querystring_filtros'` (la clave no existe todavía en el contexto).

- [ ] **Step 3: Agregar el import de `urlencode`**

En `PedidosAlmacen/views.py`, en el bloque de imports (línea 12, junto a `from datetime import ...`):

```python
from urllib.parse import urlencode
```

- [ ] **Step 4: Extraer `_construir_grupos_reporte_items` y refactorizar `reporte_items`**

En `PedidosAlmacen/views.py`, reemplazar el bloque completo de la función `reporte_items` (líneas 1832-1931, desde `@login_required...` hasta el `})` final de `return render(...)`) por:

```python
def _construir_grupos_reporte_items(request):
    """
    Query y agregacion compartidos por pantalla, export CSV y export PDF
    del reporte de items. Devuelve (grupos, filtros).
    """
    codigos_raw = request.GET.get('codigos', '').strip()
    categoria_filtro = request.GET.get('categoria', '')
    estado_filtro = request.GET.get('estado', '')
    fecha_inicio = request.GET.get('fecha_inicio', '')
    fecha_fin = request.GET.get('fecha_fin', '')
    sin_filtros_aplicados = not request.GET

    pedidos = Pedido.objects.exclude(estado='ANULADO')
    items = PedidoItem.objects.filter(pedido__in=pedidos)

    if codigos_raw:
        codigos_lista = [c.strip() for c in codigos_raw.split(',') if c.strip()]
        items = items.filter(codigo__in=codigos_lista)
    if categoria_filtro:
        items = items.filter(pedido__categoria=categoria_filtro)
    if estado_filtro:
        items = items.filter(estado=estado_filtro)
    if fecha_inicio:
        items = items.filter(pedido__fecha_creacion__date__gte=fecha_inicio)
    if fecha_fin:
        items = items.filter(pedido__fecha_creacion__date__lte=fecha_fin)
    if sin_filtros_aplicados:
        items = items.filter(cantidad_back_order__gt=0)

    grupos = list(
        items.values('codigo')
        .annotate(
            descripcion=Max('descripcion'),
            total_solicitada=Sum('cantidad_solicitada'),
            total_preparada=Coalesce(Sum('cantidad_preparada'), Value(0)),
            total_despachada=Sum('cantidad_despachada'),
            total_recibida=Sum('cantidad_recibida'),
            total_back_order=Sum('cantidad_back_order'),
            num_pedidos=Count('pedido', distinct=True),
        )
        .order_by('codigo')
    )

    codigos_pagina = [g['codigo'] for g in grupos]
    detalle_por_codigo = {}
    if codigos_pagina:
        detalle_items = items.order_by('codigo', 'pedido_id')
        for item in detalle_items:
            detalle_por_codigo.setdefault(item.codigo, []).append(item)

    existencia_por_codigo = {}
    stock_no_disponible = False
    if codigos_pagina:
        try:
            dbisam = PedidosDBISAM()
            existencia_por_codigo = dbisam.consultar_stock_multiple(codigos_pagina, deposito=DEPOSITO_ALMACEN)
        except Exception as e:
            logger.warning(f"No se pudo consultar existencia para reporte de items: {e}")
            messages.warning(
                request,
                'No se pudo consultar la existencia en almacén (a2 no disponible en este momento).',
            )
            stock_no_disponible = True

    for grupo in grupos:
        detalle = detalle_por_codigo.get(grupo['codigo'], [])
        grupo['detalle'] = detalle
        grupo['estados_badges'] = sorted({(item.estado, item.get_estado_display()) for item in detalle})
        grupo['detalle_json'] = json.dumps([
            {
                'pedido': item.pedido_id,
                'estado': item.get_estado_display(),
                'estado_code': item.estado,
                'solicitada': item.cantidad_solicitada,
                'preparada': item.cantidad_preparada or 0,
                'despachada': item.cantidad_despachada,
                'recibida': item.cantidad_recibida,
                'back_order': item.cantidad_back_order,
            }
            for item in detalle
        ]) if grupo['num_pedidos'] > 1 else '[]'
        grupo['existencia'] = None if stock_no_disponible else existencia_por_codigo.get(grupo['codigo'], 0)

    querystring_filtros = urlencode({
        k: v for k, v in {
            'codigos': codigos_raw,
            'categoria': categoria_filtro,
            'estado': estado_filtro,
            'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin,
        }.items() if v
    })

    filtros = {
        'codigos_filtro': codigos_raw,
        'categoria_filtro': categoria_filtro,
        'estado_filtro': estado_filtro,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'sin_filtros_aplicados': sin_filtros_aplicados,
        'querystring_filtros': querystring_filtros,
    }
    return grupos, filtros


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def reporte_items(request):
    grupos, filtros = _construir_grupos_reporte_items(request)

    categorias_disponibles = (
        Pedido.objects.exclude(categoria='')
        .exclude(estado='ANULADO')
        .values('categoria')
        .annotate(nombre=Max('categoria_nombre'))
        .order_by('categoria')
    )

    return render(request, 'pedidos-reporte-items.html', {
        'grupos': grupos,
        'codigos_filtro': filtros['codigos_filtro'],
        'categoria_filtro': filtros['categoria_filtro'],
        'estado_filtro': filtros['estado_filtro'],
        'fecha_inicio': filtros['fecha_inicio'],
        'fecha_fin': filtros['fecha_fin'],
        'sin_filtros_aplicados': filtros['sin_filtros_aplicados'],
        'querystring_filtros': filtros['querystring_filtros'],
        'categorias_disponibles': categorias_disponibles,
        'estados_item': PedidoItem.ESTADO_ITEM_CHOICES,
    })
```

- [ ] **Step 5: Correr los tests nuevos y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ReporteItemsTest.test_querystring_filtros_vacio_sin_filtros PedidosAlmacen.tests.ReporteItemsTest.test_querystring_filtros_incluye_solo_valores_no_vacios --settings=Programarprecios.test_settings -v 2`

Expected: PASS

- [ ] **Step 6: Correr toda la clase `ReporteItemsTest` y confirmar que no hay regresión**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ReporteItemsTest --settings=Programarprecios.test_settings -v 2`

Expected: todos los tests existentes (20 anteriores + 2 nuevos = 22) PASS. Si algo falla, es una regresión del refactor — no debe quedar ningún test existente roto.

- [ ] **Step 7: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/tests.py
git commit -m "refactor(pedidos): extrae query del reporte de items a helper compartido"
```

---

### Task 2: Exportación CSV

**Files:**
- Modify: `PedidosAlmacen/views.py` (imports; nueva función después de `reporte_items`)
- Modify: `PedidosAlmacen/urls.py`
- Test: `PedidosAlmacen/tests.py` (nueva clase `ExportarReporteItemsTest`)

**Interfaces:**
- Consumes: `_construir_grupos_reporte_items(request)` de Task 1 (misma firma y estructura de `grupos`/`filtros` documentada ahí).
- Produces: vista `exportar_reporte_items_csv(request)`, URL name `pedidos-reporte-items-csv`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `PedidosAlmacen/tests.py` (después del cierre de `MenuReporteItemsTest`):

```python
class ExportarReporteItemsTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from django.urls import reverse
        from users.models import User
        from .models import Pedido, PedidoItem
        from unittest.mock import patch
        self.reverse = reverse

        self.dbisam_patcher = patch('PedidosAlmacen.views.PedidosDBISAM')
        self.mock_dbisam = self.dbisam_patcher.start()
        self.addCleanup(self.dbisam_patcher.stop)
        self.mock_dbisam.return_value.consultar_stock_multiple.return_value = {}

        self.g_supervisor, _ = Group.objects.get_or_create(name='Pedidos Supervisor')
        self.supervisor = User.objects.create_user(username='sup_export_items', password='x')
        self.supervisor.groups.add(self.g_supervisor)
        self.tienda = User.objects.create_user(username='tnd_export_items', password='x')

        self.pedido1 = Pedido.objects.create(
            solicitante=self.supervisor, estado='PARCIAL',
            categoria='FERR', categoria_nombre='Ferretería',
        )
        PedidoItem.objects.create(
            pedido=self.pedido1, codigo='01120044', descripcion='Tubo PVC 1/2"',
            cantidad_solicitada=40, cantidad_preparada=40, cantidad_despachada=25,
            cantidad_recibida=25, cantidad_back_order=15, estado='PARCIAL',
        )
        self.pedido2 = Pedido.objects.create(
            solicitante=self.supervisor, estado='PENDIENTE',
            categoria='FERR', categoria_nombre='Ferretería',
        )
        PedidoItem.objects.create(
            pedido=self.pedido2, codigo='01120044', descripcion='Tubo PVC 1/2"',
            cantidad_solicitada=10, cantidad_preparada=0, cantidad_despachada=0,
            cantidad_recibida=0, cantidad_back_order=0, estado='PENDIENTE',
        )
        self.pedido3 = Pedido.objects.create(
            solicitante=self.supervisor, estado='RECIBIDO',
            categoria='PLOM', categoria_nombre='Plomería',
        )
        PedidoItem.objects.create(
            pedido=self.pedido3, codigo='02030011', descripcion='Cemento gris',
            cantidad_solicitada=80, cantidad_preparada=80, cantidad_despachada=80,
            cantidad_recibida=80, cantidad_back_order=0, estado='RECIBIDO',
        )

    def test_no_supervisor_redirige_csv(self):
        self.client.force_login(self.tienda)
        resp = self.client.get(self.reverse('pedidos-reporte-items-csv'))
        self.assertEqual(resp.status_code, 302)

    def test_csv_content_type_y_nombre_archivo(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items-csv'), {'estado': ''})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        self.assertIn('attachment; filename="reporte_items_', resp['Content-Disposition'])

    def test_csv_incluye_fila_por_codigo_agrupado(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items-csv'), {'estado': ''})
        contenido = resp.content.decode('utf-8-sig')
        self.assertIn('01120044', contenido)
        self.assertIn('2 pedidos', contenido)
        self.assertIn('02030011', contenido)
        self.assertIn(f'#{self.pedido3.pk}', contenido)

    def test_csv_respeta_default_de_back_order_sin_filtros(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items-csv'))
        contenido = resp.content.decode('utf-8-sig')
        self.assertIn('01120044', contenido)
        self.assertNotIn('02030011', contenido)

    def test_csv_existencia_nd_si_dbisam_falla(self):
        self.client.force_login(self.supervisor)
        self.mock_dbisam.return_value.consultar_stock_multiple.side_effect = Exception('caído')
        resp = self.client.get(self.reverse('pedidos-reporte-items-csv'), {'estado': ''})
        contenido = resp.content.decode('utf-8-sig')
        self.assertIn('N/D', contenido)
```

- [ ] **Step 2: Correr los tests y confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ExportarReporteItemsTest --settings=Programarprecios.test_settings -v 2`

Expected: FAIL — `NoReverseMatch: Reverse for 'pedidos-reporte-items-csv' not found` (la URL todavía no existe).

- [ ] **Step 3: Agregar imports necesarios**

En `PedidosAlmacen/views.py`, en el bloque de imports (junto a `import logging` / `import json`, línea 21-22):

```python
import csv
import io
```

- [ ] **Step 4: Agregar la vista `exportar_reporte_items_csv`**

En `PedidosAlmacen/views.py`, inmediatamente después de la función `reporte_items` (después del `})` de su `return render(...)`, antes de `def _sku_incidencia`:

```python
@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def exportar_reporte_items_csv(request):
    grupos, _filtros = _construir_grupos_reporte_items(request)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        'Código', 'Descripción', 'Pedido(s)', 'Estado',
        'Solicit.', 'Preparada', 'Despach.', 'Recibida', 'Back Order', 'Existencia',
    ])
    for grupo in grupos:
        if grupo['num_pedidos'] == 1:
            pedido_col = f"#{grupo['detalle'][0].pedido_id}"
        else:
            pedido_col = f"{grupo['num_pedidos']} pedidos"
        estado_col = ', '.join(label for _codigo, label in grupo['estados_badges'])
        existencia_col = 'N/D' if grupo['existencia'] is None else grupo['existencia']
        writer.writerow([
            grupo['codigo'], grupo['descripcion'], pedido_col, estado_col,
            grupo['total_solicitada'], grupo['total_preparada'], grupo['total_despachada'],
            grupo['total_recibida'], grupo['total_back_order'], existencia_col,
        ])

    nombre_archivo = f"reporte_items_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    response = HttpResponse(buffer.getvalue().encode('utf-8-sig'), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return response
```

- [ ] **Step 5: Registrar la URL**

En `PedidosAlmacen/urls.py`, agregar después de la línea `path('pedidos/reporte/items/', views.reporte_items, name='pedidos-reporte-items'),`:

```python
    path('pedidos/reporte/items/csv/', views.exportar_reporte_items_csv, name='pedidos-reporte-items-csv'),
```

- [ ] **Step 6: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ExportarReporteItemsTest --settings=Programarprecios.test_settings -v 2`

Expected: PASS (5/5)

- [ ] **Step 7: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/urls.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): exportar CSV del reporte de items"
```

---

### Task 3: Exportación PDF

**Files:**
- Modify: `PedidosAlmacen/pdf.py` (nueva función)
- Modify: `PedidosAlmacen/views.py` (import, nueva vista)
- Modify: `PedidosAlmacen/urls.py`
- Test: `PedidosAlmacen/tests.py` (clase `ExportarReporteItemsTest`)

**Interfaces:**
- Consumes: `_construir_grupos_reporte_items(request)` de Task 1. `ExportarReporteItemsTest.setUp` de Task 2 (misma clase, se agregan métodos de test nuevos).
- Produces: `generar_reporte_items_pdf(grupos: list, filtros: dict) -> bytes` en `pdf.py`; vista `exportar_reporte_items_pdf(request)`, URL name `pedidos-reporte-items-pdf`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de la clase `ExportarReporteItemsTest` en `PedidosAlmacen/tests.py` (después de `test_csv_existencia_nd_si_dbisam_falla`):

```python
    def test_no_supervisor_redirige_pdf(self):
        self.client.force_login(self.tienda)
        resp = self.client.get(self.reverse('pedidos-reporte-items-pdf'))
        self.assertEqual(resp.status_code, 302)

    def test_pdf_content_type_y_nombre_archivo(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items-pdf'), {'estado': ''})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertIn('attachment; filename="reporte_items_', resp['Content-Disposition'])

    def test_pdf_no_lanza_excepcion_sin_grupos(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items-pdf'), {'codigos': 'NOEXISTE'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_pdf_respeta_default_de_back_order_sin_filtros(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items-pdf'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_pdf_existencia_nd_si_dbisam_falla_no_rompe_generacion(self):
        self.client.force_login(self.supervisor)
        self.mock_dbisam.return_value.consultar_stock_multiple.side_effect = Exception('caído')
        resp = self.client.get(self.reverse('pedidos-reporte-items-pdf'), {'estado': ''})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
```

- [ ] **Step 2: Correr los tests y confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ExportarReporteItemsTest --settings=Programarprecios.test_settings -v 2`

Expected: FAIL — `NoReverseMatch: Reverse for 'pedidos-reporte-items-pdf' not found`

- [ ] **Step 3: Agregar `generar_reporte_items_pdf` en `pdf.py`**

En `PedidosAlmacen/pdf.py`, agregar al final del archivo (después de `generar_despacho_pdf`):

```python
def generar_reporte_items_pdf(grupos: list, filtros: dict) -> bytes:
    """
    Genera el PDF del reporte de items agrupado por codigo (solo cabecera,
    sin el detalle por pedido).

    Args:
        grupos: Lista de dicts con las mismas claves usadas en pantalla
            (codigo, descripcion, num_pedidos, detalle, estados_badges,
            total_solicitada, total_preparada, total_despachada,
            total_recibida, total_back_order, existencia).
        filtros: Dict con codigos_filtro, categoria_filtro, estado_filtro,
            fecha_inicio, fecha_fin, sin_filtros_aplicados.

    Returns:
        Bytes del PDF generado.
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        leftMargin=35, rightMargin=35, topMargin=25, bottomMargin=25,
    )
    elements = []

    st_titulo = ParagraphStyle("t", fontSize=16, textColor=_AZUL_OSCURO,
                                spaceAfter=4, alignment=TA_CENTER, fontName="Helvetica-Bold")
    st_sub = ParagraphStyle("s", fontSize=9, textColor=colors.grey,
                             spaceAfter=2, alignment=TA_CENTER)

    elements.append(Paragraph("Reporte de Items por Estado", st_titulo))

    filtros_texto = []
    if filtros.get("codigos_filtro"):
        filtros_texto.append(f"Codigos: {filtros['codigos_filtro']}")
    if filtros.get("categoria_filtro"):
        filtros_texto.append(f"Categoria: {filtros['categoria_filtro']}")
    if filtros.get("estado_filtro"):
        filtros_texto.append(f"Estado: {filtros['estado_filtro']}")
    if filtros.get("fecha_inicio"):
        filtros_texto.append(f"Desde: {filtros['fecha_inicio']}")
    if filtros.get("fecha_fin"):
        filtros_texto.append(f"Hasta: {filtros['fecha_fin']}")
    if filtros.get("sin_filtros_aplicados"):
        filtros_texto.append("Solo items con back order pendiente (default)")
    if filtros_texto:
        elements.append(Paragraph(" | ".join(filtros_texto), st_sub))
    elements.append(Paragraph(f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}", st_sub))
    elements.append(Spacer(1, 14))

    elements.append(_seccion_header("Items", 542))

    st_cell = ParagraphStyle("ic", fontSize=8, leading=10)
    st_head = ParagraphStyle("ih", fontSize=8, leading=10, fontName="Helvetica-Bold")
    data = [[
        Paragraph("Codigo", st_head), Paragraph("Descripcion", st_head),
        Paragraph("Pedido(s)", st_head), Paragraph("Estado", st_head),
        Paragraph("Solicit.", st_head), Paragraph("Preparada", st_head),
        Paragraph("Despach.", st_head), Paragraph("Recibida", st_head),
        Paragraph("Back Order", st_head), Paragraph("Existencia", st_head),
    ]]
    for grupo in grupos:
        if grupo["num_pedidos"] == 1:
            pedido_col = f"#{grupo['detalle'][0].pedido_id}"
        else:
            pedido_col = f"{grupo['num_pedidos']} pedidos"
        estado_col = ", ".join(label for _codigo, label in grupo["estados_badges"])
        existencia_col = "N/D" if grupo["existencia"] is None else str(grupo["existencia"])
        data.append([
            Paragraph(grupo["codigo"], st_cell),
            Paragraph(grupo["descripcion"], st_cell),
            Paragraph(pedido_col, st_cell),
            Paragraph(estado_col, st_cell),
            str(grupo["total_solicitada"]), str(grupo["total_preparada"]),
            str(grupo["total_despachada"]), str(grupo["total_recibida"]),
            str(grupo["total_back_order"]), existencia_col,
        ])
    if not grupos:
        data.append([Paragraph("Sin datos", st_cell), "-", "-", "-", "-", "-", "-", "-", "-", "-"])

    # Ancho util = 542 pt (612 - margenes 35*2)
    # Codigo 50 | Descripcion 118 | Pedido(s) 55 | Estado 80 | Solicit 38 | Preparada 40 | Despach 40 | Recibida 38 | BackOrder 43 | Existencia 40 = 542
    col_widths = [50, 118, 55, 80, 38, 40, 40, 38, 43, 40]
    tabla = Table(data, colWidths=col_widths, repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _GRIS_CLARO),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _GRIS_CLARO]),
        ("ALIGN", (4, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(tabla)

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
```

- [ ] **Step 4: Agregar la vista `exportar_reporte_items_pdf`**

En `PedidosAlmacen/views.py`, actualizar el import de `pdf` (línea 20):

```python
from .pdf import (
    generar_reporte_pedidos_pdf, generar_reporte_pickers_pdf,
    generar_pedido_pdf, generar_despacho_pdf, generar_reporte_items_pdf,
)
```

Agregar la vista inmediatamente después de `exportar_reporte_items_csv`:

```python
@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def exportar_reporte_items_pdf(request):
    grupos, filtros = _construir_grupos_reporte_items(request)
    pdf_bytes = generar_reporte_items_pdf(grupos, filtros)
    nombre_archivo = f"reporte_items_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return response
```

- [ ] **Step 5: Registrar la URL**

En `PedidosAlmacen/urls.py`, agregar después de la línea de `pedidos-reporte-items-csv`:

```python
    path('pedidos/reporte/items/pdf/', views.exportar_reporte_items_pdf, name='pedidos-reporte-items-pdf'),
```

- [ ] **Step 6: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ExportarReporteItemsTest --settings=Programarprecios.test_settings -v 2`

Expected: PASS (10/10 — 5 de CSV de Task 2 + 5 de PDF de este task)

- [ ] **Step 7: Commit**

```bash
git add PedidosAlmacen/pdf.py PedidosAlmacen/views.py PedidosAlmacen/urls.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): exportar PDF del reporte de items"
```

---

### Task 4: Botones de exportación en el template

**Files:**
- Modify: `templates/pedidos-reporte-items.html:20-24` (`pd-header-actions`)
- Test: `PedidosAlmacen/tests.py` (clase `ReporteItemsTest`)

**Interfaces:**
- Consumes: `querystring_filtros` del contexto de `reporte_items` (Task 1); URL names `pedidos-reporte-items-csv` (Task 2) y `pedidos-reporte-items-pdf` (Task 3).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de la clase `ReporteItemsTest` en `PedidosAlmacen/tests.py` (después de `test_querystring_filtros_incluye_solo_valores_no_vacios` de Task 1):

```python
    def test_muestra_botones_exportar_sin_filtros(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'))
        self.assertContains(resp, self.reverse('pedidos-reporte-items-csv') + '"')
        self.assertContains(resp, self.reverse('pedidos-reporte-items-pdf') + '"')

    def test_botones_exportar_incluyen_filtros_aplicados(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'), {'categoria': 'PLOM'})
        self.assertContains(resp, self.reverse('pedidos-reporte-items-csv') + '?categoria=PLOM')
        self.assertContains(resp, self.reverse('pedidos-reporte-items-pdf') + '?categoria=PLOM')
```

- [ ] **Step 2: Correr los tests y confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ReporteItemsTest.test_muestra_botones_exportar_sin_filtros PedidosAlmacen.tests.ReporteItemsTest.test_botones_exportar_incluyen_filtros_aplicados --settings=Programarprecios.test_settings -v 2`

Expected: FAIL (no se encuentran las URLs de exportar en el HTML — el template todavía no tiene los botones).

- [ ] **Step 3: Agregar los botones al template**

En `templates/pedidos-reporte-items.html`, reemplazar el bloque `pd-header-actions` (líneas 20-24):

```html
    <div class="pd-header-actions">
        <a href="{% url 'pedidos-lista' %}" class="btn btn-sm btn-outline-light">
            <i class="fas fa-arrow-left"></i> <span class="d-none d-sm-inline">Volver a Pedidos</span>
        </a>
    </div>
```

por:

```html
    <div class="pd-header-actions">
        <a href="{% url 'pedidos-reporte-items-csv' %}{% if querystring_filtros %}?{{ querystring_filtros }}{% endif %}"
           class="btn btn-sm btn-outline-success">
            <i class="fas fa-file-csv"></i> <span class="d-none d-sm-inline">Exportar CSV</span>
        </a>
        <a href="{% url 'pedidos-reporte-items-pdf' %}{% if querystring_filtros %}?{{ querystring_filtros }}{% endif %}"
           class="btn btn-sm btn-danger">
            <i class="fas fa-file-pdf"></i> <span class="d-none d-sm-inline">Exportar PDF</span>
        </a>
        <a href="{% url 'pedidos-lista' %}" class="btn btn-sm btn-outline-light">
            <i class="fas fa-arrow-left"></i> <span class="d-none d-sm-inline">Volver a Pedidos</span>
        </a>
    </div>
```

- [ ] **Step 4: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ReporteItemsTest.test_muestra_botones_exportar_sin_filtros PedidosAlmacen.tests.ReporteItemsTest.test_botones_exportar_incluyen_filtros_aplicados --settings=Programarprecios.test_settings -v 2`

Expected: PASS

- [ ] **Step 5: Correr toda la suite de `PedidosAlmacen` para confirmar que no hay regresiones**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen --settings=Programarprecios.test_settings`

Expected: OK, sin fallos ni errores.

- [ ] **Step 6: Commit**

```bash
git add templates/pedidos-reporte-items.html PedidosAlmacen/tests.py
git commit -m "feat(pedidos): botones de exportar CSV/PDF en el reporte de items"
```
