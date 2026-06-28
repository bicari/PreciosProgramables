# Reasignar/Liberar Picker en Pedidos PARCIAL — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que un supervisor reasigne (mismo u otro picker) o libere el picker de un pedido PARCIAL con back orders, para continuar la recolección de los ítems pendientes.

**Architecture:** El backend `asignar_picker` ya admite PARCIAL+back orders y sirve para reasignar; se amplía `desasignar_picker` para aceptar también `PARCIAL`. En la lista de pedidos se añaden, para PARCIAL con picker, un botón **reasignar** (reutiliza el modal `#modalAsignarPicker` existente) y un botón **liberar** (POST a `desasignar_picker`).

**Tech Stack:** Django 4.x, PostgreSQL (prod) / SQLite (tests), plantillas Django + Bootstrap 5.

## Global Constraints

- **Permiso único:** Solo `is_pedidos_supervisor(user)` (que ya incluye `is_superuser`) puede reasignar/liberar.
- **Reactivación vía supervisor:** Reasignar mueve el pedido de `PARCIAL` a `ASIGNADO` (lo hace `asignar_picker`, sin cambios). NO se modifica el filtro de la cola del picker.
- **Liberar mantiene PARCIAL:** Liberar un PARCIAL con back orders deja `picker=None` y estado `PARCIAL`.
- **Sin tocar a2 ni el flujo de despacho/recepción.**
- **Estilo:** PEP 8, seguir patrones existentes en `views.py` y en `pedidos-lista.html`.
- **Comando de tests:** `python manage.py test PedidosAlmacen --settings=Programarprecios.test_settings -v 2`

---

### Task 1: Backend — desasignar_picker acepta PARCIAL (+ regresión de reasignación)

**Files:**
- Modify: `PedidosAlmacen/views.py` (`desasignar_picker`, ~línea 495-509)
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: vistas existentes `asignar_picker` (URL name `pedidos-asignar-picker`) y `desasignar_picker` (URL name `pedidos-desasignar-picker`); grupos `Pedidos Picker` / `Pedidos Supervisor`.
- Produces: `desasignar_picker` permite liberar un pedido en estado `PARCIAL` (además de `ASIGNADO`/`PICKING`).

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `PedidosAlmacen/tests.py`:

```python
class ReasignarPickerParcialTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido, PedidoItem
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_rp', password='x')
        g_picker, _ = Group.objects.get_or_create(name='Pedidos Picker')
        self.p1 = User.objects.create_user(username='picker1', password='x')
        self.p2 = User.objects.create_user(username='picker2', password='x')
        self.p1.groups.add(g_picker)
        self.p2.groups.add(g_picker)
        # Pedido PARCIAL con picker p1 y un item en BACK_ORDER
        self.pedido = Pedido.objects.create(solicitante=self.sup, estado='PARCIAL', picker=self.p1)
        PedidoItem.objects.create(
            pedido=self.pedido, codigo='A', descripcion='a',
            cantidad_solicitada=10, cantidad_despachada=4,
            cantidad_back_order=6, estado='BACK_ORDER',
        )

    def test_reasignar_parcial_mueve_a_asignado(self):
        self.client.force_login(self.sup)
        url = self.reverse('pedidos-asignar-picker', args=[self.pedido.numero_pedido])
        resp = self.client.post(url, {'picker_id': self.p2.pk})
        self.assertEqual(resp.status_code, 302)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'ASIGNADO')
        self.assertEqual(self.pedido.picker, self.p2)
        self.assertIsNotNone(self.pedido.fecha_asignacion)

    def test_liberar_parcial_deja_parcial_sin_picker(self):
        self.client.force_login(self.sup)
        url = self.reverse('pedidos-desasignar-picker', args=[self.pedido.numero_pedido])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.pedido.refresh_from_db()
        self.assertIsNone(self.pedido.picker)
        self.assertEqual(self.pedido.estado, 'PARCIAL')

    def test_liberar_parcial_sin_backorder_pasa_a_pendiente(self):
        # Caso borde: PARCIAL sin items en BACK_ORDER → vuelve a PENDIENTE
        self.pedido.items.update(estado='PARCIAL')
        self.client.force_login(self.sup)
        url = self.reverse('pedidos-desasignar-picker', args=[self.pedido.numero_pedido])
        self.client.post(url)
        self.pedido.refresh_from_db()
        self.assertIsNone(self.pedido.picker)
        self.assertEqual(self.pedido.estado, 'PENDIENTE')
```

- [ ] **Step 2: Ejecutar los tests para verificar que fallan**

Run: `python manage.py test PedidosAlmacen.tests.ReasignarPickerParcialTest --settings=Programarprecios.test_settings -v 2`
Expected: `test_reasignar_parcial_mueve_a_asignado` PASA (asignar_picker ya soporta PARCIAL), pero `test_liberar_parcial_deja_parcial_sin_picker` y `test_liberar_parcial_sin_backorder_pasa_a_pendiente` FALLAN (desasignar rechaza PARCIAL: el pedido conserva picker y estado PARCIAL → asserts de picker None fallan).

- [ ] **Step 3: Ampliar el guard de `desasignar_picker`**

En `PedidosAlmacen/views.py`, dentro de `desasignar_picker`, reemplazar el guard de estado:

```python
    if pedido.estado not in ('ASIGNADO', 'PICKING'):
        messages.warning(request, f'El pedido #{pk} no está en estado Asignado o Picking y no puede liberarse')
        return redirect('pedidos-lista')
```

por:

```python
    if pedido.estado not in ('ASIGNADO', 'PICKING', 'PARCIAL'):
        messages.warning(request, f'El pedido #{pk} no está en estado Asignado, Picking o Parcial y no puede liberarse')
        return redirect('pedidos-lista')
```

(El resto de la función no cambia: ya hace `picker=None`, `fecha_asignacion=None` y recalcula `pedido.estado = 'PARCIAL' if tiene_bo else 'PENDIENTE'`.)

- [ ] **Step 4: Ejecutar los tests para verificar que pasan**

Run: `python manage.py test PedidosAlmacen.tests.ReasignarPickerParcialTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): permitir liberar picker en pedidos PARCIAL"
```

---

### Task 2: UI — botones reasignar y liberar en la lista para PARCIAL con picker

**Files:**
- Modify: `templates/pedidos-lista.html` (bloque de la celda del picker, ~línea 100-122)
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `desasignar_picker` ampliado (Task 1); modal `#modalAsignarPicker` y su handler JS `show.bs.modal` (ya existentes en `pedidos-lista.html`, líneas 172-212), que arma la acción del form con `data-pedido-id`.
- Produces: en la lista, para un pedido `PARCIAL` con `picker` y `items_back_order > 0`, el supervisor ve un botón **reasignar** (target `#modalAsignarPicker`, `title="Reasignar picker"`) y un botón **liberar** (form POST a `pedidos-desasignar-picker`).

- [ ] **Step 1: Escribir el test que falla**

Añadir a `PedidosAlmacen/tests.py`:

```python
class ReasignarPickerParcialTemplateTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido, PedidoItem
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_tpl', password='x')
        g_picker, _ = Group.objects.get_or_create(name='Pedidos Picker')
        self.p1 = User.objects.create_user(username='pk1', password='x')
        self.p1.groups.add(g_picker)
        self.tienda = User.objects.create_user(username='tnd_tpl', password='x')
        g_tienda, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda.groups.add(g_tienda)
        self.pedido = Pedido.objects.create(solicitante=self.tienda, estado='PARCIAL', picker=self.p1)
        PedidoItem.objects.create(
            pedido=self.pedido, codigo='A', descripcion='a',
            cantidad_solicitada=10, cantidad_despachada=4,
            cantidad_back_order=6, estado='BACK_ORDER',
        )

    def test_supervisor_ve_reasignar_y_liberar_en_parcial(self):
        self.client.force_login(self.sup)
        resp = self.client.get(self.reverse('pedidos-lista'))
        self.assertContains(resp, 'Reasignar picker')
        self.assertContains(resp, self.reverse('pedidos-desasignar-picker', args=[self.pedido.numero_pedido]))

    def test_no_supervisor_no_ve_controles(self):
        self.client.force_login(self.tienda)
        resp = self.client.get(self.reverse('pedidos-lista'))
        self.assertNotContains(resp, 'Reasignar picker')
```

- [ ] **Step 2: Ejecutar el test para verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.ReasignarPickerParcialTemplateTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL en `test_supervisor_ve_reasignar_y_liberar_en_parcial` (no existe el texto `Reasignar picker` en la plantilla).

- [ ] **Step 3: Añadir los botones en la plantilla**

En `templates/pedidos-lista.html`, reemplazar el bloque actual de la celda del picker (cuando hay picker asignado):

```django
                    {% if pedido.picker %}
                        <span class="badge bg-info text-dark">{{ pedido.picker.username|capfirst }}</span>
                        {% if es_supervisor %}{% if pedido.estado == 'ASIGNADO' or pedido.estado == 'PICKING' %}
                        <form method="post" action="{% url 'pedidos-desasignar-picker' pedido.numero_pedido %}" class="d-inline ms-1">
                            {% csrf_token %}
                            <button type="submit" class="btn btn-sm btn-outline-secondary p-0 px-1" title="Liberar picker" onclick="return confirm('¿Liberar al picker de este pedido?')">
                                <i class="fas fa-times"></i>
                            </button>
                        </form>
                        {% endif %}{% endif %}
```

por:

```django
                    {% if pedido.picker %}
                        <span class="badge bg-info text-dark">{{ pedido.picker.username|capfirst }}</span>
                        {% if es_supervisor %}
                            {% if pedido.estado == 'ASIGNADO' or pedido.estado == 'PICKING' %}
                            <form method="post" action="{% url 'pedidos-desasignar-picker' pedido.numero_pedido %}" class="d-inline ms-1">
                                {% csrf_token %}
                                <button type="submit" class="btn btn-sm btn-outline-secondary p-0 px-1" title="Liberar picker" onclick="return confirm('¿Liberar al picker de este pedido?')">
                                    <i class="fas fa-times"></i>
                                </button>
                            </form>
                            {% elif pedido.estado == 'PARCIAL' and pedido.items_back_order > 0 %}
                                {% if pickers_disponibles %}
                                <button type="button" class="btn btn-sm btn-outline-info ms-1" title="Reasignar picker"
                                    data-bs-toggle="modal" data-bs-target="#modalAsignarPicker"
                                    data-pedido-id="{{ pedido.numero_pedido }}"
                                    data-pedido-num="{{ pedido.numero_pedido }}">
                                    <i class="fas fa-user-pen"></i>
                                </button>
                                {% endif %}
                                <form method="post" action="{% url 'pedidos-desasignar-picker' pedido.numero_pedido %}" class="d-inline ms-1">
                                    {% csrf_token %}
                                    <button type="submit" class="btn btn-sm btn-outline-secondary p-0 px-1" title="Liberar picker" onclick="return confirm('¿Liberar al picker de este pedido?')">
                                        <i class="fas fa-times"></i>
                                    </button>
                                </form>
                            {% endif %}
                        {% endif %}
```

(El bloque `{% else %}` con el botón de **asignar** para PARCIAL sin picker no se toca.)

- [ ] **Step 4: Ejecutar el test para verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.ReasignarPickerParcialTemplateTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Ejecutar toda la suite de la app**

Run: `python manage.py test PedidosAlmacen --settings=Programarprecios.test_settings -v 1`
Expected: PASS (toda la suite, sin regresiones).

- [ ] **Step 6: Commit**

```bash
git add templates/pedidos-lista.html PedidosAlmacen/tests.py
git commit -m "feat(pedidos): botones reasignar y liberar picker en lista para PARCIAL"
```

---

## Notas de verificación final

Tras completar ambas tareas:
- `python manage.py test PedidosAlmacen --settings=Programarprecios.test_settings` en verde.
- Verificación manual sugerida: como supervisor, sobre un pedido PARCIAL con back orders y picker asignado, usar **reasignar** (debe quedar en ASIGNADO y aparecer en la cola del picker elegido) y **liberar** (debe quedar PARCIAL sin picker, mostrando luego el botón de asignar).
