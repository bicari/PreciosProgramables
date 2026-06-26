# Validación de existencia y configuración de depósitos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Impedir pedidos de productos sin existencia en el depósito almacén y permitir que un admin configure qué depósitos puede seleccionar el usuario al crear un pedido.

**Architecture:** Tres cambios sobre la app Django `PedidosAlmacen`, sin tocar el flujo de despacho/picking/recepción: (A) filtro "Solo con existencia" en la búsqueda HTMX, (B) bloqueo en frontend del botón "Agregar" para productos con existencia 0, (C) un modelo `DepositoPermitido` gestionado desde el admin que filtra el selector de depósito de origen, con fallback al comportamiento actual.

**Tech Stack:** Django (PostgreSQL para modelos, DBISAM/pyodbc para inventario), HTMX, Bootstrap, plantillas Django. Tests con `django.test.TestCase` + `unittest.mock`.

## Global Constraints

- **DBISAM no soporta placeholders `?`**: las queries usan f-strings. Para entradas de usuario se sanea upstream; el flag `solo_existencia` es un booleano interno y se interpola como fragmento SQL fijo (`AND FT_EXISTENCIA > 0`).
- **La existencia siempre se mide contra el depósito 1 (almacén)** — `FT_CODIGODEPOSITO = 1`, que es lo que `buscar_en_categoria` ya consulta.
- **Type hints** en funciones nuevas; docstrings Google en funciones públicas (PEP 8).
- **Runner de tests**: `python manage.py test PedidosAlmacen.tests -v 2` (no hay pytest).
- **Usuario de test**: `User.objects.create_superuser(username=..., password=...)` (modelo custom `users.models.User`, `USERNAME_FIELD='username'`). Superuser pasa todos los `is_pedidos_*`.
- **Última migración existente**: `0019_add_traslado_a2_registrado`. La nueva se genera con `makemigrations` (será `0020_*`).

---

### Task 1: Modelo `DepositoPermitido` + migración + admin

**Files:**
- Modify: `PedidosAlmacen/models.py` (añadir clase al final)
- Modify: `PedidosAlmacen/admin.py`
- Create: `PedidosAlmacen/migrations/0020_depositopermitido.py` (vía `makemigrations`)
- Modify: `PedidosAlmacen/tests.py`

**Interfaces:**
- Produces: modelo `DepositoPermitido` con campos `codigo: int (unique)`, `nombre: str`, `activo: bool (default False)`, `fecha_sync: datetime (auto_now)`.

- [ ] **Step 1: Escribir el test que falla**

Reemplaza el contenido de `PedidosAlmacen/tests.py` por:

```python
from django.test import TestCase
from django.db import IntegrityError

from .models import DepositoPermitido


class DepositoPermitidoModelTest(TestCase):
    def test_creacion_y_str(self):
        dep = DepositoPermitido.objects.create(codigo=5, nombre='Tienda Centro')
        self.assertFalse(dep.activo)  # default
        self.assertEqual(str(dep), '5 - Tienda Centro')

    def test_codigo_unico(self):
        DepositoPermitido.objects.create(codigo=5, nombre='Uno')
        with self.assertRaises(IntegrityError):
            DepositoPermitido.objects.create(codigo=5, nombre='Dos')
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests -v 2`
Expected: FAIL con `ImportError: cannot import name 'DepositoPermitido'`.

- [ ] **Step 3: Añadir el modelo**

Al final de `PedidosAlmacen/models.py` añade:

```python
class DepositoPermitido(models.Model):
    """Depósito de a2 habilitado para selección al crear un pedido.

    Se sincroniza desde SDEPOSITOS y el admin marca cuáles quedan activos.
    """
    codigo = models.IntegerField(unique=True)      # FDP_CODIGO de SDEPOSITOS
    nombre = models.CharField(max_length=150)      # FDP_DESCRIPCION
    activo = models.BooleanField(default=False)
    fecha_sync = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Depósito permitido'
        verbose_name_plural = 'Depósitos permitidos'

    def __str__(self) -> str:
        return f"{self.codigo} - {self.nombre}"
```

- [ ] **Step 4: Generar la migración**

Run: `python manage.py makemigrations PedidosAlmacen`
Expected: crea `PedidosAlmacen/migrations/0020_depositopermitido.py`.

- [ ] **Step 5: Registrar en el admin**

Reemplaza `PedidosAlmacen/admin.py` por:

```python
from django.contrib import admin
from .models import Pedido, PedidoItem, DepositoPermitido


class PedidoItemInline(admin.TabularInline):
    model = PedidoItem
    extra = 0
    readonly_fields = ('codigo', 'descripcion', 'cantidad_solicitada', 'cantidad_despachada', 'cantidad_recibida', 'estado')


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ('numero_pedido', 'solicitante', 'estado', 'fecha_creacion', 'fecha_despacho', 'fecha_recepcion')
    list_filter = ('estado', 'fecha_creacion')
    search_fields = ('numero_pedido', 'solicitante__username')
    list_per_page = 20
    ordering = ('-fecha_creacion',)
    inlines = [PedidoItemInline]


@admin.register(PedidoItem)
class PedidoItemAdmin(admin.ModelAdmin):
    list_display = ('pedido', 'codigo', 'descripcion', 'cantidad_solicitada', 'cantidad_despachada', 'cantidad_recibida', 'estado')
    list_filter = ('estado',)
    search_fields = ('codigo', 'descripcion')
    list_per_page = 30


@admin.register(DepositoPermitido)
class DepositoPermitidoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'activo', 'fecha_sync')
    list_editable = ('activo',)
    list_filter = ('activo',)
    search_fields = ('codigo', 'nombre')
    ordering = ('nombre',)
```

- [ ] **Step 6: Correr el test y verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests -v 2`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add PedidosAlmacen/models.py PedidosAlmacen/admin.py PedidosAlmacen/migrations/0020_depositopermitido.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): modelo DepositoPermitido + admin"
```

---

### Task 2: Sincronización de depósitos desde a2 (acción del admin)

Reutiliza `PedidosDBISAM.obtener_depositos()` (ya devuelve SDEPOSITOS excepto el 1). La lógica de upsert se extrae a una función pura testeable que **preserva el flag `activo`** de los registros existentes.

**Files:**
- Modify: `PedidosAlmacen/admin.py`
- Modify: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `DepositoPermitido` (Task 1); `PedidosDBISAM.obtener_depositos()` → lista de filas con atributos `FDP_CODIGO`, `FDP_DESCRIPCION`.
- Produces: `sincronizar_depositos_permitidos(rows) -> tuple[int, int]` (creados, actualizados) en `PedidosAlmacen/admin.py`.

- [ ] **Step 1: Escribir el test que falla**

Añade a `PedidosAlmacen/tests.py`:

```python
from types import SimpleNamespace

from .admin import sincronizar_depositos_permitidos


class SincronizarDepositosTest(TestCase):
    def _row(self, codigo, nombre):
        return SimpleNamespace(FDP_CODIGO=codigo, FDP_DESCRIPCION=nombre)

    def test_upsert_preserva_activo_y_actualiza_nombre(self):
        DepositoPermitido.objects.create(codigo=5, nombre='Viejo', activo=True)

        creados, actualizados = sincronizar_depositos_permitidos([
            self._row(5, 'Nuevo Nombre'),
            self._row(7, 'Tienda Norte'),
        ])

        self.assertEqual((creados, actualizados), (1, 1))

        dep5 = DepositoPermitido.objects.get(codigo=5)
        self.assertTrue(dep5.activo)            # se preserva
        self.assertEqual(dep5.nombre, 'Nuevo Nombre')  # se actualiza

        dep7 = DepositoPermitido.objects.get(codigo=7)
        self.assertFalse(dep7.activo)           # nuevo nace inactivo
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.SincronizarDepositosTest -v 2`
Expected: FAIL con `ImportError: cannot import name 'sincronizar_depositos_permitidos'`.

- [ ] **Step 3: Implementar la función y la acción**

En `PedidosAlmacen/admin.py`, añade el import de `PedidosDBISAM` arriba y la función + acción. Cambia la línea de import del modelo y agrega:

```python
from .dbisam import PedidosDBISAM
```

Antes de `DepositoPermitidoAdmin`, añade:

```python
def sincronizar_depositos_permitidos(rows) -> tuple[int, int]:
    """Upsert de depósitos desde filas de SDEPOSITOS, preservando `activo`.

    Args:
        rows: iterable de filas con atributos FDP_CODIGO y FDP_DESCRIPCION.

    Returns:
        Tupla (creados, actualizados).
    """
    creados = 0
    actualizados = 0
    for row in rows:
        _, created = DepositoPermitido.objects.update_or_create(
            codigo=int(row.FDP_CODIGO),
            defaults={'nombre': (row.FDP_DESCRIPCION or '').strip()},
        )
        if created:
            creados += 1
        else:
            actualizados += 1
    return creados, actualizados
```

Y dentro de `DepositoPermitidoAdmin` añade la acción:

```python
    actions = ['accion_sincronizar']

    @admin.action(description='Sincronizar depósitos desde a2')
    def accion_sincronizar(self, request, queryset):
        try:
            rows = PedidosDBISAM().obtener_depositos()
        except Exception as e:
            self.message_user(request, f'Error al conectar con a2: {e}', level='error')
            return
        creados, actualizados = sincronizar_depositos_permitidos(rows)
        self.message_user(
            request,
            f'Sincronización completa: {creados} creados, {actualizados} actualizados.',
        )
```

> Nota: la acción funciona aunque no se seleccionen filas (ignora `queryset`); el admin la lanza desde el menú de acciones.

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.SincronizarDepositosTest -v 2`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/admin.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): accion admin para sincronizar depositos desde a2"
```

---

### Task 3: Selector de depósito usa los activos con fallback

`crear_pedido` deja de llamar `dbisam.obtener_depositos()` directo y usa un helper que devuelve los `DepositoPermitido` activos; si no hay ninguno, cae al comportamiento actual (DBISAM, todos menos el 1).

**Files:**
- Modify: `PedidosAlmacen/views.py` (import de `DepositoPermitido`, helper nuevo, `crear_pedido`)
- Modify: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `DepositoPermitido` (Task 1); `PedidosDBISAM.obtener_depositos()`.
- Produces: `_depositos_para_selector() -> list[tuple[int, str]]` en `PedidosAlmacen/views.py`. Cada tupla es `(codigo, nombre)`; el template accede con `dep.0` / `dep.1` (compatible con el markup actual).

- [ ] **Step 1: Escribir el test que falla**

Añade a `PedidosAlmacen/tests.py`:

```python
from unittest.mock import patch
from types import SimpleNamespace as NS

from . import views


class DepositosParaSelectorTest(TestCase):
    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_usa_activos_y_no_consulta_dbisam(self, mock_db):
        DepositoPermitido.objects.create(codigo=3, nombre='Beta', activo=True)
        DepositoPermitido.objects.create(codigo=2, nombre='Alfa', activo=True)
        DepositoPermitido.objects.create(codigo=9, nombre='Inactivo', activo=False)

        resultado = views._depositos_para_selector()

        self.assertEqual(resultado, [(2, 'Alfa'), (3, 'Beta')])  # ordenado por nombre
        mock_db.assert_not_called()

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_fallback_sin_activos(self, mock_db):
        mock_db.return_value.obtener_depositos.return_value = [
            NS(FDP_CODIGO=4, FDP_DESCRIPCION='Tienda Sur'),
        ]
        resultado = views._depositos_para_selector()
        self.assertEqual(resultado, [(4, 'Tienda Sur')])

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_fallback_con_error_dbisam_devuelve_vacio(self, mock_db):
        mock_db.return_value.obtener_depositos.side_effect = Exception('odbc down')
        self.assertEqual(views._depositos_para_selector(), [])
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.DepositosParaSelectorTest -v 2`
Expected: FAIL con `AttributeError: module ... has no attribute '_depositos_para_selector'`.

- [ ] **Step 3: Implementar el helper y usarlo en `crear_pedido`**

En `PedidosAlmacen/views.py`, cambia el import de modelos para incluir `DepositoPermitido`:

```python
from .models import Pedido, PedidoItem, Despacho, DespachoItem, DepositoPermitido
```

Añade el helper (cerca de los otros helpers de módulo, p. ej. tras `_segundos_laborales`):

```python
def _depositos_para_selector() -> list[tuple[int, str]]:
    """Depósitos seleccionables al crear un pedido.

    Devuelve los DepositoPermitido activos (codigo, nombre). Si no hay ninguno
    activo, cae al listado de a2 (todos menos el almacén) como fallback.
    """
    activos = list(
        DepositoPermitido.objects.filter(activo=True)
        .order_by('nombre')
        .values_list('codigo', 'nombre')
    )
    if activos:
        return [(c, n) for c, n in activos]
    try:
        rows = PedidosDBISAM().obtener_depositos()
        return [(int(r.FDP_CODIGO), r.FDP_DESCRIPCION or '') for r in rows]
    except Exception:
        logger.exception('Fallback de depositos: error al consultar DBISAM')
        return []
```

En `crear_pedido`, reemplaza el bloque de obtención de depósitos. Cambia:

```python
    categorias = []
    depositos = []
    try:
        dbisam = PedidosDBISAM()
        categorias = dbisam.obtener_categorias()
        depositos = dbisam.obtener_depositos()
    except Exception:
        pass
```

por:

```python
    categorias = []
    try:
        categorias = PedidosDBISAM().obtener_categorias()
    except Exception:
        pass
    depositos = _depositos_para_selector()
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.DepositosParaSelectorTest -v 2`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): selector de deposito filtra por activos con fallback"
```

---

### Task 4: Filtro `solo_existencia` en la búsqueda (backend)

Añade el parámetro al método DBISAM y a la vista. La existencia se sigue midiendo en el depósito 1.

**Files:**
- Modify: `PedidosAlmacen/dbisam.py` (`buscar_en_categoria`)
- Modify: `PedidosAlmacen/views.py` (`buscar_producto`)
- Modify: `PedidosAlmacen/tests.py`

**Interfaces:**
- Produces: `PedidosDBISAM.buscar_en_categoria(categoria, query, tipo='codigo', solo_existencia=False)`. Cuando `solo_existencia=True`, la query añade `AND FT_EXISTENCIA > 0`.
- La vista `buscar_producto` lee `request.GET.get('solo_existencia') == '1'` y lo pasa como `solo_existencia=`.

- [ ] **Step 1: Escribir los tests que fallan**

Añade a `PedidosAlmacen/tests.py`:

```python
from unittest.mock import MagicMock

from .dbisam import PedidosDBISAM


class BuscarEnCategoriaFiltroTest(TestCase):
    def _capturar_sql(self, **kwargs):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = (mock_connect.return_value.__enter__.return_value
                      .cursor.return_value.__enter__.return_value)
            cursor.execute.return_value.fetchmany.return_value = []
            db.buscar_en_categoria('CAT', 'abc', 'descripcion', **kwargs)
            return cursor.execute.call_args[0][0]

    def test_con_solo_existencia_agrega_filtro(self):
        sql = self._capturar_sql(solo_existencia=True)
        self.assertIn('FT_EXISTENCIA > 0', sql)

    def test_sin_solo_existencia_no_agrega_filtro(self):
        sql = self._capturar_sql(solo_existencia=False)
        self.assertNotIn('FT_EXISTENCIA > 0', sql)


class BuscarProductoVistaTest(TestCase):
    def setUp(self):
        from users.models import User
        self.user = User.objects.create_superuser(username='admin', password='x')
        self.client.force_login(self.user)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_vista_pasa_flag_true(self, mock_db):
        mock_db.return_value.buscar_en_categoria.return_value = []
        self.client.get('/pedidos/buscar-producto/',
                        {'q': 'abc', 'categoria': 'CAT', 'solo_existencia': '1'})
        _, kwargs = mock_db.return_value.buscar_en_categoria.call_args
        self.assertTrue(kwargs.get('solo_existencia'))

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_vista_pasa_flag_false_si_ausente(self, mock_db):
        mock_db.return_value.buscar_en_categoria.return_value = []
        self.client.get('/pedidos/buscar-producto/',
                        {'q': 'abc', 'categoria': 'CAT'})
        _, kwargs = mock_db.return_value.buscar_en_categoria.call_args
        self.assertFalse(kwargs.get('solo_existencia'))
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python manage.py test PedidosAlmacen.tests.BuscarEnCategoriaFiltroTest PedidosAlmacen.tests.BuscarProductoVistaTest -v 2`
Expected: FAIL (el método aún no acepta `solo_existencia`; la vista no lo pasa como kwarg).

- [ ] **Step 3: Añadir el parámetro en `buscar_en_categoria`**

En `PedidosAlmacen/dbisam.py`, cambia la firma y el WHERE. Reemplaza:

```python
    def buscar_en_categoria(self, categoria, query, tipo='codigo'):
        try:
            if tipo == 'descripcion':
```

por:

```python
    def buscar_en_categoria(self, categoria, query, tipo='codigo', solo_existencia=False):
        try:
            if tipo == 'descripcion':
```

Y justo antes de construir la query SQL (después del bloque if/elif/else que arma `where`, antes del `with self.connect()`), añade:

```python
            filtro_existencia = " AND FT_EXISTENCIA > 0" if solo_existencia else ""
```

Luego, en el `WHERE` de la query, cambia:

```python
                                        WHERE {where} AND FT_CODIGODEPOSITO = 1
```

por:

```python
                                        WHERE {where} AND FT_CODIGODEPOSITO = 1{filtro_existencia}
```

- [ ] **Step 4: Pasar el flag desde la vista**

En `PedidosAlmacen/views.py::buscar_producto`, después de leer `tipo` y `categoria`, añade la lectura del flag y pásalo. Cambia:

```python
    query = request.GET.get('q', '').strip()
    tipo = request.GET.get('tipo', 'codigo')
    categoria = request.GET.get('categoria', '').strip()
```

por:

```python
    query = request.GET.get('q', '').strip()
    tipo = request.GET.get('tipo', 'codigo')
    categoria = request.GET.get('categoria', '').strip()
    solo_existencia = request.GET.get('solo_existencia') == '1'
```

Y cambia la llamada:

```python
        resultados_raw = dbisam.buscar_en_categoria(categoria, query, tipo)
```

por:

```python
        resultados_raw = dbisam.buscar_en_categoria(
            categoria, query, tipo, solo_existencia=solo_existencia)
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `python manage.py test PedidosAlmacen.tests.BuscarEnCategoriaFiltroTest PedidosAlmacen.tests.BuscarProductoVistaTest -v 2`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/dbisam.py PedidosAlmacen/views.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): filtro solo_existencia en busqueda de productos"
```

---

### Task 5: Frontend — checkbox "Solo con existencia" (default ON) + bloqueo del botón "Agregar"

**Files:**
- Modify: `templates/pedidos-buscar-producto.html` (botón disabled si existencia 0)
- Modify: `templates/pedidos-crear.html` (checkbox + hx-include + trigger JS)
- Modify: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: la vista `buscar_producto` ya entrega `producto.existencia` y acepta `solo_existencia=1` (Task 4).

- [ ] **Step 1: Escribir el test de render que falla**

Añade a `PedidosAlmacen/tests.py`:

```python
class BotonAgregarBloqueoTest(TestCase):
    def setUp(self):
        from users.models import User
        self.user = User.objects.create_superuser(username='admin2', password='x')
        self.client.force_login(self.user)

    def _buscar(self, existencia):
        # (FI_CODIGO, FI_DESCRIPCION, FI_REFERENCIA, FI_PUESTO, existencia, ZZCAMPO_001)
        fila = ('P1', 'Producto Uno', 'REF1', 'A1', existencia, 'RP1')
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.buscar_en_categoria.return_value = [fila]
            resp = self.client.get('/pedidos/buscar-producto/',
                                   {'q': 'pro', 'categoria': 'CAT'})
        return resp.content.decode()

    def test_existencia_cero_boton_deshabilitado(self):
        html = self._buscar(0)
        self.assertIn('disabled', html)
        self.assertIn('Sin stock', html)
        self.assertNotIn("agregarItem('P1'", html)

    def test_con_existencia_boton_habilitado(self):
        html = self._buscar(7)
        self.assertIn("agregarItem('P1'", html)
        self.assertNotIn('Sin stock', html)
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.BotonAgregarBloqueoTest -v 2`
Expected: FAIL (`test_existencia_cero_boton_deshabilitado` falla: hoy siempre se renderiza `agregarItem` y no existe "Sin stock").

- [ ] **Step 3: Bloquear el botón en el partial**

En `templates/pedidos-buscar-producto.html`, reemplaza el bloque de la última celda:

```html
            <td>
                <button type="button" class="btn btn-sm btn-success w-100"
                    onclick="agregarItem('{{ producto.codigo }}', '{{ producto.descripcion|escapejs }}', '{{ producto.referencia|escapejs }}', '{{ producto.puesto|escapejs }}', '{{ producto.ref_proveedor|escapejs }}')">
                    <i class="fas fa-plus"></i> Agregar
                </button>
            </td>
```

por:

```html
            <td>
                {% if producto.existencia > 0 %}
                <button type="button" class="btn btn-sm btn-success w-100"
                    onclick="agregarItem('{{ producto.codigo }}', '{{ producto.descripcion|escapejs }}', '{{ producto.referencia|escapejs }}', '{{ producto.puesto|escapejs }}', '{{ producto.ref_proveedor|escapejs }}')">
                    <i class="fas fa-plus"></i> Agregar
                </button>
                {% else %}
                <button type="button" class="btn btn-sm btn-secondary w-100" disabled
                    title="Sin existencia en almacen">
                    <i class="fas fa-ban"></i> Sin stock
                </button>
                {% endif %}
            </td>
```

- [ ] **Step 4: Correr el test de render y verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.BotonAgregarBloqueoTest -v 2`
Expected: PASS (2 tests).

- [ ] **Step 5: Añadir el checkbox "Solo con existencia" (default ON)**

En `templates/pedidos-crear.html`, dentro de la fila de búsqueda (después del `<div class="col-6 col-md-3">` del selector `tipo-busqueda`, como nueva columna antes del indicador "Buscando..."), inserta:

```html
                <div class="col-6 col-md-3 d-flex align-items-center">
                    <div class="form-check mb-0">
                        <input class="form-check-input" type="checkbox" value="1"
                            id="solo-existencia" name="solo_existencia" checked>
                        <label class="form-check-label small" for="solo-existencia">
                            Solo con existencia
                        </label>
                    </div>
                </div>
```

- [ ] **Step 6: Incluir el checkbox en la petición y re-disparar al cambiar**

En el mismo archivo, en el `<input id="buscar-producto">`, cambia el `hx-include` y añade el trigger `cambioFiltro`. Reemplaza:

```html
                        hx-trigger="input changed delay:500ms, keyup[key=='Enter']"
                        hx-target="#resultados-busqueda"
                        hx-swap="innerHTML"
                        hx-include="#tipo-busqueda, #campo-categoria"
```

por:

```html
                        hx-trigger="input changed delay:500ms, keyup[key=='Enter'], cambioFiltro"
                        hx-target="#resultados-busqueda"
                        hx-swap="innerHTML"
                        hx-include="#tipo-busqueda, #campo-categoria, #solo-existencia"
```

Luego, en el bloque `<script>`, junto al listener de `tipo-busqueda` (cerca de la línea `document.getElementById('tipo-busqueda').addEventListener(...)`), añade:

```javascript
document.getElementById('solo-existencia').addEventListener('change', function() {
    const input = document.getElementById('buscar-producto');
    if (input.value.trim().length >= 2) {
        htmx.trigger(input, 'cambioFiltro');
    }
});
```

- [ ] **Step 7: Verificación manual del comportamiento HTMX**

Run: `python manage.py runserver`
Pasos: entrar a Nuevo Pedido → seleccionar categoría/condición/depósito → buscar un término. Confirmar:
1. El check "Solo con existencia" aparece marcado por defecto y los resultados excluyen existencia 0.
2. Al desmarcarlo, la búsqueda se repite y aparecen productos con badge rojo "0" y botón "Sin stock" deshabilitado.
3. Al volver a marcarlo, desaparecen los de existencia 0.

- [ ] **Step 8: Correr toda la suite**

Run: `python manage.py test PedidosAlmacen.tests -v 2`
Expected: PASS (todos los tests de las Tasks 1-5).

- [ ] **Step 9: Commit**

```bash
git add templates/pedidos-buscar-producto.html templates/pedidos-crear.html PedidosAlmacen/tests.py
git commit -m "feat(pedidos): checkbox solo-existencia y bloqueo de agregar sin stock"
```

---

## Self-Review

**Spec coverage:**
- Componente A (filtro "Solo con existencia", default ON) → Task 4 (backend) + Task 5 steps 5-7 (checkbox default `checked`). ✓
- Componente B (bloqueo al agregar) → Task 5 steps 3-4 (botón `disabled`). Revalidación servidor marcada fuera de alcance en el spec; no se incluye. ✓
- Componente C (modelo + sync + admin + consumo + fallback) → Task 1 (modelo/admin), Task 2 (sync), Task 3 (consumo + fallback). ✓
- Migración sin data migration → Task 1 step 4 (`makemigrations`); fallback cubre tabla vacía → Task 3. ✓
- Existencia siempre vs depósito 1 → Global Constraints + Task 4 (no se toca `FT_CODIGODEPOSITO = 1`). ✓

**Placeholder scan:** sin TBD/TODO; todo paso con código muestra el código. ✓

**Type consistency:** `_depositos_para_selector() -> list[tuple[int, str]]` consumido por template vía `dep.0/dep.1`; `sincronizar_depositos_permitidos(rows) -> tuple[int,int]`; `buscar_en_categoria(..., solo_existencia=False)` llamado con kwarg `solo_existencia=` en la vista y en los tests. Nombres consistentes entre tasks. ✓
