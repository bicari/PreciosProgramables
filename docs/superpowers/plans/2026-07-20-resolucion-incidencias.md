# Módulo de Resolución de Incidencias — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Módulo operativo donde un supervisor resuelve incidencias de despachos registrando el número de traslado interno de a2 (validado contra DBISAM) o una resolución manual, con historial de eventos y anulación reversible.

**Architecture:** Dos modelos nuevos en PostgreSQL (`ResolucionIncidencia` agrupa incidencias resueltas juntas; `IncidenciaEvento` es un log inmutable por item) más un FK denormalizado `DespachoItem.resolucion` que apunta a la resolución activa. Un método nuevo en `PedidosDBISAM` valida contra a2 que el documento existe como traslado (SOPERACIONINV, FTI_TIPO=1) y devuelve los SKUs de su detalle (SDETALLEINV). Cuatro vistas: página GET con pestañas Pendientes/Resueltas, endpoint AJAX de validación, POST de confirmación (revalida en servidor, transacción atómica) y POST de anulación.

**Tech Stack:** Django 4.x, PostgreSQL, pyodbc/DBISAM (SQL92), Bootstrap 5 + FontAwesome (plantillas existentes), tests con `django.test.TestCase` + `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-07-20-resolucion-incidencias-design.md`

## Global Constraints

- UI, mensajes y docstrings en español; código PEP 8 con type hints.
- SQL DBISAM: SQL92 sin CTEs ni EXISTS, sin placeholders `?` — f-strings con validación previa del input (regex sobre el documento).
- Estado nuevo de `PedidoItem`: `'INCIDENCIA_RESUELTA'` (19 chars, cabe en `max_length=20`).
- Permisos: todas las vistas nuevas con `@user_passes_test(is_pedidos_supervisor, login_url='dashboard')`.
- Tests: `python manage.py test PedidosAlmacen.tests.<Clase> -v 2` (venv activado, desde la raíz del repo).
- Migración nueva será la `0023` (última existente: `0022_configuracion_pedidos_y_deposito_transito.py`).
- Commits frecuentes; no tocar los archivos modificados sin commitear que ya están en el working tree salvo los indicados en cada tarea.

---

### Task 1: Modelos `ResolucionIncidencia`, `IncidenciaEvento` y estado `INCIDENCIA_RESUELTA`

**Files:**
- Modify: `PedidosAlmacen/models.py` (choices de `PedidoItem` línea ~59; FK en `DespachoItem` línea ~140; modelos nuevos al final del archivo)
- Create: `PedidosAlmacen/migrations/0023_resolucion_incidencias.py` (vía makemigrations)
- Test: `PedidosAlmacen/tests.py` (agregar clase al final)

**Interfaces:**
- Consumes: `Pedido`, `PedidoItem`, `Despacho`, `DespachoItem`, `users.models.User` (existentes).
- Produces:
  - `ResolucionIncidencia(tipo: 'TRASLADO'|'MANUAL', documento_traslado: str, observacion: str, resuelto_por: User, fecha_resolucion: datetime, estado: 'ACTIVA'|'ANULADA', anulada_por: User|None, fecha_anulacion: datetime|None, motivo_anulacion: str)` con related_name `items_resueltos` (desde DespachoItem) y `eventos` (desde IncidenciaEvento).
  - `IncidenciaEvento(despacho_item: DespachoItem, resolucion: ResolucionIncidencia, tipo_evento: 'RESOLUCION'|'ANULACION', usuario: User|None, fecha: datetime, detalle: str)` con related_name `eventos_incidencia` en DespachoItem.
  - `DespachoItem.resolucion: FK nullable a ResolucionIncidencia` (null = incidencia pendiente).
  - `PedidoItem.ESTADO_ITEM_CHOICES` incluye `('INCIDENCIA_RESUELTA', 'Incidencia Resuelta')`.

- [ ] **Step 1: Escribir el test que falla**

Al final de `PedidosAlmacen/tests.py`:

```python
class ResolucionIncidenciaModelTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, PedidoItem, Despacho, DespachoItem
        self.user = User.objects.create_superuser(username='sup_ri', password='x')
        self.pedido = Pedido.objects.create(solicitante=self.user, estado='PARCIAL')
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='Producto 1',
            cantidad_solicitada=5, estado='INCIDENCIA',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='PARCIAL')
        self.di = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item,
            cantidad_despachada=5, tipo_incidencia='CANTIDAD_MENOR',
        )

    def test_estado_incidencia_resuelta_en_choices(self):
        from .models import PedidoItem
        self.assertIn(
            ('INCIDENCIA_RESUELTA', 'Incidencia Resuelta'),
            PedidoItem.ESTADO_ITEM_CHOICES,
        )

    def test_crear_resolucion_con_items_y_eventos(self):
        from .models import ResolucionIncidencia, IncidenciaEvento
        res = ResolucionIncidencia.objects.create(
            tipo='TRASLADO', documento_traslado='00000099', resuelto_por=self.user,
        )
        self.assertEqual(res.estado, 'ACTIVA')
        self.di.resolucion = res
        self.di.save()
        ev = IncidenciaEvento.objects.create(
            despacho_item=self.di, resolucion=res, tipo_evento='RESOLUCION',
            usuario=self.user, detalle='Traslado a2 00000099',
        )
        self.assertEqual(list(res.items_resueltos.all()), [self.di])
        self.assertEqual(list(self.di.eventos_incidencia.all()), [ev])
        self.assertEqual(list(res.eventos.all()), [ev])

    def test_resolucion_nula_significa_pendiente(self):
        from .models import DespachoItem
        pendientes = DespachoItem.objects.exclude(tipo_incidencia='').filter(
            resolucion__isnull=True,
        )
        self.assertEqual(list(pendientes), [self.di])
```

- [ ] **Step 2: Verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.ResolucionIncidenciaModelTest -v 2`
Expected: ERROR — `ImportError: cannot import name 'ResolucionIncidencia'` (y fallo del choice).

- [ ] **Step 3: Implementar los modelos**

En `PedidosAlmacen/models.py`, agregar el estado a `PedidoItem.ESTADO_ITEM_CHOICES` (después de `('INCIDENCIA', 'Incidencia')`):

```python
        ('INCIDENCIA_RESUELTA', 'Incidencia Resuelta'),
```

En `DespachoItem`, después del campo `foto_incidencia`:

```python
    # Resolución ACTIVA de la incidencia; null = incidencia pendiente.
    # El historial completo (incluidas resoluciones anuladas) vive en IncidenciaEvento.
    resolucion = models.ForeignKey(
        'ResolucionIncidencia', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='items_resueltos',
    )
```

Al final del archivo (después de `ConfiguracionPedidos`):

```python
class ResolucionIncidencia(models.Model):
    """Acto de resolución que agrupa incidencias resueltas con un mismo documento."""
    TIPO_CHOICES = [
        ('TRASLADO', 'Traslado a2'),
        ('MANUAL', 'Manual'),
    ]
    ESTADO_CHOICES = [
        ('ACTIVA', 'Activa'),
        ('ANULADA', 'Anulada'),
    ]
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    documento_traslado = models.CharField(max_length=20, blank=True, default='')
    observacion = models.CharField(max_length=255, blank=True, default='')
    resuelto_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='incidencias_resueltas',
    )
    fecha_resolucion = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='ACTIVA')
    anulada_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='resoluciones_anuladas',
    )
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['-fecha_resolucion']
        verbose_name = 'Resolución de incidencia'
        verbose_name_plural = 'Resoluciones de incidencias'

    def __str__(self) -> str:
        ref = self.documento_traslado or 'manual'
        return f"Resolución #{self.pk} ({ref})"


class IncidenciaEvento(models.Model):
    """Log inmutable de resoluciones/anulaciones por item. Nunca se edita ni borra."""
    TIPO_EVENTO_CHOICES = [
        ('RESOLUCION', 'Resolución'),
        ('ANULACION', 'Anulación'),
    ]
    despacho_item = models.ForeignKey(
        DespachoItem, on_delete=models.CASCADE, related_name='eventos_incidencia',
    )
    resolucion = models.ForeignKey(
        ResolucionIncidencia, on_delete=models.PROTECT, related_name='eventos',
    )
    tipo_evento = models.CharField(max_length=10, choices=TIPO_EVENTO_CHOICES)
    usuario = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='eventos_incidencia',
    )
    fecha = models.DateTimeField(auto_now_add=True)
    detalle = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['fecha']
        verbose_name = 'Evento de incidencia'
        verbose_name_plural = 'Eventos de incidencias'

    def __str__(self) -> str:
        return f"{self.tipo_evento} item #{self.despacho_item_id} ({self.fecha:%d/%m/%Y})"
```

- [ ] **Step 4: Generar la migración**

Run: `python manage.py makemigrations PedidosAlmacen -n resolucion_incidencias`
Expected: crea `PedidosAlmacen/migrations/0023_resolucion_incidencias.py` con los dos modelos, el FK y el alter de choices.

Run: `python manage.py migrate PedidosAlmacen`
Expected: `Applying PedidosAlmacen.0023_resolucion_incidencias... OK`

- [ ] **Step 5: Verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.ResolucionIncidenciaModelTest -v 2`
Expected: `OK` (3 tests).

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/models.py PedidosAlmacen/migrations/0023_resolucion_incidencias.py PedidosAlmacen/tests.py
git commit -m "feat(incidencias): modelos de resolucion, eventos y estado INCIDENCIA_RESUELTA"
```

---

### Task 2: Método DBISAM `validar_traslado_resolucion`

**Files:**
- Modify: `PedidosAlmacen/dbisam.py` (agregar `import re` al inicio; método después de `traslados_recepcion_existentes`, línea ~401)
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `PedidosDBISAM.connect()` (existente).
- Produces: `validar_traslado_resolucion(self, nro_documento: str) -> dict` que devuelve `{'existe': bool, 'codigos_traslado': set[str]}`. Lanza `ValueError` si el documento no cumple el formato, `pyodbc.DatabaseError` si falla la conexión/consulta.

- [ ] **Step 1: Escribir el test que falla**

Al final de `PedidosAlmacen/tests.py` (mismo patrón de mock de cursor que `BuscarEnCategoriaFiltroTest`):

```python
class ValidarTrasladoResolucionTest(TestCase):
    def _db_con_cursor(self):
        db = PedidosDBISAM()
        ctx = patch.object(db, 'connect')
        mock_connect = ctx.start()
        self.addCleanup(ctx.stop)
        cursor = (mock_connect.return_value.__enter__.return_value
                  .cursor.return_value.__enter__.return_value)
        return db, cursor

    def test_documento_invalido_lanza_valueerror(self):
        db = PedidosDBISAM()
        with self.assertRaises(ValueError):
            db.validar_traslado_resolucion("00'; DROP TABLE X--")

    def test_documento_inexistente(self):
        db, cursor = self._db_con_cursor()
        cursor.execute.return_value.fetchall.side_effect = [[]]
        resultado = db.validar_traslado_resolucion('00000099')
        self.assertFalse(resultado['existe'])
        self.assertEqual(resultado['codigos_traslado'], set())

    def test_documento_existente_devuelve_codigos(self):
        db, cursor = self._db_con_cursor()
        cursor.execute.return_value.fetchall.side_effect = [
            [(501,)],                       # SOPERACIONINV → FTI_AUTOINCREMENT
            [('SKU1 ',), ('SKU2',)],        # SDETALLEINV → FDI_CODIGO (con espacios)
        ]
        resultado = db.validar_traslado_resolucion('99')
        self.assertTrue(resultado['existe'])
        self.assertEqual(resultado['codigos_traslado'], {'SKU1', 'SKU2'})
        # La consulta debe incluir la variante con padding de 8 ceros
        primera_query = cursor.execute.call_args_list[0][0][0]
        self.assertIn("'00000099'", primera_query)
        self.assertIn('FTI_TIPO = 1', primera_query)
```

- [ ] **Step 2: Verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.ValidarTrasladoResolucionTest -v 2`
Expected: ERROR — `AttributeError: 'PedidosDBISAM' object has no attribute 'validar_traslado_resolucion'`.

- [ ] **Step 3: Implementar el método**

En `PedidosAlmacen/dbisam.py`, agregar `import re` junto a los imports existentes. Después de `traslados_recepcion_existentes`:

```python
    def validar_traslado_resolucion(self, nro_documento: str) -> dict:
        """
        Valida que un documento exista como traslado en a2 y devuelve sus SKUs.

        Busca en SOPERACIONINV el documento con FTI_TIPO = 1 (traslado). Si el
        número es puramente numérico también prueba la variante con padding de
        8 ceros (formato usado por los traslados generados por la app). Si
        existe, consulta SDETALLEINV por FDI_OPERACION_AUTOINCREMENT y devuelve
        el conjunto de códigos de producto del detalle.

        Args:
            nro_documento: Número de documento tal como lo escribió el usuario.

        Returns:
            {'existe': bool, 'codigos_traslado': set[str]} — códigos sin
            espacios de relleno.

        Raises:
            ValueError: Si el documento no cumple el formato permitido.
            pyodbc.DatabaseError: Si falla la conexión o la consulta.
        """
        doc = str(nro_documento).strip()
        if not re.fullmatch(r'[A-Za-z0-9/-]{1,20}', doc):
            raise ValueError(f'Número de documento inválido: {nro_documento!r}')

        variantes = {doc}
        if doc.isdigit():
            variantes.add(doc.rjust(8, '0'))
        docs_str = ','.join(f"'{v}'" for v in sorted(variantes))

        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute(
                        f"SELECT FTI_AUTOINCREMENT FROM SOPERACIONINV "
                        f"WHERE FTI_DOCUMENTO IN ({docs_str}) AND FTI_TIPO = 1"
                    ).fetchall()
                    if not rows:
                        return {'existe': False, 'codigos_traslado': set()}
                    ids_str = ','.join(str(int(r[0])) for r in rows)
                    detalle = cursor.execute(
                        f"SELECT DISTINCT FDI_CODIGO FROM SDETALLEINV "
                        f"WHERE FDI_OPERACION_AUTOINCREMENT IN ({ids_str})"
                    ).fetchall()
                    codigos = {str(r[0]).strip() for r in detalle if r[0]}
                    return {'existe': True, 'codigos_traslado': codigos}
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))
```

- [ ] **Step 4: Verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.ValidarTrasladoResolucionTest -v 2`
Expected: `OK` (3 tests).

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/dbisam.py PedidosAlmacen/tests.py
git commit -m "feat(incidencias): validacion de traslado de resolucion contra a2"
```

---

### Task 3: Vista GET `resolver_incidencias` + URL + plantilla base

**Files:**
- Modify: `PedidosAlmacen/views.py` (helper `_sku_incidencia` y vista, después de `reporte_incidencias` línea ~1598)
- Modify: `PedidosAlmacen/urls.py` (después de la línea del reporte de incidencias)
- Create: `templates/pedidos-resolver-incidencias.html`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `is_pedidos_supervisor`, modelos de Task 1.
- Produces:
  - URL `pedidos-resolver-incidencias` → `GET /pedidos/incidencias/resolver/` con querystring `vista` (`pendientes`|`resueltas`), `fecha_inicio`, `fecha_fin`, `tipo`.
  - `_sku_incidencia(di: DespachoItem) -> str` — SKU que debe aparecer en el traslado de resolución (usado por Tasks 4 y 5).
  - Contexto de plantilla: `incidencias`, `vista`, `total_pendientes`, `total_resueltas`, `tipos_incidencia`, `fecha_inicio`, `fecha_fin`, `tipo_filtro`.

- [ ] **Step 1: Escribir el test que falla**

Al final de `PedidosAlmacen/tests.py`:

```python
class ResolverIncidenciasVistaTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido, PedidoItem, Despacho, DespachoItem, ResolucionIncidencia
        self.sup = User.objects.create_superuser(username='sup_res', password='x')
        self.tienda = User.objects.create_user(username='tnd_res', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda.groups.add(g)
        self.pedido = Pedido.objects.create(solicitante=self.tienda, estado='PARCIAL')
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='Producto 1',
            cantidad_solicitada=5, estado='INCIDENCIA',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='PARCIAL')
        self.pendiente = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item,
            cantidad_despachada=5, tipo_incidencia='CANTIDAD_MENOR',
        )
        self.resolucion = ResolucionIncidencia.objects.create(
            tipo='MANUAL', observacion='ajuste', resuelto_por=self.sup,
        )
        item2 = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU2', descripcion='Producto 2',
            cantidad_solicitada=3, estado='INCIDENCIA_RESUELTA',
        )
        self.resuelta = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=item2,
            cantidad_despachada=3, tipo_incidencia='CANTIDAD_MAYOR',
            resolucion=self.resolucion,
        )

    def test_no_supervisor_redirige(self):
        self.client.force_login(self.tienda)
        resp = self.client.get('/pedidos/incidencias/resolver/')
        self.assertEqual(resp.status_code, 302)

    def test_pendientes_por_defecto(self):
        self.client.force_login(self.sup)
        resp = self.client.get('/pedidos/incidencias/resolver/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(resp.context['incidencias']), [self.pendiente])
        self.assertEqual(resp.context['total_pendientes'], 1)
        self.assertEqual(resp.context['total_resueltas'], 1)

    def test_vista_resueltas(self):
        self.client.force_login(self.sup)
        resp = self.client.get('/pedidos/incidencias/resolver/?vista=resueltas')
        self.assertEqual(list(resp.context['incidencias']), [self.resuelta])

    def test_sku_incidencia_helper(self):
        from .views import _sku_incidencia
        self.assertEqual(_sku_incidencia(self.pendiente), 'SKU1')
        self.pendiente.tipo_incidencia = 'PRODUCTO_ERRONEO'
        self.pendiente.codigo_real = 'REAL9'
        self.assertEqual(_sku_incidencia(self.pendiente), 'REAL9')
```

- [ ] **Step 2: Verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.ResolverIncidenciasVistaTest -v 2`
Expected: ERROR 404 / ImportError (`_sku_incidencia` no existe, URL no resuelve).

- [ ] **Step 3: Implementar helper y vista**

En `PedidosAlmacen/views.py`, actualizar el import de modelos (línea 12) para incluir los nuevos:

```python
from .models import (
    Pedido, PedidoItem, Despacho, DespachoItem, DepositoPermitido,
    ConfiguracionPedidos, ResolucionIncidencia, IncidenciaEvento,
)
```

Después de `reporte_incidencias`:

```python
def _sku_incidencia(di: DespachoItem) -> str:
    """SKU que debe figurar en el traslado a2 que resuelve la incidencia.

    Para PRODUCTO_ERRONEO es el producto que realmente llegó (codigo_real);
    para el resto, el código del PedidoItem asociado.
    """
    if di.tipo_incidencia == 'PRODUCTO_ERRONEO' and di.codigo_real:
        return di.codigo_real.strip()
    if di.pedido_item:
        return di.pedido_item.codigo.strip()
    return di.codigo_real.strip()


def _incidencias_base_qs():
    """Queryset base de DespachoItems con incidencia, excluyendo anulados."""
    return (
        DespachoItem.objects.exclude(tipo_incidencia='')
        .select_related(
            'despacho__pedido__solicitante', 'pedido_item', 'autorizado_por',
            'resolucion__resuelto_por',
        )
        .exclude(despacho__estado='ANULADO')
        .exclude(despacho__pedido__estado='ANULADO')
        .order_by('-despacho__fecha_despacho')
    )


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def resolver_incidencias(request):
    """Página de resolución de incidencias: pestañas Pendientes/Resueltas."""
    vista = request.GET.get('vista', 'pendientes')
    if vista not in ('pendientes', 'resueltas'):
        vista = 'pendientes'
    fecha_inicio = request.GET.get('fecha_inicio', '')
    fecha_fin = request.GET.get('fecha_fin', '')
    tipo_filtro = request.GET.get('tipo', '')

    qs = _incidencias_base_qs()
    if fecha_inicio:
        try:
            qs = qs.filter(despacho__fecha_despacho__date__gte=datetime.strptime(fecha_inicio, '%Y-%m-%d').date())
        except ValueError:
            pass
    if fecha_fin:
        try:
            qs = qs.filter(despacho__fecha_despacho__date__lte=datetime.strptime(fecha_fin, '%Y-%m-%d').date())
        except ValueError:
            pass
    if tipo_filtro in [t[0] for t in DespachoItem.TIPO_INCIDENCIA_CHOICES]:
        qs = qs.filter(tipo_incidencia=tipo_filtro)

    pendientes = qs.filter(resolucion__isnull=True)
    resueltas = qs.filter(resolucion__isnull=False).prefetch_related(
        'eventos_incidencia__usuario',
    )
    incidencias = pendientes if vista == 'pendientes' else resueltas

    return render(request, 'pedidos-resolver-incidencias.html', {
        'incidencias': incidencias,
        'vista': vista,
        'total_pendientes': pendientes.count(),
        'total_resueltas': resueltas.count(),
        'tipos_incidencia': DespachoItem.TIPO_INCIDENCIA_CHOICES,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'tipo_filtro': tipo_filtro,
    })
```

En `PedidosAlmacen/urls.py`, después de la línea de `pedidos-reporte-incidencias`:

```python
    path('pedidos/incidencias/resolver/', views.resolver_incidencias, name='pedidos-resolver-incidencias'),
```

- [ ] **Step 4: Crear la plantilla base**

Create `templates/pedidos-resolver-incidencias.html` (versión sin acciones; la Task 7 agrega formularios y JS):

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2><i class="fas fa-clipboard-check me-2 text-success"></i>Resolución de Incidencias</h2>
        <a href="{% url 'pedidos-reporte-incidencias' %}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Ver Reporte
        </a>
    </div>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{% if message.tags == 'error' %}danger{% else %}{{ message.tags }}{% endif %} alert-dismissible fade show">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <!-- Filtros -->
    <div class="card mb-4">
        <div class="card-header"><h6 class="mb-0"><i class="fas fa-filter me-1"></i>Filtros</h6></div>
        <div class="card-body">
            <form method="get" class="row g-3 align-items-end">
                <input type="hidden" name="vista" value="{{ vista }}">
                <div class="col-md-3">
                    <label class="form-label fw-semibold">Fecha inicio</label>
                    <input type="date" name="fecha_inicio" class="form-control" value="{{ fecha_inicio }}">
                </div>
                <div class="col-md-3">
                    <label class="form-label fw-semibold">Fecha fin</label>
                    <input type="date" name="fecha_fin" class="form-control" value="{{ fecha_fin }}">
                </div>
                <div class="col-md-3">
                    <label class="form-label fw-semibold">Tipo de incidencia</label>
                    <select name="tipo" class="form-select">
                        <option value="">Todos los tipos</option>
                        {% for valor, etiqueta in tipos_incidencia %}
                        <option value="{{ valor }}" {% if tipo_filtro == valor %}selected{% endif %}>{{ etiqueta }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="col-md-3 d-flex gap-2">
                    <button type="submit" class="btn btn-primary w-100"><i class="fas fa-search"></i> Aplicar</button>
                    <a href="{% url 'pedidos-resolver-incidencias' %}?vista={{ vista }}" class="btn btn-outline-secondary"><i class="fas fa-times"></i></a>
                </div>
            </form>
        </div>
    </div>

    <!-- Pestañas -->
    <ul class="nav nav-tabs mb-3">
        <li class="nav-item">
            <a class="nav-link {% if vista == 'pendientes' %}active{% endif %}"
               href="?vista=pendientes&fecha_inicio={{ fecha_inicio }}&fecha_fin={{ fecha_fin }}&tipo={{ tipo_filtro }}">
                <i class="fas fa-hourglass-half me-1"></i>Pendientes
                <span class="badge bg-warning text-dark">{{ total_pendientes }}</span>
            </a>
        </li>
        <li class="nav-item">
            <a class="nav-link {% if vista == 'resueltas' %}active{% endif %}"
               href="?vista=resueltas&fecha_inicio={{ fecha_inicio }}&fecha_fin={{ fecha_fin }}&tipo={{ tipo_filtro }}">
                <i class="fas fa-check-double me-1"></i>Resueltas
                <span class="badge bg-success">{{ total_resueltas }}</span>
            </a>
        </li>
    </ul>

    <div class="card">
        <div class="card-body p-0">
            <div class="table-responsive">
                <table class="table table-hover table-sm mb-0 align-middle">
                    <thead class="table-dark">
                        <tr>
                            <th>Pedido</th>
                            <th>Despacho</th>
                            <th>Fecha</th>
                            <th>Tipo</th>
                            <th>Producto</th>
                            <th class="text-center">Cant.</th>
                            <th>Solicitante</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for inc in incidencias %}
                        <tr>
                            <td>
                                <a href="{% url 'pedidos-detalle' inc.despacho.pedido.numero_pedido %}"
                                   class="fw-bold text-decoration-none">#{{ inc.despacho.pedido.numero_pedido }}</a>
                            </td>
                            <td class="text-muted">#{{ inc.despacho.numero_despacho }}</td>
                            <td class="text-nowrap">
                                {% if inc.despacho.fecha_despacho %}{{ inc.despacho.fecha_despacho|date:"d/m/Y" }}{% else %}—{% endif %}
                            </td>
                            <td>
                                {% if inc.tipo_incidencia == 'PRODUCTO_ERRONEO' %}
                                    <span class="badge bg-danger"><i class="fas fa-exchange-alt me-1"></i>Cambio SKU</span>
                                {% elif inc.tipo_incidencia == 'SKU_NO_CONTEMPLADO' %}
                                    <span class="badge bg-primary"><i class="fas fa-plus-circle me-1"></i>Prod. Nuevo</span>
                                {% elif inc.tipo_incidencia == 'CANTIDAD_MENOR' %}
                                    <span class="badge bg-secondary"><i class="fas fa-arrow-down me-1"></i>Cant. Menor</span>
                                {% elif inc.tipo_incidencia == 'CANTIDAD_MAYOR' %}
                                    <span class="badge bg-warning text-dark"><i class="fas fa-arrow-up me-1"></i>Cant. Mayor</span>
                                {% endif %}
                            </td>
                            <td>
                                {% if inc.tipo_incidencia == 'PRODUCTO_ERRONEO' and inc.codigo_real %}
                                    <span class="fw-semibold text-success">{{ inc.codigo_real }}</span><br>
                                    <small>{{ inc.descripcion_real|default:"" }}</small>
                                {% elif inc.pedido_item %}
                                    <span class="fw-semibold">{{ inc.pedido_item.codigo }}</span><br>
                                    <small>{{ inc.pedido_item.descripcion }}</small>
                                {% else %}—{% endif %}
                            </td>
                            <td class="text-center fw-bold">{{ inc.cantidad_despachada }}</td>
                            <td>{{ inc.despacho.pedido.solicitante.username|capfirst }}</td>
                        </tr>
                        {% empty %}
                        <tr>
                            <td colspan="7" class="text-center text-muted py-4">
                                <i class="fas fa-check-circle text-success fa-2x mb-2 d-block"></i>
                                No hay incidencias {{ vista }} en el período seleccionado.
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</div>
{% endblock content %}
```

- [ ] **Step 5: Verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.ResolverIncidenciasVistaTest -v 2`
Expected: `OK` (4 tests).

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/urls.py templates/pedidos-resolver-incidencias.html PedidosAlmacen/tests.py
git commit -m "feat(incidencias): pagina de resolucion con pestanas pendientes/resueltas"
```

---

### Task 4: Endpoint AJAX de validación de traslado

**Files:**
- Modify: `PedidosAlmacen/views.py` (después de `resolver_incidencias`)
- Modify: `PedidosAlmacen/urls.py`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `PedidosDBISAM.validar_traslado_resolucion(nro_documento)` (Task 2), `_sku_incidencia` (Task 3).
- Produces: URL `pedidos-validar-traslado-incidencias` → `POST /pedidos/incidencias/resolver/validar/` con `documento` e `item_ids` (lista). Respuesta JSON:
  - éxito: `{'ok': True, 'existe': bool, 'skus': [str], 'faltantes': [str], 'valido': bool}`
  - error: `{'ok': False, 'error': str}` con status 400/405/502.

- [ ] **Step 1: Escribir el test que falla**

```python
class ValidarTrasladoEndpointTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, PedidoItem, Despacho, DespachoItem
        self.sup = User.objects.create_superuser(username='sup_val', password='x')
        self.pedido = Pedido.objects.create(solicitante=self.sup, estado='PARCIAL')
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='Producto 1',
            cantidad_solicitada=5, estado='INCIDENCIA',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='PARCIAL')
        self.di = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item,
            cantidad_despachada=5, tipo_incidencia='CANTIDAD_MENOR',
        )
        self.url = '/pedidos/incidencias/resolver/validar/'
        self.client.force_login(self.sup)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_traslado_valido_cubre_skus(self, mock_db):
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'SKU1', 'OTRO'},
        }
        resp = self.client.post(self.url, {'documento': '99', 'item_ids': [self.di.id]})
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['existe'])
        self.assertTrue(data['valido'])
        self.assertEqual(data['faltantes'], [])

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_traslado_no_cubre_sku(self, mock_db):
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'OTRO'},
        }
        resp = self.client.post(self.url, {'documento': '99', 'item_ids': [self.di.id]})
        data = resp.json()
        self.assertTrue(data['existe'])
        self.assertFalse(data['valido'])
        self.assertEqual(data['faltantes'], ['SKU1'])

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_documento_inexistente(self, mock_db):
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': False, 'codigos_traslado': set(),
        }
        resp = self.client.post(self.url, {'documento': '99', 'item_ids': [self.di.id]})
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertFalse(data['existe'])

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_error_odbc_devuelve_502(self, mock_db):
        mock_db.return_value.validar_traslado_resolucion.side_effect = Exception('odbc down')
        resp = self.client.post(self.url, {'documento': '99', 'item_ids': [self.di.id]})
        self.assertEqual(resp.status_code, 502)
        self.assertFalse(resp.json()['ok'])

    def test_sin_documento_devuelve_400(self):
        resp = self.client.post(self.url, {'documento': '', 'item_ids': [self.di.id]})
        self.assertEqual(resp.status_code, 400)
```

- [ ] **Step 2: Verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.ValidarTrasladoEndpointTest -v 2`
Expected: FAIL — 404 en la URL.

- [ ] **Step 3: Implementar el endpoint**

En `PedidosAlmacen/views.py`:

```python
@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def validar_traslado_incidencias(request):
    """AJAX: valida un documento de traslado a2 contra las incidencias seleccionadas."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido'}, status=405)
    documento = request.POST.get('documento', '').strip()
    item_ids = request.POST.getlist('item_ids')
    if not documento or not item_ids:
        return JsonResponse({'ok': False, 'error': 'Documento e incidencias son requeridos'}, status=400)

    items = list(
        DespachoItem.objects.exclude(tipo_incidencia='')
        .filter(id__in=item_ids)
        .select_related('pedido_item')
    )
    if not items:
        return JsonResponse({'ok': False, 'error': 'Incidencias no encontradas'}, status=400)

    try:
        resultado = PedidosDBISAM().validar_traslado_resolucion(documento)
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'Número de documento inválido'}, status=400)
    except Exception:
        logger.exception('Error validando traslado de resolución contra a2')
        return JsonResponse(
            {'ok': False, 'error': 'No se pudo consultar a2. Intenta de nuevo.'},
            status=502,
        )

    if not resultado['existe']:
        return JsonResponse({'ok': True, 'existe': False, 'skus': [], 'faltantes': [], 'valido': False})

    skus = sorted({_sku_incidencia(di) for di in items})
    faltantes = sorted(set(skus) - resultado['codigos_traslado'])
    return JsonResponse({
        'ok': True,
        'existe': True,
        'skus': skus,
        'faltantes': faltantes,
        'valido': not faltantes,
    })
```

En `PedidosAlmacen/urls.py`, después de `pedidos-resolver-incidencias`:

```python
    path('pedidos/incidencias/resolver/validar/', views.validar_traslado_incidencias, name='pedidos-validar-traslado-incidencias'),
```

- [ ] **Step 4: Verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.ValidarTrasladoEndpointTest -v 2`
Expected: `OK` (5 tests).

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/urls.py PedidosAlmacen/tests.py
git commit -m "feat(incidencias): endpoint ajax de validacion de traslado"
```

---

### Task 5: Confirmar resolución (POST transaccional con revalidación)

**Files:**
- Modify: `PedidosAlmacen/views.py` (helpers de estados + vista, después de `validar_traslado_incidencias`)
- Modify: `PedidosAlmacen/urls.py`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: Tasks 1-4 (`ResolucionIncidencia`, `IncidenciaEvento`, `validar_traslado_resolucion`, `_sku_incidencia`).
- Produces:
  - URL `pedidos-confirmar-resolucion` → `POST /pedidos/incidencias/resolver/confirmar/` con `item_ids` (lista), `tipo` (`TRASLADO`|`MANUAL`), `documento`, `observacion`. Redirige a `pedidos-resolver-incidencias` con `messages`.
  - `_incidencias_pendientes_despacho(despacho: Despacho) -> bool`
  - `_actualizar_estados_tras_resolucion(despacho: Despacho) -> None` (despacho PARCIAL→RECIBIDO; pedido→RECIBIDO si todos sus items quedan en RECIBIDO/INCIDENCIA_RESUELTA)
  - Ambos helpers los reutiliza la Task 6.

- [ ] **Step 1: Escribir los tests que fallan**

```python
class ConfirmarResolucionTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, PedidoItem, Despacho, DespachoItem
        self.sup = User.objects.create_superuser(username='sup_conf', password='x')
        self.pedido = Pedido.objects.create(solicitante=self.sup, estado='PARCIAL')
        self.item1 = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='P1',
            cantidad_solicitada=5, cantidad_recibida=5, estado='INCIDENCIA',
        )
        self.item2 = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU2', descripcion='P2',
            cantidad_solicitada=3, cantidad_recibida=3, estado='INCIDENCIA',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='PARCIAL')
        self.di1 = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item1,
            cantidad_despachada=5, tipo_incidencia='CANTIDAD_MENOR',
        )
        self.di2 = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item2,
            cantidad_despachada=3, tipo_incidencia='CANTIDAD_MAYOR',
        )
        self.url = '/pedidos/incidencias/resolver/confirmar/'
        self.client.force_login(self.sup)

    def _post_traslado(self, item_ids, documento='99'):
        return self.client.post(self.url, {
            'item_ids': item_ids, 'tipo': 'TRASLADO', 'documento': documento,
        })

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_resuelve_todas_despacho_recibido(self, mock_db):
        from .models import ResolucionIncidencia, IncidenciaEvento
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'SKU1', 'SKU2'},
        }
        resp = self._post_traslado([self.di1.id, self.di2.id])
        self.assertEqual(resp.status_code, 302)
        self.di1.refresh_from_db(); self.di2.refresh_from_db()
        self.item1.refresh_from_db(); self.item2.refresh_from_db()
        self.despacho.refresh_from_db()
        res = ResolucionIncidencia.objects.get()
        self.assertEqual(res.tipo, 'TRASLADO')
        self.assertEqual(res.documento_traslado, '99')
        self.assertEqual(self.di1.resolucion, res)
        self.assertEqual(self.di2.resolucion, res)
        self.assertEqual(self.item1.estado, 'INCIDENCIA_RESUELTA')
        self.assertEqual(self.item2.estado, 'INCIDENCIA_RESUELTA')
        self.assertEqual(self.despacho.estado, 'RECIBIDO')
        self.assertEqual(IncidenciaEvento.objects.filter(tipo_evento='RESOLUCION').count(), 2)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_resolucion_parcial_despacho_sigue_parcial(self, mock_db):
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'SKU1'},
        }
        self._post_traslado([self.di1.id])
        self.despacho.refresh_from_db()
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.estado, 'INCIDENCIA_RESUELTA')
        self.assertEqual(self.despacho.estado, 'PARCIAL')

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_documento_inexistente_no_resuelve(self, mock_db):
        from .models import ResolucionIncidencia
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': False, 'codigos_traslado': set(),
        }
        self._post_traslado([self.di1.id])
        self.assertEqual(ResolucionIncidencia.objects.count(), 0)
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.estado, 'INCIDENCIA')

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_sku_no_cubierto_no_resuelve(self, mock_db):
        from .models import ResolucionIncidencia
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'OTRO'},
        }
        self._post_traslado([self.di1.id])
        self.assertEqual(ResolucionIncidencia.objects.count(), 0)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_error_odbc_no_resuelve(self, mock_db):
        from .models import ResolucionIncidencia
        mock_db.return_value.validar_traslado_resolucion.side_effect = Exception('odbc down')
        self._post_traslado([self.di1.id])
        self.assertEqual(ResolucionIncidencia.objects.count(), 0)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_manual_no_llama_a2(self, mock_db):
        from .models import ResolucionIncidencia
        self.client.post(self.url, {
            'item_ids': [self.di1.id], 'tipo': 'MANUAL',
            'observacion': 'Se ajustó directo en a2',
        })
        mock_db.return_value.validar_traslado_resolucion.assert_not_called()
        res = ResolucionIncidencia.objects.get()
        self.assertEqual(res.tipo, 'MANUAL')
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.estado, 'INCIDENCIA_RESUELTA')

    def test_manual_sin_observacion_no_resuelve(self):
        from .models import ResolucionIncidencia
        self.client.post(self.url, {'item_ids': [self.di1.id], 'tipo': 'MANUAL', 'observacion': ''})
        self.assertEqual(ResolucionIncidencia.objects.count(), 0)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_ya_resuelta_por_otra_sesion_no_duplica(self, mock_db):
        from .models import ResolucionIncidencia
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'SKU1'},
        }
        previa = ResolucionIncidencia.objects.create(tipo='MANUAL', observacion='x', resuelto_por=self.sup)
        self.di1.resolucion = previa
        self.di1.save()
        self._post_traslado([self.di1.id])
        self.assertEqual(ResolucionIncidencia.objects.count(), 1)
        self.di1.refresh_from_db()
        self.assertEqual(self.di1.resolucion, previa)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_pedido_recibido_si_todo_resuelto(self, mock_db):
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'SKU1', 'SKU2'},
        }
        self._post_traslado([self.di1.id, self.di2.id])
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'RECIBIDO')
        self.assertIsNotNone(self.pedido.fecha_recepcion)
```

- [ ] **Step 2: Verificar que fallan**

Run: `python manage.py test PedidosAlmacen.tests.ConfirmarResolucionTest -v 2`
Expected: FAIL — 404 en la URL.

- [ ] **Step 3: Implementar helpers y vista**

En `PedidosAlmacen/views.py`, después de `validar_traslado_incidencias`:

```python
def _incidencias_pendientes_despacho(despacho: Despacho) -> bool:
    """True si el despacho tiene incidencias sin resolución activa."""
    return despacho.items.exclude(tipo_incidencia='').filter(resolucion__isnull=True).exists()


def _actualizar_estados_tras_resolucion(despacho: Despacho) -> None:
    """Promueve despacho y pedido cuando ya no quedan incidencias pendientes.

    Despacho: PARCIAL → RECIBIDO. Pedido: → RECIBIDO si todos sus items quedan
    en RECIBIDO o INCIDENCIA_RESUELTA (equivalente a recibido).
    """
    if despacho.estado == 'PARCIAL' and not _incidencias_pendientes_despacho(despacho):
        despacho.estado = 'RECIBIDO'
        despacho.save(update_fields=['estado'])

    pedido = despacho.pedido
    estados = list(pedido.items.values_list('estado', flat=True))
    if (
        estados
        and pedido.estado not in ('ANULADO', 'CERRADO', 'RECIBIDO')
        and all(e in ('RECIBIDO', 'INCIDENCIA_RESUELTA') for e in estados)
    ):
        pedido.estado = 'RECIBIDO'
        if not pedido.fecha_recepcion:
            pedido.fecha_recepcion = timezone.now()
        pedido.save(update_fields=['estado', 'fecha_recepcion'])


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def confirmar_resolucion_incidencias(request):
    """Crea una resolución (traslado validado contra a2, o manual) para las incidencias elegidas."""
    if request.method != 'POST':
        return redirect('pedidos-resolver-incidencias')

    item_ids = request.POST.getlist('item_ids')
    tipo = request.POST.get('tipo', '')
    documento = request.POST.get('documento', '').strip()
    observacion = request.POST.get('observacion', '').strip()

    if not item_ids:
        messages.error(request, 'Selecciona al menos una incidencia.')
        return redirect('pedidos-resolver-incidencias')
    if tipo not in ('TRASLADO', 'MANUAL'):
        messages.error(request, 'Tipo de resolución inválido.')
        return redirect('pedidos-resolver-incidencias')
    if tipo == 'MANUAL' and not observacion:
        messages.error(request, 'La observación es obligatoria en una resolución manual.')
        return redirect('pedidos-resolver-incidencias')
    if tipo == 'TRASLADO' and not documento:
        messages.error(request, 'Indica el número de documento del traslado.')
        return redirect('pedidos-resolver-incidencias')

    items = list(
        DespachoItem.objects.exclude(tipo_incidencia='')
        .filter(id__in=item_ids)
        .select_related('pedido_item')
    )
    if len(items) != len(set(item_ids)):
        messages.error(request, 'Alguna de las incidencias seleccionadas no existe.')
        return redirect('pedidos-resolver-incidencias')

    # Revalidación en servidor contra a2 (no confía en el AJAX previo)
    if tipo == 'TRASLADO':
        try:
            resultado = PedidosDBISAM().validar_traslado_resolucion(documento)
        except ValueError:
            messages.error(request, 'Número de documento inválido.')
            return redirect('pedidos-resolver-incidencias')
        except Exception:
            logger.exception('Error validando traslado de resolución contra a2')
            messages.error(request, 'No se pudo validar contra a2. Intenta de nuevo.')
            return redirect('pedidos-resolver-incidencias')
        if not resultado['existe']:
            messages.error(request, f'El documento {documento} no existe como traslado en a2.')
            return redirect('pedidos-resolver-incidencias')
        faltantes = sorted({_sku_incidencia(di) for di in items} - resultado['codigos_traslado'])
        if faltantes:
            messages.error(
                request,
                f'El traslado {documento} no incluye los SKUs: {", ".join(faltantes)}.',
            )
            return redirect('pedidos-resolver-incidencias')

    with transaction.atomic():
        bloqueados = list(
            DespachoItem.objects.select_for_update()
            .filter(id__in=[di.id for di in items], resolucion__isnull=True)
            .select_related('pedido_item')
        )
        if len(bloqueados) != len(items):
            messages.error(request, 'Alguna incidencia ya fue resuelta por otro usuario. Refresca la página.')
            return redirect('pedidos-resolver-incidencias')

        resolucion = ResolucionIncidencia.objects.create(
            tipo=tipo,
            documento_traslado=documento if tipo == 'TRASLADO' else '',
            observacion=observacion,
            resuelto_por=request.user,
        )
        despachos_ids = set()
        for di in bloqueados:
            di.resolucion = resolucion
            di.save(update_fields=['resolucion'])
            IncidenciaEvento.objects.create(
                despacho_item=di, resolucion=resolucion, tipo_evento='RESOLUCION',
                usuario=request.user,
                detalle=(f'Traslado a2 {documento}' if tipo == 'TRASLADO' else f'Manual: {observacion}'),
            )
            if di.pedido_item and di.pedido_item.estado == 'INCIDENCIA':
                di.pedido_item.estado = 'INCIDENCIA_RESUELTA'
                di.pedido_item.save(update_fields=['estado'])
            despachos_ids.add(di.despacho_id)

        for despacho in Despacho.objects.select_for_update().filter(numero_despacho__in=despachos_ids):
            _actualizar_estados_tras_resolucion(despacho)

    messages.success(request, f'{len(bloqueados)} incidencia(s) resuelta(s) correctamente.')
    return redirect('pedidos-resolver-incidencias')
```

En `PedidosAlmacen/urls.py`:

```python
    path('pedidos/incidencias/resolver/confirmar/', views.confirmar_resolucion_incidencias, name='pedidos-confirmar-resolucion'),
```

- [ ] **Step 4: Verificar que pasan**

Run: `python manage.py test PedidosAlmacen.tests.ConfirmarResolucionTest -v 2`
Expected: `OK` (9 tests).

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/urls.py PedidosAlmacen/tests.py
git commit -m "feat(incidencias): confirmacion transaccional de resolucion con revalidacion a2"
```

---

### Task 6: Anular resolución

**Files:**
- Modify: `PedidosAlmacen/views.py` (helper de reversión + vista, después de `confirmar_resolucion_incidencias`)
- Modify: `PedidosAlmacen/urls.py`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: helpers y modelos de Tasks 1 y 5 (`_incidencias_pendientes_despacho`).
- Produces: URL `pedidos-anular-resolucion` → `POST /pedidos/incidencias/resolver/anular/<int:resolucion_id>/` con `motivo` obligatorio. Redirige a `pedidos-resolver-incidencias`.
  - `_revertir_estados_tras_anulacion(despacho: Despacho) -> None`

- [ ] **Step 1: Escribir los tests que fallan**

```python
class AnularResolucionTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import (
            Pedido, PedidoItem, Despacho, DespachoItem,
            ResolucionIncidencia, IncidenciaEvento,
        )
        self.sup = User.objects.create_superuser(username='sup_anul', password='x')
        self.pedido = Pedido.objects.create(solicitante=self.sup, estado='RECIBIDO')
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='P1',
            cantidad_solicitada=5, estado='INCIDENCIA_RESUELTA',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='RECIBIDO')
        self.res = ResolucionIncidencia.objects.create(
            tipo='TRASLADO', documento_traslado='00000099', resuelto_por=self.sup,
        )
        self.di = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item,
            cantidad_despachada=5, tipo_incidencia='CANTIDAD_MENOR',
            resolucion=self.res,
        )
        IncidenciaEvento.objects.create(
            despacho_item=self.di, resolucion=self.res,
            tipo_evento='RESOLUCION', usuario=self.sup, detalle='Traslado a2 00000099',
        )
        self.url = f'/pedidos/incidencias/resolver/anular/{self.res.id}/'
        self.client.force_login(self.sup)

    def test_anula_y_revierte_estados(self):
        from .models import IncidenciaEvento
        resp = self.client.post(self.url, {'motivo': 'Documento equivocado'})
        self.assertEqual(resp.status_code, 302)
        self.res.refresh_from_db(); self.di.refresh_from_db()
        self.item.refresh_from_db(); self.despacho.refresh_from_db()
        self.pedido.refresh_from_db()
        self.assertEqual(self.res.estado, 'ANULADA')
        self.assertEqual(self.res.anulada_por, self.sup)
        self.assertEqual(self.res.motivo_anulacion, 'Documento equivocado')
        self.assertIsNotNone(self.res.fecha_anulacion)
        self.assertIsNone(self.di.resolucion)
        self.assertEqual(self.item.estado, 'INCIDENCIA')
        self.assertEqual(self.despacho.estado, 'PARCIAL')
        self.assertEqual(self.pedido.estado, 'PARCIAL')
        self.assertEqual(
            IncidenciaEvento.objects.filter(despacho_item=self.di).count(), 2,
        )

    def test_sin_motivo_no_anula(self):
        self.client.post(self.url, {'motivo': ''})
        self.res.refresh_from_db()
        self.assertEqual(self.res.estado, 'ACTIVA')

    def test_ya_anulada_no_se_reanula(self):
        self.client.post(self.url, {'motivo': 'Primera'})
        self.client.post(self.url, {'motivo': 'Segunda'})
        self.res.refresh_from_db()
        self.assertEqual(self.res.motivo_anulacion, 'Primera')

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_re_resolucion_tras_anulacion_acumula_historial(self, mock_db):
        from .models import IncidenciaEvento, ResolucionIncidencia
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'SKU1'},
        }
        self.client.post(self.url, {'motivo': 'Documento equivocado'})
        self.client.post('/pedidos/incidencias/resolver/confirmar/', {
            'item_ids': [self.di.id], 'tipo': 'TRASLADO', 'documento': '100',
        })
        self.di.refresh_from_db(); self.item.refresh_from_db()
        nueva = ResolucionIncidencia.objects.exclude(pk=self.res.pk).get()
        self.assertEqual(self.di.resolucion, nueva)
        self.assertEqual(self.item.estado, 'INCIDENCIA_RESUELTA')
        # Historial: resolución original + anulación + nueva resolución
        eventos = list(
            IncidenciaEvento.objects.filter(despacho_item=self.di)
            .values_list('tipo_evento', flat=True)
        )
        self.assertEqual(eventos, ['RESOLUCION', 'ANULACION', 'RESOLUCION'])
```

- [ ] **Step 2: Verificar que fallan**

Run: `python manage.py test PedidosAlmacen.tests.AnularResolucionTest -v 2`
Expected: FAIL — 404 en la URL.

- [ ] **Step 3: Implementar helper y vista**

En `PedidosAlmacen/views.py`:

```python
def _revertir_estados_tras_anulacion(despacho: Despacho) -> None:
    """Devuelve despacho y pedido a PARCIAL si reaparecen incidencias pendientes."""
    if despacho.estado == 'RECIBIDO' and _incidencias_pendientes_despacho(despacho):
        despacho.estado = 'PARCIAL'
        despacho.save(update_fields=['estado'])

    pedido = despacho.pedido
    if pedido.estado == 'RECIBIDO' and pedido.items.filter(estado='INCIDENCIA').exists():
        pedido.estado = 'PARCIAL'
        pedido.save(update_fields=['estado'])


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def anular_resolucion_incidencia(request, resolucion_id):
    """Anula una resolución activa: las incidencias vuelven a pendientes."""
    if request.method != 'POST':
        return redirect('pedidos-resolver-incidencias')
    motivo = request.POST.get('motivo', '').strip()
    if not motivo:
        messages.error(request, 'El motivo de anulación es obligatorio.')
        return redirect('pedidos-resolver-incidencias')

    with transaction.atomic():
        try:
            resolucion = (
                ResolucionIncidencia.objects.select_for_update()
                .get(pk=resolucion_id, estado='ACTIVA')
            )
        except ResolucionIncidencia.DoesNotExist:
            messages.error(request, 'La resolución no existe o ya fue anulada.')
            return redirect('pedidos-resolver-incidencias')

        resolucion.estado = 'ANULADA'
        resolucion.anulada_por = request.user
        resolucion.fecha_anulacion = timezone.now()
        resolucion.motivo_anulacion = motivo
        resolucion.save(update_fields=['estado', 'anulada_por', 'fecha_anulacion', 'motivo_anulacion'])

        items = list(resolucion.items_resueltos.select_related('pedido_item'))
        despachos_ids = set()
        for di in items:
            IncidenciaEvento.objects.create(
                despacho_item=di, resolucion=resolucion, tipo_evento='ANULACION',
                usuario=request.user, detalle=motivo,
            )
            di.resolucion = None
            di.save(update_fields=['resolucion'])
            if di.pedido_item and di.pedido_item.estado == 'INCIDENCIA_RESUELTA':
                di.pedido_item.estado = 'INCIDENCIA'
                di.pedido_item.save(update_fields=['estado'])
            despachos_ids.add(di.despacho_id)

        for despacho in Despacho.objects.select_for_update().filter(numero_despacho__in=despachos_ids):
            _revertir_estados_tras_anulacion(despacho)

    messages.success(request, f'Resolución anulada: {len(items)} incidencia(s) vuelven a pendientes.')
    return redirect('pedidos-resolver-incidencias')
```

En `PedidosAlmacen/urls.py`:

```python
    path('pedidos/incidencias/resolver/anular/<int:resolucion_id>/', views.anular_resolucion_incidencia, name='pedidos-anular-resolucion'),
```

- [ ] **Step 4: Verificar que pasan**

Run: `python manage.py test PedidosAlmacen.tests.AnularResolucionTest -v 2`
Expected: `OK` (4 tests).

- [ ] **Step 5: Correr toda la suite de la app**

Run: `python manage.py test PedidosAlmacen -v 1`
Expected: `OK` — sin regresiones en los tests previos.

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/urls.py PedidosAlmacen/tests.py
git commit -m "feat(incidencias): anulacion de resoluciones con reversion de estados"
```

---

### Task 7: UI operativa completa, menú y badge

**Files:**
- Modify: `templates/pedidos-resolver-incidencias.html` (reescritura con formularios y JS)
- Modify: `templates/dashboard.html` (línea ~103, menú supervisor)
- Modify: `templates/pedidos-detalle.html` (línea ~236, badge del estado nuevo)
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: URLs `pedidos-validar-traslado-incidencias`, `pedidos-confirmar-resolucion`, `pedidos-anular-resolucion` (Tasks 4-6); contexto de la vista GET (Task 3).
- Produces: página final con selección múltiple, validación AJAX y anulación; entrada de menú "Incidencias" para supervisores; badge "Inc. Resuelta" en el detalle del pedido.

- [ ] **Step 1: Escribir el test que falla**

```python
class ResolverIncidenciasUITest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, PedidoItem, Despacho, DespachoItem, ResolucionIncidencia
        self.sup = User.objects.create_superuser(username='sup_ui', password='x')
        self.pedido = Pedido.objects.create(solicitante=self.sup, estado='PARCIAL')
        item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='P1',
            cantidad_solicitada=5, estado='INCIDENCIA',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='PARCIAL')
        self.di = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=item,
            cantidad_despachada=5, tipo_incidencia='CANTIDAD_MENOR',
        )
        self.res = ResolucionIncidencia.objects.create(
            tipo='TRASLADO', documento_traslado='00000099', resuelto_por=self.sup,
        )
        self.client.force_login(self.sup)

    def test_pendientes_tiene_form_y_checkboxes(self):
        resp = self.client.get('/pedidos/incidencias/resolver/')
        self.assertContains(resp, '/pedidos/incidencias/resolver/confirmar/')
        self.assertContains(resp, f'name="item_ids" value="{self.di.id}"')
        self.assertContains(resp, 'btn-validar')

    def test_resueltas_tiene_boton_anular(self):
        from .models import PedidoItem, DespachoItem
        item2 = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU2', descripcion='P2',
            cantidad_solicitada=1, estado='INCIDENCIA_RESUELTA',
        )
        DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=item2,
            cantidad_despachada=1, tipo_incidencia='CANTIDAD_MAYOR',
            resolucion=self.res,
        )
        resp = self.client.get('/pedidos/incidencias/resolver/?vista=resueltas')
        self.assertContains(resp, f'/pedidos/incidencias/resolver/anular/{self.res.id}/')
        self.assertContains(resp, '00000099')

    def test_detalle_pedido_muestra_badge_resuelta(self):
        from .models import PedidoItem
        PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU3', descripcion='P3',
            cantidad_solicitada=1, estado='INCIDENCIA_RESUELTA',
        )
        resp = self.client.get(f'/pedidos/{self.pedido.numero_pedido}/')
        self.assertContains(resp, 'Inc. Resuelta')
```

- [ ] **Step 2: Verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.ResolverIncidenciasUITest -v 2`
Expected: FAIL — la plantilla base no tiene formularios ni el badge existe.

- [ ] **Step 3: Reescribir la plantilla completa**

Reemplazar el contenido de `templates/pedidos-resolver-incidencias.html` por la versión final. Mantener intactos el header, los mensajes, los filtros y las pestañas del la versión de la Task 3; reemplazar el bloque `<div class="card">...</div>` de la tabla por:

```html
    {% if vista == 'pendientes' %}
    <form method="post" action="{% url 'pedidos-confirmar-resolucion' %}" id="form-resolucion">
        {% csrf_token %}
        <div class="card mb-3">
            <div class="card-body p-0">
                <div class="table-responsive">
                    <table class="table table-hover table-sm mb-0 align-middle">
                        <thead class="table-dark">
                            <tr>
                                <th class="text-center"><input type="checkbox" id="check-todos" title="Seleccionar todo"></th>
                                <th>Pedido</th>
                                <th>Despacho</th>
                                <th>Fecha</th>
                                <th>Tipo</th>
                                <th>Producto</th>
                                <th class="text-center">Cant.</th>
                                <th>Solicitante</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for inc in incidencias %}
                            <tr>
                                <td class="text-center">
                                    <input type="checkbox" class="check-incidencia" name="item_ids" value="{{ inc.id }}">
                                </td>
                                <td>
                                    <a href="{% url 'pedidos-detalle' inc.despacho.pedido.numero_pedido %}"
                                       class="fw-bold text-decoration-none">#{{ inc.despacho.pedido.numero_pedido }}</a>
                                </td>
                                <td class="text-muted">#{{ inc.despacho.numero_despacho }}</td>
                                <td class="text-nowrap">
                                    {% if inc.despacho.fecha_despacho %}{{ inc.despacho.fecha_despacho|date:"d/m/Y" }}{% else %}—{% endif %}
                                </td>
                                <td>
                                    {% if inc.tipo_incidencia == 'PRODUCTO_ERRONEO' %}
                                        <span class="badge bg-danger"><i class="fas fa-exchange-alt me-1"></i>Cambio SKU</span>
                                    {% elif inc.tipo_incidencia == 'SKU_NO_CONTEMPLADO' %}
                                        <span class="badge bg-primary"><i class="fas fa-plus-circle me-1"></i>Prod. Nuevo</span>
                                    {% elif inc.tipo_incidencia == 'CANTIDAD_MENOR' %}
                                        <span class="badge bg-secondary"><i class="fas fa-arrow-down me-1"></i>Cant. Menor</span>
                                    {% elif inc.tipo_incidencia == 'CANTIDAD_MAYOR' %}
                                        <span class="badge bg-warning text-dark"><i class="fas fa-arrow-up me-1"></i>Cant. Mayor</span>
                                    {% endif %}
                                </td>
                                <td>
                                    {% if inc.tipo_incidencia == 'PRODUCTO_ERRONEO' and inc.codigo_real %}
                                        <span class="fw-semibold text-success">{{ inc.codigo_real }}</span><br>
                                        <small>{{ inc.descripcion_real|default:"" }}</small>
                                    {% elif inc.pedido_item %}
                                        <span class="fw-semibold">{{ inc.pedido_item.codigo }}</span><br>
                                        <small>{{ inc.pedido_item.descripcion }}</small>
                                    {% else %}—{% endif %}
                                </td>
                                <td class="text-center fw-bold">{{ inc.cantidad_despachada }}</td>
                                <td>{{ inc.despacho.pedido.solicitante.username|capfirst }}</td>
                            </tr>
                            {% empty %}
                            <tr>
                                <td colspan="8" class="text-center text-muted py-4">
                                    <i class="fas fa-check-circle text-success fa-2x mb-2 d-block"></i>
                                    No hay incidencias pendientes en el período seleccionado.
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Panel de resolución -->
        <div class="card border-success" id="panel-resolucion">
            <div class="card-header bg-success text-white">
                <h6 class="mb-0"><i class="fas fa-clipboard-check me-1"></i>Resolver seleccionadas
                    (<span id="contador-seleccion">0</span>)</h6>
            </div>
            <div class="card-body">
                <div class="row g-3">
                    <div class="col-md-3">
                        <label class="form-label fw-semibold">Tipo de resolución</label>
                        <select name="tipo" id="tipo-resolucion" class="form-select">
                            <option value="TRASLADO" selected>Traslado a2</option>
                            <option value="MANUAL">Manual (sin documento)</option>
                        </select>
                    </div>
                    <div class="col-md-3" id="grupo-documento">
                        <label class="form-label fw-semibold">Nº documento traslado</label>
                        <div class="input-group">
                            <input type="text" name="documento" id="input-documento" class="form-control"
                                   maxlength="20" placeholder="Ej. 00000123">
                            <button type="button" class="btn btn-outline-primary" id="btn-validar">
                                <i class="fas fa-magnifying-glass"></i> Validar
                            </button>
                        </div>
                    </div>
                    <div class="col-md-6">
                        <label class="form-label fw-semibold">Observación <span id="obs-requerida" class="text-danger d-none">(obligatoria)</span></label>
                        <input type="text" name="observacion" id="input-observacion" class="form-control" maxlength="255">
                    </div>
                </div>
                <div id="resultado-validacion" class="mt-3"></div>
                <div class="mt-3 text-end">
                    <button type="submit" class="btn btn-success" id="btn-confirmar" disabled>
                        <i class="fas fa-check"></i> Confirmar resolución
                    </button>
                </div>
            </div>
        </div>
    </form>

    <script>
    (function () {
        const checks = () => Array.from(document.querySelectorAll('.check-incidencia'));
        const seleccionados = () => checks().filter(c => c.checked);
        const tipoSel = document.getElementById('tipo-resolucion');
        const grupoDoc = document.getElementById('grupo-documento');
        const obsReq = document.getElementById('obs-requerida');
        const inputDoc = document.getElementById('input-documento');
        const inputObs = document.getElementById('input-observacion');
        const btnValidar = document.getElementById('btn-validar');
        const btnConfirmar = document.getElementById('btn-confirmar');
        const resultado = document.getElementById('resultado-validacion');
        const contador = document.getElementById('contador-seleccion');
        let validacionOk = false;

        function actualizar() {
            contador.textContent = seleccionados().length;
            const manual = tipoSel.value === 'MANUAL';
            grupoDoc.classList.toggle('d-none', manual);
            obsReq.classList.toggle('d-none', !manual);
            if (manual) {
                btnConfirmar.disabled = !(seleccionados().length && inputObs.value.trim());
            } else {
                btnConfirmar.disabled = !(seleccionados().length && validacionOk);
            }
        }

        function invalidar() { validacionOk = false; resultado.innerHTML = ''; actualizar(); }

        document.getElementById('check-todos').addEventListener('change', function () {
            checks().forEach(c => { c.checked = this.checked; });
            invalidar();
        });
        document.addEventListener('change', e => {
            if (e.target.classList.contains('check-incidencia')) invalidar();
        });
        tipoSel.addEventListener('change', actualizar);
        inputObs.addEventListener('input', actualizar);
        inputDoc.addEventListener('input', invalidar);

        btnValidar.addEventListener('click', function () {
            const sel = seleccionados();
            const doc = inputDoc.value.trim();
            if (!sel.length) { resultado.innerHTML = '<div class="alert alert-warning mb-0">Selecciona al menos una incidencia.</div>'; return; }
            if (!doc) { resultado.innerHTML = '<div class="alert alert-warning mb-0">Escribe el número de documento.</div>'; return; }
            btnValidar.disabled = true;
            const fd = new FormData();
            fd.append('documento', doc);
            sel.forEach(c => fd.append('item_ids', c.value));
            fd.append('csrfmiddlewaretoken', document.querySelector('#form-resolucion [name=csrfmiddlewaretoken]').value);
            fetch("{% url 'pedidos-validar-traslado-incidencias' %}", { method: 'POST', body: fd })
                .then(r => r.json().then(data => ({ status: r.status, data })))
                .then(({ data }) => {
                    if (!data.ok) {
                        resultado.innerHTML = `<div class="alert alert-danger mb-0"><i class="fas fa-triangle-exclamation me-1"></i>${data.error}</div>`;
                    } else if (!data.existe) {
                        resultado.innerHTML = '<div class="alert alert-danger mb-0"><i class="fas fa-triangle-exclamation me-1"></i>El documento no existe como traslado en a2.</div>';
                    } else if (!data.valido) {
                        resultado.innerHTML = `<div class="alert alert-danger mb-0"><i class="fas fa-triangle-exclamation me-1"></i>El traslado no incluye los SKUs: <strong>${data.faltantes.join(', ')}</strong></div>`;
                    } else {
                        validacionOk = true;
                        resultado.innerHTML = `<div class="alert alert-success mb-0"><i class="fas fa-check-circle me-1"></i>Traslado válido. Cubre los SKUs: <strong>${data.skus.join(', ')}</strong></div>`;
                    }
                    actualizar();
                })
                .catch(() => {
                    resultado.innerHTML = '<div class="alert alert-danger mb-0">Error de conexión al validar.</div>';
                })
                .finally(() => { btnValidar.disabled = false; });
        });

        actualizar();
    })();
    </script>

    {% else %}
    <div class="card">
        <div class="card-body p-0">
            <div class="table-responsive">
                <table class="table table-hover table-sm mb-0 align-middle">
                    <thead class="table-dark">
                        <tr>
                            <th>Pedido</th>
                            <th>Producto</th>
                            <th>Tipo</th>
                            <th>Resolución</th>
                            <th>Resuelto por</th>
                            <th>Fecha</th>
                            <th>Historial</th>
                            <th class="text-center">Acción</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for inc in incidencias %}
                        <tr>
                            <td>
                                <a href="{% url 'pedidos-detalle' inc.despacho.pedido.numero_pedido %}"
                                   class="fw-bold text-decoration-none">#{{ inc.despacho.pedido.numero_pedido }}</a>
                                <br><small class="text-muted">Despacho #{{ inc.despacho.numero_despacho }}</small>
                            </td>
                            <td>
                                {% if inc.tipo_incidencia == 'PRODUCTO_ERRONEO' and inc.codigo_real %}
                                    <span class="fw-semibold">{{ inc.codigo_real }}</span>
                                {% elif inc.pedido_item %}
                                    <span class="fw-semibold">{{ inc.pedido_item.codigo }}</span>
                                {% else %}—{% endif %}
                            </td>
                            <td>{{ inc.get_tipo_incidencia_display }}</td>
                            <td>
                                {% if inc.resolucion.tipo == 'TRASLADO' %}
                                    <span class="badge bg-info text-dark"><i class="fas fa-truck me-1"></i>Traslado {{ inc.resolucion.documento_traslado }}</span>
                                {% else %}
                                    <span class="badge bg-secondary"><i class="fas fa-hand me-1"></i>Manual</span>
                                {% endif %}
                                {% if inc.resolucion.observacion %}
                                    <br><small class="text-muted">{{ inc.resolucion.observacion }}</small>
                                {% endif %}
                            </td>
                            <td>{{ inc.resolucion.resuelto_por.username|default:"—"|capfirst }}</td>
                            <td class="text-nowrap">{{ inc.resolucion.fecha_resolucion|date:"d/m/Y H:i" }}</td>
                            <td>
                                <details>
                                    <summary class="small text-primary" style="cursor:pointer;">{{ inc.eventos_incidencia.count }} evento(s)</summary>
                                    <ul class="small mb-0 ps-3">
                                        {% for ev in inc.eventos_incidencia.all %}
                                        <li>
                                            <strong>{{ ev.get_tipo_evento_display }}</strong>
                                            — {{ ev.fecha|date:"d/m/Y H:i" }}
                                            — {{ ev.usuario.username|default:"—"|capfirst }}
                                            {% if ev.detalle %}<br><span class="text-muted">{{ ev.detalle }}</span>{% endif %}
                                        </li>
                                        {% endfor %}
                                    </ul>
                                </details>
                            </td>
                            <td class="text-center">
                                <form method="post" action="{% url 'pedidos-anular-resolucion' inc.resolucion.id %}"
                                      onsubmit="return confirm('¿Anular esta resolución? Las incidencias del grupo vuelven a pendientes.');"
                                      class="d-flex gap-1 justify-content-center">
                                    {% csrf_token %}
                                    <input type="text" name="motivo" class="form-control form-control-sm"
                                           placeholder="Motivo" required style="max-width:140px;">
                                    <button type="submit" class="btn btn-sm btn-outline-danger" title="Anular resolución">
                                        <i class="fas fa-rotate-left"></i>
                                    </button>
                                </form>
                            </td>
                        </tr>
                        {% empty %}
                        <tr>
                            <td colspan="8" class="text-center text-muted py-4">
                                <i class="fas fa-inbox fa-2x mb-2 d-block"></i>
                                No hay incidencias resueltas en el período seleccionado.
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    {% endif %}
```

- [ ] **Step 4: Menú y badge**

En `templates/dashboard.html`, dentro del bloque `{% if request.user|has_group:"Pedidos Supervisor" %}` (después de la línea `<li><a href="/pedidos/reporte/">Reporte</a></li>`):

```html
                        <li><a href="/pedidos/incidencias/resolver/">Incidencias</a></li>
```

En `templates/pedidos-detalle.html`, después de la línea del badge `INCIDENCIA`:

```html
                        {% elif item.estado == 'INCIDENCIA_RESUELTA' %}<span class="badge" style="background-color:#20c997;">Inc. Resuelta</span>
```

- [ ] **Step 5: Verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.ResolverIncidenciasUITest -v 2`
Expected: `OK` (3 tests).

- [ ] **Step 6: Suite completa y verificación manual**

Run: `python manage.py test PedidosAlmacen -v 1`
Expected: `OK` sin regresiones.

Verificación manual (con el servidor de desarrollo y a2 accesible): entrar como supervisor a `/pedidos/incidencias/resolver/`, seleccionar una incidencia real, validar un número de traslado existente en a2 (debe mostrar los SKUs cubiertos), confirmar, verificar el cambio de pestaña a Resueltas, el estado del despacho y el badge en el detalle del pedido; luego anular y verificar la reversión.

- [ ] **Step 7: Commit**

```bash
git add templates/pedidos-resolver-incidencias.html templates/dashboard.html templates/pedidos-detalle.html PedidosAlmacen/tests.py
git commit -m "feat(incidencias): ui de resolucion con validacion ajax, menu y badge"
```
