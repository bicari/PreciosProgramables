# Integración de existencia por ubicación con a2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enganchar el picking de `PedidosAlmacen` (vía API móvil) a las ubicaciones físicas del producto, y agregar un job periódico que reconcilie la existencia por ubicación contra el total real en a2, sin bloquear nunca el flujo operativo de pedidos.

**Architecture:** Todo el trabajo nuevo vive en la app `ubicaciones` (modelo, servicio, comando de gestión, API) más dos puntos de integración puntuales en `PedidosAlmacen/api_views.py`. `UbicacionesService.descontar_por_picking` es el núcleo: un método reentrante que se llama cada vez que se guarda `cantidad_preparada` de un `PedidoItem`, revierte lo que había aplicado antes para ese ítem y reaplica según el valor nuevo, sin lanzar excepciones — cualquier ambigüedad o faltante de stock queda como una incidencia (`MovimientoUbicacion.pendiente_revision=True`) en vez de frenar el guardado. El job de reconciliación (`reconciliar_existencias`) reutiliza el mismo patrón de incidencia para las salidas externas que a2 refleja sin haber pasado por la app.

**Tech Stack:** Django 4.x + Django REST Framework, PostgreSQL (Postgres es donde vive `ubicaciones`), pyodbc/DBISAM solo de lectura (`PedidosDBISAM.consultar_stock_multiple`), tests con `django.test.TestCase` + `rest_framework.test.APIClient`, mocks de DBISAM vía `unittest.mock.patch`.

**Spec:** `docs/superpowers/specs/2026-09-03-integracion-existencia-ubicaciones-a2-design.md`

## Global Constraints

- `ubicaciones` nunca bloquea el flujo de `PedidosAlmacen`: `descontar_por_picking` no lanza `ValidationError` por ambigüedad de ubicación ni por falta de stock; siempre retorna un dict de resultado.
- a2 (`SINVDEP` depósito 1, `DEPOSITO_ALMACEN` en `PedidosAlmacen/dbisam.py`) sigue siendo la única fuente de verdad del total; no se toca su esquema.
- Un SKU puede tener varias `ProductoUbicacion` PICKING y varias ALMACENAJE simultáneamente — no hay restricción 1:1.
- Todas las escrituras de `UbicacionesService` van dentro de `@transaction.atomic` con `select_for_update`, igual que el resto del archivo (`ubicaciones/services.py`).
- DBISAM se mockea en tests con `@patch('ubicaciones.services.PedidosDBISAM')` (dentro de `ubicaciones`) o `@patch('ubicaciones.management.commands.reconciliar_existencias.PedidosDBISAM')` (dentro del comando) — nunca hay conexión real a DBISAM en tests. Los tests corren con `python manage.py test <app> --settings=Programarprecios.test_settings` (SQLite), con el `venv` del proyecto activado.
- Imports de `ubicaciones` dentro de `PedidosAlmacen/api_views.py` van **inline dentro de la función** (no a nivel de módulo) — sigue el patrón ya usado en ese archivo para `from ubicaciones.models import ProductoUbicacion` (ver `api_buscar_producto`).

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `ubicaciones/tests.py` | Se limpia el scaffolding del spec descartado (import roto + 5 clases de test) antes de agregar nada nuevo. |
| `ubicaciones/models.py` | `ProductoUbicacion.es_principal`; `MovimientoUbicacion` gana `cantidad`, `pendiente_revision`, `revisado_por`, `fecha_revision`, `pedido_item` (FK laxa), `activo`; nuevos `TIPO_CHOICES`. |
| `ubicaciones/migrations/0003_*.py` | Migración autogenerada para lo anterior. |
| `ubicaciones/admin.py` | Refleja los campos nuevos en `ProductoUbicacionAdmin` y `MovimientoUbicacionAdmin`. |
| `ubicaciones/services.py` | `marcar_principal`, `descontar_por_picking`, `resolver_incidencia`, `ajustar_por_reconciliacion_a2`. |
| `ubicaciones/serializers.py` | `ProductoUbicacionSerializer` gana `es_principal`; `MovimientoSerializer` gana `cantidad`, `pendiente_revision`, `revisado_por_nombre`, `fecha_revision`. |
| `ubicaciones/api_views.py` | `api_incidencias_list`, `api_resolver_incidencia`, `api_marcar_principal`. |
| `ubicaciones/api_urls.py` | Rutas para los 3 endpoints anteriores. |
| `ubicaciones/management/commands/reconciliar_existencias.py` | Comando nuevo (job periódico). |
| `PedidosAlmacen/api_views.py` | `api_update_item` y `api_preparar_pedido` (acción `finalizar`) llaman a `descontar_por_picking`. |
| `PedidosAlmacen/tests.py` | Tests nuevos para la integración anterior. |
| `docs/superpowers/specs/2026-09-02-existencia-por-ubicacion-picking-design.md` | Se elimina en la última tarea (spec descartado). |

---

### Task 1: Limpiar el scaffolding del spec descartado

**Files:**
- Modify: `ubicaciones/tests.py:11-14` (import roto), `ubicaciones/tests.py:416-446` (`SinUbicacionVistaTest`), `ubicaciones/tests.py:813-1041` (últimas 4 clases del spec descartado)

**Interfaces:**
- Consumes: nada nuevo.
- Produces: `ubicaciones/tests.py` vuelve a importar y correr en verde. Ninguna tarea posterior depende de esto salvo tener una baseline limpia.

El módulo `ubicaciones.models` no define `ExistenciaSinUbicacion` ni `PickingOrigen` (ese diseño fue descartado — ver spec 2026-09-03, "Nota de reemplazo"), pero `ubicaciones/tests.py` los importa y los usa en 5 lugares. Hoy el archivo completo falla con `ImportError` al cargar. Hay que limpiarlo antes de escribir nada nuevo.

- [ ] **Step 1: Confirmar el estado roto actual**

Run: `python manage.py test ubicaciones --settings=Programarprecios.test_settings`
Expected: `ImportError: cannot import name 'ExistenciaSinUbicacion' from 'ubicaciones.models'`

- [ ] **Step 2: Arreglar el import roto**

En `ubicaciones/tests.py`, reemplazar:

```python
from ubicaciones.models import (
    Cuerpo, ExistenciaSinUbicacion, Galpon, MovimientoUbicacion, Nivel,
    PickingOrigen, ProductoUbicacion, Rack, Ubicacion,
)
```

por:

```python
from ubicaciones.models import (
    Cuerpo, Galpon, MovimientoUbicacion, Nivel, ProductoUbicacion, Rack, Ubicacion,
)
```

- [ ] **Step 3: Eliminar `SinUbicacionVistaTest`**

Borrar por completo la clase (líneas 416-446 del archivo original, entre `AlertasStockTest` y `MapaTest`):

```python
class SinUbicacionVistaTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='ubicaciones_web')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client.force_login(self.user)

    def test_sin_ubicacion_lista_devuelve_200_y_excluye_ceros(self):
        ExistenciaSinUbicacion.objects.create(
            codigo_producto='ABC', existencia_a2=180, cantidad_asignada=170, cantidad_sin_ubicacion=10,
        )
        ExistenciaSinUbicacion.objects.create(
            codigo_producto='XYZ', existencia_a2=50, cantidad_asignada=50, cantidad_sin_ubicacion=0,
        )
        response = self.client.get(reverse('ubicaciones-sin-ubicacion'))
        self.assertEqual(response.status_code, 200)
        codigos = [r.codigo_producto for r in response.context['registros']]
        self.assertIn('ABC', codigos)
        self.assertNotIn('XYZ', codigos)

    def test_sin_ubicacion_lista_ordena_por_magnitud_absoluta(self):
        ExistenciaSinUbicacion.objects.create(
            codigo_producto='POS', existencia_a2=100, cantidad_asignada=90, cantidad_sin_ubicacion=10,
        )
        ExistenciaSinUbicacion.objects.create(
            codigo_producto='NEG', existencia_a2=30, cantidad_asignada=50, cantidad_sin_ubicacion=-20,
        )
        response = self.client.get(reverse('ubicaciones-sin-ubicacion'))
        codigos = [r.codigo_producto for r in response.context['registros']]
        self.assertEqual(codigos, ['NEG', 'POS'])  # |-20| > |10|
```

(deja `AlertasStockTest` y `MapaTest`, que están antes y después, intactas)

- [ ] **Step 4: Eliminar las 4 clases finales del archivo**

Todo desde `class ExistenciaSinUbicacionModeloTest(TestCase):` hasta el final del archivo (era la línea 815 a 1041 del original: `ExistenciaSinUbicacionModeloTest`, `PickingOrigenModeloTest`, `RecalculoSinUbicacionTest`, `AplicarPickingServiceTest`) queda eliminado. `RackFormTest`... espera, esas clases están *antes* en el archivo (líneas 633+) y no se tocan. Confirmar que el archivo termina en `CuerpoUbicacionNivelTemplatesSmokeTest.test_paginas_de_cuerpo_ubicacion_nivel_devuelven_200` (la última clase que se conserva) y que no queda nada después.

- [ ] **Step 5: Correr la suite completa de `ubicaciones` y confirmar verde**

Run: `python manage.py test ubicaciones --settings=Programarprecios.test_settings`
Expected: todos los tests pasan (0 errores de import, 0 fallos)

- [ ] **Step 6: Commit**

```bash
git add ubicaciones/tests.py
git commit -m "test(ubicaciones): elimina scaffolding del spec descartado 2026-09-02

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FVLAtuBuJc6pUP3VmUEL8g"
```

---

### Task 2: Modelo — `es_principal`, campos de incidencia en `MovimientoUbicacion`, migración

**Files:**
- Modify: `ubicaciones/models.py:166-186` (`ProductoUbicacion`), `ubicaciones/models.py:189-241` (`MovimientoUbicacion`)
- Modify: `ubicaciones/admin.py`
- Create: `ubicaciones/migrations/0003_*.py` (autogenerada)
- Test: `ubicaciones/tests.py`

**Interfaces:**
- Produces: `ProductoUbicacion.es_principal: bool` (default `False`). `MovimientoUbicacion.cantidad: int | None`, `.pendiente_revision: bool` (default `False`), `.revisado_por: User | None`, `.fecha_revision: datetime | None`, `.pedido_item: PedidoItem | None` (FK laxa a `'PedidosAlmacen.PedidoItem'`), `.activo: bool` (default `True`). `MovimientoUbicacion.TIPO_CHOICES` gana `'PICKING'` y `'AJUSTE_A2'`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `ubicaciones/tests.py`:

```python
class CamposIncidenciaModeloTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='campos_incidencia')
        self.galpon = Galpon.objects.create(codigo='1', nombre='Galpón 1', creado_por=self.user)
        self.rack = Rack.objects.create(galpon=self.galpon, codigo='A', max_niveles=6, creado_por=self.user)
        self.cuerpo = Cuerpo.objects.create(rack=self.rack, codigo='01', creado_por=self.user)
        self.ubicacion = Ubicacion.objects.create(cuerpo=self.cuerpo, codigo='01', creado_por=self.user)
        self.nivel = Nivel.objects.create(ubicacion=self.ubicacion, numero=1, creado_por=self.user)

    def test_producto_ubicacion_es_principal_default_false(self):
        pu = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel, cantidad=10)
        self.assertFalse(pu.es_principal)

    def test_movimiento_ubicacion_campos_nuevos_default(self):
        mov = MovimientoUbicacion.objects.create(tipo='PICKING', usuario=self.user, codigo_producto='ABC')
        self.assertIsNone(mov.cantidad)
        self.assertFalse(mov.pendiente_revision)
        self.assertIsNone(mov.revisado_por)
        self.assertIsNone(mov.fecha_revision)
        self.assertIsNone(mov.pedido_item)
        self.assertTrue(mov.activo)

    def test_movimiento_ubicacion_admite_tipo_ajuste_a2(self):
        mov = MovimientoUbicacion.objects.create(
            tipo='AJUSTE_A2', codigo_producto='ABC', cantidad=5, pendiente_revision=True,
        )
        self.assertEqual(mov.cantidad, 5)
        self.assertTrue(mov.pendiente_revision)

    def test_movimiento_ubicacion_admite_pedido_item(self):
        from PedidosAlmacen.models import Pedido, PedidoItem
        pedido = Pedido.objects.create(solicitante=self.user)
        item = PedidoItem.objects.create(
            pedido=pedido, codigo='ABC', descripcion='Producto ABC', cantidad_solicitada=10,
        )
        mov = MovimientoUbicacion.objects.create(tipo='PICKING', codigo_producto='ABC', pedido_item=item)
        self.assertEqual(mov.pedido_item_id, item.id)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python manage.py test ubicaciones.tests.CamposIncidenciaModeloTest --settings=Programarprecios.test_settings`
Expected: `FieldError` o `TypeError` (los campos/choices todavía no existen)

- [ ] **Step 3: Agregar los campos al modelo**

En `ubicaciones/models.py`, en la clase `ProductoUbicacion`, después de `stock_minimo`:

```python
    stock_minimo = models.PositiveIntegerField(null=True, blank=True)
    es_principal = models.BooleanField(default=False)
```

En `MovimientoUbicacion`, agregar a `TIPO_CHOICES` (después de `'DESFUSION_NIVEL'`):

```python
        ('DESFUSION_NIVEL', 'Desfusión de nivel'),
        ('PICKING', 'Descuento por picking'),
        ('AJUSTE_A2', 'Ajuste por reconciliación con a2'),
    ]
```

Y agregar los campos nuevos justo antes de `notas`:

```python
    cantidad = models.IntegerField(null=True, blank=True)
    pendiente_revision = models.BooleanField(default=False)
    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='incidencias_ubicacion_revisadas',
    )
    fecha_revision = models.DateTimeField(null=True, blank=True)
    pedido_item = models.ForeignKey(
        'PedidosAlmacen.PedidoItem',
        on_delete=models.CASCADE, null=True, blank=True,
        related_name='movimientos_ubicacion',
    )
    activo = models.BooleanField(default=True)
    notas = models.TextField(blank=True, default='')
```

(mantiene `notas` donde ya estaba, solo se insertan los campos nuevos antes)

- [ ] **Step 4: Generar y aplicar la migración**

Run: `python manage.py makemigrations ubicaciones --settings=Programarprecios.test_settings`
Expected: crea `ubicaciones/migrations/0003_productoubicacion_es_principal_and_more.py` (o nombre similar autogenerado)

Run: `python manage.py test ubicaciones.tests.CamposIncidenciaModeloTest --settings=Programarprecios.test_settings`
Expected: PASS (las 4 pruebas)

- [ ] **Step 5: Reflejar los campos en el admin**

En `ubicaciones/admin.py`, `ProductoUbicacionAdmin`:

```python
@admin.register(ProductoUbicacion)
class ProductoUbicacionAdmin(admin.ModelAdmin):
    list_display = ['codigo_producto', 'nivel', 'cantidad', 'stock_minimo', 'es_principal', 'fecha_asignacion']
    search_fields = ['codigo_producto']
    list_filter = ['nivel__ubicacion__cuerpo__rack', 'es_principal']
    readonly_fields = ['fecha_asignacion', 'asignado_por']
```

`MovimientoUbicacionAdmin`:

```python
@admin.register(MovimientoUbicacion)
class MovimientoUbicacionAdmin(admin.ModelAdmin):
    list_display = [
        'tipo', 'codigo_producto', 'cantidad', 'pendiente_revision', 'rack',
        'nivel_origen', 'nivel_destino', 'usuario', 'fecha',
    ]
    list_filter = ['tipo', 'pendiente_revision']
    search_fields = ['codigo_producto']
    date_hierarchy = 'fecha'
    readonly_fields = [
        'tipo', 'galpon', 'rack', 'cuerpo', 'ubicacion', 'nivel',
        'nivel_origen', 'nivel_destino', 'codigo_producto', 'cantidad',
        'pendiente_revision', 'revisado_por', 'fecha_revision', 'pedido_item',
        'activo', 'usuario', 'fecha', 'notas',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

- [ ] **Step 6: Correr toda la suite de `ubicaciones`**

Run: `python manage.py test ubicaciones --settings=Programarprecios.test_settings`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add ubicaciones/models.py ubicaciones/admin.py ubicaciones/migrations/0003_*.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): agrega es_principal y campos de incidencia a MovimientoUbicacion

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FVLAtuBuJc6pUP3VmUEL8g"
```

---

### Task 3: Servicio — `marcar_principal`

**Files:**
- Modify: `ubicaciones/services.py` (agregar al final del archivo)
- Test: `ubicaciones/tests.py`

**Interfaces:**
- Consumes: `ProductoUbicacion.es_principal` (Task 2).
- Produces: `UbicacionesService.marcar_principal(producto_ubicacion: ProductoUbicacion, usuario) -> ProductoUbicacion`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `ubicaciones/tests.py`:

```python
class MarcarPrincipalServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='marcar_principal')
        self.galpon = Galpon.objects.create(codigo='1', nombre='Galpón 1', creado_por=self.user)
        self.rack = Rack.objects.create(galpon=self.galpon, codigo='A', max_niveles=6, creado_por=self.user)
        self.cuerpo = Cuerpo.objects.create(rack=self.rack, codigo='01', creado_por=self.user)
        self.ubicacion = Ubicacion.objects.create(cuerpo=self.cuerpo, codigo='01', creado_por=self.user)
        self.nivel1 = Nivel.objects.create(ubicacion=self.ubicacion, numero=1, creado_por=self.user)
        self.nivel2 = Nivel.objects.create(ubicacion=self.ubicacion, numero=2, creado_por=self.user)
        self.pu1 = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel1, cantidad=10)
        self.pu2 = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel2, cantidad=5)

    def test_marcar_principal_activa_el_flag(self):
        UbicacionesService.marcar_principal(self.pu1, self.user)
        self.pu1.refresh_from_db()
        self.assertTrue(self.pu1.es_principal)

    def test_marcar_principal_desmarca_otras_del_mismo_codigo(self):
        UbicacionesService.marcar_principal(self.pu1, self.user)
        UbicacionesService.marcar_principal(self.pu2, self.user)
        self.pu1.refresh_from_db()
        self.pu2.refresh_from_db()
        self.assertFalse(self.pu1.es_principal)
        self.assertTrue(self.pu2.es_principal)

    def test_marcar_principal_no_afecta_otro_codigo_producto(self):
        pu_otro = ProductoUbicacion.objects.create(codigo_producto='XYZ', nivel=self.nivel1, cantidad=1)
        UbicacionesService.marcar_principal(pu_otro, self.user)
        UbicacionesService.marcar_principal(self.pu1, self.user)
        pu_otro.refresh_from_db()
        self.assertTrue(pu_otro.es_principal)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python manage.py test ubicaciones.tests.MarcarPrincipalServiceTest --settings=Programarprecios.test_settings`
Expected: `AttributeError: type object 'UbicacionesService' has no attribute 'marcar_principal'`

- [ ] **Step 3: Implementar**

Agregar al final de `ubicaciones/services.py` (después de `desfusionar_nivel`):

```python
    # ------------------------------------------------------------------ Principal / picking

    @staticmethod
    @transaction.atomic
    def marcar_principal(producto_ubicacion: ProductoUbicacion, usuario) -> ProductoUbicacion:
        """Marca esta ProductoUbicacion como principal para su codigo_producto,
        desmarcando cualquier otra del mismo código."""
        ProductoUbicacion.objects.filter(
            codigo_producto=producto_ubicacion.codigo_producto,
        ).exclude(pk=producto_ubicacion.pk).update(es_principal=False)
        producto_ubicacion.es_principal = True
        producto_ubicacion.save(update_fields=['es_principal'])
        return producto_ubicacion
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python manage.py test ubicaciones.tests.MarcarPrincipalServiceTest --settings=Programarprecios.test_settings`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ubicaciones/services.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): agrega UbicacionesService.marcar_principal

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FVLAtuBuJc6pUP3VmUEL8g"
```

---

### Task 4: Servicio — `descontar_por_picking` (núcleo del picking)

**Files:**
- Modify: `ubicaciones/services.py`
- Test: `ubicaciones/tests.py`

**Interfaces:**
- Consumes: `MovimientoUbicacion.{cantidad,pendiente_revision,pedido_item,activo}` (Task 2). Recibe un objeto `pedido_item` con atributos `.codigo` (str) y `.pk`/`.id` — no importa `PedidosAlmacen.models` a nivel de módulo, solo usa duck typing.
- Produces: `UbicacionesService.descontar_por_picking(pedido_item, cantidad: int, usuario, nivel_id: int | None = None) -> dict` con claves `aplicado: bool`, `nivel_id: int | None`, `incidencia: bool`, `mensaje: str`. **Nunca lanza `ValidationError`.** Usado por `PedidosAlmacen/api_views.py` en las Tasks 9 y 10.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `ubicaciones/tests.py`:

```python
class DescontarPorPickingServiceTest(TestCase):
    def setUp(self):
        from PedidosAlmacen.models import Pedido, PedidoItem
        self.user = User.objects.create(username='descontar_picking')
        self.galpon = Galpon.objects.create(codigo='1', nombre='Galpón 1', creado_por=self.user)
        self.rack = Rack.objects.create(galpon=self.galpon, codigo='A', max_niveles=6, creado_por=self.user)
        self.cuerpo = Cuerpo.objects.create(rack=self.rack, codigo='01', creado_por=self.user)
        self.ubicacion = Ubicacion.objects.create(cuerpo=self.cuerpo, codigo='01', creado_por=self.user)
        self.nivel = Nivel.objects.create(
            ubicacion=self.ubicacion, numero=1, tipo=Nivel.PICKING, creado_por=self.user,
        )
        self.pu = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel, cantidad=50)
        self.pedido = Pedido.objects.create(solicitante=self.user)
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='ABC', descripcion='Producto ABC', cantidad_solicitada=30,
        )

    def test_sin_ubicacion_picking_no_hace_nada(self):
        item_sin_ubicacion = type(self.item).objects.create(
            pedido=self.pedido, codigo='SIN-UBICACION', descripcion='X', cantidad_solicitada=5,
        )
        resultado = UbicacionesService.descontar_por_picking(item_sin_ubicacion, 5, self.user)
        self.assertFalse(resultado['aplicado'])
        self.assertFalse(resultado['incidencia'])
        self.assertFalse(MovimientoUbicacion.objects.filter(tipo='PICKING').exists())

    def test_una_sola_ubicacion_descuenta_automatico(self):
        resultado = UbicacionesService.descontar_por_picking(self.item, 30, self.user)
        self.pu.refresh_from_db()
        self.assertEqual(self.pu.cantidad, 20)
        self.assertTrue(resultado['aplicado'])
        self.assertEqual(resultado['nivel_id'], self.nivel.pk)
        self.assertFalse(resultado['incidencia'])

    def test_una_sola_ubicacion_crea_movimiento_picking_activo(self):
        UbicacionesService.descontar_por_picking(self.item, 30, self.user)
        mov = MovimientoUbicacion.objects.get(tipo='PICKING', pedido_item=self.item)
        self.assertEqual(mov.cantidad, 30)
        self.assertTrue(mov.activo)
        self.assertFalse(mov.pendiente_revision)
        self.assertEqual(mov.nivel_origen_id, self.nivel.pk)

    def test_varias_ubicaciones_sin_indicar_no_descuenta_y_marca_incidencia(self):
        nivel2 = Nivel.objects.create(ubicacion=self.ubicacion, numero=2, tipo=Nivel.PICKING, creado_por=self.user)
        ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=nivel2, cantidad=20)

        resultado = UbicacionesService.descontar_por_picking(self.item, 30, self.user)

        self.pu.refresh_from_db()
        self.assertEqual(self.pu.cantidad, 50)  # sin tocar
        self.assertFalse(resultado['aplicado'])
        self.assertTrue(resultado['incidencia'])
        mov = MovimientoUbicacion.objects.get(tipo='PICKING', pedido_item=self.item)
        self.assertTrue(mov.pendiente_revision)
        self.assertFalse(mov.activo)
        self.assertEqual(mov.cantidad, 30)

    def test_varias_ubicaciones_con_nivel_id_valido_descuenta_esa(self):
        nivel2 = Nivel.objects.create(ubicacion=self.ubicacion, numero=2, tipo=Nivel.PICKING, creado_por=self.user)
        pu2 = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=nivel2, cantidad=20)

        resultado = UbicacionesService.descontar_por_picking(self.item, 15, self.user, nivel_id=nivel2.pk)

        pu2.refresh_from_db()
        self.pu.refresh_from_db()
        self.assertEqual(pu2.cantidad, 5)
        self.assertEqual(self.pu.cantidad, 50)  # la otra ubicación no se tocó
        self.assertTrue(resultado['aplicado'])
        self.assertEqual(resultado['nivel_id'], nivel2.pk)

    def test_faltante_de_stock_descuenta_a_cero_y_marca_incidencia(self):
        resultado = UbicacionesService.descontar_por_picking(self.item, 80, self.user)
        self.pu.refresh_from_db()
        self.assertEqual(self.pu.cantidad, 0)
        self.assertTrue(resultado['aplicado'])
        self.assertTrue(resultado['incidencia'])
        mov = MovimientoUbicacion.objects.get(tipo='PICKING', pedido_item=self.item)
        self.assertTrue(mov.pendiente_revision)
        self.assertTrue(mov.activo)  # sí quedó un descuento vigente (a 0), a diferencia del caso de ambigüedad
        self.assertEqual(mov.cantidad, 80)

    def test_reeditar_revierte_y_reaplica(self):
        UbicacionesService.descontar_por_picking(self.item, 30, self.user)
        self.pu.refresh_from_db()
        self.assertEqual(self.pu.cantidad, 20)

        UbicacionesService.descontar_por_picking(self.item, 15, self.user)
        self.pu.refresh_from_db()
        self.assertEqual(self.pu.cantidad, 35)  # 50 - 15
        self.assertEqual(
            MovimientoUbicacion.objects.filter(tipo='PICKING', pedido_item=self.item, activo=True).count(), 1,
        )

    def test_reeditar_a_cero_revierte_todo_sin_reaplicar(self):
        UbicacionesService.descontar_por_picking(self.item, 30, self.user)
        resultado = UbicacionesService.descontar_por_picking(self.item, 0, self.user)
        self.pu.refresh_from_db()
        self.assertEqual(self.pu.cantidad, 50)
        self.assertFalse(resultado['aplicado'])
        self.assertFalse(
            MovimientoUbicacion.objects.filter(tipo='PICKING', pedido_item=self.item, activo=True).exists(),
        )

    def test_reeditar_tras_incidencia_por_ambiguedad_no_revierte_nada_falso(self):
        nivel2 = Nivel.objects.create(ubicacion=self.ubicacion, numero=2, tipo=Nivel.PICKING, creado_por=self.user)
        ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=nivel2, cantidad=20)
        UbicacionesService.descontar_por_picking(self.item, 30, self.user)  # incidencia, sin descuento

        resultado = UbicacionesService.descontar_por_picking(self.item, 15, self.user, nivel_id=self.nivel.pk)

        self.pu.refresh_from_db()
        self.assertEqual(self.pu.cantidad, 35)  # 50 - 15, no se revirtió nada porque no había nada activo
        self.assertTrue(resultado['aplicado'])
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python manage.py test ubicaciones.tests.DescontarPorPickingServiceTest --settings=Programarprecios.test_settings`
Expected: `AttributeError: type object 'UbicacionesService' has no attribute 'descontar_por_picking'`

- [ ] **Step 3: Implementar**

Agregar al final de `ubicaciones/services.py`:

```python
    @staticmethod
    @transaction.atomic
    def descontar_por_picking(
        pedido_item, cantidad: int, usuario, nivel_id: int | None = None,
    ) -> dict:
        """Descuenta `cantidad` de la ubicación PICKING del producto de `pedido_item`.

        Reentrante: revierte el descuento vigente para este pedido_item (si lo
        hay) antes de aplicar el nuevo, así que puede llamarse cada vez que se
        guarda cantidad_preparada sin duplicar descuentos. Nunca lanza
        ValidationError: cualquier ambigüedad (varias ubicaciones sin indicar
        cuál) o faltante de stock queda registrado como incidencia
        (pendiente_revision=True) en vez de bloquear la operación.
        """
        codigo = pedido_item.codigo
        resultado = {'aplicado': False, 'nivel_id': None, 'incidencia': False, 'mensaje': ''}

        if nivel_id is not None:
            nivel_id = int(nivel_id)

        # Paso 1: revertir el descuento vigente para este ítem, si existe.
        anterior = (
            MovimientoUbicacion.objects
            .select_for_update()
            .filter(tipo='PICKING', pedido_item=pedido_item, activo=True)
            .first()
        )
        if anterior is not None:
            if anterior.nivel_origen_id is not None and anterior.cantidad:
                pu_anterior = (
                    ProductoUbicacion.objects
                    .select_for_update()
                    .filter(codigo_producto=codigo, nivel_id=anterior.nivel_origen_id)
                    .first()
                )
                if pu_anterior is None:
                    ProductoUbicacion.objects.create(
                        codigo_producto=codigo, nivel_id=anterior.nivel_origen_id, cantidad=anterior.cantidad,
                    )
                else:
                    pu_anterior.cantidad += anterior.cantidad
                    pu_anterior.save(update_fields=['cantidad'])
            anterior.activo = False
            anterior.save(update_fields=['activo'])

        if cantidad <= 0:
            return resultado

        # Paso 2: resolver la ubicación de origen.
        candidatos = list(
            ProductoUbicacion.objects
            .select_for_update()
            .filter(
                codigo_producto=codigo, nivel__tipo=Nivel.PICKING, nivel__activo=True,
                nivel__fusionado_en__isnull=True,
            )
            .select_related('nivel__ubicacion__cuerpo__rack__galpon')
        )

        if not candidatos:
            return resultado

        if len(candidatos) == 1:
            origen = candidatos[0]
        else:
            origen = next((pu for pu in candidatos if pu.nivel_id == nivel_id), None)
            if origen is None:
                MovimientoUbicacion.objects.create(
                    tipo='PICKING', pedido_item=pedido_item, codigo_producto=codigo,
                    cantidad=cantidad, pendiente_revision=True, activo=False, usuario=usuario,
                    notas='Ambigüedad: varias ubicaciones PICKING, ninguna indicada.',
                )
                resultado['incidencia'] = True
                resultado['mensaje'] = 'Varias ubicaciones PICKING; se registró incidencia sin descuento.'
                return resultado

        # Paso 3: aplicar el descuento.
        disponible = origen.cantidad
        incidencia = cantidad > disponible
        descuento = min(cantidad, disponible)
        origen.cantidad = disponible - descuento
        origen.save(update_fields=['cantidad'])

        MovimientoUbicacion.objects.create(
            tipo='PICKING', pedido_item=pedido_item, codigo_producto=codigo,
            nivel_origen=origen.nivel, cantidad=cantidad, activo=True,
            pendiente_revision=incidencia, usuario=usuario,
            galpon=origen.nivel.galpon, rack=origen.nivel.rack,
            notas='Faltante de stock en la ubicación.' if incidencia else '',
        )
        resultado.update(aplicado=True, nivel_id=origen.nivel_id, incidencia=incidencia)
        if incidencia:
            resultado['mensaje'] = f'Ubicación quedó en 0; faltaron {cantidad - disponible} unidades.'
        return resultado
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python manage.py test ubicaciones.tests.DescontarPorPickingServiceTest --settings=Programarprecios.test_settings`
Expected: PASS (las 9 pruebas)

- [ ] **Step 5: Correr toda la suite de `ubicaciones`**

Run: `python manage.py test ubicaciones --settings=Programarprecios.test_settings`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ubicaciones/services.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): agrega UbicacionesService.descontar_por_picking

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FVLAtuBuJc6pUP3VmUEL8g"
```

---

### Task 5: Servicio — `resolver_incidencia`

**Files:**
- Modify: `ubicaciones/services.py`
- Test: `ubicaciones/tests.py`

**Interfaces:**
- Consumes: `MovimientoUbicacion.{pendiente_revision,revisado_por,fecha_revision}` (Task 2).
- Produces: `UbicacionesService.resolver_incidencia(movimiento: MovimientoUbicacion, usuario, nota: str = '') -> MovimientoUbicacion`. Usado por `api_resolver_incidencia` (Task 8).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `ubicaciones/tests.py`:

```python
class ResolverIncidenciaServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='resolver_incidencia')
        self.mov = MovimientoUbicacion.objects.create(
            tipo='AJUSTE_A2', codigo_producto='ABC', cantidad=10, pendiente_revision=True,
        )

    def test_resolver_incidencia_limpia_pendiente_revision(self):
        UbicacionesService.resolver_incidencia(self.mov, self.user)
        self.mov.refresh_from_db()
        self.assertFalse(self.mov.pendiente_revision)
        self.assertEqual(self.mov.revisado_por, self.user)
        self.assertIsNotNone(self.mov.fecha_revision)

    def test_resolver_incidencia_agrega_nota(self):
        UbicacionesService.resolver_incidencia(self.mov, self.user, nota='Conteo físico confirmado')
        self.mov.refresh_from_db()
        self.assertIn('Conteo físico confirmado', self.mov.notas)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python manage.py test ubicaciones.tests.ResolverIncidenciaServiceTest --settings=Programarprecios.test_settings`
Expected: `AttributeError: type object 'UbicacionesService' has no attribute 'resolver_incidencia'`

- [ ] **Step 3: Implementar**

Agregar al final de `ubicaciones/services.py`:

```python
    @staticmethod
    @transaction.atomic
    def resolver_incidencia(movimiento: MovimientoUbicacion, usuario, nota: str = '') -> MovimientoUbicacion:
        movimiento.pendiente_revision = False
        movimiento.revisado_por = usuario
        movimiento.fecha_revision = timezone.now()
        if nota:
            movimiento.notas = f"{movimiento.notas}\n{nota}".strip()
        movimiento.save(update_fields=['pendiente_revision', 'revisado_por', 'fecha_revision', 'notas'])
        return movimiento
```

Agregar el import de `timezone` al principio de `ubicaciones/services.py` si no está:

```python
from django.utils import timezone
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python manage.py test ubicaciones.tests.ResolverIncidenciaServiceTest --settings=Programarprecios.test_settings`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ubicaciones/services.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): agrega UbicacionesService.resolver_incidencia

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FVLAtuBuJc6pUP3VmUEL8g"
```

---

### Task 6: Servicio — `ajustar_por_reconciliacion_a2`

**Files:**
- Modify: `ubicaciones/services.py`
- Test: `ubicaciones/tests.py`

**Interfaces:**
- Consumes: `ProductoUbicacion.es_principal` (Task 2/3).
- Produces: `UbicacionesService.ajustar_por_reconciliacion_a2(codigo_producto: str, existencia_a2: int, usuario=None) -> dict` con claves `faltante: int`, `ajustado: bool`, `nivel_id: int | None`. Usado por el comando de gestión (Task 7).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `ubicaciones/tests.py`:

```python
class AjustarPorReconciliacionA2ServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='ajuste_a2')
        self.galpon = Galpon.objects.create(codigo='1', nombre='Galpón 1', creado_por=self.user)
        self.rack = Rack.objects.create(galpon=self.galpon, codigo='A', max_niveles=6, creado_por=self.user)
        self.cuerpo = Cuerpo.objects.create(rack=self.rack, codigo='01', creado_por=self.user)
        self.ubicacion = Ubicacion.objects.create(cuerpo=self.cuerpo, codigo='01', creado_por=self.user)
        self.nivel1 = Nivel.objects.create(ubicacion=self.ubicacion, numero=1, creado_por=self.user)
        self.nivel2 = Nivel.objects.create(ubicacion=self.ubicacion, numero=2, creado_por=self.user)

    def test_sin_diferencia_no_hace_nada(self):
        ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel1, cantidad=30)
        resultado = UbicacionesService.ajustar_por_reconciliacion_a2('ABC', existencia_a2=50)
        self.assertEqual(resultado['faltante'], 0)
        self.assertFalse(resultado['ajustado'])
        self.assertFalse(MovimientoUbicacion.objects.filter(tipo='AJUSTE_A2').exists())

    def test_diferencia_positiva_no_hace_nada(self):
        # a2 tiene más de lo asignado: es stock sin ubicación, no es incidencia.
        ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel1, cantidad=30)
        resultado = UbicacionesService.ajustar_por_reconciliacion_a2('ABC', existencia_a2=30)
        self.assertEqual(resultado['faltante'], 0)
        self.assertFalse(MovimientoUbicacion.objects.filter(tipo='AJUSTE_A2').exists())

    def test_faltante_con_una_sola_ubicacion_ajusta_ahi(self):
        pu = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel1, cantidad=30)
        resultado = UbicacionesService.ajustar_por_reconciliacion_a2('ABC', existencia_a2=20, usuario=self.user)
        pu.refresh_from_db()
        self.assertEqual(pu.cantidad, 20)  # 30 - 10 de faltante
        self.assertEqual(resultado['faltante'], 10)
        self.assertTrue(resultado['ajustado'])
        self.assertEqual(resultado['nivel_id'], self.nivel1.pk)
        mov = MovimientoUbicacion.objects.get(tipo='AJUSTE_A2', codigo_producto='ABC')
        self.assertEqual(mov.cantidad, 10)
        self.assertTrue(mov.pendiente_revision)

    def test_faltante_clava_a_cero_si_supera_lo_disponible(self):
        pu = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel1, cantidad=5)
        UbicacionesService.ajustar_por_reconciliacion_a2('ABC', existencia_a2=-100)
        pu.refresh_from_db()
        self.assertEqual(pu.cantidad, 0)

    def test_faltante_con_varias_y_principal_marcada_ajusta_esa(self):
        pu1 = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel1, cantidad=30, es_principal=True)
        pu2 = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel2, cantidad=20)
        resultado = UbicacionesService.ajustar_por_reconciliacion_a2('ABC', existencia_a2=40)
        pu1.refresh_from_db()
        pu2.refresh_from_db()
        self.assertEqual(pu1.cantidad, 20)  # 30 - 10
        self.assertEqual(pu2.cantidad, 20)  # sin tocar
        self.assertTrue(resultado['ajustado'])
        self.assertEqual(resultado['nivel_id'], self.nivel1.pk)

    def test_faltante_con_varias_sin_principal_solo_incidencia(self):
        pu1 = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel1, cantidad=30)
        pu2 = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel2, cantidad=20)
        resultado = UbicacionesService.ajustar_por_reconciliacion_a2('ABC', existencia_a2=40)
        pu1.refresh_from_db()
        pu2.refresh_from_db()
        self.assertEqual(pu1.cantidad, 30)
        self.assertEqual(pu2.cantidad, 20)
        self.assertFalse(resultado['ajustado'])
        self.assertEqual(resultado['faltante'], 10)
        mov = MovimientoUbicacion.objects.get(tipo='AJUSTE_A2', codigo_producto='ABC')
        self.assertTrue(mov.pendiente_revision)
        self.assertIsNone(mov.nivel_destino)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python manage.py test ubicaciones.tests.AjustarPorReconciliacionA2ServiceTest --settings=Programarprecios.test_settings`
Expected: `AttributeError: type object 'UbicacionesService' has no attribute 'ajustar_por_reconciliacion_a2'`

- [ ] **Step 3: Implementar**

Agregar al final de `ubicaciones/services.py`:

```python
    @staticmethod
    @transaction.atomic
    def ajustar_por_reconciliacion_a2(codigo_producto: str, existencia_a2: int, usuario=None) -> dict:
        """Compara la existencia real en a2 contra lo asignado por ubicación
        para un producto y, si a2 quedó por debajo (salida externa), ajusta
        la ubicación resuelta sin ambigüedad y registra la incidencia.
        No lanza excepciones."""
        asignaciones = list(
            ProductoUbicacion.objects
            .select_for_update()
            .filter(codigo_producto=codigo_producto)
            .select_related('nivel__ubicacion__cuerpo__rack__galpon')
        )
        resultado = {'faltante': 0, 'ajustado': False, 'nivel_id': None}
        if not asignaciones:
            return resultado

        suma = sum(pu.cantidad for pu in asignaciones)
        if existencia_a2 >= suma:
            return resultado

        faltante = suma - existencia_a2
        resultado['faltante'] = faltante

        if len(asignaciones) == 1:
            origen = asignaciones[0]
        else:
            origen = next((pu for pu in asignaciones if pu.es_principal), None)

        if origen is not None:
            disponible = origen.cantidad
            descuento = min(faltante, disponible)
            origen.cantidad = disponible - descuento
            origen.save(update_fields=['cantidad'])
            resultado['ajustado'] = True
            resultado['nivel_id'] = origen.nivel_id

        MovimientoUbicacion.objects.create(
            tipo='AJUSTE_A2', codigo_producto=codigo_producto, cantidad=faltante,
            pendiente_revision=True, activo=False, usuario=usuario,
            nivel_destino=origen.nivel if origen else None,
            galpon=origen.nivel.galpon if origen else None,
            rack=origen.nivel.rack if origen else None,
            notas=(
                'Salida externa detectada por reconciliación con a2.' if origen else
                'Salida externa detectada; ambigüedad de ubicación, requiere resolución manual.'
            ),
        )
        return resultado
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python manage.py test ubicaciones.tests.AjustarPorReconciliacionA2ServiceTest --settings=Programarprecios.test_settings`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ubicaciones/services.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): agrega UbicacionesService.ajustar_por_reconciliacion_a2

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FVLAtuBuJc6pUP3VmUEL8g"
```

---

### Task 7: Comando de gestión `reconciliar_existencias`

**Files:**
- Create: `ubicaciones/management/commands/reconciliar_existencias.py`
- Test: `ubicaciones/tests.py`

**Interfaces:**
- Consumes: `UbicacionesService.ajustar_por_reconciliacion_a2` (Task 6); `PedidosDBISAM.consultar_stock_multiple` (ya existente en `PedidosAlmacen/dbisam.py`); `DEPOSITO_ALMACEN` (ya existente).
- Produces: comando `python manage.py reconciliar_existencias`, ejecutado por el Task Scheduler de Windows (fuera del alcance de este plan configurarlo, solo se entrega el comando).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `ubicaciones/tests.py`:

```python
class ReconciliarExistenciasCommandTest(TestCase):
    def setUp(self):
        from django.core.management import call_command
        self.call_command = call_command
        self.user = User.objects.create(username='reconciliar_cmd')
        self.galpon = Galpon.objects.create(codigo='1', nombre='Galpón 1', creado_por=self.user)
        self.rack = Rack.objects.create(galpon=self.galpon, codigo='A', max_niveles=6, creado_por=self.user)
        self.cuerpo = Cuerpo.objects.create(rack=self.rack, codigo='01', creado_por=self.user)
        self.ubicacion = Ubicacion.objects.create(cuerpo=self.cuerpo, codigo='01', creado_por=self.user)
        self.nivel = Nivel.objects.create(ubicacion=self.ubicacion, numero=1, creado_por=self.user)

    def test_sin_asignaciones_no_consulta_dbisam(self):
        with patch('ubicaciones.management.commands.reconciliar_existencias.PedidosDBISAM') as mock_db:
            self.call_command('reconciliar_existencias')
            mock_db.return_value.consultar_stock_multiple.assert_not_called()

    def test_sin_diferencia_no_ajusta(self):
        pu = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel, cantidad=30)
        with patch('ubicaciones.management.commands.reconciliar_existencias.PedidosDBISAM') as mock_db:
            mock_db.return_value.consultar_stock_multiple.return_value = {'ABC': 30}
            self.call_command('reconciliar_existencias')
        pu.refresh_from_db()
        self.assertEqual(pu.cantidad, 30)
        self.assertFalse(MovimientoUbicacion.objects.filter(tipo='AJUSTE_A2').exists())

    def test_diferencia_con_una_ubicacion_ajusta(self):
        pu = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel, cantidad=30)
        with patch('ubicaciones.management.commands.reconciliar_existencias.PedidosDBISAM') as mock_db:
            mock_db.return_value.consultar_stock_multiple.return_value = {'ABC': 20}
            self.call_command('reconciliar_existencias')
        pu.refresh_from_db()
        self.assertEqual(pu.cantidad, 20)
        self.assertTrue(MovimientoUbicacion.objects.filter(tipo='AJUSTE_A2', codigo_producto='ABC').exists())

    def test_producto_no_devuelto_por_dbisam_se_trata_como_cero(self):
        pu = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel, cantidad=10)
        with patch('ubicaciones.management.commands.reconciliar_existencias.PedidosDBISAM') as mock_db:
            mock_db.return_value.consultar_stock_multiple.return_value = {}
            self.call_command('reconciliar_existencias')
        pu.refresh_from_db()
        self.assertEqual(pu.cantidad, 0)

    def test_error_dbisam_no_modifica_postgres(self):
        pu = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel, cantidad=30)
        with patch('ubicaciones.management.commands.reconciliar_existencias.PedidosDBISAM') as mock_db:
            mock_db.return_value.consultar_stock_multiple.side_effect = Exception('odbc down')
            self.call_command('reconciliar_existencias')
        pu.refresh_from_db()
        self.assertEqual(pu.cantidad, 30)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python manage.py test ubicaciones.tests.ReconciliarExistenciasCommandTest --settings=Programarprecios.test_settings`
Expected: `Unknown command: 'reconciliar_existencias'`

- [ ] **Step 3: Implementar el comando**

Crear `ubicaciones/management/commands/reconciliar_existencias.py`:

```python
"""
Management command que reconcilia la existencia por ubicación (Postgres)
contra el total real en a2 (SINVDEP, depósito almacén).

Escribe en Postgres (a diferencia de validar_traslados_recepcion, que es
de solo lectura): cuando a2 queda por debajo de lo asignado por ubicación,
ajusta la ubicación que se puede resolver sin ambigüedad (una sola
asignación, o la marcada es_principal si hay varias) y registra el
faltante como incidencia pendiente_revision. Si hay varias ubicaciones y
ninguna es principal, no ajusta nada — solo deja la incidencia para que
un supervisor la resuelva a mano.

Diseñado para ejecutarse periódicamente vía el Task Scheduler de Windows,
igual que validar_traslados_recepcion.

Uso:
    python manage.py reconciliar_existencias
"""

from django.core.management.base import BaseCommand

from PedidosAlmacen.dbisam import DEPOSITO_ALMACEN, PedidosDBISAM
from ubicaciones.models import ProductoUbicacion
from ubicaciones.services import UbicacionesService


class Command(BaseCommand):
    help = (
        "Reconcilia la existencia por ubicación contra el total real en a2. "
        "Ajusta automáticamente cuando puede resolver sin ambigüedad la "
        "ubicación afectada; si no, solo registra la incidencia."
    )

    def handle(self, *args, **options) -> None:
        codigos = list(
            ProductoUbicacion.objects.values_list('codigo_producto', flat=True).distinct()
        )
        if not codigos:
            self.stdout.write(self.style.WARNING('No hay productos con ubicación asignada.'))
            return

        try:
            existencias = PedidosDBISAM().consultar_stock_multiple(codigos, deposito=DEPOSITO_ALMACEN)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'Error al consultar a2: {e}'))
            return

        ajustados, sin_resolver = 0, 0
        for codigo in codigos:
            resultado = UbicacionesService.ajustar_por_reconciliacion_a2(
                codigo, existencias.get(codigo, 0),
            )
            if resultado['faltante'] <= 0:
                continue
            if resultado['ajustado']:
                ajustados += 1
                self.stdout.write(self.style.WARNING(
                    f"{codigo}: faltante {resultado['faltante']} — ajustado en nivel {resultado['nivel_id']}"
                ))
            else:
                sin_resolver += 1
                self.stdout.write(self.style.ERROR(
                    f"{codigo}: faltante {resultado['faltante']} — ambigüedad, requiere revisión manual"
                ))

        self.stdout.write('')
        self.stdout.write(f'Productos revisados: {len(codigos)}')
        self.stdout.write(f'Ajustados automáticamente: {ajustados}')
        self.stdout.write(f'Con incidencia sin resolver: {sin_resolver}')
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python manage.py test ubicaciones.tests.ReconciliarExistenciasCommandTest --settings=Programarprecios.test_settings`
Expected: PASS (5 pruebas)

- [ ] **Step 5: Correr toda la suite de `ubicaciones`**

Run: `python manage.py test ubicaciones --settings=Programarprecios.test_settings`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ubicaciones/management/commands/reconciliar_existencias.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): agrega comando reconciliar_existencias

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FVLAtuBuJc6pUP3VmUEL8g"
```

---

### Task 8: API — incidencias y marcar-principal

**Files:**
- Modify: `ubicaciones/serializers.py`
- Modify: `ubicaciones/api_views.py`
- Modify: `ubicaciones/api_urls.py`
- Test: `ubicaciones/tests.py`

**Interfaces:**
- Consumes: `UbicacionesService.resolver_incidencia` (Task 5), `UbicacionesService.marcar_principal` (Task 3).
- Produces: `GET /api/ubicaciones/incidencias/`, `POST /api/ubicaciones/movimientos/<pk>/resolver/`, `POST /api/producto-ubicaciones/<pk>/marcar-principal/`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `ubicaciones/tests.py`, dentro de `ApiUbicacionesTest` (o como clase nueva — se agrega como clase nueva para no tocar el `setUp` existente):

```python
class ApiIncidenciasTest(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        self.user = User.objects.create_superuser(username='api_incidencias', password='x')
        self.api = APIClient()
        self.api.force_authenticate(user=self.user)
        self.galpon = Galpon.objects.create(codigo='1', nombre='Galpón 1', creado_por=self.user)
        self.rack = Rack.objects.create(galpon=self.galpon, codigo='A', max_niveles=6, creado_por=self.user)
        self.cuerpo = Cuerpo.objects.create(rack=self.rack, codigo='01', creado_por=self.user)
        self.ubicacion = Ubicacion.objects.create(cuerpo=self.cuerpo, codigo='01', creado_por=self.user)
        self.nivel = Nivel.objects.create(ubicacion=self.ubicacion, numero=1, creado_por=self.user)

    def test_listar_incidencias_solo_pendientes(self):
        MovimientoUbicacion.objects.create(
            tipo='AJUSTE_A2', codigo_producto='ABC', cantidad=5, pendiente_revision=True,
        )
        MovimientoUbicacion.objects.create(
            tipo='AJUSTE_A2', codigo_producto='XYZ', cantidad=3, pendiente_revision=False,
        )
        resp = self.api.get('/api/ubicaciones/incidencias/')
        self.assertEqual(resp.status_code, 200)
        codigos = [m['codigo_producto'] for m in resp.data]
        self.assertIn('ABC', codigos)
        self.assertNotIn('XYZ', codigos)

    def test_listar_incidencias_filtra_por_codigo(self):
        MovimientoUbicacion.objects.create(
            tipo='PICKING', codigo_producto='ABC', cantidad=5, pendiente_revision=True,
        )
        MovimientoUbicacion.objects.create(
            tipo='PICKING', codigo_producto='XYZ', cantidad=3, pendiente_revision=True,
        )
        resp = self.api.get('/api/ubicaciones/incidencias/', {'codigo': 'ABC'})
        codigos = [m['codigo_producto'] for m in resp.data]
        self.assertEqual(codigos, ['ABC'])

    def test_resolver_incidencia_via_api(self):
        mov = MovimientoUbicacion.objects.create(
            tipo='AJUSTE_A2', codigo_producto='ABC', cantidad=5, pendiente_revision=True,
        )
        resp = self.api.post(f'/api/ubicaciones/movimientos/{mov.pk}/resolver/', data={'nota': 'ok'}, format='json')
        self.assertEqual(resp.status_code, 200)
        mov.refresh_from_db()
        self.assertFalse(mov.pendiente_revision)
        self.assertEqual(mov.revisado_por, self.user)

    def test_marcar_principal_via_api(self):
        pu1 = ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel, cantidad=10)
        resp = self.api.post(f'/api/producto-ubicaciones/{pu1.pk}/marcar-principal/')
        self.assertEqual(resp.status_code, 200)
        pu1.refresh_from_db()
        self.assertTrue(pu1.es_principal)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python manage.py test ubicaciones.tests.ApiIncidenciasTest --settings=Programarprecios.test_settings`
Expected: 404 en las 4 pruebas (las rutas no existen todavía)

- [ ] **Step 3: Extender los serializers**

En `ubicaciones/serializers.py`, `ProductoUbicacionSerializer`:

```python
class ProductoUbicacionSerializer(serializers.ModelSerializer):
    nivel_codigo = serializers.CharField(source='nivel.codigo_completo', read_only=True)
    tipo_nivel = serializers.CharField(source='nivel.tipo', read_only=True)

    class Meta:
        model = ProductoUbicacion
        fields = [
            'id', 'codigo_producto', 'nivel', 'nivel_codigo', 'tipo_nivel',
            'cantidad', 'stock_minimo', 'es_principal',
        ]
```

`MovimientoSerializer`:

```python
class MovimientoSerializer(serializers.ModelSerializer):
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    usuario_nombre = serializers.SerializerMethodField()
    rack_codigo = serializers.CharField(source='rack.codigo', read_only=True, default=None)
    nivel_origen_str = serializers.CharField(source='nivel_origen.codigo_completo', read_only=True, default=None)
    nivel_destino_str = serializers.CharField(source='nivel_destino.codigo_completo', read_only=True, default=None)
    revisado_por_nombre = serializers.SerializerMethodField()

    class Meta:
        model = MovimientoUbicacion
        fields = [
            'id', 'tipo', 'tipo_display', 'rack_codigo',
            'nivel_origen_str', 'nivel_destino_str',
            'codigo_producto', 'cantidad', 'pendiente_revision',
            'revisado_por_nombre', 'fecha_revision',
            'usuario_nombre', 'fecha', 'notas',
        ]

    def get_usuario_nombre(self, obj) -> str:
        return obj.usuario.username if obj.usuario else ''

    def get_revisado_por_nombre(self, obj) -> str:
        return obj.revisado_por.username if obj.revisado_por else ''
```

- [ ] **Step 4: Agregar las vistas**

En `ubicaciones/api_views.py`, agregar al final (después de `api_producto_ubicaciones`):

```python
@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_incidencias_list(request):
    qs = MovimientoUbicacion.objects.filter(pendiente_revision=True).select_related('usuario', 'rack')
    codigo = request.query_params.get('codigo')
    tipo = request.query_params.get('tipo')
    if codigo:
        qs = qs.filter(codigo_producto__icontains=codigo)
    if tipo:
        qs = qs.filter(tipo=tipo)
    return Response(MovimientoSerializer(qs.order_by('-fecha')[:200], many=True).data)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_resolver_incidencia(request, pk: int):
    try:
        movimiento = MovimientoUbicacion.objects.get(pk=pk)
    except MovimientoUbicacion.DoesNotExist:
        return Response({'error': 'Movimiento no encontrado.'}, status=404)
    nota = request.data.get('nota', '')
    UbicacionesService.resolver_incidencia(movimiento, request.user, nota)
    return Response(MovimientoSerializer(movimiento).data)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_marcar_principal(request, pk: int):
    try:
        pu = ProductoUbicacion.objects.get(pk=pk)
    except ProductoUbicacion.DoesNotExist:
        return Response({'error': 'Asignación no encontrada.'}, status=404)
    UbicacionesService.marcar_principal(pu, request.user)
    return Response(ProductoUbicacionSerializer(pu).data)
```

- [ ] **Step 5: Agregar las rutas**

En `ubicaciones/api_urls.py`, agregar antes del cierre de la lista `urlpatterns`:

```python
    path('ubicaciones/incidencias/', api_views.api_incidencias_list, name='api-ubicaciones-incidencias'),
    path('ubicaciones/movimientos/<int:pk>/resolver/', api_views.api_resolver_incidencia, name='api-movimiento-resolver'),
    path('producto-ubicaciones/<int:pk>/marcar-principal/', api_views.api_marcar_principal, name='api-pu-marcar-principal'),
```

- [ ] **Step 6: Correr y verificar que pasa**

Run: `python manage.py test ubicaciones.tests.ApiIncidenciasTest --settings=Programarprecios.test_settings`
Expected: PASS (4 pruebas)

- [ ] **Step 7: Correr toda la suite de `ubicaciones`**

Run: `python manage.py test ubicaciones --settings=Programarprecios.test_settings`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add ubicaciones/serializers.py ubicaciones/api_views.py ubicaciones/api_urls.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): agrega API de incidencias y marcar-principal

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FVLAtuBuJc6pUP3VmUEL8g"
```

---

### Task 9: Integración — `api_update_item` descuenta la ubicación de picking

**Files:**
- Modify: `PedidosAlmacen/api_views.py:78-86`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `UbicacionesService.descontar_por_picking` (Task 4).
- Produces: `PATCH /api/pedidos/<pedido_pk>/items/<item_pk>/` acepta el campo opcional `ubicacion_picking` (nivel_id) en el body, y la respuesta gana la clave `ubicacion_picking` con el dict de resultado cuando se guardó `cantidad_preparada`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `PedidosAlmacen/tests.py`:

```python
class ApiUpdateItemDescuentaUbicacionTest(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        from users.models import User
        from .models import Pedido, PedidoItem
        from ubicaciones.models import Cuerpo, Galpon, Nivel, ProductoUbicacion, Rack, Ubicacion

        self.user = User.objects.create_superuser(username='api_item_ubic', password='x')
        self.api = APIClient()
        self.api.force_authenticate(user=self.user)

        self.pedido = Pedido.objects.create(solicitante=self.user, estado='PICKING')
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='Producto Uno',
            cantidad_solicitada=10, estado='PENDIENTE',
        )

        galpon = Galpon.objects.create(codigo='1', nombre='Galpón 1', creado_por=self.user)
        rack = Rack.objects.create(galpon=galpon, codigo='A', max_niveles=6, creado_por=self.user)
        cuerpo = Cuerpo.objects.create(rack=rack, codigo='01', creado_por=self.user)
        ubicacion = Ubicacion.objects.create(cuerpo=cuerpo, codigo='01', creado_por=self.user)
        self.nivel = Nivel.objects.create(ubicacion=ubicacion, numero=1, tipo=Nivel.PICKING, creado_por=self.user)
        self.pu = ProductoUbicacion.objects.create(codigo_producto='SKU1', nivel=self.nivel, cantidad=50)

        self.url = f'/api/pedidos/{self.pedido.numero_pedido}/items/{self.item.id}/'

    def test_guardar_cantidad_descuenta_ubicacion(self):
        resp = self.api.patch(self.url, data={'cantidad_preparada': 6}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('ubicacion_picking', resp.data)
        self.assertTrue(resp.data['ubicacion_picking']['aplicado'])
        self.pu.refresh_from_db()
        self.assertEqual(self.pu.cantidad, 44)

    def test_reeditar_no_duplica_el_descuento(self):
        self.api.patch(self.url, data={'cantidad_preparada': 6}, format='json')
        self.api.patch(self.url, data={'cantidad_preparada': 4}, format='json')
        self.pu.refresh_from_db()
        self.assertEqual(self.pu.cantidad, 46)  # 50 - 4, no 50 - 6 - 4

    def test_producto_sin_ubicacion_guarda_igual(self):
        from .models import PedidoItem
        item_sin_ubicacion = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SIN-UBIC', descripcion='Otro', cantidad_solicitada=5, estado='PENDIENTE',
        )
        url = f'/api/pedidos/{self.pedido.numero_pedido}/items/{item_sin_ubicacion.id}/'
        resp = self.api.patch(url, data={'cantidad_preparada': 5}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['ubicacion_picking']['aplicado'])
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.ApiUpdateItemDescuentaUbicacionTest --settings=Programarprecios.test_settings`
Expected: `AssertionError` — `'ubicacion_picking' not found in resp.data` (todavía no se llama al servicio)

- [ ] **Step 3: Implementar**

En `PedidosAlmacen/api_views.py`, reemplazar `api_update_item`:

```python
@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def api_update_item(request, pedido_pk, item_pk):
    item = get_object_or_404(PedidoItem, id=item_pk, pedido__numero_pedido=pedido_pk)
    cantidad = request.data.get('cantidad_preparada')
    resultado_ubicacion = None
    if cantidad is not None:
        item.cantidad_preparada = int(cantidad)
        item.save(update_fields=['cantidad_preparada'])
        from ubicaciones.services import UbicacionesService
        resultado_ubicacion = UbicacionesService.descontar_por_picking(
            item, int(cantidad), request.user, nivel_id=request.data.get('ubicacion_picking'),
        )
    data = PedidoItemSerializer(item).data
    if resultado_ubicacion is not None:
        data['ubicacion_picking'] = resultado_ubicacion
    return Response(data)
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.ApiUpdateItemDescuentaUbicacionTest --settings=Programarprecios.test_settings`
Expected: PASS (3 pruebas)

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/api_views.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): api_update_item descuenta la ubicacion de picking

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FVLAtuBuJc6pUP3VmUEL8g"
```

---

### Task 10: Integración — `api_preparar_pedido` (acción `finalizar`) descuenta por ítem

**Files:**
- Modify: `PedidosAlmacen/api_views.py:152-163`
- Test: `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `UbicacionesService.descontar_por_picking` (Task 4).
- Produces: `POST /api/pedidos/<pk>/preparar/` con `accion=finalizar` acepta el campo opcional `ubicaciones_picking` (dict `{item_id: nivel_id}`) junto a `cantidades`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `PedidosAlmacen/tests.py`:

```python
class ApiPrepararPedidoFinalizarDescuentaUbicacionTest(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient
        from users.models import User
        from .models import Pedido, PedidoItem
        from ubicaciones.models import Cuerpo, Galpon, Nivel, ProductoUbicacion, Rack, Ubicacion

        self.user = User.objects.create_superuser(username='api_finalizar_ubic', password='x')
        self.api = APIClient()
        self.api.force_authenticate(user=self.user)

        self.pedido = Pedido.objects.create(
            solicitante=self.user, picker=self.user, estado='PICKING',
        )
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='Producto Uno',
            cantidad_solicitada=10, estado='PENDIENTE',
        )

        galpon = Galpon.objects.create(codigo='1', nombre='Galpón 1', creado_por=self.user)
        rack = Rack.objects.create(galpon=galpon, codigo='A', max_niveles=6, creado_por=self.user)
        cuerpo = Cuerpo.objects.create(rack=rack, codigo='01', creado_por=self.user)
        ubicacion = Ubicacion.objects.create(cuerpo=cuerpo, codigo='01', creado_por=self.user)
        self.nivel = Nivel.objects.create(ubicacion=ubicacion, numero=1, tipo=Nivel.PICKING, creado_por=self.user)
        self.pu = ProductoUbicacion.objects.create(codigo_producto='SKU1', nivel=self.nivel, cantidad=50)

        self.url = f'/api/pedidos/{self.pedido.numero_pedido}/preparar/'

    def test_finalizar_descuenta_ubicacion_por_item(self):
        resp = self.api.post(
            self.url,
            data={'accion': 'finalizar', 'cantidades': {str(self.item.id): 7}},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.pu.refresh_from_db()
        self.assertEqual(self.pu.cantidad, 43)

    def test_finalizar_usa_ubicacion_indicada_cuando_hay_varias(self):
        from ubicaciones.models import Nivel, ProductoUbicacion
        nivel2 = Nivel.objects.create(
            ubicacion=self.nivel.ubicacion, numero=2, tipo=Nivel.PICKING, creado_por=self.user,
        )
        pu2 = ProductoUbicacion.objects.create(codigo_producto='SKU1', nivel=nivel2, cantidad=20)

        resp = self.api.post(
            self.url,
            data={
                'accion': 'finalizar',
                'cantidades': {str(self.item.id): 7},
                'ubicaciones_picking': {str(self.item.id): nivel2.pk},
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        pu2.refresh_from_db()
        self.pu.refresh_from_db()
        self.assertEqual(pu2.cantidad, 13)
        self.assertEqual(self.pu.cantidad, 50)  # sin tocar
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python manage.py test PedidosAlmacen.tests.ApiPrepararPedidoFinalizarDescuentaUbicacionTest --settings=Programarprecios.test_settings`
Expected: `AssertionError: 50 != 43` (todavía no se llama al servicio)

- [ ] **Step 3: Implementar**

En `PedidosAlmacen/api_views.py`, dentro de `api_preparar_pedido`, reemplazar la rama `elif accion == 'finalizar':`:

```python
    elif accion == 'finalizar':
        from ubicaciones.services import UbicacionesService
        cantidades = request.data.get('cantidades', {})
        ubicaciones_por_item = request.data.get('ubicaciones_picking', {})
        items = pedido.items.filter(estado__in=['PENDIENTE', 'BACK_ORDER', 'PARCIAL'])
        for item in items:
            cantidad = cantidades.get(str(item.id))
            if cantidad is not None:
                item.cantidad_preparada = int(cantidad)
                item.save(update_fields=['cantidad_preparada'])
                UbicacionesService.descontar_por_picking(
                    item, int(cantidad), request.user,
                    nivel_id=ubicaciones_por_item.get(str(item.id)),
                )
        if pedido.estado == 'PICKING':
            pedido.fecha_fin_picking = timezone.now()
        pedido.estado = 'EN_PREPARACION'
        pedido.save(update_fields=['estado', 'fecha_fin_picking'])
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python manage.py test PedidosAlmacen.tests.ApiPrepararPedidoFinalizarDescuentaUbicacionTest --settings=Programarprecios.test_settings`
Expected: PASS (2 pruebas)

- [ ] **Step 5: Correr toda la suite de `PedidosAlmacen` y `ubicaciones`**

Run: `python manage.py test PedidosAlmacen ubicaciones --settings=Programarprecios.test_settings`
Expected: PASS (nada roto por la integración — presta atención especial a `TimestampsPickingTest.test_api_finalizar_setea_fin`, que ejercita la misma rama de código y no debe verse afectada)

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/api_views.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): api_preparar_pedido finalizar descuenta ubicacion por item

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FVLAtuBuJc6pUP3VmUEL8g"
```

---

### Task 11: Limpieza final — eliminar el spec descartado y verificación completa

**Files:**
- Delete: `docs/superpowers/specs/2026-09-02-existencia-por-ubicacion-picking-design.md`

**Interfaces:**
- Consumes: nada (tarea de cierre).
- Produces: nada nuevo — verifica que todo el trabajo de las Tasks 1-10 queda consistente.

- [ ] **Step 1: Eliminar el spec descartado**

```bash
git rm docs/superpowers/specs/2026-09-02-existencia-por-ubicacion-picking-design.md
```

- [ ] **Step 2: Correr toda la suite del proyecto una última vez**

Run: `python manage.py test PedidosAlmacen ubicaciones --settings=Programarprecios.test_settings`
Expected: PASS, 0 errores, 0 fallos

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore(ubicaciones): elimina spec descartado 2026-09-02

El spec de integracion de existencia con a2 (2026-09-03) reemplaza por
completo el diseno anterior de picking (PickingOrigen/ExistenciaSinUbicacion),
ya implementado con las decisiones nuevas: nunca bloquear el flujo de
pedidos, multiples ubicaciones PICKING/ALMACENAJE por SKU, y job de
reconciliacion periodica con a2.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FVLAtuBuJc6pUP3VmUEL8g
EOF
)"
```

---

## Self-Review

**1. Spec coverage:**
- Principios (nunca bloquea, varias ubicaciones sin 1:1) → Task 4 (`descontar_por_picking` nunca lanza excepción) y Task 6 (`ajustar_por_reconciliacion_a2` idem). ✓
- Modelo (`es_principal`, campos de `MovimientoUbicacion`, tipos `PICKING`/`AJUSTE_A2`) → Task 2. ✓
- Servicio `descontar_por_picking` reentrante, con los 3 casos (0/1/varias ubicaciones) y faltante de stock → Task 4. ✓
- Integración `PedidosAlmacen` (`api_update_item`, `api_preparar_pedido`) → Tasks 9 y 10. ✓
- No disparo al limpiar `cantidad_preparada` en despacho → cubierto por diseño: solo se llama a `descontar_por_picking` desde los dos puntos de entrada de las Tasks 9/10, nunca desde `api_crear_despacho` (no se toca ese archivo/función en este plan). ✓
- Reconciliación con a2 (comando, cascada única/es_principal/ninguna) → Tasks 6 y 7. ✓
- API (incidencias, resolver, marcar-principal) → Task 8. ✓
- Manejo de errores (tabla del spec) → cada fila tiene un test dedicado: producto sin ubicación (Task 4 test 1), varias sin indicar (Task 4 test 4), faltante de stock (Task 4 test 6), reedición (Task 4 tests 7-8), DBISAM caído en el comando (Task 7 test 5), despacho anulado no revierte (no se toca ese código — comportamiento por omisión, documentado en el spec como limitación aceptada, no requiere test nuevo). ✓
- Testing (spec sección final) → cada bullet del spec tiene tarea/tests correspondientes. ✓
- Nota de reemplazo (eliminar spec 2026-09-02 y sus tests) → Tasks 1 y 11. ✓

**2. Placeholder scan:** sin TBD/TODO; todos los pasos incluyen código completo, no descripciones vagas.

**3. Type consistency:** `descontar_por_picking(pedido_item, cantidad: int, usuario, nivel_id: int | None = None) -> dict` se usa igual en Tasks 4, 9 y 10. `ajustar_por_reconciliacion_a2(codigo_producto: str, existencia_a2: int, usuario=None) -> dict` igual en Tasks 6 y 7. Claves del dict de resultado (`aplicado`, `nivel_id`, `incidencia`, `mensaje` / `faltante`, `ajustado`, `nivel_id`) se usan consistentemente en todos los tests que las consumen. Campo de payload `ubicacion_picking` (singular, Task 9) vs. `ubicaciones_picking` (plural, dict por item, Task 10) — intencionalmente distintos porque uno es un solo ítem y el otro es un batch; documentado en cada tarea.
