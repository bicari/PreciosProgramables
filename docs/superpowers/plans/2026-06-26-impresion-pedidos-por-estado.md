# Impresión de pedidos por estado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir imprimir el PDF de un pedido filtrando sus items por estado (Todos, Despachado, Back Order, Recibido, Parcial) eligiendo la variante en un modal del detalle.

**Architecture:** Se reusa la vista y el generador de PDF existentes. `generar_pedido_pdf` recibe un parámetro `vista` que decide columnas y título; `exportar_pedido_pdf` lee `?vista=`, valida permiso por rol y filtra los items por estado antes de delegar. El detalle expone las variantes permitidas (con conteo por estado) y un modal Bootstrap las ofrece como enlaces.

**Tech Stack:** Django, PostgreSQL (modelos `Pedido`/`PedidoItem`), reportlab (PDF), Bootstrap 5 (modal), `django.test.TestCase`.

## Global Constraints

- Python 3.11+, PEP 8, type hints en funciones nuevas/modificadas (CLAUDE.md).
- Textos de UI en español.
- Filtrado **por estado exacto** de `PedidoItem.estado`; un item `PARCIAL` solo aparece en la variante `parcial` (y en `todos`).
- Permisos: Almacén/Supervisor → todas las variantes; Tienda → solo `todos`, `recibido`, `back_order`. Validación en servidor.
- La variante `todos` conserva exactamente el comportamiento actual (incluida la lógica `mostrar_cantidades`).
- Spec de referencia: `docs/superpowers/specs/2026-06-26-impresion-pedidos-por-estado-design.md`.

---

### Task 1: Parámetro `vista` en `generar_pedido_pdf`

Añade soporte de variantes al generador de PDF: columnas de cantidad y título según `vista`. La variante `todos` queda idéntica a hoy.

**Files:**
- Modify: `PedidosAlmacen/pdf.py` (función `generar_pedido_pdf`, ~líneas 257-476)
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Produces: `generar_pedido_pdf(pedido, items, vista: str = 'todos', mostrar_cantidades: bool = False) -> bytes`
  - `vista` ∈ `{'todos','despachado','back_order','recibido','parcial'}`.
  - `'todos'` → comportamiento actual. Variantes filtradas añaden columnas de cantidad propias e ignoran `mostrar_cantidades`.

- [ ] **Step 1: Escribir el test que falla**

Añadir al final de `PedidosAlmacen/tests.py`:

```python
class GenerarPedidoPDFVistaTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, PedidoItem
        u = User.objects.create_superuser(username='pdfu', password='x')
        self.pedido = Pedido.objects.create(solicitante=u)
        PedidoItem.objects.create(
            pedido=self.pedido, codigo='A', descripcion='Articulo A',
            cantidad_solicitada=5, estado='PARCIAL',
            cantidad_despachada=2, cantidad_back_order=3, cantidad_recibida=0,
        )

    def test_genera_pdf_para_cada_vista(self):
        from .pdf import generar_pedido_pdf
        for vista in ['todos', 'despachado', 'back_order', 'recibido', 'parcial']:
            pdf = generar_pedido_pdf(self.pedido, self.pedido.items.all(), vista=vista)
            self.assertTrue(pdf.startswith(b'%PDF'), f'vista={vista} no produjo PDF')

    def test_vista_default_es_todos(self):
        from .pdf import generar_pedido_pdf
        pdf = generar_pedido_pdf(self.pedido, self.pedido.items.all())
        self.assertTrue(pdf.startswith(b'%PDF'))
```

- [ ] **Step 2: Ejecutar el test y verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.GenerarPedidoPDFVistaTest -v 2`
Expected: FAIL — `generar_pedido_pdf() got an unexpected keyword argument 'vista'`.

- [ ] **Step 3: Añadir las tablas de configuración de variantes**

En `PedidosAlmacen/pdf.py`, debajo de `_LABEL_CONDICION` (~línea 30), agregar:

```python
# Sufijo de título por variante de impresión ('' = sin sufijo).
_VISTA_LABEL = {
    "todos": "",
    "despachado": "Despachado",
    "back_order": "Back Order",
    "recibido": "Recibido",
    "parcial": "Parcial",
}
# Columnas de cantidad (encabezado, atributo del item) por variante filtrada.
_VISTA_CANTIDADES = {
    "despachado": [("Despachado", "cantidad_despachada")],
    "back_order": [("Back Order", "cantidad_back_order")],
    "recibido": [("Recibido", "cantidad_recibida")],
    "parcial": [("Despachado", "cantidad_despachada"), ("Back Order", "cantidad_back_order")],
}
# Anchos de columna (suman 542 pt) segun cantidad de columnas de cantidad extra.
# Cols fijas: Codigo, Descripcion, Referencia, Puesto, Ref.Prov, Solicitado, <cant...>, Observacion
_VISTA_WIDTHS = {
    1: [50, 150, 65, 52, 52, 45, 48, 80],
    2: [48, 132, 60, 48, 48, 42, 44, 44, 76],
}
```

- [ ] **Step 4: Aceptar el parámetro `vista` y ajustar el título**

Cambiar la firma (línea ~257):

```python
def generar_pedido_pdf(pedido, items, vista: str = "todos", mostrar_cantidades: bool = False) -> bytes:
```

Y el título del encabezado (línea ~304). Reemplazar:

```python
    elements.append(Paragraph(f"Pedido de Almacen  #{ pedido.numero_pedido}", st_titulo))
```

por:

```python
    sufijo_vista = _VISTA_LABEL.get(vista, "")
    titulo_pedido = f"Pedido de Almacen  #{pedido.numero_pedido}"
    if sufijo_vista:
        titulo_pedido += f"  —  {sufijo_vista}"
    elements.append(Paragraph(titulo_pedido, st_titulo))
```

- [ ] **Step 5: Construir cabeceras y anchos según la variante**

Reemplazar el bloque `if mostrar_cantidades: ... else: ...` que define `cabeceras`/`col_widths` (líneas ~402-425) por:

```python
    es_filtrada = vista in _VISTA_CANTIDADES
    if es_filtrada:
        cantidad_cols = _VISTA_CANTIDADES[vista]
        cabeceras = [
            Paragraph("Codigo", st_th),
            Paragraph("Descripcion", st_th),
            Paragraph("Referencia", st_th),
            Paragraph("Puesto", st_th),
            Paragraph("Ref. Prov.", st_th),
            Paragraph("Solicitado", st_th),
        ]
        for encabezado, _attr in cantidad_cols:
            cabeceras.append(Paragraph(encabezado, st_th))
        cabeceras.append(Paragraph("Observacion", st_th))
        col_widths = _VISTA_WIDTHS[len(cantidad_cols)]
    elif mostrar_cantidades:
        cabeceras = [
            Paragraph("Codigo", st_th),
            Paragraph("Descripcion", st_th),
            Paragraph("Referencia", st_th),
            Paragraph("Puesto", st_th),
            Paragraph("Ref. Prov.", st_th),
            Paragraph("Solicitado", st_th),
            Paragraph("Despachado", st_th),
            Paragraph("Recibido", st_th),
            Paragraph("Observacion", st_th),
        ]
        col_widths = [50, 148, 68, 55, 55, 42, 40, 44, 40]
    else:
        cabeceras = [
            Paragraph("Codigo", st_th),
            Paragraph("Descripcion", st_th),
            Paragraph("Referencia", st_th),
            Paragraph("Puesto", st_th),
            Paragraph("Ref. Prov.", st_th),
            Paragraph("Solicitado", st_th),
            Paragraph("Observacion", st_th),
        ]
        col_widths = [55, 175, 75, 60, 60, 47, 70]
```

- [ ] **Step 6: Renderizar las celdas de cantidad según la variante**

Reemplazar el bucle de filas (líneas ~429-444) por:

```python
    for item in items:
        fila = [
            Paragraph(item.codigo, st_td),
            Paragraph(item.descripcion, st_td),
            Paragraph(item.referencia or "-", st_td),
            Paragraph(item.puesto or "-", st_td),
            Paragraph(item.ref_proveedor or "-", st_td),
            Paragraph(str(item.cantidad_solicitada), st_td_c),
        ]
        if es_filtrada:
            for _encabezado, attr in cantidad_cols:
                fila.append(Paragraph(str(getattr(item, attr)), st_td_c))
        elif mostrar_cantidades:
            fila += [
                Paragraph(str(item.cantidad_despachada), st_td_c),
                Paragraph(str(item.cantidad_recibida), st_td_c),
            ]
        fila.append(Paragraph(item.observacion or "-", st_td))
        data.append(fila)
```

- [ ] **Step 7: Ejecutar el test y verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.GenerarPedidoPDFVistaTest -v 2`
Expected: PASS (2 tests).

- [ ] **Step 8: Commit**

```bash
git add PedidosAlmacen/pdf.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): variante de impresion por estado en generar_pedido_pdf"
```

---

### Task 2: Filtrado y permisos en `exportar_pedido_pdf`

Lee `?vista=`, valida la variante y el permiso por rol, filtra los items por estado y delega en `generar_pedido_pdf`.

**Files:**
- Modify: `PedidosAlmacen/views.py` (constante nueva + helper + `exportar_pedido_pdf` ~líneas 1245-1259)
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `generar_pedido_pdf(pedido, items, vista=..., mostrar_cantidades=...)` (Task 1).
- Produces:
  - `VISTAS_PEDIDO: dict[str, dict]` — config de variantes.
  - `_puede_vista_pedido(user, vista: str) -> bool`.
  - Endpoint `pedidos-pdf` acepta `?vista=`; nombre de archivo `pedido_<n>[_<vista>].pdf`.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `PedidosAlmacen/tests.py`:

```python
class ExportarPedidoVistaTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido, PedidoItem
        from django.urls import reverse
        self.reverse = reverse
        self.almacen = User.objects.create_superuser(username='alm', password='x')
        self.tienda = User.objects.create_user(username='tnd', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda.groups.add(g)
        self.pedido = Pedido.objects.create(solicitante=self.tienda)
        for codigo, estado in [('A', 'DESPACHADO'), ('B', 'BACK_ORDER'),
                               ('C', 'RECIBIDO'), ('D', 'PARCIAL')]:
            PedidoItem.objects.create(
                pedido=self.pedido, codigo=codigo, descripcion=codigo.lower(),
                cantidad_solicitada=1, estado=estado,
            )

    def _url(self, vista=None):
        u = self.reverse('pedidos-pdf', args=[self.pedido.numero_pedido])
        return f'{u}?vista={vista}' if vista else u

    @patch('PedidosAlmacen.views.generar_pedido_pdf', return_value=b'%PDF-x')
    def test_filtra_por_estado_exacto(self, mock_pdf):
        self.client.force_login(self.almacen)
        resp = self.client.get(self._url('despachado'))
        self.assertEqual(resp.status_code, 200)
        args, kwargs = mock_pdf.call_args
        self.assertEqual([i.estado for i in args[1]], ['DESPACHADO'])
        self.assertEqual(kwargs.get('vista'), 'despachado')

    @patch('PedidosAlmacen.views.generar_pedido_pdf', return_value=b'%PDF-x')
    def test_vista_invalida_cae_a_todos(self, mock_pdf):
        self.client.force_login(self.almacen)
        resp = self.client.get(self._url('inexistente'))
        self.assertEqual(resp.status_code, 200)
        args, kwargs = mock_pdf.call_args
        self.assertEqual(len(list(args[1])), 4)
        self.assertEqual(kwargs.get('vista'), 'todos')

    @patch('PedidosAlmacen.views.generar_pedido_pdf', return_value=b'%PDF-x')
    def test_tienda_no_puede_despachado(self, mock_pdf):
        self.client.force_login(self.tienda)
        resp = self.client.get(self._url('despachado'))
        self.assertEqual(resp.status_code, 302)
        mock_pdf.assert_not_called()

    @patch('PedidosAlmacen.views.generar_pedido_pdf', return_value=b'%PDF-x')
    def test_tienda_puede_recibido(self, mock_pdf):
        self.client.force_login(self.tienda)
        resp = self.client.get(self._url('recibido'))
        self.assertEqual(resp.status_code, 200)
        args, kwargs = mock_pdf.call_args
        self.assertEqual([i.estado for i in args[1]], ['RECIBIDO'])

    @patch('PedidosAlmacen.views.generar_pedido_pdf', return_value=b'%PDF-x')
    def test_variante_vacia_responde_200(self, mock_pdf):
        from .models import Pedido, PedidoItem
        pedido2 = Pedido.objects.create(solicitante=self.almacen)
        PedidoItem.objects.create(pedido=pedido2, codigo='Z', descripcion='z',
                                  cantidad_solicitada=1, estado='DESPACHADO')
        self.client.force_login(self.almacen)
        url = self.reverse('pedidos-pdf', args=[pedido2.numero_pedido]) + '?vista=back_order'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        args, _ = mock_pdf.call_args
        self.assertEqual(len(list(args[1])), 0)
```

- [ ] **Step 2: Ejecutar los tests y verificar que fallan**

Run: `python manage.py test PedidosAlmacen.tests.ExportarPedidoVistaTest -v 2`
Expected: FAIL — `test_vista_invalida_cae_a_todos` falla porque hoy no se lee `vista` (mock recibido sin kwarg `vista`), y `test_tienda_no_puede_despachado` devuelve 200 en vez de 302.

- [ ] **Step 3: Añadir la config de variantes y el helper de permiso**

En `PedidosAlmacen/views.py`, junto a los helpers de rol (después de `_solo_picker`, ~línea 104), agregar:

```python
# Variantes de impresión de un pedido. 'estado' None = sin filtro (todos los items).
# 'tienda' indica si un usuario solo-Tienda puede generarla.
VISTAS_PEDIDO = {
    'todos':      {'label': 'Todos',      'estado': None,         'tienda': True},
    'despachado': {'label': 'Despachado', 'estado': 'DESPACHADO', 'tienda': False},
    'back_order': {'label': 'Back Order', 'estado': 'BACK_ORDER', 'tienda': True},
    'recibido':   {'label': 'Recibido',   'estado': 'RECIBIDO',   'tienda': True},
    'parcial':    {'label': 'Parcial',    'estado': 'PARCIAL',    'tienda': False},
}


def _puede_vista_pedido(user, vista: str) -> bool:
    """True si el usuario puede generar la variante de impresión indicada."""
    cfg = VISTAS_PEDIDO.get(vista)
    if cfg is None:
        return False
    if _solo_tienda(user):
        return cfg['tienda']
    return True
```

- [ ] **Step 4: Reescribir `exportar_pedido_pdf`**

Reemplazar el cuerpo de `exportar_pedido_pdf` (líneas ~1245-1259, desde `items = pedido.items.all()` hasta el `return response`) por:

```python
    vista = request.GET.get('vista', 'todos')
    if vista not in VISTAS_PEDIDO:
        vista = 'todos'
    if not _puede_vista_pedido(request.user, vista):
        messages.error(request, 'No tienes permiso para imprimir esa variante del pedido')
        return redirect('pedidos-detalle', pk=pk)

    items = pedido.items.all()
    estado_filtro = VISTAS_PEDIDO[vista]['estado']
    if estado_filtro is not None:
        items = items.filter(estado=estado_filtro)

    mostrar_cantidades = is_pedidos_almacen(request.user) or is_pedidos_supervisor(request.user)
    pdf_bytes = generar_pedido_pdf(pedido, items, vista=vista, mostrar_cantidades=mostrar_cantidades)

    sufijo = '' if vista == 'todos' else f'_{vista}'
    nombre_archivo = f"pedido_{pedido.numero_pedido}{sufijo}.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return response
```

(La validación de propiedad `_solo_tienda` y la línea `mostrar_cantidades` previa quedan sustituidas; mantener intactas las líneas anteriores que obtienen `pedido` y verifican `_solo_tienda(request.user) and pedido.solicitante != request.user`.)

- [ ] **Step 5: Ejecutar los tests y verificar que pasan**

Run: `python manage.py test PedidosAlmacen.tests.ExportarPedidoVistaTest -v 2`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): filtrado por estado y permisos en exportar_pedido_pdf"
```

---

### Task 3: Conteos y variantes permitidas en `detalle_pedido`

Expone al template la lista de variantes que el usuario puede imprimir, cada una con su conteo de items.

**Files:**
- Modify: `PedidosAlmacen/views.py` (`detalle_pedido` ~líneas 241-269)
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `VISTAS_PEDIDO`, `_puede_vista_pedido` (Task 2).
- Produces: contexto `vistas_pdf: list[dict]` con claves `clave`, `label`, `count`, en el orden de `VISTAS_PEDIDO`.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `PedidosAlmacen/tests.py`:

```python
class DetallePedidoVistasPdfTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido, PedidoItem
        from django.urls import reverse
        self.reverse = reverse
        self.almacen = User.objects.create_superuser(username='alm2', password='x')
        self.tienda = User.objects.create_user(username='tnd2', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda.groups.add(g)
        self.pedido = Pedido.objects.create(solicitante=self.tienda)
        for codigo, estado in [('A', 'DESPACHADO'), ('B', 'BACK_ORDER'),
                               ('C', 'RECIBIDO'), ('D', 'PARCIAL')]:
            PedidoItem.objects.create(
                pedido=self.pedido, codigo=codigo, descripcion=codigo.lower(),
                cantidad_solicitada=1, estado=estado,
            )

    def test_almacen_ve_todas_las_variantes_con_conteo(self):
        self.client.force_login(self.almacen)
        resp = self.client.get(self.reverse('pedidos-detalle', args=[self.pedido.numero_pedido]))
        por_clave = {v['clave']: v['count'] for v in resp.context['vistas_pdf']}
        self.assertEqual(por_clave['todos'], 4)
        self.assertEqual(por_clave['despachado'], 1)
        self.assertEqual(por_clave['parcial'], 1)

    def test_tienda_no_ve_despachado_ni_parcial(self):
        self.client.force_login(self.tienda)
        resp = self.client.get(self.reverse('pedidos-detalle', args=[self.pedido.numero_pedido]))
        claves = [v['clave'] for v in resp.context['vistas_pdf']]
        self.assertNotIn('despachado', claves)
        self.assertNotIn('parcial', claves)
        self.assertIn('recibido', claves)
        self.assertIn('back_order', claves)
        self.assertIn('todos', claves)
```

- [ ] **Step 2: Ejecutar los tests y verificar que fallan**

Run: `python manage.py test PedidosAlmacen.tests.DetallePedidoVistasPdfTest -v 2`
Expected: FAIL — `KeyError: 'vistas_pdf'` (no está en el contexto).

- [ ] **Step 3: Calcular `vistas_pdf` y pasarlo al contexto**

En `detalle_pedido`, tras la línea `items = pedido.items.all()` (~línea 252), agregar:

```python
    from django.db.models import Count
    conteos = {
        fila['estado']: fila['c']
        for fila in items.values('estado').annotate(c=Count('id'))
    }
    total_items = items.count()
    vistas_pdf = []
    for clave, cfg in VISTAS_PEDIDO.items():
        if not _puede_vista_pedido(request.user, clave):
            continue
        count = total_items if cfg['estado'] is None else conteos.get(cfg['estado'], 0)
        vistas_pdf.append({'clave': clave, 'label': cfg['label'], 'count': count})
```

En el `render(...)`, añadir la clave al diccionario de contexto:

```python
        'vistas_pdf': vistas_pdf,
```

- [ ] **Step 4: Ejecutar los tests y verificar que pasan**

Run: `python manage.py test PedidosAlmacen.tests.DetallePedidoVistasPdfTest -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): expone variantes de impresion con conteo en detalle"
```

---

### Task 4: Modal de impresión en el template

Reemplaza el botón "Descargar PDF" por uno que abre un modal con las variantes permitidas; las variantes sin items quedan deshabilitadas.

**Files:**
- Modify: `templates/pedidos-detalle.html` (~líneas 7-14, botón de acciones)
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: contexto `vistas_pdf` (Task 3) y `pedido`.

- [ ] **Step 1: Escribir el test que falla**

Añadir al final de `PedidosAlmacen/tests.py`:

```python
class DetallePedidoModalTest(TestCase):
    def test_detalle_incluye_modal_y_variantes(self):
        from users.models import User
        from .models import Pedido, PedidoItem
        from django.urls import reverse
        almacen = User.objects.create_superuser(username='alm3', password='x')
        pedido = Pedido.objects.create(solicitante=almacen)
        PedidoItem.objects.create(pedido=pedido, codigo='A', descripcion='a',
                                  cantidad_solicitada=1, estado='DESPACHADO')
        self.client.force_login(almacen)
        resp = self.client.get(reverse('pedidos-detalle', args=[pedido.numero_pedido]))
        self.assertContains(resp, 'modalImprimirPedido')
        self.assertContains(resp, 'vista=despachado')
```

- [ ] **Step 2: Ejecutar el test y verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.DetallePedidoModalTest -v 2`
Expected: FAIL — el HTML no contiene `modalImprimirPedido`.

- [ ] **Step 3: Reemplazar el botón PDF por el disparador del modal**

En `templates/pedidos-detalle.html`, reemplazar el `<a>` del PDF (líneas 8-10):

```html
            <a href="{% url 'pedidos-pdf' pedido.numero_pedido %}" class="btn btn-outline-danger" title="Descargar PDF">
                <i class="fas fa-file-pdf"></i> <span class="d-none d-sm-inline">Descargar PDF</span>
            </a>
```

por:

```html
            <button type="button" class="btn btn-outline-danger" data-bs-toggle="modal" data-bs-target="#modalImprimirPedido" title="Imprimir PDF">
                <i class="fas fa-file-pdf"></i> <span class="d-none d-sm-inline">Imprimir PDF</span>
            </button>
```

- [ ] **Step 4: Añadir el markup del modal**

Inmediatamente después del `</div>` que cierra la cabecera de acciones (línea 15, el `</div>` que cierra `<div class="d-flex justify-content-between...">`), insertar:

```html
    <div class="modal fade" id="modalImprimirPedido" tabindex="-1" aria-labelledby="modalImprimirPedidoLabel" aria-hidden="true">
        <div class="modal-dialog">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="modalImprimirPedidoLabel">Imprimir pedido #{{ pedido.numero_pedido }}</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>
                </div>
                <div class="modal-body">
                    <p class="text-muted small mb-2">Elige qué items incluir en el PDF:</p>
                    <div class="list-group">
                        {% for v in vistas_pdf %}
                            {% if v.count > 0 %}
                            <a href="{% url 'pedidos-pdf' pedido.numero_pedido %}?vista={{ v.clave }}"
                               class="list-group-item list-group-item-action d-flex justify-content-between align-items-center">
                                {{ v.label }}
                                <span class="badge bg-secondary rounded-pill">{{ v.count }}</span>
                            </a>
                            {% else %}
                            <span class="list-group-item disabled d-flex justify-content-between align-items-center">
                                {{ v.label }}
                                <span class="badge bg-light text-muted rounded-pill">0</span>
                            </span>
                            {% endif %}
                        {% endfor %}
                    </div>
                </div>
            </div>
        </div>
    </div>
```

- [ ] **Step 5: Ejecutar el test y verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.DetallePedidoModalTest -v 2`
Expected: PASS.

- [ ] **Step 6: Verificación manual rápida**

Run: `python manage.py runserver` y abrir el detalle de un pedido. Confirmar que el botón "Imprimir PDF" abre el modal, que las variantes muestran su conteo, que las de conteo 0 aparecen deshabilitadas y que al elegir una se descarga el PDF correcto.

- [ ] **Step 7: Commit**

```bash
git add templates/pedidos-detalle.html PedidosAlmacen/tests.py
git commit -m "feat(pedidos): modal para imprimir pedido por variante de estado"
```

---

### Task 5: Verificación final

- [ ] **Step 1: Ejecutar toda la suite de la app**

Run: `python manage.py test PedidosAlmacen -v 2`
Expected: PASS (todas, incluidas las clases nuevas).

- [ ] **Step 2: Confirmar que no quedan referencias rotas al botón anterior**

Run: `grep -rn "Descargar PDF" templates/pedidos-detalle.html`
Expected: sin coincidencias (el botón del pedido ahora dice "Imprimir PDF"; el botón de despacho, si aplica, es independiente).

---

## Self-Review

**Cobertura del spec:**
- Variantes y filtrado por estado exacto → Task 1 (PDF) + Task 2 (filtro de items).
- PARCIAL como variante propia → incluido en `VISTAS_PEDIDO`/`_VISTA_CANTIDADES`.
- Permisos (Tienda limitada, validación servidor) → Task 2 (`_puede_vista_pedido`, redirect) + Task 3 (oculta opciones).
- Modal con conteos y opciones deshabilitadas → Task 3 (conteos) + Task 4 (markup).
- Nombre de archivo y título por variante → Task 1 (título) + Task 2 (filename).
- Casos borde (variante vacía, vista inválida, Tienda forzando) → tests en Task 2.

**Placeholders:** ninguno; todos los pasos incluyen código y comandos concretos.

**Consistencia de tipos/nombres:** `generar_pedido_pdf(..., vista=...)` definido en Task 1 y consumido igual en Task 2; `VISTAS_PEDIDO`/`_puede_vista_pedido` definidos en Task 2 y reusados en Task 3; contexto `vistas_pdf` (claves `clave`/`label`/`count`) producido en Task 3 y consumido en Task 4. Claves de variante (`todos`, `despachado`, `back_order`, `recibido`, `parcial`) idénticas entre `VISTAS_PEDIDO` (views) y `_VISTA_LABEL`/`_VISTA_CANTIDADES` (pdf).
