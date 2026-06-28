# Anulación de Pedidos y Despachos — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar un estado terminal `ANULADO` a `Pedido` y `Despacho`, ejecutable solo por supervisores/superuser, que excluye al objeto de todos los KPIs y deja rastro de auditoría.

**Architecture:** Estado `ANULADO` con campos de auditoría (`motivo_anulacion`, `anulado_por`, `fecha_anulacion`, `estado_anterior`) en ambos modelos. Dos vistas POST protegidas con `@user_passes_test(is_pedidos_supervisor)`. Los reportes KPI cambian su queryset base a `.exclude(estado='ANULADO')`. Las listas siguen mostrando los anulados con badge rojo.

**Tech Stack:** Django 4.x, PostgreSQL (prod), SQLite (tests), `pyodbc`/DBISAM (no afectado: anular es solo administrativo en Django).

## Global Constraints

- **Sin tocar a2:** Anular NO genera ningún movimiento ni traslado en a2/DBISAM. Es solo cambio de estado en Django.
- **Estado terminal:** No existe acción de "desanular". Una vez `ANULADO`, no se revierte desde la app.
- **Permiso único:** Solo `is_pedidos_supervisor(user)` (que ya incluye `is_superuser`) puede anular.
- **Independencia:** Anular un pedido NO toca sus despachos y viceversa.
- **Motivo obligatorio:** Toda anulación exige un `motivo` de texto no vacío.
- **Estilo:** PEP 8, type hints donde el código vecino los use, snake_case. Seguir patrones existentes en `views.py`.
- **Comando de tests:** `python manage.py test PedidosAlmacen --settings=Programarprecios.test_settings -v 2`

---

### Task 1: Modelos y migración (estado ANULADO + auditoría)

**Files:**
- Modify: `PedidosAlmacen/models.py` (`Pedido.ESTADO_CHOICES` ~línea 6-15, `Despacho.ESTADO_CHOICES` ~línea 72-78)
- Create: `PedidosAlmacen/migrations/0020_add_estado_anulado.py`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Produces: `Pedido` y `Despacho` con valor de estado `'ANULADO'` y campos `motivo_anulacion: str`, `anulado_por: User|None`, `fecha_anulacion: datetime|None`, `estado_anterior: str`.

- [ ] **Step 1: Escribir el test que falla**

Añadir al final de `PedidosAlmacen/tests.py`:

```python
class AnulacionModeloTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, Despacho
        self.user = User.objects.create_superuser(username='sup_model', password='x')
        self.pedido = Pedido.objects.create(solicitante=self.user)
        self.despacho = Despacho.objects.create(pedido=self.pedido)

    def test_pedido_acepta_estado_anulado_y_campos(self):
        from django.utils import timezone
        self.pedido.estado_anterior = self.pedido.estado
        self.pedido.estado = 'ANULADO'
        self.pedido.motivo_anulacion = 'Pedido duplicado'
        self.pedido.anulado_por = self.user
        self.pedido.fecha_anulacion = timezone.now()
        self.pedido.save()
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'ANULADO')
        self.assertEqual(self.pedido.motivo_anulacion, 'Pedido duplicado')
        self.assertEqual(self.pedido.anulado_por, self.user)
        self.assertIsNotNone(self.pedido.fecha_anulacion)
        self.assertEqual(self.pedido.estado_anterior, 'PENDIENTE')

    def test_despacho_acepta_estado_anulado_y_campos(self):
        self.despacho.estado_anterior = self.despacho.estado
        self.despacho.estado = 'ANULADO'
        self.despacho.motivo_anulacion = 'Error de carga'
        self.despacho.anulado_por = self.user
        self.despacho.save()
        self.despacho.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'ANULADO')
        self.assertEqual(self.despacho.estado_anterior, 'PREPARANDO')
        self.assertEqual(self.despacho.anulado_por, self.user)

    def test_anulado_en_choices(self):
        from .models import Pedido, Despacho
        self.assertIn('ANULADO', dict(Pedido.ESTADO_CHOICES))
        self.assertIn('ANULADO', dict(Despacho.ESTADO_CHOICES))
```

- [ ] **Step 2: Ejecutar el test para verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.AnulacionModeloTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL (campos `estado_anterior`/`motivo_anulacion`/... no existen aún, y `ANULADO` no está en choices).

- [ ] **Step 3: Modificar los modelos**

En `PedidosAlmacen/models.py`, añadir `('ANULADO', 'Anulado')` al final de `Pedido.ESTADO_CHOICES`:

```python
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('ASIGNADO', 'Asignado'),
        ('PICKING', 'Picking'),
        ('EN_PREPARACION', 'En Preparación'),
        ('DESPACHADO', 'Despachado'),
        ('PARCIAL', 'Parcial'),
        ('RECIBIDO', 'Recibido'),
        ('CERRADO', 'Cerrado'),
        ('ANULADO', 'Anulado'),
    ]
```

Añadir los campos de auditoría dentro de `Pedido` (debajo de `fecha_asignacion`):

```python
    fecha_asignacion = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True, default='')
    anulado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pedidos_anulados',
    )
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    estado_anterior = models.CharField(max_length=20, blank=True, default='')
```

Añadir `('ANULADO', 'Anulado')` al final de `Despacho.ESTADO_CHOICES`:

```python
    ESTADO_CHOICES = [
        ('PENDIENTE_APROBACION', 'Pendiente de Aprobación'),
        ('PREPARANDO', 'Preparando'),
        ('ENVIADO', 'Enviado'),
        ('RECIBIDO', 'Recibido'),
        ('PARCIAL', 'Parcial'),
        ('ANULADO', 'Anulado'),
    ]
```

Añadir los campos de auditoría dentro de `Despacho` (debajo de `traslado_a2_registrado`):

```python
    traslado_a2_registrado = models.BooleanField(default=False)
    motivo_anulacion = models.TextField(blank=True, default='')
    anulado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='despachos_anulados',
    )
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    estado_anterior = models.CharField(max_length=20, blank=True, default='')
```

- [ ] **Step 4: Generar la migración**

Run: `python manage.py makemigrations PedidosAlmacen --name add_estado_anulado --settings=Programarprecios.test_settings`
Expected: crea `PedidosAlmacen/migrations/0020_add_estado_anulado.py` con `AddField` para los 8 campos nuevos (4 en pedido, 4 en despacho) y `AlterField` para `estado` de ambos modelos (por el cambio de choices). Verificar que `dependencies` apunta a `0019_add_traslado_a2_registrado`.

- [ ] **Step 5: Verificar que no quedan migraciones pendientes**

Run: `python manage.py makemigrations --check --dry-run --settings=Programarprecios.test_settings`
Expected: "No changes detected".

- [ ] **Step 6: Ejecutar el test para verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.AnulacionModeloTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add PedidosAlmacen/models.py PedidosAlmacen/migrations/0020_add_estado_anulado.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): estado ANULADO y campos de auditoria en Pedido y Despacho"
```

---

### Task 2: Vista anular_pedido + URL

**Files:**
- Modify: `PedidosAlmacen/views.py` (añadir vista; usar imports ya presentes: `timezone`, `messages`, `logger`, `get_object_or_404`, `redirect`, `user_passes_test`, `is_pedidos_supervisor`)
- Modify: `PedidosAlmacen/urls.py`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `Pedido` con estado `ANULADO` y campos de auditoría (Task 1).
- Produces: vista `anular_pedido(request, pk)` con URL name `pedidos-anular`. POST con campo `motivo`. Redirige siempre a `pedidos-detalle`.

- [ ] **Step 1: Escribir el test que falla**

Añadir a `PedidosAlmacen/tests.py`:

```python
class AnularPedidoVistaTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_p', password='x')
        self.tienda = User.objects.create_user(username='tnd_p', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda.groups.add(g)
        self.pedido = Pedido.objects.create(solicitante=self.tienda, estado='PICKING')
        self.pedido.picker = self.sup
        self.pedido.save()

    def _url(self):
        return self.reverse('pedidos-anular', args=[self.pedido.numero_pedido])

    def test_supervisor_anula_con_motivo_y_libera_picker(self):
        self.client.force_login(self.sup)
        resp = self.client.post(self._url(), {'motivo': 'Duplicado'})
        self.assertEqual(resp.status_code, 302)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'ANULADO')
        self.assertEqual(self.pedido.estado_anterior, 'PICKING')
        self.assertEqual(self.pedido.motivo_anulacion, 'Duplicado')
        self.assertEqual(self.pedido.anulado_por, self.sup)
        self.assertIsNotNone(self.pedido.fecha_anulacion)
        self.assertIsNone(self.pedido.picker)

    def test_sin_motivo_no_anula(self):
        self.client.force_login(self.sup)
        self.client.post(self._url(), {'motivo': '   '})
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'PICKING')

    def test_tienda_no_puede_anular(self):
        self.client.force_login(self.tienda)
        resp = self.client.post(self._url(), {'motivo': 'x'})
        self.assertEqual(resp.status_code, 302)  # redirect a dashboard
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'PICKING')

    def test_ya_anulado_no_se_reanula(self):
        from django.utils import timezone
        self.pedido.estado = 'ANULADO'
        self.pedido.motivo_anulacion = 'Primera'
        self.pedido.fecha_anulacion = timezone.now()
        self.pedido.save()
        self.client.force_login(self.sup)
        self.client.post(self._url(), {'motivo': 'Segunda'})
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.motivo_anulacion, 'Primera')

    def test_get_no_anula(self):
        self.client.force_login(self.sup)
        self.client.get(self._url())
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'PICKING')
```

- [ ] **Step 2: Ejecutar el test para verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.AnularPedidoVistaTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL con `NoReverseMatch: 'pedidos-anular'`.

- [ ] **Step 3: Añadir la vista**

En `PedidosAlmacen/views.py`, añadir tras `detalle_pedido` (después de la línea ~305):

```python
@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def anular_pedido(request, pk):
    pedido = get_object_or_404(Pedido, numero_pedido=pk)
    if request.method != 'POST':
        return redirect('pedidos-detalle', pk=pk)
    if pedido.estado == 'ANULADO':
        messages.warning(request, 'Este pedido ya está anulado')
        return redirect('pedidos-detalle', pk=pk)
    motivo = request.POST.get('motivo', '').strip()
    if not motivo:
        messages.error(request, 'Debes indicar un motivo para anular el pedido')
        return redirect('pedidos-detalle', pk=pk)
    pedido.estado_anterior = pedido.estado
    if pedido.estado in ('ASIGNADO', 'PICKING'):
        pedido.picker = None
    pedido.estado = 'ANULADO'
    pedido.anulado_por = request.user
    pedido.fecha_anulacion = timezone.now()
    pedido.motivo_anulacion = motivo
    pedido.save()
    logger.info(
        'Pedido #%s anulado por %s. Motivo: %s',
        pedido.numero_pedido, request.user.username, motivo,
    )
    messages.success(request, f'Pedido #{pedido.numero_pedido} anulado')
    return redirect('pedidos-detalle', pk=pk)
```

- [ ] **Step 4: Añadir la URL**

En `PedidosAlmacen/urls.py`, añadir dentro de `urlpatterns` (junto al resto de rutas de pedido):

```python
    path('pedidos/<int:pk>/anular/', views.anular_pedido, name='pedidos-anular'),
```

- [ ] **Step 5: Ejecutar el test para verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.AnularPedidoVistaTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/urls.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): vista anular_pedido (solo supervisor/superuser, libera picker)"
```

---

### Task 3: Vista anular_despacho + URL

**Files:**
- Modify: `PedidosAlmacen/views.py`
- Modify: `PedidosAlmacen/urls.py`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `Despacho` con estado `ANULADO` y auditoría (Task 1).
- Produces: vista `anular_despacho(request, despacho_id)` con URL name `despachos-anular`. POST con `motivo`. Redirige a `pedidos-detalle` del pedido del despacho.

- [ ] **Step 1: Escribir el test que falla**

Añadir a `PedidosAlmacen/tests.py`:

```python
class AnularDespachoVistaTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido, Despacho
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_d', password='x')
        self.tienda = User.objects.create_user(username='tnd_d', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda.groups.add(g)
        self.pedido = Pedido.objects.create(solicitante=self.tienda, estado='DESPACHADO')
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='ENVIADO')

    def _url(self):
        return self.reverse('despachos-anular', args=[self.despacho.numero_despacho])

    def test_supervisor_anula_despacho(self):
        self.client.force_login(self.sup)
        resp = self.client.post(self._url(), {'motivo': 'Carga erronea'})
        self.assertEqual(resp.status_code, 302)
        self.despacho.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'ANULADO')
        self.assertEqual(self.despacho.estado_anterior, 'ENVIADO')
        self.assertEqual(self.despacho.anulado_por, self.sup)
        self.assertIsNotNone(self.despacho.fecha_anulacion)
        # Independencia: el pedido NO se toca
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'DESPACHADO')

    def test_sin_motivo_no_anula(self):
        self.client.force_login(self.sup)
        self.client.post(self._url(), {'motivo': ''})
        self.despacho.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'ENVIADO')

    def test_tienda_no_puede_anular(self):
        self.client.force_login(self.tienda)
        self.client.post(self._url(), {'motivo': 'x'})
        self.despacho.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'ENVIADO')

    def test_ya_anulado_no_se_reanula(self):
        from django.utils import timezone
        self.despacho.estado = 'ANULADO'
        self.despacho.motivo_anulacion = 'Primera'
        self.despacho.fecha_anulacion = timezone.now()
        self.despacho.save()
        self.client.force_login(self.sup)
        self.client.post(self._url(), {'motivo': 'Segunda'})
        self.despacho.refresh_from_db()
        self.assertEqual(self.despacho.motivo_anulacion, 'Primera')
```

- [ ] **Step 2: Ejecutar el test para verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.AnularDespachoVistaTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL con `NoReverseMatch: 'despachos-anular'`.

- [ ] **Step 3: Añadir la vista**

En `PedidosAlmacen/views.py`, añadir tras `lista_despachos` (después de la línea ~684):

```python
@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def anular_despacho(request, despacho_id):
    despacho = get_object_or_404(Despacho, numero_despacho=despacho_id)
    if request.method != 'POST':
        return redirect('pedidos-detalle', pk=despacho.pedido_id)
    if despacho.estado == 'ANULADO':
        messages.warning(request, 'Este despacho ya está anulado')
        return redirect('pedidos-detalle', pk=despacho.pedido_id)
    motivo = request.POST.get('motivo', '').strip()
    if not motivo:
        messages.error(request, 'Debes indicar un motivo para anular el despacho')
        return redirect('pedidos-detalle', pk=despacho.pedido_id)
    despacho.estado_anterior = despacho.estado
    despacho.estado = 'ANULADO'
    despacho.anulado_por = request.user
    despacho.fecha_anulacion = timezone.now()
    despacho.motivo_anulacion = motivo
    despacho.save()
    logger.info(
        'Despacho #%s anulado por %s. Motivo: %s',
        despacho.numero_despacho, request.user.username, motivo,
    )
    messages.success(request, f'Despacho #{despacho.numero_despacho} anulado')
    return redirect('pedidos-detalle', pk=despacho.pedido_id)
```

- [ ] **Step 4: Añadir la URL**

En `PedidosAlmacen/urls.py`, añadir junto a la ruta de `despachos-lista`:

```python
    path('despachos/<int:despacho_id>/anular/', views.anular_despacho, name='despachos-anular'),
```

- [ ] **Step 5: Ejecutar el test para verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.AnularDespachoVistaTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/urls.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): vista anular_despacho independiente del pedido"
```

---

### Task 4: Exclusión de anulados en KPIs + contador informativo

**Files:**
- Modify: `PedidosAlmacen/views.py` (`reporte_pedidos` ~línea 1088, `exportar_reporte_pdf` ~línea 1200, `reporte_incidencias` ~línea 1324)
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: estado `ANULADO` (Task 1).
- Produces: contexto de `reporte_pedidos` con clave nueva `total_anulados: int`. KPIs (`total_pedidos`, `por_estado`, totales de ítems, tiempos, incidencias) excluyen anulados.

- [ ] **Step 1: Escribir el test que falla**

Añadir a `PedidosAlmacen/tests.py`:

```python
class ReporteExcluyeAnuladosTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, PedidoItem
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_r', password='x')
        # Pedido válido
        self.ok = Pedido.objects.create(solicitante=self.sup, estado='RECIBIDO')
        PedidoItem.objects.create(pedido=self.ok, codigo='A', descripcion='a',
                                  cantidad_solicitada=5, cantidad_despachada=5,
                                  cantidad_recibida=5, estado='RECIBIDO')
        # Pedido anulado (no debe contar en KPIs)
        self.anu = Pedido.objects.create(solicitante=self.sup, estado='ANULADO',
                                         motivo_anulacion='x')
        PedidoItem.objects.create(pedido=self.anu, codigo='B', descripcion='b',
                                  cantidad_solicitada=100, cantidad_despachada=100,
                                  cantidad_recibida=100, estado='RECIBIDO')

    def test_kpis_excluyen_anulados(self):
        self.client.force_login(self.sup)
        resp = self.client.get(self.reverse('pedidos-reporte'))
        self.assertEqual(resp.context['total_pedidos'], 1)
        self.assertEqual(resp.context['total_solicitado'], 5)
        estados = [fila['estado'] for fila in resp.context['por_estado']]
        self.assertNotIn('ANULADO', estados)

    def test_contador_anulados_presente(self):
        self.client.force_login(self.sup)
        resp = self.client.get(self.reverse('pedidos-reporte'))
        self.assertEqual(resp.context['total_anulados'], 1)
```

- [ ] **Step 2: Ejecutar el test para verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.ReporteExcluyeAnuladosTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL (`total_pedidos` == 2 y `KeyError`/None en `total_anulados`).

- [ ] **Step 3: Excluir anulados y añadir contador en `reporte_pedidos`**

En `PedidosAlmacen/views.py`, dentro de `reporte_pedidos`, cambiar la línea base del queryset:

```python
    pedidos = Pedido.objects.exclude(estado='ANULADO')
```

Y justo después de calcular `total_pedidos` (tras la línea `total_pedidos = pedidos.count()`), añadir el contador sobre el mismo rango de fechas pero filtrando anulados:

```python
    anulados_qs = Pedido.objects.filter(estado='ANULADO')
    if fecha_inicio:
        anulados_qs = anulados_qs.filter(fecha_creacion__date__gte=fecha_inicio)
    if fecha_fin:
        anulados_qs = anulados_qs.filter(fecha_creacion__date__lte=fecha_fin)
    total_anulados = anulados_qs.count()
```

Añadir `'total_anulados': total_anulados,` al diccionario de contexto del `render`.

- [ ] **Step 4: Excluir anulados en `exportar_reporte_pdf` y `reporte_incidencias`**

En `exportar_reporte_pdf`, cambiar la línea base:

```python
    pedidos = Pedido.objects.exclude(estado='ANULADO')
```

En `reporte_incidencias`, encadenar al queryset `qs` de `DespachoItem` (tras el `.order_by('-despacho__fecha_despacho')`):

```python
    ).order_by('-despacho__fecha_despacho').exclude(
        despacho__estado='ANULADO'
    ).exclude(despacho__pedido__estado='ANULADO')
```

- [ ] **Step 5: Ejecutar el test para verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.ReporteExcluyeAnuladosTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): excluir anulados de KPIs y contador informativo en reporte"
```

---

### Task 5: Plantillas (badge ANULADO + botón Anular con modal)

**Files:**
- Modify: `templates/pedidos-lista.html` (bloque de badges de estado ~línea 78-93)
- Modify: `templates/despachos-lista.html` (bloque de badges de estado ~línea 66-75)
- Modify: `templates/pedidos-detalle.html` (badge de estado del pedido ~línea 83-98; badges de despacho ~línea 261-269; botonera ~línea 8-12)
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: URLs `pedidos-anular` y `despachos-anular` (Tasks 2, 3); contexto `es_supervisor` ya presente en `detalle_pedido`.
- Produces: HTML — badge `ANULADO`, bloque de auditoría, y botón/modal de anulación visibles solo para supervisor.

- [ ] **Step 1: Escribir el test que falla**

Añadir a `PedidosAlmacen/tests.py`:

```python
class AnularDetalleTemplateTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_t', password='x')
        self.tienda = User.objects.create_user(username='tnd_t', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda.groups.add(g)
        self.pedido = Pedido.objects.create(solicitante=self.tienda, estado='PENDIENTE')

    def _detalle(self):
        return self.reverse('pedidos-detalle', args=[self.pedido.numero_pedido])

    def test_supervisor_ve_boton_anular(self):
        self.client.force_login(self.sup)
        resp = self.client.get(self._detalle())
        self.assertContains(resp, 'modalAnularPedido')
        self.assertContains(resp, self.reverse('pedidos-anular', args=[self.pedido.numero_pedido]))

    def test_tienda_no_ve_boton_anular(self):
        self.client.force_login(self.tienda)
        resp = self.client.get(self._detalle())
        self.assertNotContains(resp, 'modalAnularPedido')

    def test_pedido_anulado_muestra_motivo(self):
        from django.utils import timezone
        self.pedido.estado = 'ANULADO'
        self.pedido.estado_anterior = 'PENDIENTE'
        self.pedido.motivo_anulacion = 'Motivo de prueba visible'
        self.pedido.anulado_por = self.sup
        self.pedido.fecha_anulacion = timezone.now()
        self.pedido.save()
        self.client.force_login(self.sup)
        resp = self.client.get(self._detalle())
        self.assertContains(resp, 'Motivo de prueba visible')
        # Ya anulado: no debe ofrecer volver a anular
        self.assertNotContains(resp, 'modalAnularPedido')
```

- [ ] **Step 2: Ejecutar el test para verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.AnularDetalleTemplateTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL (no existe `modalAnularPedido` en la plantilla).

- [ ] **Step 3: Badge ANULADO en `templates/pedidos-lista.html`**

En el bloque de badges de estado (tras el `{% elif pedido.estado == 'CERRADO' %}`), añadir antes del cierre del `if`:

```django
                    {% elif pedido.estado == 'ANULADO' %}
                        <span class="badge bg-danger"><i class="fas fa-ban"></i> Anulado</span>
```

- [ ] **Step 4: Badge ANULADO en `templates/despachos-lista.html`**

En el bloque de badges (tras el `{% elif despacho.estado == 'PARCIAL' %}`), añadir:

```django
                    {% elif despacho.estado == 'ANULADO' %}
                        <span class="badge bg-danger"><i class="fas fa-ban"></i> Anulado</span>
```

- [ ] **Step 5: Badges + bloque de auditoría + botón/modal en `templates/pedidos-detalle.html`**

(a) En el badge de estado del pedido (tras `{% elif pedido.estado == 'CERRADO' %}`), añadir:

```django
                                {% elif pedido.estado == 'ANULADO' %}
                                    <span class="badge bg-danger"><i class="fas fa-ban"></i> Anulado</span>
```

(b) En el badge de estado del despacho (tras `{% elif despacho.estado == 'PREPARANDO' %}` ... antes de cerrar el `if` de ese bloque), añadir:

```django
                            {% elif despacho.estado == 'ANULADO' %}
                                <span class="badge bg-danger"><i class="fas fa-ban"></i> Anulado</span>
```

(c) En la botonera superior (junto al botón de imprimir, ~línea 8-12), añadir el botón de anular pedido visible solo para supervisor y solo si no está anulado:

```django
            {% if es_supervisor and pedido.estado != 'ANULADO' %}
            <button type="button" class="btn btn-outline-danger" data-bs-toggle="modal" data-bs-target="#modalAnularPedido" title="Anular pedido">
                <i class="fas fa-ban"></i> Anular
            </button>
            {% endif %}
```

(d) Bloque de auditoría: cuando el pedido esté anulado, mostrarlo bajo la cabecera (por ejemplo tras el bloque de mensajes/alertas, ~línea 51):

```django
            {% if pedido.estado == 'ANULADO' %}
            <div class="alert alert-danger">
                <strong><i class="fas fa-ban"></i> Pedido anulado</strong>
                {% if pedido.estado_anterior %}(estado previo: {{ pedido.estado_anterior }}){% endif %}<br>
                <strong>Motivo:</strong> {{ pedido.motivo_anulacion }}<br>
                <small>Por {{ pedido.anulado_por.username|default:"-" }} el {{ pedido.fecha_anulacion|date:"d/m/Y H:i" }}</small>
            </div>
            {% endif %}
```

(e) Modal de confirmación con motivo obligatorio (añadir al final del bloque de contenido de la plantilla, junto al `modalImprimirPedido`):

```django
{% if es_supervisor and pedido.estado != 'ANULADO' %}
<div class="modal fade" id="modalAnularPedido" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog">
    <form method="post" action="{% url 'pedidos-anular' pedido.numero_pedido %}">
      {% csrf_token %}
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">Anular pedido #{{ pedido.numero_pedido }}</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>
        </div>
        <div class="modal-body">
          <p class="text-danger"><i class="fas fa-exclamation-triangle"></i> Esta acción es irreversible y saca el pedido de los reportes KPI. No revierte inventario en a2.</p>
          <label class="form-label fw-bold">Motivo de la anulación <span class="text-danger">*</span></label>
          <textarea name="motivo" class="form-control" rows="3" required></textarea>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
          <button type="submit" class="btn btn-danger">Anular pedido</button>
        </div>
      </div>
    </form>
  </div>
</div>
{% endif %}
```

(f) Botón + modal para anular cada despacho no anulado, dentro del bloque que itera los despachos (junto a `Despacho #{{ despacho.numero_despacho }}`), gated por `es_supervisor`:

```django
            {% if es_supervisor and despacho.estado != 'ANULADO' %}
            <button type="button" class="btn btn-sm btn-outline-danger" data-bs-toggle="modal" data-bs-target="#modalAnularDespacho{{ despacho.numero_despacho }}" title="Anular despacho">
                <i class="fas fa-ban"></i> Anular
            </button>
            <div class="modal fade" id="modalAnularDespacho{{ despacho.numero_despacho }}" tabindex="-1" aria-hidden="true">
              <div class="modal-dialog">
                <form method="post" action="{% url 'despachos-anular' despacho.numero_despacho %}">
                  {% csrf_token %}
                  <div class="modal-content">
                    <div class="modal-header">
                      <h5 class="modal-title">Anular despacho #{{ despacho.numero_despacho }}</h5>
                      <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>
                    </div>
                    <div class="modal-body">
                      <p class="text-danger"><i class="fas fa-exclamation-triangle"></i> Acción irreversible. No revierte inventario en a2.</p>
                      <label class="form-label fw-bold">Motivo <span class="text-danger">*</span></label>
                      <textarea name="motivo" class="form-control" rows="3" required></textarea>
                    </div>
                    <div class="modal-footer">
                      <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
                      <button type="submit" class="btn btn-danger">Anular despacho</button>
                    </div>
                  </div>
                </form>
              </div>
            </div>
            {% endif %}
```

- [ ] **Step 6: Ejecutar el test para verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.AnularDetalleTemplateTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (3 tests).

- [ ] **Step 7: Ejecutar toda la suite de la app**

Run: `python manage.py test PedidosAlmacen --settings=Programarprecios.test_settings -v 2`
Expected: PASS (toda la suite, sin regresiones).

- [ ] **Step 8: Commit**

```bash
git add templates/pedidos-lista.html templates/despachos-lista.html templates/pedidos-detalle.html PedidosAlmacen/tests.py
git commit -m "feat(pedidos): badge ANULADO en listas y boton/modal de anulacion en detalle"
```

---

## Notas de verificación final

Tras completar las 5 tareas:
- `python manage.py test PedidosAlmacen --settings=Programarprecios.test_settings` en verde.
- Verificación manual sugerida: como supervisor, anular un pedido y un despacho desde el detalle (con y sin motivo), confirmar que el reporte KPI ya no los cuenta y que aparecen con badge rojo en las listas.
