# Reporte de Items por Estado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new supervisor-only report in `PedidosAlmacen` that lists `PedidoItem` lines grouped by código de producto, with cantidades agregadas, existencia de almacén en vivo (DBISAM) y detalle expandible por pedido cuando un código tiene más de un pedido.

**Architecture:** Una nueva vista Django (`reporte_items`) agrega `PedidoItem` por `codigo` con `Sum`/`Count` de Django ORM, adjunta la existencia consultada en una sola llamada a `PedidosDBISAM.consultar_stock_multiple`, y renderiza un template que usa el sistema visual ya existente (`pd-header`, `pr-filter-card`, `pl-tabla`) más la funcionalidad nativa de **child rows de DataTables** (`row().child()`) para el detalle expandible — sin agregar ninguna dependencia nueva.

**Tech Stack:** Django ORM (Sum, Count, Max, Coalesce — ya importados en `views.py`), DataTables (ya vendorizado en `static/vendor/datatables/`), jQuery, Bootstrap 5.

## Global Constraints

- Spec de referencia: `docs/superpowers/specs/2026-08-03-reporte-items-estado-design.md` — seguirla al pie de la letra; cualquier desviación debe justificarse.
- Acceso restringido a grupo `Pedidos Supervisor` (`@user_passes_test(is_pedidos_supervisor, login_url='dashboard')`, ya definida en `PedidosAlmacen/views.py`).
- Sin filtro de fechas, sin export PDF, sin nuevas dependencias JS/CSS (no agregar la extensión RowGroup de DataTables).
- Tests se corren con: `venv\Scripts\python.exe manage.py test PedidosAlmacen --settings=Programarprecios.test_settings` (ver `PedidosAlmacen/tests.py` para el patrón de imports locales dentro de cada `setUp`).
- Mock de DBISAM siempre vía `patch('PedidosAlmacen.views.PedidosDBISAM')` (el target es el import dentro de `views.py`, no `PedidosAlmacen.dbisam.PedidosDBISAM`).

---

## Task 1: URL + vista con filtros, exclusión de ANULADO y agregación por código

**Files:**
- Modify: `PedidosAlmacen/urls.py`
- Modify: `PedidosAlmacen/views.py` (nueva función `reporte_items`, insertada después de `reporte_incidencias`)
- Create: `templates/pedidos-reporte-items.html` (versión mínima; se reemplaza completa en Task 3)
- Modify: `PedidosAlmacen/tests.py` (nueva clase `ReporteItemsTest`)

**Interfaces:**
- Consumes: `Pedido`, `PedidoItem` (ya importados en `views.py`), `is_pedidos_supervisor` (definida en el mismo archivo), `Sum`/`Count`/`Max`/`Value`/`Coalesce` (ya importados en `views.py`).
- Produces: vista `reporte_items(request)` registrada como url name `pedidos-reporte-items` en `/pedidos/reporte/items/`. Contexto:
  - `grupos`: lista de dicts, cada uno con claves `codigo`, `descripcion`, `total_solicitada`, `total_preparada`, `total_despachada`, `total_recibida`, `total_back_order`, `num_pedidos` (int), `detalle` (lista de instancias `PedidoItem`), `estados_badges` (lista ordenada de tuplas `(estado_code, estado_label)`), `detalle_json` (str JSON), `existencia` (siempre `None` hasta Task 2).
  - `codigos_filtro`, `categoria_filtro`, `estado_filtro`: strings (valor crudo de los filtros GET).
  - `categorias_disponibles`: queryset de dicts `{'categoria': ..., 'nombre': ...}`.
  - `estados_item`: `PedidoItem.ESTADO_ITEM_CHOICES`.

- [ ] **Step 1: Escribir los tests que fallan**

Modificar `PedidosAlmacen/tests.py` agregando al final del archivo:

```python
class ReporteItemsTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from django.urls import reverse
        from users.models import User
        from .models import Pedido, PedidoItem
        self.reverse = reverse

        self.g_supervisor, _ = Group.objects.get_or_create(name='Pedidos Supervisor')
        self.supervisor = User.objects.create_user(username='sup_items', password='x')
        self.supervisor.groups.add(self.g_supervisor)
        self.tienda = User.objects.create_user(username='tnd_items', password='x')

        # Código 01120044: 2 pedidos (PARCIAL + PENDIENTE) -> debe agruparse
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
        # Código 02030011: 1 solo pedido, categoría distinta -> no debe agruparse
        self.pedido3 = Pedido.objects.create(
            solicitante=self.supervisor, estado='RECIBIDO',
            categoria='PLOM', categoria_nombre='Plomería',
        )
        PedidoItem.objects.create(
            pedido=self.pedido3, codigo='02030011', descripcion='Cemento gris',
            cantidad_solicitada=80, cantidad_preparada=80, cantidad_despachada=80,
            cantidad_recibida=80, cantidad_back_order=0, estado='RECIBIDO',
        )
        # Pedido anulado -> su item nunca debe aparecer
        self.pedido_anulado = Pedido.objects.create(
            solicitante=self.supervisor, estado='ANULADO', motivo_anulacion='x',
        )
        PedidoItem.objects.create(
            pedido=self.pedido_anulado, codigo='99999999', descripcion='No debe aparecer',
            cantidad_solicitada=5, estado='PENDIENTE',
        )

    def test_no_supervisor_redirige(self):
        self.client.force_login(self.tienda)
        resp = self.client.get(self.reverse('pedidos-reporte-items'))
        self.assertEqual(resp.status_code, 302)

    def test_supervisor_accede(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'))
        self.assertEqual(resp.status_code, 200)

    def test_excluye_pedidos_anulados_por_defecto(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'))
        codigos = [g['codigo'] for g in resp.context['grupos']]
        self.assertNotIn('99999999', codigos)

    def test_agrega_cantidades_de_multiples_pedidos_del_mismo_codigo(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'))
        grupos_por_codigo = {g['codigo']: g for g in resp.context['grupos']}
        grupo = grupos_por_codigo['01120044']
        self.assertEqual(grupo['num_pedidos'], 2)
        self.assertEqual(grupo['total_solicitada'], 50)
        self.assertEqual(grupo['total_preparada'], 40)
        self.assertEqual(grupo['total_despachada'], 25)
        self.assertEqual(grupo['total_recibida'], 25)
        self.assertEqual(grupo['total_back_order'], 15)

    def test_codigo_con_un_solo_pedido_no_se_agrupa(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'))
        grupos_por_codigo = {g['codigo']: g for g in resp.context['grupos']}
        self.assertEqual(grupos_por_codigo['02030011']['num_pedidos'], 1)

    def test_filtro_por_codigo_unico(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'), {'codigos': '02030011'})
        codigos = [g['codigo'] for g in resp.context['grupos']]
        self.assertEqual(codigos, ['02030011'])

    def test_filtro_por_multiples_codigos(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'), {'codigos': '01120044, 02030011'})
        codigos = sorted(g['codigo'] for g in resp.context['grupos'])
        self.assertEqual(codigos, ['01120044', '02030011'])

    def test_filtro_por_categoria(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'), {'categoria': 'PLOM'})
        codigos = [g['codigo'] for g in resp.context['grupos']]
        self.assertEqual(codigos, ['02030011'])

    def test_filtro_por_estado(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'), {'estado': 'PENDIENTE'})
        codigos = [g['codigo'] for g in resp.context['grupos']]
        self.assertEqual(codigos, ['01120044'])
        grupo = resp.context['grupos'][0]
        self.assertEqual(grupo['num_pedidos'], 1)
        self.assertEqual(grupo['total_solicitada'], 10)
```

- [ ] **Step 2: Ejecutar los tests para confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ReporteItemsTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL — `NoReverseMatch: Reverse for 'pedidos-reporte-items' not found` (la url todavía no existe).

- [ ] **Step 3: Agregar la url**

En `PedidosAlmacen/urls.py`, dentro de la lista `urlpatterns`, agregar esta línea inmediatamente después de la línea de `pedidos-reporte-incidencias`:

```python
    path('pedidos/reporte/items/', views.reporte_items, name='pedidos-reporte-items'),
```

(queda entre `path('pedidos/reporte/incidencias/', ...)` y `path('pedidos/incidencias/resolver/', ...)`).

- [ ] **Step 4: Crear el template mínimo**

Crear `templates/pedidos-reporte-items.html`:

```html
{% extends "dashboard.html" %}
{% load permisos_tags %}
{% block content %}
<div class="pd-header">
    <div class="pd-header-left">
        <div>
            <span class="pd-header-eyebrow">Almacén</span>
            <div class="pd-header-title-row">
                <h1 class="pd-header-num">Reporte de Items por Estado</h1>
            </div>
        </div>
    </div>
</div>
<p>{{ grupos|length }} código{{ grupos|length|pluralize }} encontrado{{ grupos|length|pluralize }}.</p>
<style>
.pd-header { background:#2e353d; color:#fff; border-radius:12px; padding:1.1rem 1.5rem; margin-bottom:1.25rem; }
.pd-header-eyebrow { display:block; font-size:0.62rem; font-weight:700; letter-spacing:0.1em; text-transform:uppercase; color:rgba(255,255,255,0.45); }
.pd-header-num { font-size:1.5rem; font-weight:700; margin:0; }
</style>
{% endblock content %}
```

- [ ] **Step 5: Implementar la vista `reporte_items`**

En `PedidosAlmacen/views.py`, buscar el final de `reporte_incidencias` (justo antes de `def _sku_incidencia`):

```python
        'fecha_fin': fecha_fin,
        'tipo_filtro': tipo_filtro,
        'tipos_incidencia': TIPOS_INCIDENCIA,
    })


def _sku_incidencia(di: DespachoItem) -> str:
```

Reemplazar por (agregando la nueva función entre ambas):

```python
        'fecha_fin': fecha_fin,
        'tipo_filtro': tipo_filtro,
        'tipos_incidencia': TIPOS_INCIDENCIA,
    })


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def reporte_items(request):
    codigos_raw = request.GET.get('codigos', '').strip()
    categoria_filtro = request.GET.get('categoria', '')
    estado_filtro = request.GET.get('estado', '')

    pedidos = Pedido.objects.exclude(estado='ANULADO')
    items = PedidoItem.objects.filter(pedido__in=pedidos)

    if codigos_raw:
        codigos_lista = [c.strip() for c in codigos_raw.split(',') if c.strip()]
        items = items.filter(codigo__in=codigos_lista)
    if categoria_filtro:
        items = items.filter(pedido__categoria=categoria_filtro)
    if estado_filtro:
        items = items.filter(estado=estado_filtro)

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
        detalle_items = (
            items.filter(codigo__in=codigos_pagina)
            .select_related('pedido')
            .order_by('codigo', 'pedido_id')
        )
        for item in detalle_items:
            detalle_por_codigo.setdefault(item.codigo, []).append(item)

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
        ])
        grupo['existencia'] = None  # se completa en la Task 2

    categorias_disponibles = (
        Pedido.objects.exclude(categoria='')
        .values('categoria')
        .annotate(nombre=Max('categoria_nombre'))
        .order_by('categoria')
    )

    return render(request, 'pedidos-reporte-items.html', {
        'grupos': grupos,
        'codigos_filtro': codigos_raw,
        'categoria_filtro': categoria_filtro,
        'estado_filtro': estado_filtro,
        'categorias_disponibles': categorias_disponibles,
        'estados_item': PedidoItem.ESTADO_ITEM_CHOICES,
    })


def _sku_incidencia(di: DespachoItem) -> str:
```

No se requieren nuevos imports: `Sum`, `Count`, `Max`, `Value`, `Coalesce`, `Pedido`, `PedidoItem`, `json`, `login_required`, `user_passes_test`, `is_pedidos_supervisor` ya están importados/definidos en el archivo.

- [ ] **Step 6: Ejecutar los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ReporteItemsTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (9 tests).

- [ ] **Step 7: Commit**

```bash
git add PedidosAlmacen/urls.py PedidosAlmacen/views.py PedidosAlmacen/tests.py templates/pedidos-reporte-items.html
git commit -m "feat(pedidos): vista de reporte de items agrupado por codigo con filtros"
```

---

## Task 2: Existencia de almacén vía DBISAM (con fallback N/D)

**Files:**
- Modify: `PedidosAlmacen/views.py` (dentro de `reporte_items`)
- Modify: `PedidosAlmacen/tests.py` (agregar tests a `ReporteItemsTest`)

**Interfaces:**
- Consumes: `PedidosDBISAM` (ya importado en `views.py`), método `consultar_stock_multiple(codigos, deposito=None) -> dict[str, int]` (lanza excepción si falla la conexión).
- Produces: `grupo['existencia']` ahora es `int` (existencia real, 0 si el código no está en SINVDEP) cuando DBISAM responde, o `None` para TODOS los grupos si la consulta falla (fallback N/D). En ese caso se agrega un mensaje `messages.warning(...)` al request.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a la clase `ReporteItemsTest` en `PedidosAlmacen/tests.py`:

```python
    def test_existencia_ok(self):
        from unittest.mock import patch
        self.client.force_login(self.supervisor)
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.consultar_stock_multiple.return_value = {
                '01120044': 128, '02030011': 340,
            }
            resp = self.client.get(self.reverse('pedidos-reporte-items'))
        grupos_por_codigo = {g['codigo']: g for g in resp.context['grupos']}
        self.assertEqual(grupos_por_codigo['01120044']['existencia'], 128)
        self.assertEqual(grupos_por_codigo['02030011']['existencia'], 340)

    def test_existencia_codigo_sin_stock_es_cero(self):
        from unittest.mock import patch
        self.client.force_login(self.supervisor)
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.consultar_stock_multiple.return_value = {'01120044': 128}
            resp = self.client.get(self.reverse('pedidos-reporte-items'))
        grupos_por_codigo = {g['codigo']: g for g in resp.context['grupos']}
        self.assertEqual(grupos_por_codigo['02030011']['existencia'], 0)

    def test_existencia_fallback_nd_si_dbisam_falla(self):
        from unittest.mock import patch
        self.client.force_login(self.supervisor)
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.consultar_stock_multiple.side_effect = Exception('DBISAM caído')
            resp = self.client.get(self.reverse('pedidos-reporte-items'))
        self.assertEqual(resp.status_code, 200)
        for grupo in resp.context['grupos']:
            self.assertIsNone(grupo['existencia'])
        mensajes = [str(m) for m in resp.context['messages']]
        self.assertTrue(any('existencia' in m.lower() for m in mensajes))
```

- [ ] **Step 2: Ejecutar los tests para confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ReporteItemsTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL en los 3 tests nuevos — `grupo['existencia']` es siempre `None` (todavía hardcodeado en Task 1).

- [ ] **Step 3: Implementar la consulta de existencia**

En `PedidosAlmacen/views.py`, dentro de `reporte_items`, reemplazar:

```python
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
        ])
        grupo['existencia'] = None  # se completa en la Task 2
```

por:

```python
    existencia_por_codigo = {}
    stock_no_disponible = False
    if codigos_pagina:
        try:
            dbisam = PedidosDBISAM()
            existencia_por_codigo = dbisam.consultar_stock_multiple(codigos_pagina)
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
        ])
        grupo['existencia'] = None if stock_no_disponible else existencia_por_codigo.get(grupo['codigo'], 0)
```

- [ ] **Step 4: Ejecutar los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ReporteItemsTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): existencia de almacen en reporte de items via DBISAM con fallback N/D"
```

---

## Task 3: Template completo (filtros, tabla agrupada, detalle expandible con child rows de DataTables)

**Files:**
- Modify: `templates/pedidos-reporte-items.html` (reemplazo completo del archivo mínimo de Task 1)
- Modify: `PedidosAlmacen/tests.py` (agregar tests de contenido renderizado a `ReporteItemsTest`)

**Interfaces:**
- Consumes: todas las claves de contexto producidas en Task 1/2 (`grupos`, `codigos_filtro`, `categoria_filtro`, `estado_filtro`, `categorias_disponibles`, `estados_item`), y las urls `pedidos-lista`, `pedidos-detalle`, `pedidos-reporte-items` (ya existentes/creada en Task 1).
- Produces: HTML renderizado consumido únicamente por el navegador (no hay otras tasks que dependan de su estructura interna).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `ReporteItemsTest` en `PedidosAlmacen/tests.py`:

```python
    def test_template_muestra_boton_detalle_para_codigo_con_multiples_pedidos(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'))
        self.assertContains(resp, 'grp-detail-btn')
        self.assertContains(resp, '01120044')

    def test_template_no_muestra_boton_detalle_para_codigo_de_un_solo_pedido(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'), {'codigos': '02030011'})
        self.assertNotContains(resp, 'grp-detail-btn')
        self.assertContains(resp, 'grp-no-detail')

    def test_template_muestra_nd_cuando_falla_dbisam(self):
        from unittest.mock import patch
        self.client.force_login(self.supervisor)
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.consultar_stock_multiple.side_effect = Exception('caído')
            resp = self.client.get(self.reverse('pedidos-reporte-items'))
        self.assertContains(resp, 'N/D')

    def test_template_incluye_filtros_aplicados_en_el_formulario(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('pedidos-reporte-items'), {'codigos': '02030011', 'categoria': 'PLOM'})
        self.assertContains(resp, 'value="02030011"')
        self.assertContains(resp, 'selected')
```

- [ ] **Step 2: Ejecutar los tests para confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ReporteItemsTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL en los 4 tests nuevos (el template mínimo de Task 1 no tiene filtros, tabla, ni clases `grp-*`).

- [ ] **Step 3: Reemplazar el template completo**

Reemplazar TODO el contenido de `templates/pedidos-reporte-items.html` por:

```html
{% extends "dashboard.html" %}
{% load permisos_tags %}
{% block content %}
{% load static %}
<link rel="stylesheet" href="{% static 'vendor/datatables/css/dataTables.bootstrap5.min.css' %}">
<script src="{% static 'vendor/jquery/jquery-3.6.0.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/jquery.dataTables.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/dataTables.bootstrap5.min.js' %}"></script>

<!-- HEADER OSCURO -->
<div class="pd-header">
    <div class="pd-header-left">
        <div>
            <span class="pd-header-eyebrow">Almacén</span>
            <div class="pd-header-title-row">
                <h1 class="pd-header-num">Reporte de Items por Estado</h1>
            </div>
        </div>
    </div>
    <div class="pd-header-actions">
        <a href="{% url 'pedidos-lista' %}" class="btn btn-sm btn-outline-light">
            <i class="fas fa-arrow-left"></i> <span class="d-none d-sm-inline">Volver a Pedidos</span>
        </a>
    </div>
</div>

{% if messages %}
    {% for message in messages %}
    <div class="alert alert-{{ message.tags }} alert-dismissible fade show mb-3" role="alert">
        {{ message }}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    </div>
    {% endfor %}
{% endif %}

<!-- FILTROS -->
<div class="pr-filter-card mb-4">
    <div class="pr-filter-header">
        <span class="pr-filter-label"><i class="fas fa-filter me-1"></i>Filtros</span>
    </div>
    <form method="get" class="pr-filter-body">
        <div class="pr-filter-fields">
            <div class="pr-filter-field pr-filter-field--wide">
                <label class="pr-field-label">Código(s) de producto</label>
                <input type="text" name="codigos" class="form-control form-control-sm"
                       value="{{ codigos_filtro }}" placeholder="Ej: 01010001, 01010002">
            </div>
            <div class="pr-filter-field">
                <label class="pr-field-label">Categoría</label>
                <select name="categoria" class="form-select form-select-sm">
                    <option value="">Todas</option>
                    {% for cat in categorias_disponibles %}
                    <option value="{{ cat.categoria }}" {% if categoria_filtro == cat.categoria %}selected{% endif %}>
                        {% if cat.nombre %}{{ cat.nombre }}{% else %}{{ cat.categoria }}{% endif %}
                    </option>
                    {% endfor %}
                </select>
            </div>
            <div class="pr-filter-field">
                <label class="pr-field-label">Estado del item</label>
                <select name="estado" class="form-select form-select-sm">
                    <option value="">Todos</option>
                    {% for value, label in estados_item %}
                    <option value="{{ value }}" {% if estado_filtro == value %}selected{% endif %}>{{ label }}</option>
                    {% endfor %}
                </select>
            </div>
        </div>
        <div class="pr-filter-actions">
            <button type="submit" class="btn btn-sm btn-primary">
                <i class="fas fa-search"></i> Aplicar
            </button>
            <a href="{% url 'pedidos-reporte-items' %}" class="btn btn-sm btn-outline-secondary" title="Limpiar filtros">
                <i class="fas fa-times"></i>
            </a>
        </div>
    </form>
</div>

<!-- TABLA -->
<div class="pl-table-card">
    <table id="tablaItems" class="table table-hover pl-tabla" style="width:100%">
        <thead>
            <tr>
                <th>Código</th>
                <th>Descripción</th>
                <th>Pedido</th>
                <th>Estado</th>
                <th class="num">Solicit.</th>
                <th class="num">Preparada</th>
                <th class="num">Despach.</th>
                <th class="num">Recibida</th>
                <th class="num">Back Order</th>
                <th class="num">Existencia</th>
                <th>Detalle</th>
            </tr>
        </thead>
        <tbody>
            {% for grupo in grupos %}
            <tr data-detalle='{{ grupo.detalle_json }}'>
                <td class="pl-codigo">
                    {{ grupo.codigo }}
                    {% if grupo.num_pedidos > 1 %}<span class="grp-count">{{ grupo.num_pedidos }} pedidos</span>{% endif %}
                </td>
                <td class="descripcion">{{ grupo.descripcion }}</td>
                <td>
                    {% if grupo.num_pedidos == 1 %}
                        <a class="pl-num-link" href="{% url 'pedidos-detalle' grupo.detalle.0.pedido_id %}">#{{ grupo.detalle.0.pedido_id }}</a>
                    {% else %}—{% endif %}
                </td>
                <td>
                    {% for estado_code, estado_label in grupo.estados_badges %}
                    <span class="badge badge-estado-{{ estado_code|lower }}">{{ estado_label }}</span>
                    {% endfor %}
                </td>
                <td class="num">{{ grupo.total_solicitada }}</td>
                <td class="num">{{ grupo.total_preparada }}</td>
                <td class="num">{{ grupo.total_despachada }}</td>
                <td class="num">{{ grupo.total_recibida }}</td>
                <td class="num">{{ grupo.total_back_order }}</td>
                <td class="num">
                    {% if grupo.existencia is None %}
                        <span class="existencia-nd" title="No se pudo consultar a2 al generar el reporte">N/D</span>
                    {% elif grupo.existencia == 0 %}
                        <span class="existencia-cero">{{ grupo.existencia }}</span>
                    {% elif grupo.existencia < 10 %}
                        <span class="existencia-baja">{{ grupo.existencia }}</span>
                    {% else %}
                        <span class="existencia-ok">{{ grupo.existencia }}</span>
                    {% endif %}
                </td>
                <td>
                    {% if grupo.num_pedidos > 1 %}
                    <button type="button" class="grp-detail-btn">
                        <span class="grp-caret">▶</span> Detalle
                    </button>
                    {% else %}
                    <span class="grp-no-detail">—</span>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>

<style>
/* ── pd-header (compartido con el resto de reportes) ── */
.pd-header          { background:#2e353d; color:#fff; border-radius:12px; padding:1.1rem 1.5rem; display:flex; align-items:center; justify-content:space-between; gap:1rem; flex-wrap:wrap; margin-bottom:1.25rem; box-shadow:0 2px 12px rgba(0,0,0,0.12); }
.pd-header-left     { display:flex; align-items:center; gap:1rem; flex-wrap:wrap; }
.pd-header-eyebrow  { display:block; font-size:0.62rem; font-weight:700; letter-spacing:0.1em; text-transform:uppercase; color:rgba(255,255,255,0.45); margin-bottom:0.1rem; }
.pd-header-title-row{ display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap; }
.pd-header-num      { font-size:1.5rem; font-weight:700; margin:0; letter-spacing:-0.01em; line-height:1; }
.pd-header-actions  { display:flex; gap:0.5rem; flex-wrap:wrap; }

/* ── Filtros ── */
.pr-filter-card     { background:#fff; border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,0.06); overflow:hidden; }
.pr-filter-header   { padding:0.6rem 1.25rem; border-bottom:1px solid #e9ecef; background:#f8f9fa; }
.pr-filter-label    { font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#6c757d; }
.pr-filter-body     { padding:1rem 1.25rem; display:flex; align-items:flex-end; gap:1rem; flex-wrap:wrap; }
.pr-filter-fields   { display:flex; gap:0.75rem; flex-wrap:wrap; flex:1; }
.pr-filter-field    { display:flex; flex-direction:column; gap:0.25rem; min-width:130px; flex:1; }
.pr-filter-field--wide { min-width:260px; flex:1.6; }
.pr-field-label     { font-size:0.72rem; font-weight:600; color:#495057; margin:0; }
.pr-filter-actions  { display:flex; gap:0.5rem; align-items:flex-end; flex-shrink:0; }

/* ── Tarjeta de tabla ── */
.pl-table-card { background:#fff; border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,0.06); overflow:hidden; margin-bottom:1.25rem; }
.pl-dt-top { padding:0.75rem 1.25rem; border-bottom:1px solid #e9ecef; display:flex; align-items:center; justify-content:flex-end; }
.pl-dt-top .dataTables_filter { display:flex; align-items:center; }
.pl-dt-top .dataTables_filter label { display:flex; align-items:center; gap:0.5rem; font-size:0.75rem; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; color:#6c757d; margin:0; white-space:nowrap; }
.pl-dt-top .dataTables_filter input { border:1.5px solid #e9ecef; border-radius:8px; padding:0.38rem 0.75rem; font-size:0.84rem; outline:none; min-width:200px; color:#212529; background:#fff; }
.pl-dt-bot { padding:0.65rem 1.25rem; border-top:1px solid #e9ecef; display:flex; align-items:center; justify-content:space-between; gap:0.5rem; flex-wrap:wrap; }
.pl-dt-bot .dataTables_info { font-size:0.78rem; color:#6c757d; padding:0; }
.pl-dt-bot .pagination { margin:0; }
.pl-dt-bot .page-link { font-size:0.8rem; padding:0.3rem 0.6rem; }

/* ── Tabla interna ── */
.pl-tabla thead th  { font-size:0.7rem; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; color:#6c757d; background:#f8f9fa !important; border-bottom:2px solid #e9ecef !important; padding:0.6rem 0.75rem; white-space:nowrap; }
.pl-tabla thead th.num { text-align:right; }
.pl-tabla tbody td  { font-size:0.875rem; vertical-align:middle; padding:0.6rem 0.75rem; border-bottom:1px solid #f4f6f8; }
.pl-tabla tbody td.num { text-align:right; font-variant-numeric: tabular-nums; }
.pl-tabla tbody tr:last-child td { border-bottom:none; }
.pl-tabla tbody tr:hover td { background:#f8f9fc; }
.pl-tabla td.descripcion { max-width:260px; }

.pl-num-link { font-family:'Consolas','Courier New',monospace; font-size:0.8rem; font-weight:700; color:#1a56db; text-decoration:none; background:#e8f0ff; padding:0.15em 0.45em; border-radius:4px; white-space:nowrap; }
.pl-codigo { font-family:'Consolas','Courier New',monospace; font-size:0.82rem; font-weight:700; color:#495057; }

.badge { display:inline-flex; align-items:center; font-size:0.72rem; font-weight:600; padding:0.32em 0.62em; border-radius:5px; line-height:1; white-space:nowrap; margin-right:0.25em; }
.badge-estado-pendiente            { background:#fff3cd; color:#7a5c00; }
.badge-estado-despachado           { background:#0d6efd; color:#fff; }
.badge-estado-parcial              { background:#fd7e14; color:#fff; }
.badge-estado-recibido             { background:#198754; color:#fff; }
.badge-estado-back_order           { background:#e9ecef; color:#495057; }
.badge-estado-incidencia           { background:#f8d7da; color:#7a1420; }
.badge-estado-incidencia_resuelta  { background:#cff4fc; color:#055160; }
.badge-estado-cerrado              { background:#2e353d; color:#fff; }

.existencia-ok    { color:#198754; font-weight:700; font-family:'Consolas','Courier New',monospace; }
.existencia-baja   { color:#d39e00; font-weight:700; font-family:'Consolas','Courier New',monospace; }
.existencia-cero  { color:#dc3545; font-weight:700; font-family:'Consolas','Courier New',monospace; }
.existencia-nd    { color:#adb5bd; font-style:italic; font-size:0.78rem; }

.grp-count { font-weight:500; font-size:0.7rem; color:#868e96; background:#eef0f2; border-radius:10px; padding:0.1em 0.55em; margin-left:0.4rem; }
.grp-detail-btn { display:inline-flex; align-items:center; gap:0.4rem; font-size:0.74rem; font-weight:600; color:#495057; background:#fff; border:1.5px solid #dee2e6; border-radius:6px; padding:0.28rem 0.65rem; cursor:pointer; }
.grp-detail-btn:hover { background:#eef1fa; border-color:#c8d1e0; }
.grp-detail-btn .grp-caret { display:inline-block; font-size:0.65rem; color:#868e96; transition:transform 0.15s; }
.grp-detail-btn.is-open .grp-caret { transform:rotate(90deg); }
.grp-no-detail { font-size:0.75rem; color:#ced4da; }
.grp-child-pedido { font-family:'Consolas','Courier New',monospace; font-size:0.78rem; }
.grp-child-table td { padding-top:0.4rem; padding-bottom:0.4rem; color:#495057; border-bottom:1px solid #f4f6f8; }
.grp-child-table td:first-child { padding-left:1.9rem; }

/* ── Responsive ── */
@media (max-width: 767px) {
    .pd-header-num { font-size:1.25rem; }
    .pd-header     { padding:0.9rem 1rem; }
}
</style>

<script>
var PEDIDO_URL_TEMPLATE = "{% url 'pedidos-detalle' 0 %}";

function formatDetalleItems(lineas) {
    var filas = lineas.map(function (l) {
        var url = PEDIDO_URL_TEMPLATE.replace('/0/', '/' + l.pedido + '/');
        return '<tr>' +
            '<td></td><td></td>' +
            '<td class="grp-child-pedido">↳ <a class="pl-num-link" href="' + url + '">#' + l.pedido + '</a></td>' +
            '<td><span class="badge badge-estado-' + l.estado_code.toLowerCase() + '">' + l.estado + '</span></td>' +
            '<td class="num">' + l.solicitada + '</td>' +
            '<td class="num">' + l.preparada + '</td>' +
            '<td class="num">' + l.despachada + '</td>' +
            '<td class="num">' + l.recibida + '</td>' +
            '<td class="num">' + l.back_order + '</td>' +
            '<td class="num">—</td>' +
            '<td></td>' +
        '</tr>';
    }).join('');
    return '<table class="pl-tabla grp-child-table" style="width:100%; margin:0;">' + filas + '</table>';
}

$(document).ready(function () {
    var table = $('#tablaItems').DataTable({
        language: { url: "/static/vendor/datatables/i18n/es-ES.json" },
        paging: true,
        searching: true,
        ordering: true,
        info: true,
        lengthChange: false,
        order: [[0, 'asc']],
        pageLength: 25,
        columnDefs: [{ orderable: false, targets: -1 }],
        dom: "<'pl-dt-top'f><'table-responsive'tr><'pl-dt-bot'ip>",
    });

    $('#tablaItems tbody').on('click', 'button.grp-detail-btn', function () {
        var btn = $(this);
        var tr = btn.closest('tr');
        var row = table.row(tr);
        if (row.child.isShown()) {
            row.child.hide();
            btn.removeClass('is-open');
        } else {
            var detalle = JSON.parse(tr.attr('data-detalle') || '[]');
            row.child(formatDetalleItems(detalle)).show();
            btn.addClass('is-open');
        }
    });
});
</script>
{% endblock content %}
```

- [ ] **Step 4: Ejecutar los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ReporteItemsTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (16 tests).

- [ ] **Step 5: Verificación manual en navegador**

Levantar el servidor (`venv\Scripts\python.exe manage.py runserver --settings=Programarprecios.test_settings`), iniciar sesión como usuario del grupo `Pedidos Supervisor`, navegar a `/pedidos/reporte/items/` y confirmar visualmente:
- La tabla carga con DataTables (buscador y paginación visibles).
- Un código con 2+ pedidos muestra el botón "Detalle"; al hacer clic expande una subtabla con las líneas de cada pedido y el caret rota; un segundo clic la colapsa.
- Un código de un solo pedido no muestra botón (solo "—").
- Los filtros de código/categoría/estado, al aplicarse, recargan la página con los valores reflejados en el formulario.

- [ ] **Step 6: Commit**

```bash
git add templates/pedidos-reporte-items.html PedidosAlmacen/tests.py
git commit -m "feat(pedidos): template del reporte de items con detalle expandible via child rows"
```

---

## Task 4: Link en el menú de dashboard.html

**Files:**
- Modify: `templates/dashboard.html`
- Modify: `PedidosAlmacen/tests.py` (agregar clase `MenuReporteItemsTest`)

**Interfaces:**
- Consumes: url `pedidos-reporte-items` (creada en Task 1), filtro de template `has_group` (`permisos_tags`, ya usado en el resto de `dashboard.html`).
- Produces: nada consumido por otras tasks — es el punto final de integración visible para el usuario.

- [ ] **Step 1: Escribir el test que falla**

Agregar al final de `PedidosAlmacen/tests.py`:

```python
class MenuReporteItemsTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from django.urls import reverse
        from users.models import User
        self.reverse = reverse
        self.g_supervisor, _ = Group.objects.get_or_create(name='Pedidos Supervisor')
        self.supervisor = User.objects.create_user(username='sup_menu', password='x')
        self.supervisor.groups.add(self.g_supervisor)
        self.tienda = User.objects.create_user(username='tnd_menu', password='x')

    def test_supervisor_ve_el_link_en_el_menu(self):
        self.client.force_login(self.supervisor)
        resp = self.client.get(self.reverse('dashboard'))
        self.assertContains(resp, '/pedidos/reporte/items/')

    def test_no_supervisor_no_ve_el_link(self):
        self.client.force_login(self.tienda)
        resp = self.client.get(self.reverse('dashboard'))
        self.assertNotContains(resp, '/pedidos/reporte/items/')
```

- [ ] **Step 2: Ejecutar el test para confirmar que falla**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.MenuReporteItemsTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL en `test_supervisor_ve_el_link_en_el_menu` (el link todavía no existe en `dashboard.html`).

- [ ] **Step 3: Agregar el link al menú**

En `templates/dashboard.html`, reemplazar:

```html
                        {% if request.user|has_group:"Pedidos Supervisor" %}
                        <li><a href="/pedidos/reporte/">Reporte</a></li>
                        <li><a href="/pedidos/incidencias/resolver/">Incidencias</a></li>
                        {% endif %}
```

por:

```html
                        {% if request.user|has_group:"Pedidos Supervisor" %}
                        <li><a href="/pedidos/reporte/">Reporte</a></li>
                        <li><a href="/pedidos/reporte/items/">Reporte de Items</a></li>
                        <li><a href="/pedidos/incidencias/resolver/">Incidencias</a></li>
                        {% endif %}
```

- [ ] **Step 4: Ejecutar los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.MenuReporteItemsTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Ejecutar toda la suite de `PedidosAlmacen` para descartar regresiones**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen --settings=Programarprecios.test_settings`
Expected: PASS (todos los tests existentes + los 18 nuevos de este plan).

- [ ] **Step 6: Commit**

```bash
git add templates/dashboard.html PedidosAlmacen/tests.py
git commit -m "feat(pedidos): link al reporte de items en el menu de Pedidos Supervisor"
```

---

## Self-Review Notes

- **Cobertura del spec:** las 7 decisiones de la spec están cubiertas — unidad de fila por código (Task 1), detalle expandible con child rows nativos de DataTables (Task 3), filtros código/categoría/estado (Task 1), sin fechas + exclusión ANULADO (Task 1), existencia en vivo con fallback N/D (Task 2), sin export PDF (ninguna task lo agrega), permisos Pedidos Supervisor (Task 1 + Task 4).
- **Consistencia de tipos:** `grupo['existencia']` es `int | None` en todas las tasks; `grupo['detalle']` siempre lista de `PedidoItem`; `grupo['detalle_json']` siempre `str`. El JS consume las mismas claves (`pedido`, `estado`, `estado_code`, `solicitada`, `preparada`, `despachada`, `recibida`, `back_order`) que la vista serializa — verificado.
- **Sin placeholders:** cada step contiene código completo y ejecutable; ningún "TODO" ni "similar a la Task N" sin repetir el código.
