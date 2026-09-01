# Condición "Insumos" y pedidos mixtos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar la condición `INSUMOS` a los pedidos de almacén y permitir "pedidos mixtos" que combinen productos de más de una categoría en un mismo pedido.

**Architecture:** Cambio mínimo sobre el modelo `Pedido`/`PedidoItem` existente (`PedidosAlmacen/models.py`): un choice nuevo en `CONDICION_CHOICES`, un flag `es_mixto` en `Pedido`, y `categoria`/`categoria_nombre` movidos también a nivel de línea (`PedidoItem`) para que los pedidos mixtos conserven trazabilidad exacta por producto. La UI de creación (`templates/pedidos-crear.html`) gana un checkbox que libera el selector de categoría entre ítems; los reportes pasan a agregar "por categoría" desde `PedidoItem` en vez de `Pedido`.

**Tech Stack:** Django 5.2, PostgreSQL (prod) / SQLite (`Programarprecios.test_settings`, tests), htmx, JS vanilla.

## Global Constraints

- Los tests se corren con: `venv\Scripts\python.exe manage.py test PedidosAlmacen --settings=Programarprecios.test_settings` (SQLite en memoria; el usuario Postgres del proyecto no tiene permiso CREATEDB).
- Seguir PEP 8, type hints y docstrings Google en funciones públicas nuevas, por convención del proyecto (`CLAUDE.md`).
- `condicion` sigue bloqueándose tras el primer ítem en todos los casos; solo `categoria` se libera en modo mixto.
- No modificar `serializers.py` ni la API REST: fuera del alcance de este spec.

---

### Task 1: Condición "Insumos" en el modelo

**Files:**
- Modify: `PedidosAlmacen/models.py:18-22`
- Create: `PedidosAlmacen/migrations/0029_add_condicion_insumos.py`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Produces: `Pedido.CONDICION_CHOICES` incluye `('INSUMOS', 'Insumos')`, consumido por Task 2 (labels/badges) y por la vista `crear_pedido` (sin cambios, ya lee choices dinámicamente).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `PedidosAlmacen/tests.py`:

```python
class CondicionInsumosTest(TestCase):
    """INSUMOS es una condición válida y queda sujeta al límite normal de
    Picking (igual que SURTIDO), a diferencia de URGENTE/CLIENTE_RETIRA."""

    def setUp(self):
        from django.utils import timezone
        from users.models import User
        self.timezone = timezone
        self.sup = User.objects.create_superuser(username='sup_insumos', password='x')
        self.picker = User.objects.create_user(username='picker_insumos', password='x')

    def _crear_pedido(self, condicion, estado='ASIGNADO'):
        from .models import Pedido, PedidoItem
        pedido = Pedido.objects.create(
            solicitante=self.sup, estado=estado, condicion=condicion,
            picker=self.picker, fecha_asignacion=self.timezone.now(),
        )
        PedidoItem.objects.create(
            pedido=pedido, codigo='SKU1', descripcion='P1',
            cantidad_solicitada=5, estado='PENDIENTE',
        )
        return pedido

    def test_condicion_insumos_es_valida(self):
        pedido = self._crear_pedido('INSUMOS')
        pedido.full_clean()
        self.assertEqual(pedido.condicion, 'INSUMOS')

    def test_insumos_no_exime_del_limite_de_picking(self):
        from rest_framework.test import APIClient
        self._crear_pedido('SURTIDO', estado='PICKING')
        pedido_insumos = self._crear_pedido('INSUMOS', estado='ASIGNADO')

        api = APIClient()
        api.force_authenticate(user=self.sup)
        resp = api.post(
            f'/api/pedidos/{pedido_insumos.numero_pedido}/preparar/',
            data={'accion': 'iniciar'}, format='json',
        )
        self.assertEqual(resp.status_code, 409)
        pedido_insumos.refresh_from_db()
        self.assertEqual(pedido_insumos.estado, 'ASIGNADO')

    def test_urgente_si_exime_del_limite_de_picking(self):
        from rest_framework.test import APIClient
        self._crear_pedido('SURTIDO', estado='PICKING')
        pedido_urgente = self._crear_pedido('URGENTE', estado='ASIGNADO')

        api = APIClient()
        api.force_authenticate(user=self.sup)
        resp = api.post(
            f'/api/pedidos/{pedido_urgente.numero_pedido}/preparar/',
            data={'accion': 'iniciar'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        pedido_urgente.refresh_from_db()
        self.assertEqual(pedido_urgente.estado, 'PICKING')
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CondicionInsumosTest --settings=Programarprecios.test_settings -v 2`
Expected: `test_condicion_insumos_es_valida` FAIL con `ValidationError` (INSUMOS no está en choices); los otros dos deberían PASAR ya (el límite de Picking ya existe para valores no exentos), pero correrlos confirma que no se rompe nada al agregar el choice.

- [ ] **Step 3: Agregar el choice al modelo**

En `PedidosAlmacen/models.py:18-22`, reemplazar:

```python
    CONDICION_CHOICES = [
        ('URGENTE', 'Urgente'),
        ('SURTIDO', 'Surtido'),
        ('CLIENTE_RETIRA', 'Cliente Retira'),
    ]
```

por:

```python
    CONDICION_CHOICES = [
        ('URGENTE', 'Urgente'),
        ('SURTIDO', 'Surtido'),
        ('CLIENTE_RETIRA', 'Cliente Retira'),
        ('INSUMOS', 'Insumos'),
    ]
```

- [ ] **Step 4: Generar la migración**

Run: `venv\Scripts\python.exe manage.py makemigrations PedidosAlmacen --name add_condicion_insumos --settings=Programarprecios.test_settings`

Verificar que el archivo generado (`PedidosAlmacen/migrations/0029_add_condicion_insumos.py`) sea equivalente a:

```python
import PedidosAlmacen.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('PedidosAlmacen', '0028_add_recibido_sin_despachar'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pedido',
            name='condicion',
            field=models.CharField(blank=True, choices=[('URGENTE', 'Urgente'), ('SURTIDO', 'Surtido'), ('CLIENTE_RETIRA', 'Cliente Retira'), ('INSUMOS', 'Insumos')], default='', max_length=20),
        ),
    ]
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CondicionInsumosTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/models.py PedidosAlmacen/migrations/0029_add_condicion_insumos.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): agrega condición INSUMOS"
```

---

### Task 2: Label PDF y badges de "Insumos"

**Files:**
- Modify: `PedidosAlmacen/pdf.py:26-30`
- Modify: `templates/pedidos-lista.html:94-102`
- Modify: `templates/pedidos-detalle.html:141-149`
- Modify: `templates/pedidos-reporte.html:137-146, 224-230`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `Pedido.CONDICION_CHOICES` con `INSUMOS` (Task 1).

- [ ] **Step 1: Escribir los tests que fallan**

```python
class BadgeInsumosTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_badge_insumos', password='x')
        self.pedido = Pedido.objects.create(
            solicitante=self.sup, estado='PENDIENTE', condicion='INSUMOS',
        )
        self.client.force_login(self.sup)

    def test_lista_muestra_badge_insumos(self):
        resp = self.client.get(self.reverse('pedidos-lista'))
        self.assertContains(resp, 'Insumos')

    def test_detalle_muestra_badge_insumos(self):
        resp = self.client.get(self.reverse('pedidos-detalle', args=[self.pedido.numero_pedido]))
        self.assertContains(resp, 'Insumos')
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.BadgeInsumosTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL (ambos pedidos caen en la rama `else`/`—`, no contienen el texto "Insumos")

- [ ] **Step 3: Agregar el label en el PDF**

En `PedidosAlmacen/pdf.py:26-30`, reemplazar:

```python
_LABEL_CONDICION = {
    "URGENTE": "Urgente",
    "SURTIDO": "Surtido",
    "CLIENTE_RETIRA": "Cliente Retira",
}
```

por:

```python
_LABEL_CONDICION = {
    "URGENTE": "Urgente",
    "SURTIDO": "Surtido",
    "CLIENTE_RETIRA": "Cliente Retira",
    "INSUMOS": "Insumos",
}
```

- [ ] **Step 4: Badge en `pedidos-lista.html`**

En `templates/pedidos-lista.html:94-102`, reemplazar:

```html
                <td>
                    {% if pedido.condicion == 'URGENTE' %}
                        <span class="badge bg-danger"><i class="fas fa-bolt me-1"></i>Urgente</span>
                    {% elif pedido.condicion == 'SURTIDO' %}
                        <span class="badge bg-success">Surtido</span>
                    {% elif pedido.condicion == 'CLIENTE_RETIRA' %}
                        <span class="badge bg-info text-dark">Cliente Retira</span>
                    {% else %}
                        <span class="text-muted">—</span>
                    {% endif %}
                </td>
```

por:

```html
                <td>
                    {% if pedido.condicion == 'URGENTE' %}
                        <span class="badge bg-danger"><i class="fas fa-bolt me-1"></i>Urgente</span>
                    {% elif pedido.condicion == 'SURTIDO' %}
                        <span class="badge bg-success">Surtido</span>
                    {% elif pedido.condicion == 'CLIENTE_RETIRA' %}
                        <span class="badge bg-info text-dark">Cliente Retira</span>
                    {% elif pedido.condicion == 'INSUMOS' %}
                        <span class="badge bg-secondary">Insumos</span>
                    {% else %}
                        <span class="text-muted">—</span>
                    {% endif %}
                </td>
```

- [ ] **Step 5: Badge en `pedidos-detalle.html`**

En `templates/pedidos-detalle.html:141-149`, reemplazar:

```html
            <div class="pd-meta-row">
                <dt class="pd-meta-label">Condición</dt>
                <dd class="pd-meta-value">
                    {% if pedido.condicion == 'URGENTE' %}<span class="badge bg-danger">Urgente</span>
                    {% elif pedido.condicion == 'SURTIDO' %}<span class="badge bg-success">Surtido</span>
                    {% elif pedido.condicion == 'CLIENTE_RETIRA' %}<span class="badge bg-info">Cliente Retira</span>
                    {% else %}-{% endif %}
                </dd>
            </div>
```

por:

```html
            <div class="pd-meta-row">
                <dt class="pd-meta-label">Condición</dt>
                <dd class="pd-meta-value">
                    {% if pedido.condicion == 'URGENTE' %}<span class="badge bg-danger">Urgente</span>
                    {% elif pedido.condicion == 'SURTIDO' %}<span class="badge bg-success">Surtido</span>
                    {% elif pedido.condicion == 'CLIENTE_RETIRA' %}<span class="badge bg-info">Cliente Retira</span>
                    {% elif pedido.condicion == 'INSUMOS' %}<span class="badge bg-secondary">Insumos</span>
                    {% else %}-{% endif %}
                </dd>
            </div>
```

- [ ] **Step 6: Ramas en `pedidos-reporte.html`**

En `templates/pedidos-reporte.html:137-146`, reemplazar:

```html
            {% if condicion_top %}
                {% if condicion_top.condicion == 'URGENTE' %}
                    <div class="pr-metric-value text-danger">Urgente</div>
                {% elif condicion_top.condicion == 'SURTIDO' %}
                    <div class="pr-metric-value text-success">Surtido</div>
                {% elif condicion_top.condicion == 'CLIENTE_RETIRA' %}
                    <div class="pr-metric-value text-info">Cliente Retira</div>
                {% else %}
                    <div class="pr-metric-value">{{ condicion_top.condicion }}</div>
                {% endif %}
```

por:

```html
            {% if condicion_top %}
                {% if condicion_top.condicion == 'URGENTE' %}
                    <div class="pr-metric-value text-danger">Urgente</div>
                {% elif condicion_top.condicion == 'SURTIDO' %}
                    <div class="pr-metric-value text-success">Surtido</div>
                {% elif condicion_top.condicion == 'CLIENTE_RETIRA' %}
                    <div class="pr-metric-value text-info">Cliente Retira</div>
                {% elif condicion_top.condicion == 'INSUMOS' %}
                    <div class="pr-metric-value">Insumos</div>
                {% else %}
                    <div class="pr-metric-value">{{ condicion_top.condicion }}</div>
                {% endif %}
```

Y en `templates/pedidos-reporte.html:224-230`, reemplazar:

```html
                            {% if item.condicion == 'URGENTE' %}<span class="badge bg-danger">Urgente</span>
                            {% elif item.condicion == 'SURTIDO' %}<span class="badge bg-success">Surtido</span>
                            {% elif item.condicion == 'CLIENTE_RETIRA' %}<span class="badge bg-info text-dark">Cliente Retira</span>
                            {% else %}<span class="badge bg-secondary">{{ item.condicion|default:"—" }}</span>{% endif %}
```

por:

```html
                            {% if item.condicion == 'URGENTE' %}<span class="badge bg-danger">Urgente</span>
                            {% elif item.condicion == 'SURTIDO' %}<span class="badge bg-success">Surtido</span>
                            {% elif item.condicion == 'CLIENTE_RETIRA' %}<span class="badge bg-info text-dark">Cliente Retira</span>
                            {% elif item.condicion == 'INSUMOS' %}<span class="badge bg-secondary">Insumos</span>
                            {% else %}<span class="badge bg-secondary">{{ item.condicion|default:"—" }}</span>{% endif %}
```

- [ ] **Step 7: Correr los tests y verificar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.BadgeInsumosTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (2 tests)

- [ ] **Step 8: Commit**

```bash
git add PedidosAlmacen/pdf.py templates/pedidos-lista.html templates/pedidos-detalle.html templates/pedidos-reporte.html PedidosAlmacen/tests.py
git commit -m "feat(pedidos): badges y label PDF para condición Insumos"
```

---

### Task 3: Modelo de pedidos mixtos (`es_mixto` + categoría por ítem)

**Files:**
- Modify: `PedidosAlmacen/models.py:23-95` (`Pedido`, `PedidoItem`)
- Create: `PedidosAlmacen/migrations/0030_pedido_es_mixto_pedidoitem_categoria.py`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Produces: `Pedido.es_mixto` (bool, default `False`); `PedidoItem.categoria` / `PedidoItem.categoria_nombre` (str, default `''`). Consumidos por Task 4 (vista `crear_pedido`), Task 6 (badges) y Task 7 (reportes).

- [ ] **Step 1: Escribir el test que falla**

```python
class PedidoMixtoModeloTest(TestCase):
    """Los campos nuevos existen y tienen los defaults esperados."""

    def test_es_mixto_default_false(self):
        from users.models import User
        from .models import Pedido
        sup = User.objects.create_superuser(username='sup_modelo_mixto', password='x')
        pedido = Pedido.objects.create(solicitante=sup, estado='PENDIENTE')
        self.assertFalse(pedido.es_mixto)

    def test_pedidoitem_categoria_default_vacio(self):
        from users.models import User
        from .models import Pedido, PedidoItem
        sup = User.objects.create_superuser(username='sup_modelo_mixto2', password='x')
        pedido = Pedido.objects.create(solicitante=sup, estado='PENDIENTE')
        item = PedidoItem.objects.create(
            pedido=pedido, codigo='SKU1', descripcion='P1', cantidad_solicitada=1,
        )
        self.assertEqual(item.categoria, '')
        self.assertEqual(item.categoria_nombre, '')
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.PedidoMixtoModeloTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL con `TypeError`/`AttributeError` (`es_mixto`/`categoria` no existen todavía en los modelos)

- [ ] **Step 3: Agregar los campos al modelo**

En `PedidosAlmacen/models.py`, agregar dentro de `class Pedido`, después de `motivo_cierre` (línea 63):

```python
    motivo_cierre = models.TextField(blank=True, default='')
    # Permite combinar productos de más de una categoría en el mismo pedido;
    # cada PedidoItem guarda su propia categoria/categoria_nombre.
    es_mixto = models.BooleanField(default=False)
```

Y dentro de `class PedidoItem`, después de `ref_proveedor` (línea 85):

```python
    ref_proveedor = models.CharField(max_length=100, blank=True, default='')
    categoria = models.CharField(max_length=70, blank=True, default='')
    categoria_nombre = models.CharField(max_length=150, blank=True, default='')
```

- [ ] **Step 4: Generar la migración**

Run: `venv\Scripts\python.exe manage.py makemigrations PedidosAlmacen --name pedido_es_mixto_pedidoitem_categoria --settings=Programarprecios.test_settings`

Editar el archivo generado (`PedidosAlmacen/migrations/0030_pedido_es_mixto_pedidoitem_categoria.py`) para agregar la migración de datos que rellena `categoria`/`categoria_nombre` en los `PedidoItem` ya existentes, copiándolos de su `Pedido` padre. El archivo final debe quedar equivalente a:

```python
from django.db import migrations, models


def backfill_categoria_items(apps, schema_editor):
    PedidoItem = apps.get_model('PedidosAlmacen', 'PedidoItem')
    for item in PedidoItem.objects.select_related('pedido').filter(categoria=''):
        pedido = item.pedido
        if pedido.categoria:
            item.categoria = pedido.categoria
            item.categoria_nombre = pedido.categoria_nombre
            item.save(update_fields=['categoria', 'categoria_nombre'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('PedidosAlmacen', '0029_add_condicion_insumos'),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='es_mixto',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='pedidoitem',
            name='categoria',
            field=models.CharField(blank=True, default='', max_length=70),
        ),
        migrations.AddField(
            model_name='pedidoitem',
            name='categoria_nombre',
            field=models.CharField(blank=True, default='', max_length=150),
        ),
        migrations.RunPython(backfill_categoria_items, noop_reverse),
    ]
```

Nota: esta migración de datos no tiene cobertura automatizada — no hay precedente en el proyecto para testear `RunPython` con `MigrationExecutor`, y el test DB se crea vacío (nada que backfillear). Verificar manualmente en un entorno con datos reales (staging o copia de producción) que, tras aplicar la migración, `PedidoItem.objects.exclude(categoria='').count()` coincide con el total de ítems cuyo `Pedido.categoria` no está vacío.

- [ ] **Step 5: Correr el test y verificar que pasa**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.PedidoMixtoModeloTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/models.py PedidosAlmacen/migrations/0030_pedido_es_mixto_pedidoitem_categoria.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): agrega es_mixto en Pedido y categoria por linea en PedidoItem"
```

---

### Task 4: Vista `crear_pedido` — persistir mixto y categoría por línea

**Files:**
- Modify: `PedidosAlmacen/views.py:245-372`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `Pedido.es_mixto`, `PedidoItem.categoria`/`categoria_nombre` (Task 3).
- Consumes (formato de request): cada dict de `items_data` (parseado de `items_json`) puede traer las claves opcionales `categoria`/`categoria_nombre`; si faltan, se usa la categoría de cabecera del POST como fallback. El POST puede traer `es_mixto` (`'on'` si el checkbox está marcado).
- Produces: `Pedido.categoria`/`categoria_nombre` de cabecera = categoría del primer ítem de `items_data` (no la del `<select>` al momento del submit).

- [ ] **Step 1: Escribir los tests que fallan**

```python
class CrearPedidoMixtoTest(TestCase):
    """crear_pedido persiste es_mixto y la categoría de cada PedidoItem según lo agregado."""

    def setUp(self):
        from users.models import User
        from django.urls import reverse
        self.reverse = reverse
        self.user = User.objects.create_superuser(username='mixto_u', password='x')
        self.client.force_login(self.user)
        self.url = self.reverse('pedidos-crear')

    def _post(self, items, es_mixto, mock_stock):
        form_data = {
            'categoria': items[0]['categoria'],
            'categoria_nombre': items[0]['categoria_nombre'],
            'condicion': 'URGENTE',
            'deposito': '2',
            'deposito_nombre': 'Tienda Norte',
            'items_json': json.dumps(items),
        }
        if es_mixto:
            form_data['es_mixto'] = 'on'
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.obtener_categorias.return_value = []
            mock_db.return_value.consultar_stock_multiple.return_value = mock_stock
            return self.client.post(self.url, form_data)

    def test_pedido_mixto_guarda_categoria_por_item(self):
        from .models import Pedido
        items = [
            {'codigo': 'SKU1', 'descripcion': 'Producto Uno', 'cantidad': '2',
             'referencia': '', 'puesto': '', 'ref_proveedor': '',
             'categoria': 'CAT1', 'categoria_nombre': 'Categoría 1'},
            {'codigo': 'SKU2', 'descripcion': 'Producto Dos', 'cantidad': '3',
             'referencia': '', 'puesto': '', 'ref_proveedor': '',
             'categoria': 'CAT2', 'categoria_nombre': 'Categoría 2'},
        ]
        resp = self._post(items, es_mixto=True, mock_stock={'SKU1': 10, 'SKU2': 10})
        self.assertEqual(resp.status_code, 302)
        pedido = Pedido.objects.get()
        self.assertTrue(pedido.es_mixto)
        self.assertEqual(pedido.categoria, 'CAT1')
        self.assertEqual(pedido.items.get(codigo='SKU1').categoria, 'CAT1')
        self.assertEqual(pedido.items.get(codigo='SKU2').categoria, 'CAT2')

    def test_pedido_no_mixto_no_marca_es_mixto(self):
        from .models import Pedido
        items = [
            {'codigo': 'SKU1', 'descripcion': 'Producto Uno', 'cantidad': '2',
             'referencia': '', 'puesto': '', 'ref_proveedor': '',
             'categoria': 'CAT1', 'categoria_nombre': 'Categoría 1'},
        ]
        resp = self._post(items, es_mixto=False, mock_stock={'SKU1': 10})
        self.assertEqual(resp.status_code, 302)
        pedido = Pedido.objects.get()
        self.assertFalse(pedido.es_mixto)
        self.assertEqual(pedido.items.get().categoria, 'CAT1')
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CrearPedidoMixtoTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL — `pedido.es_mixto` no existe como kwarg válido reconocido aún por la vista (el pedido se crea pero `es_mixto` queda en `False` siempre, y los items quedan con `categoria=''`).

- [ ] **Step 3: Leer `es_mixto` del POST**

En `PedidosAlmacen/views.py:264-268`, reemplazar:

```python
        items_json = request.POST.get('items_json', '[]')
        categoria_codigo = request.POST.get('categoria', '').strip()
        categoria_nombre = request.POST.get('categoria_nombre', '').strip()
        condicion = request.POST.get('condicion', '').strip()
```

por:

```python
        items_json = request.POST.get('items_json', '[]')
        categoria_codigo = request.POST.get('categoria', '').strip()
        categoria_nombre = request.POST.get('categoria_nombre', '').strip()
        condicion = request.POST.get('condicion', '').strip()
        es_mixto = request.POST.get('es_mixto') == 'on'
```

- [ ] **Step 4: Propagar `es_mixto` en la rehidratación de stock**

En `PedidosAlmacen/views.py:330-342`, dentro del bloque `ctx.update({...})` de rehidratación por conflicto de stock, agregar la clave `es_mixto_inicial`:

```python
                ctx.update({
                    'items_json_inicial': items_json,
                    'stock_info_json': json.dumps({
                        item['codigo']: disponibilidad.get(item['codigo'], {}).get(
                            'disponible', int(item['cantidad']))
                        for item in items_data
                    }),
                    'categoria_inicial': categoria_codigo,
                    'categoria_nombre_inicial': categoria_nombre,
                    'condicion_inicial': condicion,
                    'deposito_inicial': deposito_codigo,
                    'deposito_nombre_inicial': deposito_nombre or deposito_codigo,
                    'es_mixto_inicial': es_mixto,
                })
```

- [ ] **Step 5: Persistir categoría por ítem y de cabecera**

En `PedidosAlmacen/views.py:345-367`, reemplazar:

```python
        pedido = Pedido.objects.create(
            solicitante=request.user,
            observaciones=form.data.get('observaciones', ''),
            categoria=categoria_codigo,
            categoria_nombre=categoria_nombre,
            condicion=condicion,
            deposito=deposito_nombre or deposito_codigo,
            deposito_codigo=deposito_codigo_int,
        )

        items = [
            PedidoItem(
                pedido=pedido,
                codigo=item['codigo'],
                descripcion=item['descripcion'],
                referencia=item.get('referencia', ''),
                puesto=item.get('puesto', ''),
                ref_proveedor=item.get('ref_proveedor', ''),
                cantidad_solicitada=int(item['cantidad']),
            )
            for item in items_data
        ]
        PedidoItem.objects.bulk_create(items)
```

por:

```python
        primer_item = items_data[0]
        pedido = Pedido.objects.create(
            solicitante=request.user,
            observaciones=form.data.get('observaciones', ''),
            categoria=primer_item.get('categoria') or categoria_codigo,
            categoria_nombre=primer_item.get('categoria_nombre') or categoria_nombre,
            condicion=condicion,
            deposito=deposito_nombre or deposito_codigo,
            deposito_codigo=deposito_codigo_int,
            es_mixto=es_mixto,
        )

        items = [
            PedidoItem(
                pedido=pedido,
                codigo=item['codigo'],
                descripcion=item['descripcion'],
                referencia=item.get('referencia', ''),
                puesto=item.get('puesto', ''),
                ref_proveedor=item.get('ref_proveedor', ''),
                cantidad_solicitada=int(item['cantidad']),
                categoria=item.get('categoria', categoria_codigo),
                categoria_nombre=item.get('categoria_nombre', categoria_nombre),
            )
            for item in items_data
        ]
        PedidoItem.objects.bulk_create(items)
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CrearPedidoMixtoTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (2 tests)

- [ ] **Step 7: Correr la suite completa de `crear_pedido` para descartar regresiones**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CrearPedidoStockTest PedidosAlmacen.tests.CrearPedidoDisponibilidadTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (todos los tests existentes, sin cambios de comportamiento para pedidos no-mixtos)

- [ ] **Step 8: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): crear_pedido persiste es_mixto y categoria por linea"
```

---

### Task 5: UI de creación — checkbox "Pedido mixto"

**Files:**
- Modify: `templates/pedidos-crear.html`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: campo `es_mixto` leído por la vista (Task 4); atributo `Pedido.es_mixto` para rehidratación.
- Produces: cada objeto en `itemsPedido` (y por lo tanto cada entrada de `items_json` enviada al backend) trae `categoria`/`categoria_nombre`, consumido por Task 4.

- [ ] **Step 1: Escribir el test que falla**

```python
class CrearPedidoTemplateMixtoTest(TestCase):
    def test_checkbox_mixto_presente(self):
        from users.models import User
        from django.urls import reverse
        user = User.objects.create_superuser(username='tpl_mixto_u', password='x')
        self.client.force_login(user)
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.obtener_categorias.return_value = []
            resp = self.client.get(reverse('pedidos-crear'))
        self.assertContains(resp, 'id="checkbox-mixto"')
        self.assertContains(resp, 'name="es_mixto"')
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CrearPedidoTemplateMixtoTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL (el checkbox no existe todavía en el template)

- [ ] **Step 3: Agregar el checkbox al HTML**

En `templates/pedidos-crear.html:21-29`, reemplazar:

```html
                <div class="col-md-4">
                    <label for="selector-categoria" class="form-label fw-bold">Categoria <span class="text-danger">*</span></label>
                    <select id="selector-categoria" class="form-select" onchange="seleccionarCategoria(this)">
                        <option value="">-- Seleccione categoria --</option>
                        {% for cat in categorias %}
                        <option value="{{ cat.0 }}" data-nombre="{{ cat.1 }}">{{ cat.1 }}</option>
                        {% endfor %}
                    </select>
                </div>
```

por:

```html
                <div class="col-md-4">
                    <label for="selector-categoria" class="form-label fw-bold">Categoria <span class="text-danger">*</span></label>
                    <select id="selector-categoria" class="form-select" onchange="seleccionarCategoria(this)">
                        <option value="">-- Seleccione categoria --</option>
                        {% for cat in categorias %}
                        <option value="{{ cat.0 }}" data-nombre="{{ cat.1 }}">{{ cat.1 }}</option>
                        {% endfor %}
                    </select>
                    <div class="form-check mt-2">
                        <input class="form-check-input" type="checkbox" id="checkbox-mixto" name="es_mixto">
                        <label class="form-check-label small" for="checkbox-mixto">
                            Pedido mixto (varias categorías)
                        </label>
                    </div>
                </div>
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CrearPedidoTemplateMixtoTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS

- [ ] **Step 5: Capturar categoría por ítem en `agregarItem`**

En `templates/pedidos-crear.html:424-436`, reemplazar:

```javascript
function agregarItem(codigo, descripcion, referencia, puesto, ref_proveedor, cantidad) {
    cantidad = Math.max(1, parseInt(cantidad) || 1);
    const existe = itemsPedido.find(i => i.codigo === codigo);
    let targetIdx;
    if (existe) {
        existe.cantidad += cantidad;
        targetIdx = itemsPedido.indexOf(existe);
        renderItems();
    } else {
        itemsPedido.push({ codigo, descripcion, referencia: referencia || '', puesto: puesto || '', ref_proveedor: ref_proveedor || '', cantidad });
        targetIdx = itemsPedido.length - 1;
        renderItems();
    }
```

por:

```javascript
function agregarItem(codigo, descripcion, referencia, puesto, ref_proveedor, cantidad) {
    cantidad = Math.max(1, parseInt(cantidad) || 1);
    const existe = itemsPedido.find(i => i.codigo === codigo);
    let targetIdx;
    if (existe) {
        existe.cantidad += cantidad;
        targetIdx = itemsPedido.indexOf(existe);
        renderItems();
    } else {
        itemsPedido.push({
            codigo, descripcion,
            referencia: referencia || '', puesto: puesto || '', ref_proveedor: ref_proveedor || '',
            cantidad,
            categoria: document.getElementById('campo-categoria').value,
            categoria_nombre: document.getElementById('campo-categoria-nombre').value,
        });
        targetIdx = itemsPedido.length - 1;
        renderItems();
    }
```

- [ ] **Step 6: Liberar solo el selector de categoría en modo mixto**

En `templates/pedidos-crear.html:406-422`, reemplazar:

```javascript
function bloquearCategoria() {
    if (!categoriaFijada && itemsPedido.length > 0) {
        categoriaFijada = true;
        document.getElementById('selector-categoria').disabled = true;
        document.getElementById('selector-condicion').disabled = true;
        document.getElementById('selector-deposito').disabled = true;
        document.getElementById('info-categoria').classList.remove('alert-warning');
        document.getElementById('info-categoria').classList.add('alert-success');
    } else if (itemsPedido.length === 0) {
        categoriaFijada = false;
        document.getElementById('selector-categoria').disabled = false;
        document.getElementById('selector-condicion').disabled = false;
        document.getElementById('selector-deposito').disabled = false;
        document.getElementById('info-categoria').classList.remove('alert-success');
        document.getElementById('info-categoria').classList.add('alert-warning');
    }
}
```

por:

```javascript
function bloquearCategoria() {
    const esMixto = document.getElementById('checkbox-mixto').checked;
    if (!categoriaFijada && itemsPedido.length > 0) {
        categoriaFijada = true;
        if (!esMixto) {
            document.getElementById('selector-categoria').disabled = true;
        }
        document.getElementById('selector-condicion').disabled = true;
        document.getElementById('selector-deposito').disabled = true;
        document.getElementById('checkbox-mixto').disabled = true;
        document.getElementById('info-categoria').classList.remove('alert-warning');
        document.getElementById('info-categoria').classList.add('alert-success');
    } else if (itemsPedido.length === 0) {
        categoriaFijada = false;
        document.getElementById('selector-categoria').disabled = false;
        document.getElementById('selector-condicion').disabled = false;
        document.getElementById('selector-deposito').disabled = false;
        document.getElementById('checkbox-mixto').disabled = false;
        document.getElementById('info-categoria').classList.remove('alert-success');
        document.getElementById('info-categoria').classList.add('alert-warning');
    }
}
```

- [ ] **Step 7: Rehidratar el checkbox tras un error de stock**

En `templates/pedidos-crear.html:338-350`, reemplazar:

```html
{% if items_json_inicial %}
<script>
window._rehidratarPedido = {
    items: {{ items_json_inicial|safe }},
    stock: {{ stock_info_json|safe }},
    categoria: "{{ categoria_inicial|escapejs }}",
    categoriaNombre: "{{ categoria_nombre_inicial|escapejs }}",
    condicion: "{{ condicion_inicial|escapejs }}",
    deposito: "{{ deposito_inicial|escapejs }}",
    depositoNombre: "{{ deposito_nombre_inicial|escapejs }}"
};
</script>
{% endif %}
```

por:

```html
{% if items_json_inicial %}
<script>
window._rehidratarPedido = {
    items: {{ items_json_inicial|safe }},
    stock: {{ stock_info_json|safe }},
    categoria: "{{ categoria_inicial|escapejs }}",
    categoriaNombre: "{{ categoria_nombre_inicial|escapejs }}",
    condicion: "{{ condicion_inicial|escapejs }}",
    deposito: "{{ deposito_inicial|escapejs }}",
    depositoNombre: "{{ deposito_nombre_inicial|escapejs }}",
    esMixto: {{ es_mixto_inicial|yesno:"true,false" }}
};
</script>
{% endif %}
```

Y en `templates/pedidos-crear.html:585-605`, reemplazar:

```javascript
document.addEventListener('DOMContentLoaded', function() {
    const datos = window._rehidratarPedido;
    if (!datos || !datos.items.length) return;

    const catSel = document.getElementById('selector-categoria');
    catSel.value = datos.categoria;
    seleccionarCategoria(catSel);

    document.getElementById('selector-condicion').value = datos.condicion;
    document.getElementById('selector-deposito').value = datos.deposito;
    validarFormulario();

    itemsPedido = datos.items.map(function(item) {
        const disponible = datos.stock[item.codigo] !== undefined ? datos.stock[item.codigo] : 0;
        return Object.assign({}, item, {
            stockDisponible: disponible,
            stockError: item.cantidad > disponible
        });
    });
    renderItems();
});
```

por:

```javascript
document.addEventListener('DOMContentLoaded', function() {
    const datos = window._rehidratarPedido;
    if (!datos || !datos.items.length) return;

    const catSel = document.getElementById('selector-categoria');
    catSel.value = datos.categoria;
    seleccionarCategoria(catSel);

    document.getElementById('selector-condicion').value = datos.condicion;
    document.getElementById('selector-deposito').value = datos.deposito;
    document.getElementById('checkbox-mixto').checked = !!datos.esMixto;
    validarFormulario();

    itemsPedido = datos.items.map(function(item) {
        const disponible = datos.stock[item.codigo] !== undefined ? datos.stock[item.codigo] : 0;
        return Object.assign({}, item, {
            stockDisponible: disponible,
            stockError: item.cantidad > disponible
        });
    });
    renderItems();
});
```

- [ ] **Step 8: Verificación manual en navegador**

Esta capa es JS de cliente, sin cobertura por `TestCase` de Django. Levantar el servidor de desarrollo, entrar a "Nuevo Pedido", marcar "Pedido mixto", agregar un producto de la categoría A, cambiar el selector a la categoría B (debe permitirlo estando marcado el checkbox) y agregar un segundo producto; confirmar que ambos ítems terminan en el carrito y que el checkbox y el selector de categoría quedan bloqueados tras el primer ítem si el checkbox NO está marcado.

- [ ] **Step 9: Correr toda la suite de `crear_pedido` para descartar regresiones**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.CrearPedidoStockTest PedidosAlmacen.tests.CrearPedidoDisponibilidadTest PedidosAlmacen.tests.CrearPedidoMixtoTest PedidosAlmacen.tests.CrearPedidoTemplateMixtoTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add templates/pedidos-crear.html PedidosAlmacen/tests.py
git commit -m "feat(pedidos): checkbox de pedido mixto en creacion de pedidos"
```

---

### Task 6: Badge "Mixto" en lista y detalle

**Files:**
- Modify: `templates/pedidos-lista.html:87-92`
- Modify: `templates/pedidos-detalle.html:134-140`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `Pedido.es_mixto` (Task 3).

- [ ] **Step 1: Escribir los tests que fallan**

```python
class BadgeMixtoTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_badge_mixto', password='x')
        self.pedido = Pedido.objects.create(
            solicitante=self.sup, estado='PENDIENTE', es_mixto=True,
            categoria='CAT1', categoria_nombre='Categoría 1',
        )
        self.client.force_login(self.sup)

    def test_lista_muestra_badge_mixto(self):
        resp = self.client.get(self.reverse('pedidos-lista'))
        self.assertContains(resp, 'Mixto')

    def test_detalle_muestra_badge_mixto(self):
        resp = self.client.get(self.reverse('pedidos-detalle', args=[self.pedido.numero_pedido]))
        self.assertContains(resp, 'Mixto')
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.BadgeMixtoTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL (ambas vistas siguen mostrando el nombre de categoría, no "Mixto")

- [ ] **Step 3: Badge en `pedidos-lista.html`**

En `templates/pedidos-lista.html:87-92`, reemplazar:

```html
                <td>
                    {% if pedido.categoria %}
                        <span class="fw-semibold">{{ pedido.categoria }}</span>
                        {% if pedido.categoria_nombre %}<br><small class="text-muted">{{ pedido.categoria_nombre }}</small>{% endif %}
                    {% else %}<span class="text-muted">—</span>{% endif %}
                </td>
```

por:

```html
                <td>
                    {% if pedido.es_mixto %}
                        <span class="badge bg-warning text-dark"><i class="fas fa-layer-group me-1"></i>Mixto</span>
                    {% elif pedido.categoria %}
                        <span class="fw-semibold">{{ pedido.categoria }}</span>
                        {% if pedido.categoria_nombre %}<br><small class="text-muted">{{ pedido.categoria_nombre }}</small>{% endif %}
                    {% else %}<span class="text-muted">—</span>{% endif %}
                </td>
```

- [ ] **Step 4: Badge en `pedidos-detalle.html`**

En `templates/pedidos-detalle.html:134-140`, reemplazar:

```html
            <div class="pd-meta-row">
                <dt class="pd-meta-label">Categoría</dt>
                <dd class="pd-meta-value">
                    <span class="badge bg-secondary">{{ pedido.categoria|default:"-" }}</span>
                    {% if pedido.categoria_nombre %}<small class="text-muted ms-1">{{ pedido.categoria_nombre }}</small>{% endif %}
                </dd>
            </div>
```

por:

```html
            <div class="pd-meta-row">
                <dt class="pd-meta-label">Categoría</dt>
                <dd class="pd-meta-value">
                    {% if pedido.es_mixto %}
                        <span class="badge bg-warning text-dark"><i class="fas fa-layer-group me-1"></i>Mixto</span>
                    {% else %}
                        <span class="badge bg-secondary">{{ pedido.categoria|default:"-" }}</span>
                        {% if pedido.categoria_nombre %}<small class="text-muted ms-1">{{ pedido.categoria_nombre }}</small>{% endif %}
                    {% endif %}
                </dd>
            </div>
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.BadgeMixtoTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (2 tests)

- [ ] **Step 6: Commit**

```bash
git add templates/pedidos-lista.html templates/pedidos-detalle.html PedidosAlmacen/tests.py
git commit -m "feat(pedidos): badge Mixto en lista y detalle de pedidos"
```

---

### Task 7: Reportes — agregación "por categoría" a nivel de línea

**Files:**
- Modify: `PedidosAlmacen/views.py:1560-1570, 1602-1648` (`reporte_pedidos`)
- Modify: `PedidosAlmacen/views.py:1680-1691, 1728-1748` (`exportar_reporte_pdf`)
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `PedidoItem.categoria`/`categoria_nombre` (Task 3, ya poblado por Task 4 para pedidos nuevos, y por la migración de datos de Task 3 para pedidos preexistentes).

- [ ] **Step 1: Escribir los tests que fallan**

```python
class ReportePorCategoriaMixtoTest(TestCase):
    """El reporte cuenta un pedido mixto en cada categoría de sus ítems (una sola
    vez por categoría), y el filtro por categoría lo encuentra por cualquiera de ellas."""

    def setUp(self):
        from users.models import User
        from .models import Pedido, PedidoItem
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_rep_mixto', password='x')
        self.pedido = Pedido.objects.create(
            solicitante=self.sup, estado='PENDIENTE', es_mixto=True,
            categoria='CAT1', categoria_nombre='Categoría 1',
        )
        PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='Uno', cantidad_solicitada=1,
            categoria='CAT1', categoria_nombre='Categoría 1',
        )
        PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU2', descripcion='Dos', cantidad_solicitada=1,
            categoria='CAT2', categoria_nombre='Categoría 2',
        )
        self.client.force_login(self.sup)

    def test_por_categoria_cuenta_el_pedido_en_ambas_categorias(self):
        resp = self.client.get(self.reverse('pedidos-reporte'))
        conteos = {fila['categoria']: fila['total'] for fila in resp.context['por_categoria']}
        self.assertEqual(conteos.get('CAT1'), 1)
        self.assertEqual(conteos.get('CAT2'), 1)

    def test_filtro_por_segunda_categoria_encuentra_el_pedido(self):
        resp = self.client.get(self.reverse('pedidos-reporte'), {'categoria': 'CAT2'})
        self.assertEqual(resp.context['total_pedidos'], 1)

    def test_categoria_con_dos_items_no_se_duplica(self):
        from .models import PedidoItem
        PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU3', descripcion='Tres', cantidad_solicitada=1,
            categoria='CAT1', categoria_nombre='Categoría 1',
        )
        resp = self.client.get(self.reverse('pedidos-reporte'))
        conteos = {fila['categoria']: fila['total'] for fila in resp.context['por_categoria']}
        self.assertEqual(conteos.get('CAT1'), 1)
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ReportePorCategoriaMixtoTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL — `test_por_categoria_cuenta_el_pedido_en_ambas_categorias` y `test_filtro_por_segunda_categoria_encuentra_el_pedido` fallan porque hoy `por_categoria`/`categoria_filtro` usan `Pedido.categoria` (solo `CAT1`, nunca `CAT2`).

- [ ] **Step 3: Filtrar por categoría vía `PedidoItem` en `reporte_pedidos`**

En `PedidosAlmacen/views.py:1569-1570`, reemplazar:

```python
    if categoria_filtro:
        pedidos = pedidos.filter(categoria=categoria_filtro)
```

por:

```python
    if categoria_filtro:
        pedidos = pedidos.filter(items__categoria=categoria_filtro).distinct()
```

- [ ] **Step 4: Agregar "por categoría" desde `PedidoItem` en `reporte_pedidos`**

En `PedidosAlmacen/views.py:1602-1608`, reemplazar:

```python
    categoria_top = (
        pedidos.exclude(categoria='')
        .values('categoria', 'categoria_nombre')
        .annotate(total=Count('numero_pedido'))
        .order_by('-total')
        .first()
    )
```

por:

```python
    categoria_top = (
        PedidoItem.objects.filter(pedido__in=pedidos).exclude(categoria='')
        .values('categoria', 'categoria_nombre')
        .annotate(total=Count('pedido_id', distinct=True))
        .order_by('-total')
        .first()
    )
```

Y en `PedidosAlmacen/views.py:1624-1629`, reemplazar:

```python
    por_categoria = (
        pedidos.exclude(categoria='')
        .values('categoria', 'categoria_nombre')
        .annotate(total=Count('numero_pedido'))
        .order_by('-total')[:10]
    )
```

por:

```python
    por_categoria = (
        PedidoItem.objects.filter(pedido__in=pedidos).exclude(categoria='')
        .values('categoria', 'categoria_nombre')
        .annotate(total=Count('pedido_id', distinct=True))
        .order_by('-total')[:10]
    )
```

- [ ] **Step 5: Poblar el filtro de categorías disponibles desde `PedidoItem`**

En `PedidosAlmacen/views.py:1643-1648`, reemplazar:

```python
    categorias_disponibles = (
        Pedido.objects.exclude(categoria='')
        .values('categoria')
        .annotate(nombre=Max('categoria_nombre'))
        .order_by('categoria')
    )
```

por:

```python
    categorias_disponibles = (
        PedidoItem.objects.exclude(categoria='')
        .values('categoria')
        .annotate(nombre=Max('categoria_nombre'))
        .order_by('categoria')
    )
```

- [ ] **Step 6: Aplicar los mismos cambios en `exportar_reporte_pdf`**

En `PedidosAlmacen/views.py:1688-1689`, reemplazar:

```python
    if categoria_filtro:
        pedidos = pedidos.filter(categoria=categoria_filtro)
```

por:

```python
    if categoria_filtro:
        pedidos = pedidos.filter(items__categoria=categoria_filtro).distinct()
```

En `PedidosAlmacen/views.py:1728-1731`, reemplazar:

```python
        'categoria_top': (
            pedidos.exclude(categoria='')
            .values('categoria', 'categoria_nombre').annotate(total=Count('numero_pedido'))
            .order_by('-total').first()
        ),
```

por:

```python
        'categoria_top': (
            PedidoItem.objects.filter(pedido__in=pedidos).exclude(categoria='')
            .values('categoria', 'categoria_nombre').annotate(total=Count('pedido_id', distinct=True))
            .order_by('-total').first()
        ),
```

Y en `PedidosAlmacen/views.py:1745-1748`, reemplazar:

```python
        'por_categoria': list(
            pedidos.exclude(categoria='').values('categoria', 'categoria_nombre')
            .annotate(total=Count('numero_pedido')).order_by('-total')[:10]
        ),
```

por:

```python
        'por_categoria': list(
            PedidoItem.objects.filter(pedido__in=pedidos).exclude(categoria='')
            .values('categoria', 'categoria_nombre')
            .annotate(total=Count('pedido_id', distinct=True)).order_by('-total')[:10]
        ),
```

- [ ] **Step 7: Correr los tests y verificar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ReportePorCategoriaMixtoTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS (3 tests)

- [ ] **Step 8: Correr la suite de reportes completa para descartar regresiones**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.ReporteExcluyeAnuladosTest --settings=Programarprecios.test_settings -v 2`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): reportes agregan categoria por linea, soportan pedidos mixtos"
```

---

## Verificación final

- [ ] Correr toda la suite de `PedidosAlmacen`:

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen --settings=Programarprecios.test_settings`
Expected: PASS (todos los tests, incluidos los preexistentes — sin regresiones)
