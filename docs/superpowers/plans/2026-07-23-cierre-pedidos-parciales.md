# Cierre de Pedidos Parciales — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que Supervisores, Almacenistas y superusers cierren pedidos en estado `PARCIAL` sin despachos pendientes, dejando los back orders en 0 y con auditoría (quién, cuándo, motivo).

**Architecture:** Sigue el patrón existente de anulación en `PedidosAlmacen`: vista solo-POST con transacción + `select_for_update`, botón con modal Bootstrap en `pedidos-detalle.html`, campos de auditoría en el modelo `Pedido`, nuevo estado `CERRADO` a nivel de `PedidoItem`. Spec: `docs/superpowers/specs/2026-07-23-cierre-pedidos-parciales-design.md`.

**Tech Stack:** Django (app `PedidosAlmacen`), PostgreSQL en producción, tests con SQLite vía `Programarprecios.test_settings` (archivo local no commiteado).

## Global Constraints

- Tests SIEMPRE con: `venv\Scripts\python.exe manage.py test PedidosAlmacen --settings=Programarprecios.test_settings` (el Python del sistema no tiene las dependencias; Postgres no permite CREATEDB).
- `select_for_update()` sin `select_related()` de FKs nullables en la misma queryset (SQLite lo tolera pero Postgres revienta con outer joins nullables).
- Modelo de usuario propio `users.models.User`: NO tiene `first_name`/`last_name`; usar `username`. Tiene campo booleano `status`.
- Mensajes al usuario y comentarios en español; código PEP 8, snake_case.
- Estados bloqueantes de despacho para el cierre: `ENVIADO`, `PENDIENTE_APROBACION`, `PREPARANDO`. NO bloquean: `RECIBIDO`, `PARCIAL`, `ANULADO`.
- Permiso de cierre: grupo `Pedidos Supervisor` o grupo `Pedidos Almacen` o superuser (helpers existentes `is_pedidos_supervisor` / `is_pedidos_almacen`, ambos ya incluyen superuser).

---

### Task 1: Modelo y migración (estado CERRADO de item + auditoría de cierre en Pedido)

**Files:**
- Modify: `PedidosAlmacen/models.py` (clases `Pedido` y `PedidoItem`)
- Create: `PedidosAlmacen/migrations/0027_*.py` (vía makemigrations)
- Test: `PedidosAlmacen/tests.py` (nueva clase al final del archivo)

**Interfaces:**
- Consumes: modelos existentes `Pedido`, `PedidoItem` de `PedidosAlmacen/models.py`.
- Produces: `Pedido.cerrado_por` (FK nullable a User, related_name `pedidos_cerrados`), `Pedido.fecha_cierre` (DateTimeField nullable), `Pedido.motivo_cierre` (TextField default `''`), y choice `('CERRADO', 'Cerrado')` en `PedidoItem.ESTADO_ITEM_CHOICES`. Las Tasks 2 y 3 dependen de estos nombres exactos.

- [ ] **Step 1: Escribir el test que falla**

Al final de `PedidosAlmacen/tests.py` agregar:

```python
class CierrePedidoModeloTest(TestCase):
    def test_pedido_tiene_campos_de_cierre(self):
        from users.models import User
        from .models import Pedido, PedidoItem
        from django.utils import timezone

        user = User.objects.create_user(username='mod_cierre', password='x')
        pedido = Pedido.objects.create(
            solicitante=user, estado='PARCIAL',
            cerrado_por=user, fecha_cierre=timezone.now(),
            motivo_cierre='prueba de cierre',
        )
        item = PedidoItem.objects.create(
            pedido=pedido, codigo='X1', descripcion='Prod X',
            cantidad_solicitada=3, estado='CERRADO',
        )

        pedido.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(pedido.cerrado_por, user)
        self.assertEqual(pedido.motivo_cierre, 'prueba de cierre')
        self.assertIsNotNone(pedido.fecha_cierre)
        self.assertEqual(item.estado, 'CERRADO')
        self.assertIn(pedido, user.pedidos_cerrados.all())
        self.assertIn(
            ('CERRADO', 'Cerrado'), PedidoItem.ESTADO_ITEM_CHOICES,
        )
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CierrePedidoModeloTest --settings=Programarprecios.test_settings`
Expected: FAIL/ERROR con `TypeError: ... got unexpected keyword arguments: 'cerrado_por' ...` (los campos no existen).

- [ ] **Step 3: Agregar los campos al modelo**

En `PedidosAlmacen/models.py`, clase `Pedido`, después del bloque de anulación (tras la línea `estado_anterior = models.CharField(max_length=20, blank=True, default='')`) agregar:

```python
    # Cierre administrativo de pedidos PARCIAL con back orders incompletables.
    cerrado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pedidos_cerrados',
    )
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    motivo_cierre = models.TextField(blank=True, default='')
```

En la clase `PedidoItem`, en `ESTADO_ITEM_CHOICES`, agregar al final de la lista (tras `('INCIDENCIA_RESUELTA', 'Incidencia Resuelta'),`):

```python
        ('CERRADO', 'Cerrado'),
```

- [ ] **Step 4: Generar la migración**

Run: `venv\Scripts\python.exe manage.py makemigrations PedidosAlmacen`
Expected: crea `PedidosAlmacen/migrations/0027_...py` con `AddField` × 3 sobre `pedido` y `AlterField` sobre `pedidoitem.estado`.

- [ ] **Step 5: Correr el test y verificar que pasa**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CierrePedidoModeloTest --settings=Programarprecios.test_settings`
Expected: PASS (ok, 1 test).

- [ ] **Step 6: Aplicar la migración a la BD real**

Run: `venv\Scripts\python.exe manage.py migrate PedidosAlmacen`
Expected: `Applying PedidosAlmacen.0027_... OK`

- [ ] **Step 7: Commit**

```bash
git add PedidosAlmacen/models.py PedidosAlmacen/migrations/ PedidosAlmacen/tests.py
git commit -m "feat(pedidos): campos de cierre en Pedido y estado CERRADO por item"
```

---

### Task 2: Vista `cerrar_pedido` + URL

**Files:**
- Modify: `PedidosAlmacen/views.py` (helpers cerca de `is_pedidos_almacen` ~línea 87; vista nueva después de `anular_pedido`, ~línea 427)
- Modify: `PedidosAlmacen/urls.py` (tras la ruta `pedidos-anular`)
- Test: `PedidosAlmacen/tests.py` (nueva clase al final)

**Interfaces:**
- Consumes: campos de Task 1 (`cerrado_por`, `fecha_cierre`, `motivo_cierre`, estado de item `CERRADO`); helpers existentes `is_pedidos_supervisor(user)`, `is_pedidos_almacen(user)`; `logger`, `messages`, `transaction`, `timezone` ya importados en `views.py`.
- Produces: `_puede_cerrar_pedido(pedido) -> bool` (elegibilidad sin permisos, la usa Task 3), `is_pedidos_supervisor_o_almacen(user) -> bool`, vista `cerrar_pedido(request, pk)` y URL name `pedidos-cerrar` (`pedidos/<pk>/cerrar/`).

- [ ] **Step 1: Escribir los tests que fallan**

Al final de `PedidosAlmacen/tests.py` agregar:

```python
class CerrarPedidoVistaTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from users.models import User
        from .models import Pedido, PedidoItem

        g_sup, _ = Group.objects.get_or_create(name='Pedidos Supervisor')
        g_alm, _ = Group.objects.get_or_create(name='Pedidos Almacen')
        g_tnd, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        g_pick, _ = Group.objects.get_or_create(name='Pedidos Picker')

        self.supervisor = User.objects.create_user(username='sup_cierre', password='x')
        self.supervisor.groups.add(g_sup)
        self.almacen = User.objects.create_user(username='alm_cierre', password='x')
        self.almacen.groups.add(g_alm)
        self.tienda = User.objects.create_user(username='tnd_cierre', password='x')
        self.tienda.groups.add(g_tnd)
        self.picker = User.objects.create_user(username='pick_cierre', password='x')
        self.picker.groups.add(g_pick)
        self.superuser = User.objects.create_superuser(username='root_cierre', password='x')

        self.pedido = Pedido.objects.create(solicitante=self.tienda, estado='PARCIAL')
        self.item_parcial = PedidoItem.objects.create(
            pedido=self.pedido, codigo='A1', descripcion='Prod A',
            cantidad_solicitada=10, cantidad_despachada=6,
            cantidad_back_order=4, estado='PARCIAL',
        )
        self.item_bo = PedidoItem.objects.create(
            pedido=self.pedido, codigo='B2', descripcion='Prod B',
            cantidad_solicitada=5, cantidad_despachada=0,
            cantidad_back_order=5, estado='BACK_ORDER',
        )
        self.item_recibido = PedidoItem.objects.create(
            pedido=self.pedido, codigo='C3', descripcion='Prod C',
            cantidad_solicitada=2, cantidad_despachada=2,
            cantidad_back_order=0, cantidad_recibida=2, estado='RECIBIDO',
        )

    def _cerrar(self, user, motivo='proveedor sin stock'):
        self.client.force_login(user)
        return self.client.post(
            f'/pedidos/{self.pedido.numero_pedido}/cerrar/',
            {'motivo': motivo},
        )

    def _refrescar(self):
        self.pedido.refresh_from_db()
        self.item_parcial.refresh_from_db()
        self.item_bo.refresh_from_db()
        self.item_recibido.refresh_from_db()

    def test_supervisor_cierra_pedido_parcial(self):
        resp = self._cerrar(self.supervisor)
        self.assertRedirects(
            resp, f'/pedidos/{self.pedido.numero_pedido}/',
            fetch_redirect_response=False,
        )
        self._refrescar()
        self.assertEqual(self.pedido.estado, 'CERRADO')
        self.assertEqual(self.pedido.cerrado_por, self.supervisor)
        self.assertEqual(self.pedido.motivo_cierre, 'proveedor sin stock')
        self.assertIsNotNone(self.pedido.fecha_cierre)
        self.assertEqual(self.item_parcial.estado, 'CERRADO')
        self.assertEqual(self.item_parcial.cantidad_back_order, 0)
        self.assertEqual(self.item_bo.estado, 'CERRADO')
        self.assertEqual(self.item_bo.cantidad_back_order, 0)
        # El item ya recibido no se toca
        self.assertEqual(self.item_recibido.estado, 'RECIBIDO')
        self.assertEqual(self.item_recibido.cantidad_recibida, 2)

    def test_almacen_puede_cerrar(self):
        self._cerrar(self.almacen)
        self._refrescar()
        self.assertEqual(self.pedido.estado, 'CERRADO')
        self.assertEqual(self.pedido.cerrado_por, self.almacen)

    def test_superuser_puede_cerrar(self):
        self._cerrar(self.superuser)
        self._refrescar()
        self.assertEqual(self.pedido.estado, 'CERRADO')

    def test_tienda_no_puede_cerrar(self):
        self._cerrar(self.tienda)
        self._refrescar()
        self.assertEqual(self.pedido.estado, 'PARCIAL')
        self.assertEqual(self.item_parcial.cantidad_back_order, 4)

    def test_picker_no_puede_cerrar(self):
        self._cerrar(self.picker)
        self._refrescar()
        self.assertEqual(self.pedido.estado, 'PARCIAL')

    def test_motivo_obligatorio(self):
        self._cerrar(self.supervisor, motivo='   ')
        self._refrescar()
        self.assertEqual(self.pedido.estado, 'PARCIAL')
        self.assertEqual(self.item_parcial.cantidad_back_order, 4)

    def test_get_no_cierra(self):
        self.client.force_login(self.supervisor)
        self.client.get(f'/pedidos/{self.pedido.numero_pedido}/cerrar/')
        self._refrescar()
        self.assertEqual(self.pedido.estado, 'PARCIAL')

    def test_rechaza_pedido_no_parcial(self):
        for estado in ('PENDIENTE', 'ASIGNADO', 'PICKING', 'EN_PREPARACION',
                       'DESPACHADO', 'RECIBIDO', 'CERRADO', 'ANULADO'):
            self.pedido.estado = estado
            self.pedido.save()
            self._cerrar(self.supervisor)
            self.pedido.refresh_from_db()
            self.assertEqual(self.pedido.estado, estado)
        self.item_parcial.refresh_from_db()
        self.assertEqual(self.item_parcial.cantidad_back_order, 4)

    def test_despacho_pendiente_bloquea_cierre(self):
        from .models import Despacho
        for estado_despacho in ('ENVIADO', 'PENDIENTE_APROBACION', 'PREPARANDO'):
            despacho = Despacho.objects.create(
                pedido=self.pedido, estado=estado_despacho,
            )
            self._cerrar(self.supervisor)
            self._refrescar()
            self.assertEqual(self.pedido.estado, 'PARCIAL',
                             f'despacho {estado_despacho} debería bloquear')
            despacho.delete()

    def test_despacho_finalizado_no_bloquea(self):
        from .models import Despacho
        for estado_despacho in ('RECIBIDO', 'PARCIAL', 'ANULADO'):
            Despacho.objects.create(pedido=self.pedido, estado=estado_despacho)
        self._cerrar(self.supervisor)
        self._refrescar()
        self.assertEqual(self.pedido.estado, 'CERRADO')
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CerrarPedidoVistaTest --settings=Programarprecios.test_settings`
Expected: los tests que cierran fallan con 404 (la URL `/cerrar/` no existe); los negativos pueden pasar de rebote — lo importante es que `test_supervisor_cierra_pedido_parcial` FALLA.

- [ ] **Step 3: Implementar helpers, vista y URL**

En `PedidosAlmacen/views.py`, justo después de la definición de `is_pedidos_supervisor` (~línea 91) agregar:

```python
def is_pedidos_supervisor_o_almacen(user):
    """Puede cerrar pedidos: Supervisor, Almacén o superuser."""
    return is_pedidos_supervisor(user) or is_pedidos_almacen(user)
```

Justo antes de la definición de `anular_pedido` (~línea 400) agregar:

```python
def _puede_cerrar_pedido(pedido: Pedido) -> bool:
    """True si el pedido es elegible para cierre (no chequea permisos).

    Elegible: estado PARCIAL y sin despachos aún no finalizados.
    """
    if pedido.estado != 'PARCIAL':
        return False
    return not pedido.despachos.filter(
        estado__in=('ENVIADO', 'PENDIENTE_APROBACION', 'PREPARANDO')
    ).exists()
```

Después de la función `anular_pedido` (tras su `return redirect(...)` final, ~línea 427) agregar:

```python
@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor_o_almacen, login_url='dashboard')
def cerrar_pedido(request, pk):
    """Cierra un pedido PARCIAL cuyos back orders no se van a completar.

    Deja cantidad_back_order = 0 en los items pendientes (PARCIAL/BACK_ORDER),
    los marca CERRADO y registra auditoría en el pedido.
    """
    if request.method != 'POST':
        return redirect('pedidos-detalle', pk=pk)
    motivo = request.POST.get('motivo', '').strip()
    if not motivo:
        messages.error(request, 'Debes indicar un motivo para cerrar el pedido')
        return redirect('pedidos-detalle', pk=pk)
    with transaction.atomic():
        pedido = get_object_or_404(
            Pedido.objects.select_for_update(), numero_pedido=pk,
        )
        if not _puede_cerrar_pedido(pedido):
            messages.error(
                request,
                'Este pedido no se puede cerrar: debe estar en estado Parcial '
                'y no tener despachos pendientes',
            )
            return redirect('pedidos-detalle', pk=pk)
        pedido.items.filter(estado__in=('PARCIAL', 'BACK_ORDER')).update(
            cantidad_back_order=0, estado='CERRADO',
        )
        pedido.estado = 'CERRADO'
        pedido.cerrado_por = request.user
        pedido.fecha_cierre = timezone.now()
        pedido.motivo_cierre = motivo
        pedido.save()
    logger.info(
        'Pedido #%s cerrado por %s. Motivo: %s',
        pedido.numero_pedido, request.user.username, motivo,
    )
    messages.success(request, f'Pedido #{pedido.numero_pedido} cerrado')
    return redirect('pedidos-detalle', pk=pk)
```

En `PedidosAlmacen/urls.py`, tras la línea de `pedidos-anular`, agregar:

```python
    path('pedidos/<int:pk>/cerrar/', views.cerrar_pedido, name='pedidos-cerrar'),
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CerrarPedidoVistaTest --settings=Programarprecios.test_settings`
Expected: PASS (ok, 10 tests).

- [ ] **Step 5: Correr la suite completa de la app**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen --settings=Programarprecios.test_settings`
Expected: PASS sin regresiones.

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/urls.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): vista cerrar_pedido para pedidos parciales sin despachos pendientes"
```

---

### Task 3: UI en el detalle del pedido (botón, modal, badge y bloque de auditoría)

**Files:**
- Modify: `PedidosAlmacen/views.py` (contexto de `detalle_pedido`, ~línea 383)
- Modify: `templates/pedidos-detalle.html` (header de acciones ~línea 74, bloque de alertas ~línea 98, badges de item ~línea 237, modales al final ~línea 507)
- Test: `PedidosAlmacen/tests.py` (nueva clase al final)

**Interfaces:**
- Consumes: `_puede_cerrar_pedido(pedido)` e `is_pedidos_supervisor_o_almacen(user)` de Task 2; URL name `pedidos-cerrar`; campos `cerrado_por`/`fecha_cierre`/`motivo_cierre` de Task 1; variables de contexto existentes del detalle (`es_supervisor`, `es_despachador`).
- Produces: flag de contexto `puede_cerrar` en `detalle_pedido`; elementos de template `#modalCerrarPedido`, badge de item `Cerrado`, alerta de auditoría de cierre.

- [ ] **Step 1: Escribir los tests que fallan**

Al final de `PedidosAlmacen/tests.py` agregar:

```python
class CerrarPedidoUITest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from users.models import User
        from .models import Pedido, PedidoItem

        g_sup, _ = Group.objects.get_or_create(name='Pedidos Supervisor')
        g_tnd, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.supervisor = User.objects.create_user(username='sup_ui_c', password='x')
        self.supervisor.groups.add(g_sup)
        self.tienda = User.objects.create_user(username='tnd_ui_c', password='x')
        self.tienda.groups.add(g_tnd)

        self.pedido = Pedido.objects.create(solicitante=self.tienda, estado='PARCIAL')
        PedidoItem.objects.create(
            pedido=self.pedido, codigo='A1', descripcion='Prod A',
            cantidad_solicitada=10, cantidad_despachada=6,
            cantidad_back_order=4, estado='PARCIAL',
        )

    def _detalle(self, user):
        self.client.force_login(user)
        return self.client.get(f'/pedidos/{self.pedido.numero_pedido}/')

    def test_supervisor_ve_boton_cerrar_en_pedido_elegible(self):
        resp = self._detalle(self.supervisor)
        self.assertContains(resp, 'modalCerrarPedido')
        self.assertContains(resp, f'/pedidos/{self.pedido.numero_pedido}/cerrar/')

    def test_tienda_no_ve_boton_cerrar(self):
        resp = self._detalle(self.tienda)
        self.assertNotContains(resp, 'modalCerrarPedido')

    def test_pedido_no_elegible_no_muestra_boton(self):
        from .models import Despacho
        Despacho.objects.create(pedido=self.pedido, estado='ENVIADO')
        resp = self._detalle(self.supervisor)
        self.assertNotContains(resp, 'modalCerrarPedido')

    def test_pedido_cerrado_muestra_auditoria_y_badge_item(self):
        from django.utils import timezone
        self.pedido.estado = 'CERRADO'
        self.pedido.cerrado_por = self.supervisor
        self.pedido.fecha_cierre = timezone.now()
        self.pedido.motivo_cierre = 'proveedor descontinuó el producto'
        self.pedido.save()
        self.pedido.items.update(estado='CERRADO', cantidad_back_order=0)

        resp = self._detalle(self.supervisor)
        self.assertContains(resp, 'Pedido cerrado')
        self.assertContains(resp, 'proveedor descontinuó el producto')
        self.assertContains(resp, self.supervisor.username)
        self.assertNotContains(resp, 'modalCerrarPedido')
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CerrarPedidoUITest --settings=Programarprecios.test_settings`
Expected: FAIL en `test_supervisor_ve_boton_cerrar_en_pedido_elegible` y `test_pedido_cerrado_muestra_auditoria_y_badge_item` (el template aún no tiene esos elementos).

- [ ] **Step 3: Agregar el flag `puede_cerrar` al contexto del detalle**

En `PedidosAlmacen/views.py`, dentro de `detalle_pedido`, en el diccionario del `render` (~línea 383), después de la línea `'es_despachador': es_despachador,` agregar:

```python
        'puede_cerrar': (es_supervisor or es_despachador) and _puede_cerrar_pedido(pedido),
```

- [ ] **Step 4: Agregar botón, modal, badge y bloque de auditoría al template**

En `templates/pedidos-detalle.html`:

(a) En el header de acciones, después del bloque `{% endif %}` del botón Anular (~línea 78), agregar:

```html
        {% if puede_cerrar %}
        <button type="button" class="btn btn-sm btn-dark" data-bs-toggle="modal" data-bs-target="#modalCerrarPedido" title="Cerrar pedido">
            <i class="fas fa-lock"></i> <span class="d-none d-sm-inline">Cerrar</span>
        </button>
        {% endif %}
```

(b) Después del bloque `{% if pedido.estado == 'ANULADO' %}...{% endif %}` (~línea 98), agregar:

```html
{% if pedido.estado == 'CERRADO' and pedido.fecha_cierre %}
<div class="alert alert-secondary mb-3">
    <strong><i class="fas fa-lock"></i> Pedido cerrado</strong> — los back orders pendientes quedaron en 0<br>
    <strong>Motivo:</strong> {{ pedido.motivo_cierre }}<br>
    <small>Por {{ pedido.cerrado_por.username|default:"-" }} el {{ pedido.fecha_cierre|date:"d/m/Y H:i" }}</small>
</div>
{% endif %}
```

(c) En los badges de estado de item, después de la línea de `INCIDENCIA_RESUELTA` (~línea 237), agregar:

```html
                        {% elif item.estado == 'CERRADO' %}<span class="badge bg-secondary">Cerrado</span>
```

(d) Al final, después del bloque del `modalAnularPedido` (`{% endif %}` ~línea 507), agregar:

```html
{% if puede_cerrar %}
<div class="modal fade" id="modalCerrarPedido" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog">
    <form method="post" action="{% url 'pedidos-cerrar' pedido.numero_pedido %}">
      {% csrf_token %}
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title">Cerrar pedido #{{ pedido.numero_pedido }}</h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>
        </div>
        <div class="modal-body">
          <p class="text-secondary"><i class="fas fa-exclamation-triangle"></i> Los back orders pendientes quedarán en 0, los items incompletos pasarán a Cerrado y el pedido saldrá de las listas activas. Esta acción no se puede deshacer.</p>
          <label class="form-label fw-bold">Motivo del cierre <span class="text-danger">*</span></label>
          <textarea name="motivo" class="form-control" rows="3" required></textarea>
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancelar</button>
          <button type="submit" class="btn btn-dark">Cerrar pedido</button>
        </div>
      </div>
    </form>
  </div>
</div>
{% endif %}
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CerrarPedidoUITest --settings=Programarprecios.test_settings`
Expected: PASS (ok, 4 tests).

- [ ] **Step 6: Correr la suite completa de la app**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen --settings=Programarprecios.test_settings`
Expected: PASS sin regresiones.

- [ ] **Step 7: Commit**

```bash
git add PedidosAlmacen/views.py templates/pedidos-detalle.html PedidosAlmacen/tests.py
git commit -m "feat(pedidos): boton y modal de cierre de pedidos parciales en el detalle"
```
