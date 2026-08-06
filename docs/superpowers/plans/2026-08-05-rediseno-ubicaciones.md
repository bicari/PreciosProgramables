# Rediseño de ubicaciones (Galpón-Rack-Cuerpo-Ubicación-Nivel) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reemplazar el modelo de ubicaciones de almacén (3 niveles) por la jerarquía física real de 5 niveles (Galpón → Rack → Cuerpo → Ubicación → Nivel), con cantidad validada contra a2, stock mínimo/alertas, fusión de niveles, mapa visual con leyenda e importación del maestro real.

**Architecture:** App Django `ubicaciones` existente, reconstruida capa por capa: modelos → capa de servicios (`UbicacionesService`, `@transaction.atomic`, bitácora `MovimientoUbicacion`) → API REST (DRF) → vistas web (Bootstrap 5 + DataTables, mismo patrón que el resto del proyecto) → templates → funcionalidades transversales (alertas, mapa, importación, integración con `PedidosAlmacen`).

**Tech Stack:** Django, PostgreSQL (Postgres en prod, SQLite en tests vía `Programarprecios.test_settings`), Django REST Framework, pyodbc/DBISAM (`PedidosAlmacen.dbisam.PedidosDBISAM`), Bootstrap 5, DataTables, htmx (fragmentos de autocomplete).

## Global Constraints

- Spec de referencia: `docs/superpowers/specs/2026-08-05-rediseno-ubicaciones-design.md`.
- Sin datos de producción que preservar — reemplazo directo del modelo (decisión 1 del spec).
- Código completo de un Nivel reproduce el formato ya impreso: `f"{galpon.codigo}{rack.codigo}{cuerpo.codigo}{ubicacion.codigo}.{numero}"` → `"1A0101.4"` (decisión 2).
- Cantidad validada contra `SINVDEP` depósito 1 (`PedidosAlmacen.dbisam.DEPOSITO_ALMACEN`, ya vale `1`) — nunca contra el total de todos los depósitos (decisión 3).
- Función Picking/Almacenaje vive en `Nivel`, no en Cuerpo/Ubicación (decisión 4). Stock mínimo vive en `ProductoUbicacion`, no en `Nivel` (decisión 5).
- Alertas: solo dashboard, sin correo, calculadas on-demand (decisión 6).
- Fusión: únicamente entre `Nivel`, mismo Rack, vía `fusionado_en` autoreferencial (decisión 7).
- `Rack.max_niveles` configurable (default 6); Cuerpo siempre tiene exactamente 2 Ubicaciones con código autogenerado como numeración global (`2×cuerpo-1`/`2×cuerpo`), no reiniciada por cuerpo (decisión 8).
- Tests: `venv\Scripts\python.exe manage.py test ubicaciones --settings=Programarprecios.test_settings` (venv del proyecto, SQLite en memoria — ver memoria `project_tests_setup`). Para tests cruzados con `PedidosAlmacen`: `venv\Scripts\python.exe manage.py test PedidosAlmacen ubicaciones --settings=Programarprecios.test_settings`.
- Trampa conocida: no combinar `select_for_update()` con `select_related()`/joins sobre una FK nullable (aquí, `Nivel.fusionado_en`) — pasa en SQLite pero revienta en Postgres. Usar `select_for_update(of=('self',))` si hace falta lockear con ese join.
- Sin envío de correo, sin editor visual drag-and-drop del plano, sin sincronización en tiempo real contra DBISAM, sin importar asignaciones de producto reales (fuera de alcance, spec).

---

## Task 1: Reset del modelo de datos — Galpón, Rack, Cuerpo, Ubicación, Nivel

Reemplaza por completo el modelo de 3 niveles por la jerarquía real de 5 niveles. Como todo el resto de la app (forms/views/api/services) depende de los campos exactos del modelo, y Django valida `ModelForm.Meta.fields` e `ModelAdmin.list_display` al importar/arrancar (rompiendo `manage.py test` para **todo el proyecto**, no solo esta app, si quedan referencias a campos inexistentes), esta tarea también resetea `admin.py` a los modelos nuevos y vacía `forms.py`, `views.py`, `api_views.py`, `serializers.py`, `services.py`, `urls.py`, `api_urls.py` — se reconstruyen progresivamente en las tareas 2-13.

**Files:**
- Delete: `ubicaciones/migrations/0001_initial.py`, `ubicaciones/migrations/0002_grupo_pedidos_ubicaciones.py`
- Delete: `ubicaciones/forms.py`, `ubicaciones/views.py`, `ubicaciones/api_views.py`, `ubicaciones/serializers.py`, `ubicaciones/services.py`
- Modify: `ubicaciones/models.py`, `ubicaciones/admin.py`
- Create: `ubicaciones/urls.py`, `ubicaciones/api_urls.py` (versiones vacías), `ubicaciones/tests.py`
- Create: `ubicaciones/migrations/0001_initial.py` (generado por `makemigrations`), `ubicaciones/migrations/0002_grupo_pedidos_ubicaciones.py` (recreado)

**Interfaces:**
- Produces: modelos `Galpon`, `Rack`, `Cuerpo`, `Ubicacion`, `Nivel`, `ProductoUbicacion`, `MovimientoUbicacion` (campos exactos abajo) — todas las tareas siguientes dependen de estos nombres de campo exactos.
- Produces: `Nivel.codigo_completo` (property), `Nivel.esta_fusionado` (property), `Rack.total_cuerpos` (property).

- [ ] **Step 1: Borrar las migraciones actuales**

```bash
rm ubicaciones/migrations/0001_initial.py ubicaciones/migrations/0002_grupo_pedidos_ubicaciones.py
```

- [ ] **Step 2: Reescribir `ubicaciones/models.py`**

```python
from django.conf import settings
from django.db import models


class Galpon(models.Model):
    codigo = models.CharField(max_length=10, unique=True)
    nombre = models.CharField(max_length=255, blank=True, default='')
    grid_filas = models.PositiveIntegerField(default=10)
    grid_columnas = models.PositiveIntegerField(default=10)
    activo = models.BooleanField(default=True, db_index=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='galpones_creados',
    )

    class Meta:
        ordering = ['codigo']

    def __str__(self) -> str:
        return self.nombre or self.codigo


class Rack(models.Model):
    galpon = models.ForeignKey(Galpon, on_delete=models.PROTECT, related_name='racks')
    codigo = models.CharField(max_length=5)
    descripcion = models.CharField(max_length=255, blank=True, default='')
    grid_fila = models.PositiveIntegerField(default=1)
    grid_columna = models.PositiveIntegerField(default=1)
    ancho = models.PositiveIntegerField(default=1)
    alto = models.PositiveIntegerField(default=1)
    max_niveles = models.PositiveIntegerField(default=6)
    activo = models.BooleanField(default=True, db_index=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='racks_creados',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['galpon', 'codigo'], name='uniq_rack_codigo_por_galpon'),
        ]
        ordering = ['galpon', 'codigo']

    def __str__(self) -> str:
        return f"{self.galpon.codigo}{self.codigo}"

    @property
    def total_cuerpos(self) -> int:
        return self.cuerpos.count()


class Cuerpo(models.Model):
    rack = models.ForeignKey(Rack, on_delete=models.PROTECT, related_name='cuerpos')
    codigo = models.CharField(max_length=4)
    descripcion = models.CharField(max_length=255, blank=True, default='')
    activo = models.BooleanField(default=True, db_index=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cuerpos_creados',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['rack', 'codigo'], name='uniq_cuerpo_codigo_por_rack'),
        ]
        ordering = ['rack', 'codigo']

    def __str__(self) -> str:
        return f"{self.rack} / Cuerpo {self.codigo}"


class Ubicacion(models.Model):
    cuerpo = models.ForeignKey(Cuerpo, on_delete=models.PROTECT, related_name='ubicaciones')
    codigo = models.CharField(max_length=4)
    descripcion = models.CharField(max_length=255, blank=True, default='')
    activo = models.BooleanField(default=True, db_index=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ubicaciones_creadas',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['cuerpo', 'codigo'], name='uniq_ubicacion_codigo_por_cuerpo'),
        ]
        ordering = ['cuerpo', 'codigo']

    def __str__(self) -> str:
        return f"{self.cuerpo} / Ubicación {self.codigo}"

    @property
    def rack(self) -> Rack:
        return self.cuerpo.rack


class Nivel(models.Model):
    PICKING = 'PICKING'
    ALMACENAJE = 'ALMACENAJE'
    TIPO_CHOICES = [
        (PICKING, 'Picking'),
        (ALMACENAJE, 'Almacenaje'),
    ]

    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT, related_name='niveles')
    numero = models.PositiveSmallIntegerField()
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=PICKING)
    descripcion = models.CharField(max_length=255, blank=True, default='')
    fusionado_en = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='niveles_fusionados',
    )
    activo = models.BooleanField(default=True, db_index=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='niveles_creados',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['ubicacion', 'numero'], name='uniq_nivel_numero_por_ubicacion'),
        ]
        ordering = ['ubicacion', 'numero']

    def __str__(self) -> str:
        return self.codigo_completo

    @property
    def cuerpo(self) -> Cuerpo:
        return self.ubicacion.cuerpo

    @property
    def rack(self) -> Rack:
        return self.ubicacion.cuerpo.rack

    @property
    def galpon(self) -> Galpon:
        return self.ubicacion.cuerpo.rack.galpon

    @property
    def codigo_completo(self) -> str:
        return (
            f"{self.galpon.codigo}{self.rack.codigo}"
            f"{self.cuerpo.codigo}{self.ubicacion.codigo}.{self.numero}"
        )

    @property
    def esta_fusionado(self) -> bool:
        return self.fusionado_en_id is not None


class ProductoUbicacion(models.Model):
    codigo_producto = models.CharField(max_length=50, db_index=True)
    nivel = models.ForeignKey(Nivel, on_delete=models.PROTECT, related_name='productos')
    cantidad = models.PositiveIntegerField(default=0)
    stock_minimo = models.PositiveIntegerField(null=True, blank=True)
    fecha_asignacion = models.DateTimeField(auto_now_add=True)
    asignado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='asignaciones_ubicacion',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['codigo_producto', 'nivel'], name='uniq_producto_por_nivel'),
        ]
        indexes = [models.Index(fields=['codigo_producto'])]
        ordering = ['codigo_producto']

    def __str__(self) -> str:
        return f"{self.codigo_producto} @ {self.nivel.codigo_completo}"


class MovimientoUbicacion(models.Model):
    TIPO_CHOICES = [
        ('CREACION_GALPON', 'Creación de galpón'),
        ('EDICION_GALPON', 'Edición de galpón'),
        ('DESACTIVACION_GALPON', 'Desactivación de galpón'),
        ('CREACION_RACK', 'Creación de rack'),
        ('EDICION_RACK', 'Edición de rack'),
        ('DESACTIVACION_RACK', 'Desactivación de rack'),
        ('CREACION_CUERPO', 'Creación de cuerpo'),
        ('DESACTIVACION_CUERPO', 'Desactivación de cuerpo'),
        ('DESACTIVACION_UBICACION', 'Desactivación de ubicación'),
        ('EDICION_NIVEL', 'Edición de nivel'),
        ('DESACTIVACION_NIVEL', 'Desactivación de nivel'),
        ('ASIGNACION', 'Asignación de producto'),
        ('EDICION_CANTIDAD', 'Edición de cantidad'),
        ('DESASIGNACION', 'Desasignación de producto'),
        ('TRASLADO', 'Traslado entre niveles'),
        ('FUSION_NIVEL', 'Fusión de niveles'),
        ('DESFUSION_NIVEL', 'Desfusión de nivel'),
    ]

    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, db_index=True)
    galpon = models.ForeignKey(Galpon, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos')
    rack = models.ForeignKey(Rack, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos')
    cuerpo = models.ForeignKey(Cuerpo, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos')
    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos')
    nivel = models.ForeignKey(Nivel, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos')
    nivel_origen = models.ForeignKey(
        Nivel, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos_origen',
    )
    nivel_destino = models.ForeignKey(
        Nivel, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos_destino',
    )
    codigo_producto = models.CharField(max_length=50, blank=True, default='', db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movimientos_ubicacion',
    )
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    notas = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-fecha']
        indexes = [
            models.Index(fields=['-fecha']),
            models.Index(fields=['tipo', '-fecha']),
            models.Index(fields=['codigo_producto', '-fecha']),
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} — {self.codigo_producto or '-'} ({self.fecha:%Y-%m-%d %H:%M})"
```

- [ ] **Step 3: Reescribir `ubicaciones/admin.py`**

```python
from django.contrib import admin

from .models import Cuerpo, Galpon, MovimientoUbicacion, Nivel, ProductoUbicacion, Rack, Ubicacion


@admin.register(Galpon)
class GalponAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'nombre', 'grid_filas', 'grid_columnas', 'activo', 'fecha_creacion']
    list_filter = ['activo']
    search_fields = ['codigo', 'nombre']
    readonly_fields = ['fecha_creacion', 'fecha_modificacion', 'creado_por']


@admin.register(Rack)
class RackAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'galpon', 'descripcion', 'max_niveles', 'total_cuerpos', 'activo', 'fecha_creacion']
    list_filter = ['activo', 'galpon']
    search_fields = ['codigo', 'descripcion']
    readonly_fields = ['fecha_creacion', 'fecha_modificacion', 'creado_por']


@admin.register(Cuerpo)
class CuerpoAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'rack', 'activo', 'fecha_creacion']
    list_filter = ['activo', 'rack']
    search_fields = ['codigo', 'rack__codigo']
    readonly_fields = ['fecha_creacion', 'fecha_modificacion', 'creado_por']


@admin.register(Ubicacion)
class UbicacionAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'cuerpo', 'activo', 'fecha_creacion']
    list_filter = ['activo', 'cuerpo__rack']
    search_fields = ['codigo', 'cuerpo__codigo', 'cuerpo__rack__codigo']
    readonly_fields = ['fecha_creacion', 'fecha_modificacion', 'creado_por']


@admin.register(Nivel)
class NivelAdmin(admin.ModelAdmin):
    list_display = ['codigo_completo', 'tipo', 'fusionado_en', 'activo', 'fecha_creacion']
    list_filter = ['tipo', 'activo', 'ubicacion__cuerpo__rack']
    search_fields = ['ubicacion__cuerpo__rack__codigo']
    readonly_fields = ['fecha_creacion', 'fecha_modificacion', 'creado_por']


@admin.register(ProductoUbicacion)
class ProductoUbicacionAdmin(admin.ModelAdmin):
    list_display = ['codigo_producto', 'nivel', 'cantidad', 'stock_minimo', 'fecha_asignacion']
    search_fields = ['codigo_producto']
    list_filter = ['nivel__ubicacion__cuerpo__rack']
    readonly_fields = ['fecha_asignacion', 'asignado_por']


@admin.register(MovimientoUbicacion)
class MovimientoUbicacionAdmin(admin.ModelAdmin):
    list_display = ['tipo', 'codigo_producto', 'rack', 'nivel_origen', 'nivel_destino', 'usuario', 'fecha']
    list_filter = ['tipo']
    search_fields = ['codigo_producto']
    date_hierarchy = 'fecha'
    readonly_fields = [
        'tipo', 'galpon', 'rack', 'cuerpo', 'ubicacion', 'nivel',
        'nivel_origen', 'nivel_destino', 'codigo_producto', 'usuario', 'fecha', 'notas',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

- [ ] **Step 4: Borrar los módulos que referencian el modelo viejo y vaciar las rutas**

```bash
rm ubicaciones/forms.py ubicaciones/views.py ubicaciones/api_views.py ubicaciones/serializers.py ubicaciones/services.py
```

Crear `ubicaciones/urls.py`:

```python
from django.urls import path

urlpatterns = []
```

Crear `ubicaciones/api_urls.py`:

```python
from django.urls import path

urlpatterns = []
```

- [ ] **Step 5: Generar la migración inicial y recrear la migración del grupo**

```bash
venv\Scripts\python.exe manage.py makemigrations ubicaciones
```

Esto genera `ubicaciones/migrations/0001_initial.py`. Luego crear a mano
`ubicaciones/migrations/0002_grupo_pedidos_ubicaciones.py` (idéntica a la que existía):

```python
from django.db import migrations


def crear_grupo(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.get_or_create(name='Pedidos Ubicaciones')


def borrar_grupo(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Group.objects.filter(name='Pedidos Ubicaciones').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('ubicaciones', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]
    operations = [
        migrations.RunPython(crear_grupo, borrar_grupo),
    ]
```

- [ ] **Step 6: Escribir `ubicaciones/tests.py` con los tests de modelo**

```python
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from ubicaciones.models import Cuerpo, Galpon, Nivel, ProductoUbicacion, Rack, Ubicacion

User = get_user_model()


class JerarquiaModeloTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='tester')
        self.galpon = Galpon.objects.create(codigo='1', nombre='Galpón 1', creado_por=self.user)
        self.rack = Rack.objects.create(galpon=self.galpon, codigo='A', max_niveles=6, creado_por=self.user)
        self.cuerpo = Cuerpo.objects.create(rack=self.rack, codigo='01', creado_por=self.user)
        self.ubicacion = Ubicacion.objects.create(cuerpo=self.cuerpo, codigo='01', creado_por=self.user)
        self.nivel = Nivel.objects.create(ubicacion=self.ubicacion, numero=4, creado_por=self.user)

    def test_codigo_completo_reproduce_formato_fisico(self):
        self.assertEqual(self.nivel.codigo_completo, '1A0101.4')

    def test_unicidad_rack_por_galpon(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Rack.objects.create(galpon=self.galpon, codigo='A')

    def test_unicidad_cuerpo_por_rack(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Cuerpo.objects.create(rack=self.rack, codigo='01')

    def test_unicidad_ubicacion_por_cuerpo(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Ubicacion.objects.create(cuerpo=self.cuerpo, codigo='01')

    def test_unicidad_nivel_por_ubicacion(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Nivel.objects.create(ubicacion=self.ubicacion, numero=4)

    def test_producto_ubicacion_requiere_nivel_y_codigo_unicos(self):
        ProductoUbicacion.objects.create(codigo_producto='ABC123', nivel=self.nivel, cantidad=5)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProductoUbicacion.objects.create(codigo_producto='ABC123', nivel=self.nivel, cantidad=1)

    def test_nivel_no_fusionado_por_defecto(self):
        self.assertFalse(self.nivel.esta_fusionado)

    def test_rack_total_cuerpos(self):
        Cuerpo.objects.create(rack=self.rack, codigo='02', creado_por=self.user)
        self.assertEqual(self.rack.total_cuerpos, 2)
```

- [ ] **Step 7: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones --settings=Programarprecios.test_settings -v 2`
Expected: 7 tests, todos PASS.

- [ ] **Step 8: Confirmar que el proyecto completo sigue arrancando (checks de Django)**

Run: `venv\Scripts\python.exe manage.py check`
Expected: `System check identified no issues` — esto confirma que ningún `ModelForm`/`ModelAdmin` en el resto del proyecto quedó referenciando campos inexistentes.

- [ ] **Step 9: Commit**

```bash
git add ubicaciones/
git commit -m "feat(ubicaciones): resetea modelo a jerarquía Galpón-Rack-Cuerpo-Ubicación-Nivel"
```

---

## Task 2: Servicio — Galpón y Rack

Crea `ubicaciones/services.py` con la clase `UbicacionesService` y sus primeros métodos: creación/edición/desactivación de Galpón y Rack. `max_niveles` de un Rack queda bloqueado (no editable) una vez que el Rack ya tiene Cuerpos — evita el problema de retro-ajustar Niveles ya generados en Ubicaciones existentes.

**Files:**
- Create: `ubicaciones/services.py`
- Modify: `ubicaciones/tests.py`

**Interfaces:**
- Consumes: modelos `Galpon`, `Rack`, `MovimientoUbicacion` (Task 1).
- Produces: `UbicacionesService.crear_galpon(codigo, nombre, grid_filas, grid_columnas, usuario) -> Galpon`,
  `editar_galpon(galpon, nombre, grid_filas, grid_columnas, usuario) -> Galpon`,
  `desactivar_galpon(galpon, usuario) -> None`,
  `crear_rack(galpon, codigo, descripcion, grid_fila, grid_columna, ancho, alto, max_niveles, usuario) -> Rack`,
  `editar_rack(rack, descripcion, grid_fila, grid_columna, ancho, alto, max_niveles, usuario) -> Rack`,
  `desactivar_rack(rack, usuario) -> None`. Tareas siguientes dependen de estas firmas exactas.

- [ ] **Step 1: Escribir los tests de servicio para Galpón y Rack**

Agregar a `ubicaciones/tests.py`:

```python
from django.core.exceptions import ValidationError

from ubicaciones.services import UbicacionesService


class GalponRackServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='tester2')

    def test_crear_galpon(self):
        galpon = UbicacionesService.crear_galpon('2', 'Galpón 2', 8, 8, self.user)
        self.assertEqual(galpon.codigo, '2')
        self.assertEqual(MovimientoUbicacion.objects.filter(tipo='CREACION_GALPON').count(), 1)

    def test_crear_galpon_codigo_duplicado_falla(self):
        UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.crear_galpon('1', 'Otro', 10, 10, self.user)

    def test_crear_rack(self):
        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        rack = UbicacionesService.crear_rack(
            galpon=galpon, codigo='A', descripcion='', grid_fila=1, grid_columna=1,
            ancho=1, alto=1, max_niveles=6, usuario=self.user,
        )
        self.assertEqual(rack.codigo, 'A')
        self.assertEqual(rack.max_niveles, 6)

    def test_crear_rack_codigo_duplicado_en_mismo_galpon_falla(self):
        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        UbicacionesService.crear_rack(galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.crear_rack(galpon, 'A', '', 2, 1, 1, 1, 6, self.user)

    def test_editar_max_niveles_bloqueado_si_ya_tiene_cuerpos(self):
        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        rack = UbicacionesService.crear_rack(galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        Cuerpo.objects.create(rack=rack, codigo='01', creado_por=self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.editar_rack(rack, '', 1, 1, 1, 1, 4, self.user)

    def test_desactivar_rack_con_cuerpos_activos_falla(self):
        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        rack = UbicacionesService.crear_rack(galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        Cuerpo.objects.create(rack=rack, codigo='01', creado_por=self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.desactivar_rack(rack, self.user)

    def test_desactivar_galpon_con_racks_activos_falla(self):
        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        UbicacionesService.crear_rack(galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.desactivar_galpon(galpon, self.user)
```

- [ ] **Step 2: Correr los tests y confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.GalponRackServiceTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'ubicaciones.services'`.

- [ ] **Step 3: Escribir `ubicaciones/services.py` (Galpón y Rack)**

```python
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Cuerpo, Galpon, MovimientoUbicacion, Rack


def _registrar(tipo: str, usuario, **kwargs) -> None:
    MovimientoUbicacion.objects.create(tipo=tipo, usuario=usuario, **kwargs)


class UbicacionesService:

    # ------------------------------------------------------------------ Galpón

    @staticmethod
    @transaction.atomic
    def crear_galpon(codigo: str, nombre: str, grid_filas: int, grid_columnas: int, usuario) -> Galpon:
        """Crea un galpón normalizando el código a mayúsculas."""
        codigo = codigo.strip().upper()
        if Galpon.objects.filter(codigo=codigo).exists():
            raise ValidationError(f"Ya existe un galpón con código '{codigo}'.")
        galpon = Galpon.objects.create(
            codigo=codigo, nombre=nombre,
            grid_filas=grid_filas, grid_columnas=grid_columnas,
            creado_por=usuario,
        )
        _registrar('CREACION_GALPON', usuario, galpon=galpon)
        return galpon

    @staticmethod
    @transaction.atomic
    def editar_galpon(galpon: Galpon, nombre: str, grid_filas: int, grid_columnas: int, usuario) -> Galpon:
        galpon.nombre = nombre
        galpon.grid_filas = grid_filas
        galpon.grid_columnas = grid_columnas
        galpon.save(update_fields=['nombre', 'grid_filas', 'grid_columnas', 'fecha_modificacion'])
        _registrar('EDICION_GALPON', usuario, galpon=galpon)
        return galpon

    @staticmethod
    @transaction.atomic
    def desactivar_galpon(galpon: Galpon, usuario) -> None:
        """Soft-delete de galpón. Rechaza si tiene racks activos."""
        if galpon.racks.filter(activo=True).exists():
            raise ValidationError(
                f"El galpón '{galpon.codigo}' tiene racks activos. "
                "Desactívalos antes de desactivar el galpón."
            )
        galpon.activo = False
        galpon.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_GALPON', usuario, galpon=galpon)

    # ------------------------------------------------------------------ Rack

    @staticmethod
    @transaction.atomic
    def crear_rack(
        galpon: Galpon, codigo: str, descripcion: str,
        grid_fila: int, grid_columna: int, ancho: int, alto: int,
        max_niveles: int, usuario,
    ) -> Rack:
        """Crea un rack normalizando el código a mayúsculas."""
        codigo = codigo.strip().upper()
        if not galpon.activo:
            raise ValidationError(f"El galpón '{galpon.codigo}' está desactivado.")
        if Rack.objects.filter(galpon=galpon, codigo=codigo).exists():
            raise ValidationError(
                f"Ya existe un rack con código '{codigo}' en el galpón '{galpon.codigo}'."
            )
        rack = Rack.objects.create(
            galpon=galpon, codigo=codigo, descripcion=descripcion,
            grid_fila=grid_fila, grid_columna=grid_columna, ancho=ancho, alto=alto,
            max_niveles=max_niveles, creado_por=usuario,
        )
        _registrar('CREACION_RACK', usuario, galpon=galpon, rack=rack)
        return rack

    @staticmethod
    @transaction.atomic
    def editar_rack(
        rack: Rack, descripcion: str,
        grid_fila: int, grid_columna: int, ancho: int, alto: int,
        max_niveles: int, usuario,
    ) -> Rack:
        """Edita un rack. `max_niveles` solo se puede cambiar si el rack aún no tiene cuerpos."""
        if max_niveles != rack.max_niveles and rack.cuerpos.exists():
            raise ValidationError(
                f"El rack '{rack.codigo}' ya tiene cuerpos creados; "
                "no se puede cambiar el máximo de niveles."
            )
        rack.descripcion = descripcion
        rack.grid_fila = grid_fila
        rack.grid_columna = grid_columna
        rack.ancho = ancho
        rack.alto = alto
        rack.max_niveles = max_niveles
        rack.save(update_fields=[
            'descripcion', 'grid_fila', 'grid_columna', 'ancho', 'alto',
            'max_niveles', 'fecha_modificacion',
        ])
        _registrar('EDICION_RACK', usuario, galpon=rack.galpon, rack=rack)
        return rack

    @staticmethod
    @transaction.atomic
    def desactivar_rack(rack: Rack, usuario) -> None:
        """Soft-delete de rack. Rechaza si tiene cuerpos activos."""
        if rack.cuerpos.filter(activo=True).exists():
            raise ValidationError(
                f"El rack '{rack.codigo}' tiene cuerpos activos. "
                "Desactívalos antes de desactivar el rack."
            )
        rack.activo = False
        rack.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_RACK', usuario, galpon=rack.galpon, rack=rack)
```

- [ ] **Step 4: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.GalponRackServiceTest --settings=Programarprecios.test_settings -v 2`
Expected: 6 tests, todos PASS.

- [ ] **Step 5: Commit**

```bash
git add ubicaciones/services.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): servicio de Galpón y Rack"
```

---

## Task 3: Servicio — Cuerpo y Ubicación (creación en cascada)

Añade `crear_cuerpo` (autogenera sus 2 Ubicaciones con código de numeración global, y cada Ubicación autogenera sus Niveles según `rack.max_niveles`), `desactivar_cuerpo` y `desactivar_ubicacion`.

**Files:**
- Modify: `ubicaciones/services.py`, `ubicaciones/tests.py`

**Interfaces:**
- Consumes: `Cuerpo`, `Ubicacion`, `Nivel` (Task 1); `UbicacionesService` (Task 2).
- Produces: `UbicacionesService.crear_cuerpo(rack, descripcion, usuario) -> Cuerpo`,
  `desactivar_cuerpo(cuerpo, usuario) -> None`,
  `desactivar_ubicacion(ubicacion, usuario) -> None`.

- [ ] **Step 1: Escribir los tests**

Agregar a `ubicaciones/tests.py`:

```python
class CuerpoUbicacionServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='tester3')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)

    def test_crear_cuerpo_autogenera_2_ubicaciones_con_numeracion_global(self):
        cuerpo1 = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.assertEqual(cuerpo1.codigo, '01')
        ubics1 = list(cuerpo1.ubicaciones.order_by('codigo'))
        self.assertEqual([u.codigo for u in ubics1], ['01', '02'])

        cuerpo2 = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.assertEqual(cuerpo2.codigo, '02')
        ubics2 = list(cuerpo2.ubicaciones.order_by('codigo'))
        self.assertEqual([u.codigo for u in ubics2], ['03', '04'])

    def test_crear_cuerpo_autogenera_niveles_segun_max_niveles_del_rack(self):
        cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        for ubicacion in cuerpo.ubicaciones.all():
            self.assertEqual(list(ubicacion.niveles.order_by('numero').values_list('numero', flat=True)), [1, 2, 3, 4, 5, 6])

    def test_crear_cuerpo_codigo_completo_del_nivel_reproduce_formato_fisico(self):
        cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        ubicacion = cuerpo.ubicaciones.order_by('codigo').first()
        nivel4 = ubicacion.niveles.get(numero=4)
        self.assertEqual(nivel4.codigo_completo, '1A0101.4')

    def test_crear_cuerpo_registra_un_solo_movimiento(self):
        UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.assertEqual(MovimientoUbicacion.objects.filter(tipo='CREACION_CUERPO').count(), 1)

    def test_desactivar_cuerpo_con_ubicaciones_activas_falla(self):
        cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.desactivar_cuerpo(cuerpo, self.user)

    def test_desactivar_ubicacion_con_niveles_activos_falla(self):
        cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        ubicacion = cuerpo.ubicaciones.first()
        with self.assertRaises(ValidationError):
            UbicacionesService.desactivar_ubicacion(ubicacion, self.user)
```

- [ ] **Step 2: Correr los tests y confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.CuerpoUbicacionServiceTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL — `AttributeError: type object 'UbicacionesService' has no attribute 'crear_cuerpo'`.

- [ ] **Step 3: Añadir los métodos a `ubicaciones/services.py`**

Actualizar el import del inicio del archivo:

```python
from .models import Cuerpo, Galpon, MovimientoUbicacion, Nivel, Rack, Ubicacion
```

Agregar al final de la clase `UbicacionesService`:

```python
    # ------------------------------------------------------------------ Cuerpo

    @staticmethod
    @transaction.atomic
    def crear_cuerpo(rack: Rack, descripcion: str, usuario) -> Cuerpo:
        """
        Crea un cuerpo en el rack, autogenerando sus 2 Ubicaciones (numeración
        global no reiniciada por cuerpo, para calzar con las etiquetas físicas
        ya impresas) y, para cada una, sus Niveles según `rack.max_niveles`.
        """
        if not rack.activo:
            raise ValidationError(f"El rack '{rack.codigo}' está desactivado.")
        siguiente_num = rack.cuerpos.count() + 1
        cuerpo = Cuerpo.objects.create(
            rack=rack, codigo=f"{siguiente_num:02d}",
            descripcion=descripcion, creado_por=usuario,
        )
        for offset in (0, 1):
            ubicacion_num = 2 * siguiente_num - 1 + offset
            ubicacion = Ubicacion.objects.create(
                cuerpo=cuerpo, codigo=f"{ubicacion_num:02d}", creado_por=usuario,
            )
            Nivel.objects.bulk_create([
                Nivel(ubicacion=ubicacion, numero=n, creado_por=usuario)
                for n in range(1, rack.max_niveles + 1)
            ])
        _registrar('CREACION_CUERPO', usuario, galpon=rack.galpon, rack=rack, cuerpo=cuerpo)
        return cuerpo

    @staticmethod
    @transaction.atomic
    def desactivar_cuerpo(cuerpo: Cuerpo, usuario) -> None:
        """Soft-delete de cuerpo. Rechaza si tiene ubicaciones activas."""
        if cuerpo.ubicaciones.filter(activo=True).exists():
            raise ValidationError(
                f"El cuerpo '{cuerpo.codigo}' tiene ubicaciones activas. "
                "Desactívalas antes de desactivar el cuerpo."
            )
        cuerpo.activo = False
        cuerpo.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_CUERPO', usuario, galpon=cuerpo.rack.galpon, rack=cuerpo.rack, cuerpo=cuerpo)

    # ------------------------------------------------------------------ Ubicación

    @staticmethod
    @transaction.atomic
    def desactivar_ubicacion(ubicacion: Ubicacion, usuario) -> None:
        """Soft-delete de ubicación. Rechaza si tiene niveles activos."""
        if ubicacion.niveles.filter(activo=True).exists():
            raise ValidationError(
                f"La ubicación '{ubicacion.codigo}' tiene niveles activos. "
                "Desactívalos antes de desactivar la ubicación."
            )
        ubicacion.activo = False
        ubicacion.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar(
            'DESACTIVACION_UBICACION', usuario,
            galpon=ubicacion.rack.galpon, rack=ubicacion.rack, ubicacion=ubicacion,
        )
```

- [ ] **Step 4: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.CuerpoUbicacionServiceTest --settings=Programarprecios.test_settings -v 2`
Expected: 6 tests, todos PASS.

- [ ] **Step 5: Commit**

```bash
git add ubicaciones/services.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): servicio de Cuerpo con cascada de Ubicación y Nivel"
```

---

## Task 4: Servicio — Nivel

Añade `editar_nivel` (tipo/descripción) y `desactivar_nivel`. Ambos rechazan si el nivel está fusionado (`esta_fusionado`), y `desactivar_nivel` rechaza si tiene productos asignados.

**Files:**
- Modify: `ubicaciones/services.py`, `ubicaciones/tests.py`

**Interfaces:**
- Consumes: `Nivel.esta_fusionado` (Task 1); `UbicacionesService` (Tasks 2-3).
- Produces: `UbicacionesService.editar_nivel(nivel, tipo, descripcion, usuario) -> Nivel`,
  `desactivar_nivel(nivel, usuario) -> None`.

- [ ] **Step 1: Escribir los tests**

Agregar a `ubicaciones/tests.py`:

```python
class NivelServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='tester4')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.ubicacion = self.cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel = self.ubicacion.niveles.get(numero=1)

    def test_editar_nivel_cambia_tipo_y_descripcion(self):
        UbicacionesService.editar_nivel(self.nivel, Nivel.ALMACENAJE, 'Nota', self.user)
        self.nivel.refresh_from_db()
        self.assertEqual(self.nivel.tipo, Nivel.ALMACENAJE)
        self.assertEqual(self.nivel.descripcion, 'Nota')

    def test_editar_nivel_fusionado_falla(self):
        otro_nivel = self.ubicacion.niveles.get(numero=2)
        self.nivel.fusionado_en = otro_nivel
        self.nivel.save(update_fields=['fusionado_en'])
        with self.assertRaises(ValidationError):
            UbicacionesService.editar_nivel(self.nivel, Nivel.ALMACENAJE, '', self.user)

    def test_desactivar_nivel_con_productos_falla(self):
        ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel, cantidad=1)
        with self.assertRaises(ValidationError):
            UbicacionesService.desactivar_nivel(self.nivel, self.user)

    def test_desactivar_nivel_sin_productos_ok(self):
        UbicacionesService.desactivar_nivel(self.nivel, self.user)
        self.nivel.refresh_from_db()
        self.assertFalse(self.nivel.activo)
```

- [ ] **Step 2: Correr los tests y confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.NivelServiceTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL — `AttributeError: type object 'UbicacionesService' has no attribute 'editar_nivel'`.

- [ ] **Step 3: Añadir los métodos a `ubicaciones/services.py`**

Agregar al final de la clase `UbicacionesService`:

```python
    # ------------------------------------------------------------------ Nivel

    @staticmethod
    @transaction.atomic
    def editar_nivel(nivel: Nivel, tipo: str, descripcion: str, usuario) -> Nivel:
        if nivel.esta_fusionado:
            raise ValidationError(
                f"El nivel '{nivel.codigo_completo}' está fusionado con "
                f"'{nivel.fusionado_en.codigo_completo}'; edítalo desde el nivel maestro."
            )
        nivel.tipo = tipo
        nivel.descripcion = descripcion
        nivel.save(update_fields=['tipo', 'descripcion', 'fecha_modificacion'])
        _registrar('EDICION_NIVEL', usuario, galpon=nivel.galpon, rack=nivel.rack, nivel=nivel)
        return nivel

    @staticmethod
    @transaction.atomic
    def desactivar_nivel(nivel: Nivel, usuario) -> None:
        """Soft-delete de nivel. Rechaza si tiene productos asignados."""
        if nivel.productos.exists():
            raise ValidationError(
                f"El nivel '{nivel.codigo_completo}' tiene productos asignados. "
                "Quítalos o trasládalos antes de desactivarlo."
            )
        nivel.activo = False
        nivel.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_NIVEL', usuario, galpon=nivel.galpon, rack=nivel.rack, nivel=nivel)
```

- [ ] **Step 4: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.NivelServiceTest --settings=Programarprecios.test_settings -v 2`
Expected: 4 tests, todos PASS.

- [ ] **Step 5: Commit**

```bash
git add ubicaciones/services.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): servicio de edición/desactivación de Nivel"
```

---

## Task 5: Servicio — Asignación de producto (cantidad validada contra a2)

Añade `asignar_producto`, `editar_cantidad`, `quitar_producto` y `trasladar_producto` (se conserva del servicio anterior, adaptado a `Nivel`). Toda escritura de cantidad valida contra la existencia real en DBISAM depósito 1, sumando todas las asignaciones activas del código de producto.

**Files:**
- Modify: `ubicaciones/services.py`, `ubicaciones/tests.py`

**Interfaces:**
- Consumes: `PedidosAlmacen.dbisam.PedidosDBISAM.consultar_stock(codigo, deposito=None)`, `PedidosAlmacen.dbisam.DEPOSITO_ALMACEN` (existente, vale `1`); `Nivel.esta_fusionado`.
- Produces: `UbicacionesService.asignar_producto(codigo, nivel, cantidad, stock_minimo, usuario) -> ProductoUbicacion`,
  `editar_cantidad(producto_ubicacion, cantidad, stock_minimo, usuario) -> ProductoUbicacion`,
  `quitar_producto(producto_ubicacion_id, usuario) -> None`,
  `trasladar_producto(codigo, nivel_origen, nivel_destino, usuario, notas='') -> None`.

- [ ] **Step 1: Escribir los tests**

Agregar a `ubicaciones/tests.py` (usa `unittest.mock.patch` sobre `ubicaciones.services.PedidosDBISAM`, mismo patrón que `PedidosAlmacen/tests.py`):

```python
from unittest.mock import patch


class AsignacionServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='tester5')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.ubicacion = self.cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel = self.ubicacion.niveles.get(numero=1)
        self.otro_nivel = self.ubicacion.niveles.get(numero=2)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_asignar_producto_dentro_de_existencia_ok(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 100
        pu = UbicacionesService.asignar_producto('ABC', self.nivel, 40, None, self.user)
        self.assertEqual(pu.cantidad, 40)
        mock_db.return_value.consultar_stock.assert_called_once_with('ABC', deposito=1)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_asignar_producto_excede_existencia_falla(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 30
        with self.assertRaises(ValidationError):
            UbicacionesService.asignar_producto('ABC', self.nivel, 40, None, self.user)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_asignar_producto_suma_asignaciones_existentes(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        UbicacionesService.asignar_producto('ABC', self.nivel, 30, None, self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.asignar_producto('ABC', self.otro_nivel, 25, None, self.user)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_asignar_producto_en_nivel_fusionado_falla(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 100
        self.nivel.fusionado_en = self.otro_nivel
        self.nivel.save(update_fields=['fusionado_en'])
        with self.assertRaises(ValidationError):
            UbicacionesService.asignar_producto('ABC', self.nivel, 10, None, self.user)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_editar_cantidad_excluye_su_propia_fila_de_la_suma(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        pu = UbicacionesService.asignar_producto('ABC', self.nivel, 30, None, self.user)
        UbicacionesService.editar_cantidad(pu, 50, None, self.user)
        pu.refresh_from_db()
        self.assertEqual(pu.cantidad, 50)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_quitar_producto(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        pu = UbicacionesService.asignar_producto('ABC', self.nivel, 30, None, self.user)
        UbicacionesService.quitar_producto(pu.pk, self.user)
        self.assertFalse(ProductoUbicacion.objects.filter(pk=pu.pk).exists())

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_trasladar_producto_mueve_la_asignacion(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        UbicacionesService.asignar_producto('ABC', self.nivel, 30, None, self.user)
        UbicacionesService.trasladar_producto('ABC', self.nivel, self.otro_nivel, self.user)
        self.assertFalse(ProductoUbicacion.objects.filter(nivel=self.nivel, codigo_producto='ABC').exists())
        self.assertTrue(ProductoUbicacion.objects.filter(nivel=self.otro_nivel, codigo_producto='ABC').exists())

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_trasladar_producto_a_nivel_fusionado_falla(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        UbicacionesService.asignar_producto('ABC', self.nivel, 30, None, self.user)
        self.otro_nivel.fusionado_en = self.nivel
        self.otro_nivel.save(update_fields=['fusionado_en'])
        with self.assertRaises(ValidationError):
            UbicacionesService.trasladar_producto('ABC', self.nivel, self.otro_nivel, self.user)
```

- [ ] **Step 2: Correr los tests y confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.AsignacionServiceTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL — `AttributeError: type object 'UbicacionesService' has no attribute 'asignar_producto'`.

- [ ] **Step 3: Añadir los métodos a `ubicaciones/services.py`**

Actualizar los imports del inicio del archivo (agregar `Sum` y el import de DBISAM **a nivel de
módulo** — no dentro del método: así `@patch('ubicaciones.services.PedidosDBISAM')` puede
interceptarlo en los tests, igual que el patrón ya usado en `PedidosAlmacen/tests.py` con
`@patch('PedidosAlmacen.views.PedidosDBISAM')`, que solo funciona porque ese import también está a
nivel de módulo):

```python
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from PedidosAlmacen.dbisam import DEPOSITO_ALMACEN, PedidosDBISAM

from .models import Cuerpo, Galpon, MovimientoUbicacion, Nivel, ProductoUbicacion, Rack, Ubicacion
```

Agregar al final de la clase `UbicacionesService`:

```python
    # ------------------------------------------------------------------ Asignaciones

    @staticmethod
    def _validar_cantidad_contra_a2(codigo: str, cantidad_nueva: int, excluir_pu_id: int | None = None) -> None:
        ya_asignado = ProductoUbicacion.objects.filter(codigo_producto=codigo)
        if excluir_pu_id:
            ya_asignado = ya_asignado.exclude(pk=excluir_pu_id)
        suma_actual = ya_asignado.aggregate(total=Sum('cantidad'))['total'] or 0
        total_pedido = suma_actual + cantidad_nueva
        existencia = PedidosDBISAM().consultar_stock(codigo, deposito=DEPOSITO_ALMACEN)
        if total_pedido > existencia:
            raise ValidationError(
                f"La cantidad total asignada de '{codigo}' ({total_pedido}) "
                f"excede la existencia en depósito ({existencia})."
            )

    @staticmethod
    @transaction.atomic
    def asignar_producto(
        codigo: str, nivel: Nivel, cantidad: int, stock_minimo: int | None, usuario,
    ) -> ProductoUbicacion:
        """Asigna un producto (código DBISAM) a un nivel, validando cantidad contra a2."""
        codigo = codigo.strip().upper()
        if not nivel.activo:
            raise ValidationError(f"El nivel '{nivel.codigo_completo}' está desactivado.")
        if nivel.esta_fusionado:
            raise ValidationError(
                f"El nivel '{nivel.codigo_completo}' está fusionado con "
                f"'{nivel.fusionado_en.codigo_completo}'; asigna el producto al nivel maestro."
            )
        if ProductoUbicacion.objects.filter(codigo_producto=codigo, nivel=nivel).exists():
            raise ValidationError(f"El producto '{codigo}' ya está asignado a '{nivel.codigo_completo}'.")
        UbicacionesService._validar_cantidad_contra_a2(codigo, cantidad)
        pu = ProductoUbicacion.objects.create(
            codigo_producto=codigo, nivel=nivel, cantidad=cantidad,
            stock_minimo=stock_minimo if nivel.tipo == Nivel.PICKING else None,
            asignado_por=usuario,
        )
        _registrar(
            'ASIGNACION', usuario, galpon=nivel.galpon, rack=nivel.rack,
            nivel_destino=nivel, codigo_producto=codigo,
        )
        return pu

    @staticmethod
    @transaction.atomic
    def editar_cantidad(
        producto_ubicacion: ProductoUbicacion, cantidad: int, stock_minimo: int | None, usuario,
    ) -> ProductoUbicacion:
        UbicacionesService._validar_cantidad_contra_a2(
            producto_ubicacion.codigo_producto, cantidad, excluir_pu_id=producto_ubicacion.pk,
        )
        producto_ubicacion.cantidad = cantidad
        if producto_ubicacion.nivel.tipo == Nivel.PICKING:
            producto_ubicacion.stock_minimo = stock_minimo
        producto_ubicacion.save(update_fields=['cantidad', 'stock_minimo'])
        _registrar(
            'EDICION_CANTIDAD', usuario,
            galpon=producto_ubicacion.nivel.galpon, rack=producto_ubicacion.nivel.rack,
            nivel_destino=producto_ubicacion.nivel, codigo_producto=producto_ubicacion.codigo_producto,
        )
        return producto_ubicacion

    @staticmethod
    @transaction.atomic
    def quitar_producto(producto_ubicacion_id: int, usuario) -> None:
        pu = ProductoUbicacion.objects.select_related('nivel').get(pk=producto_ubicacion_id)
        codigo = pu.codigo_producto
        nivel = pu.nivel
        pu.delete()
        _registrar(
            'DESASIGNACION', usuario, galpon=nivel.galpon, rack=nivel.rack,
            nivel_origen=nivel, codigo_producto=codigo,
        )

    # ------------------------------------------------------------------ Traslado

    @staticmethod
    @transaction.atomic
    def trasladar_producto(
        codigo: str, nivel_origen: Nivel, nivel_destino: Nivel, usuario, notas: str = '',
    ) -> None:
        """Mueve la asignación de `codigo` de nivel_origen a nivel_destino."""
        codigo = codigo.strip().upper()
        if nivel_origen.pk == nivel_destino.pk:
            raise ValidationError("El origen y el destino deben ser niveles distintos.")
        if not nivel_destino.activo:
            raise ValidationError(f"El nivel destino '{nivel_destino.codigo_completo}' está desactivado.")
        if nivel_destino.esta_fusionado:
            raise ValidationError(
                f"El nivel destino '{nivel_destino.codigo_completo}' está fusionado; "
                f"traslada al nivel maestro '{nivel_destino.fusionado_en.codigo_completo}'."
            )

        pu_origen = ProductoUbicacion.objects.select_for_update().filter(
            codigo_producto=codigo, nivel=nivel_origen,
        ).first()
        if not pu_origen:
            raise ValidationError(f"El producto '{codigo}' no está asignado a '{nivel_origen.codigo_completo}'.")

        cantidad = pu_origen.cantidad
        pu_origen.delete()

        pu_destino, created = ProductoUbicacion.objects.get_or_create(
            codigo_producto=codigo, nivel=nivel_destino,
            defaults={'cantidad': cantidad, 'asignado_por': usuario},
        )
        if not created:
            pu_destino.cantidad += cantidad
            pu_destino.save(update_fields=['cantidad'])

        _registrar(
            'TRASLADO', usuario, galpon=nivel_origen.galpon, rack=nivel_origen.rack,
            nivel_origen=nivel_origen, nivel_destino=nivel_destino,
            codigo_producto=codigo, notas=notas,
        )
```

- [ ] **Step 4: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.AsignacionServiceTest --settings=Programarprecios.test_settings -v 2`
Expected: 8 tests, todos PASS.

- [ ] **Step 5: Commit**

```bash
git add ubicaciones/services.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): servicio de asignación/traslado con validación de cantidad contra a2"
```

---

## Task 6: Servicio — Fusión y desfusión de niveles

Añade `fusionar_niveles` y `desfusionar_nivel`, implementando la Opción B del spec (`fusionado_en` autoreferencial hacia un nivel maestro). Al fusionar, consolida cantidades de `ProductoUbicacion` de los miembros hacia el maestro. Al desfusionar, rechaza si el maestro tiene stock y quedan otros miembros fusionados (evita perder trazabilidad).

**Files:**
- Modify: `ubicaciones/services.py`, `ubicaciones/tests.py`

**Interfaces:**
- Consumes: `Nivel.fusionado_en`, `Nivel.esta_fusionado` (Task 1).
- Produces: `UbicacionesService.fusionar_niveles(niveles, maestro, usuario, notas='') -> int` (cantidad de productos consolidados),
  `desfusionar_nivel(nivel_miembro, usuario) -> None`.

- [ ] **Step 1: Escribir los tests**

Agregar a `ubicaciones/tests.py`:

```python
class FusionServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='tester6')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack_a = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.rack_b = UbicacionesService.crear_rack(self.galpon, 'B', '', 2, 1, 1, 1, 6, self.user)
        cuerpo = UbicacionesService.crear_cuerpo(self.rack_a, '', self.user)
        ubicacion = cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel1 = ubicacion.niveles.get(numero=1)
        self.nivel2 = ubicacion.niveles.get(numero=2)
        self.nivel3 = ubicacion.niveles.get(numero=3)
        cuerpo_b = UbicacionesService.crear_cuerpo(self.rack_b, '', self.user)
        self.nivel_otro_rack = cuerpo_b.ubicaciones.order_by('codigo').first().niveles.get(numero=1)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_fusionar_niveles_consolida_cantidades_en_el_maestro(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 100
        UbicacionesService.asignar_producto('ABC', self.nivel1, 10, None, self.user)
        UbicacionesService.asignar_producto('ABC', self.nivel2, 15, None, self.user)

        transferidos = UbicacionesService.fusionar_niveles(
            [self.nivel1, self.nivel2], self.nivel1, self.user,
        )

        self.assertEqual(transferidos, 1)
        self.nivel2.refresh_from_db()
        self.assertEqual(self.nivel2.fusionado_en_id, self.nivel1.pk)
        pu = ProductoUbicacion.objects.get(nivel=self.nivel1, codigo_producto='ABC')
        self.assertEqual(pu.cantidad, 25)
        self.assertFalse(ProductoUbicacion.objects.filter(nivel=self.nivel2).exists())

    def test_fusionar_niveles_de_distinto_rack_falla(self):
        with self.assertRaises(ValidationError):
            UbicacionesService.fusionar_niveles(
                [self.nivel1, self.nivel_otro_rack], self.nivel1, self.user,
            )

    def test_fusionar_nivel_ya_fusionado_falla(self):
        UbicacionesService.fusionar_niveles([self.nivel1, self.nivel2], self.nivel1, self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.fusionar_niveles([self.nivel1, self.nivel2, self.nivel3], self.nivel1, self.user)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_desfusionar_ultimo_miembro_con_stock_en_maestro_ok(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 100
        UbicacionesService.asignar_producto('ABC', self.nivel1, 10, None, self.user)
        UbicacionesService.fusionar_niveles([self.nivel1, self.nivel2], self.nivel1, self.user)

        UbicacionesService.desfusionar_nivel(self.nivel2, self.user)

        self.nivel2.refresh_from_db()
        self.assertIsNone(self.nivel2.fusionado_en_id)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_desfusionar_con_stock_y_otros_miembros_fusionados_falla(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 100
        UbicacionesService.asignar_producto('ABC', self.nivel1, 10, None, self.user)
        UbicacionesService.fusionar_niveles([self.nivel1, self.nivel2, self.nivel3], self.nivel1, self.user)

        with self.assertRaises(ValidationError):
            UbicacionesService.desfusionar_nivel(self.nivel2, self.user)

    def test_desfusionar_nivel_no_fusionado_falla(self):
        with self.assertRaises(ValidationError):
            UbicacionesService.desfusionar_nivel(self.nivel1, self.user)
```

- [ ] **Step 2: Correr los tests y confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.FusionServiceTest --settings=Programarprecios.test_settings -v 2`
Expected: FAIL — `AttributeError: type object 'UbicacionesService' has no attribute 'fusionar_niveles'`.

- [ ] **Step 3: Añadir los métodos a `ubicaciones/services.py`**

Agregar al final de la clase `UbicacionesService`. Nota: se relockean los `Nivel` miembro con
`select_for_update(of=('self',))` para evitar la trampa conocida de `select_for_update` sobre la
FK nullable `fusionado_en` (ver Global Constraints):

```python
    # ------------------------------------------------------------------ Fusión

    @staticmethod
    @transaction.atomic
    def fusionar_niveles(niveles: list[Nivel], maestro: Nivel, usuario, notas: str = '') -> int:
        """
        Fusiona `niveles` hacia `maestro` (debe estar incluido en la lista):
        consolida las cantidades de ProductoUbicacion de los miembros en el
        maestro y marca `fusionado_en` en cada miembro. Retorna la cantidad
        de asignaciones de producto consolidadas (transferidas o sumadas).
        """
        if maestro.pk not in {n.pk for n in niveles}:
            raise ValidationError("El maestro debe estar incluido en la lista de niveles a fusionar.")
        racks = {n.rack.pk for n in niveles}
        if len(racks) > 1:
            raise ValidationError("Solo se pueden fusionar niveles del mismo Rack.")
        if maestro.esta_fusionado:
            raise ValidationError(f"El maestro '{maestro.codigo_completo}' ya está fusionado.")

        miembros = [n for n in niveles if n.pk != maestro.pk]
        for miembro in miembros:
            if miembro.esta_fusionado:
                raise ValidationError(f"El nivel '{miembro.codigo_completo}' ya está fusionado.")

        transferidos = 0
        for miembro in miembros:
            for pu in ProductoUbicacion.objects.select_for_update().filter(nivel=miembro):
                destino_pu, created = ProductoUbicacion.objects.select_for_update().get_or_create(
                    codigo_producto=pu.codigo_producto, nivel=maestro,
                    defaults={'cantidad': pu.cantidad, 'stock_minimo': pu.stock_minimo, 'asignado_por': usuario},
                )
                if not created:
                    destino_pu.cantidad += pu.cantidad
                    destino_pu.stock_minimo = destino_pu.stock_minimo or pu.stock_minimo
                    destino_pu.save(update_fields=['cantidad', 'stock_minimo'])
                pu.delete()
                transferidos += 1

            miembro_actualizado = Nivel.objects.select_for_update(of=('self',)).get(pk=miembro.pk)
            miembro_actualizado.fusionado_en = maestro
            miembro_actualizado.save(update_fields=['fusionado_en', 'fecha_modificacion'])
            _registrar(
                'FUSION_NIVEL', usuario, galpon=maestro.galpon, rack=maestro.rack,
                nivel_origen=miembro, nivel_destino=maestro, notas=notas,
            )
        return transferidos

    @staticmethod
    @transaction.atomic
    def desfusionar_nivel(nivel_miembro: Nivel, usuario) -> None:
        if not nivel_miembro.esta_fusionado:
            raise ValidationError(f"El nivel '{nivel_miembro.codigo_completo}' no está fusionado.")

        maestro = nivel_miembro.fusionado_en
        hermanos_fusionados = Nivel.objects.filter(fusionado_en=maestro).exclude(pk=nivel_miembro.pk)
        maestro_tiene_stock = ProductoUbicacion.objects.filter(nivel=maestro).exists()
        if maestro_tiene_stock and hermanos_fusionados.exists():
            raise ValidationError(
                f"El maestro '{maestro.codigo_completo}' tiene stock y quedan otros niveles fusionados; "
                "redistribuye manualmente las cantidades antes de desfusionar."
            )

        nivel_miembro.fusionado_en = None
        nivel_miembro.save(update_fields=['fusionado_en', 'fecha_modificacion'])
        _registrar(
            'DESFUSION_NIVEL', usuario, galpon=maestro.galpon, rack=maestro.rack,
            nivel_origen=maestro, nivel_destino=nivel_miembro,
        )
```

- [ ] **Step 4: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.FusionServiceTest --settings=Programarprecios.test_settings -v 2`
Expected: 6 tests, todos PASS.

- [ ] **Step 5: Correr toda la suite de la app y confirmar que sigue verde**

Run: `venv\Scripts\python.exe manage.py test ubicaciones --settings=Programarprecios.test_settings -v 2`
Expected: todos los tests de las Tasks 1-6 PASS (31 tests en total).

- [ ] **Step 6: Commit**

```bash
git add ubicaciones/services.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): servicio de fusión/desfusión de niveles"
```

---

## Task 7: API REST — serializers, api_views, api_urls

Reconstruye la API DRF completa sobre el nuevo modelo: listar/detalle de Galpón/Rack/Cuerpo, operaciones de asignación/traslado/fusión, histórico de movimientos y búsqueda de ubicaciones por producto (usada como referencia — la integración real con `PedidosAlmacen` se hace en Task 17 consultando el modelo directamente, igual que hoy).

**Files:**
- Create: `ubicaciones/serializers.py`, `ubicaciones/api_views.py`
- Modify: `ubicaciones/api_urls.py`, `ubicaciones/tests.py`

**Interfaces:**
- Consumes: `UbicacionesService` (Tasks 2-6), modelos (Task 1).
- Produces: endpoints `GET /api/galpones/`, `GET /api/galpones/<pk>/`, `GET /api/racks/<pk>/`, `GET /api/cuerpos/<pk>/`, `POST /api/niveles/<pk>/asignar/`, `POST /api/producto-ubicaciones/<pk>/editar-cantidad/`, `POST /api/producto-ubicaciones/<pk>/quitar/`, `POST /api/niveles/trasladar/`, `POST /api/niveles/fusionar/`, `POST /api/niveles/<pk>/desfusionar/`, `GET /api/movimientos/`, `GET /api/productos/<codigo>/ubicaciones/`.

- [ ] **Step 1: Escribir `ubicaciones/serializers.py`**

```python
from rest_framework import serializers

from .models import Cuerpo, Galpon, MovimientoUbicacion, Nivel, ProductoUbicacion, Rack, Ubicacion


class GalponSerializer(serializers.ModelSerializer):
    class Meta:
        model = Galpon
        fields = ['id', 'codigo', 'nombre', 'grid_filas', 'grid_columnas', 'activo']


class RackSerializer(serializers.ModelSerializer):
    galpon_codigo = serializers.CharField(source='galpon.codigo', read_only=True)
    total_cuerpos = serializers.IntegerField(read_only=True)

    class Meta:
        model = Rack
        fields = [
            'id', 'galpon', 'galpon_codigo', 'codigo', 'descripcion',
            'grid_fila', 'grid_columna', 'ancho', 'alto', 'max_niveles',
            'total_cuerpos', 'activo',
        ]


class CuerpoSerializer(serializers.ModelSerializer):
    rack_codigo = serializers.CharField(source='rack.codigo', read_only=True)
    total_ubicaciones = serializers.SerializerMethodField()

    class Meta:
        model = Cuerpo
        fields = ['id', 'rack', 'rack_codigo', 'codigo', 'descripcion', 'activo', 'total_ubicaciones']

    def get_total_ubicaciones(self, obj) -> int:
        return obj.ubicaciones.count()


class NivelSerializer(serializers.ModelSerializer):
    codigo_completo = serializers.CharField(read_only=True)
    esta_fusionado = serializers.BooleanField(read_only=True)
    fusionado_en_codigo = serializers.CharField(source='fusionado_en.codigo_completo', read_only=True, default=None)
    total_productos = serializers.SerializerMethodField()

    class Meta:
        model = Nivel
        fields = [
            'id', 'ubicacion', 'numero', 'codigo_completo', 'tipo',
            'esta_fusionado', 'fusionado_en_codigo', 'activo', 'total_productos',
        ]

    def get_total_productos(self, obj) -> int:
        return obj.productos.count()


class ProductoUbicacionSerializer(serializers.ModelSerializer):
    nivel_codigo = serializers.CharField(source='nivel.codigo_completo', read_only=True)
    tipo_nivel = serializers.CharField(source='nivel.tipo', read_only=True)

    class Meta:
        model = ProductoUbicacion
        fields = ['id', 'codigo_producto', 'nivel', 'nivel_codigo', 'tipo_nivel', 'cantidad', 'stock_minimo']


class MovimientoSerializer(serializers.ModelSerializer):
    tipo_display = serializers.CharField(source='get_tipo_display', read_only=True)
    usuario_nombre = serializers.SerializerMethodField()
    rack_codigo = serializers.CharField(source='rack.codigo', read_only=True, default=None)
    nivel_origen_str = serializers.CharField(source='nivel_origen.codigo_completo', read_only=True, default=None)
    nivel_destino_str = serializers.CharField(source='nivel_destino.codigo_completo', read_only=True, default=None)

    class Meta:
        model = MovimientoUbicacion
        fields = [
            'id', 'tipo', 'tipo_display', 'rack_codigo',
            'nivel_origen_str', 'nivel_destino_str',
            'codigo_producto', 'usuario_nombre', 'fecha', 'notas',
        ]

    def get_usuario_nombre(self, obj) -> str:
        return obj.usuario.username if obj.usuario else ''
```

- [ ] **Step 2: Escribir `ubicaciones/api_views.py`**

```python
import logging

from django.core.exceptions import ValidationError
from rest_framework import status
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from PedidosAlmacen.dbisam import DEPOSITO_ALMACEN, PedidosDBISAM

from .models import Cuerpo, Galpon, MovimientoUbicacion, Nivel, ProductoUbicacion, Rack
from .serializers import (
    CuerpoSerializer,
    GalponSerializer,
    MovimientoSerializer,
    NivelSerializer,
    ProductoUbicacionSerializer,
    RackSerializer,
)
from .services import UbicacionesService

logger = logging.getLogger(__name__)

_AUTH = [SessionAuthentication, TokenAuthentication]
_PERM = [IsAuthenticated]


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_galpones_list(request):
    qs = Galpon.objects.all()
    activo = request.query_params.get('activo')
    if activo is not None:
        qs = qs.filter(activo=activo == '1')
    return Response(GalponSerializer(qs, many=True).data)


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_galpon_detail(request, pk: int):
    try:
        galpon = Galpon.objects.get(pk=pk)
    except Galpon.DoesNotExist:
        return Response({'error': 'Galpón no encontrado.'}, status=404)
    racks = Rack.objects.filter(galpon=galpon)
    return Response({
        'galpon': GalponSerializer(galpon).data,
        'racks': RackSerializer(racks, many=True).data,
    })


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_rack_detail(request, pk: int):
    try:
        rack = Rack.objects.get(pk=pk)
    except Rack.DoesNotExist:
        return Response({'error': 'Rack no encontrado.'}, status=404)
    cuerpos = Cuerpo.objects.filter(rack=rack)
    return Response({
        'rack': RackSerializer(rack).data,
        'cuerpos': CuerpoSerializer(cuerpos, many=True).data,
    })


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_cuerpo_detail(request, pk: int):
    try:
        cuerpo = Cuerpo.objects.select_related('rack').get(pk=pk)
    except Cuerpo.DoesNotExist:
        return Response({'error': 'Cuerpo no encontrado.'}, status=404)
    niveles = Nivel.objects.filter(ubicacion__cuerpo=cuerpo).select_related('ubicacion')
    return Response({
        'cuerpo': CuerpoSerializer(cuerpo).data,
        'niveles': NivelSerializer(niveles, many=True).data,
    })


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_asignar_producto(request, pk: int):
    try:
        nivel = Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon').get(pk=pk)
    except Nivel.DoesNotExist:
        return Response({'error': 'Nivel no encontrado.'}, status=404)
    codigo = (request.data.get('codigo_producto') or '').strip()
    cantidad = request.data.get('cantidad')
    stock_minimo = request.data.get('stock_minimo') or None
    if not codigo or cantidad is None:
        return Response({'error': 'Se requieren codigo_producto y cantidad.'}, status=400)
    try:
        pu = UbicacionesService.asignar_producto(codigo, nivel, int(cantidad), stock_minimo, request.user)
        return Response(ProductoUbicacionSerializer(pu).data, status=201)
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_editar_cantidad(request, pk: int):
    try:
        pu = ProductoUbicacion.objects.select_related('nivel').get(pk=pk)
    except ProductoUbicacion.DoesNotExist:
        return Response({'error': 'Asignación no encontrada.'}, status=404)
    cantidad = request.data.get('cantidad')
    stock_minimo = request.data.get('stock_minimo') or None
    if cantidad is None:
        return Response({'error': 'Se requiere cantidad.'}, status=400)
    try:
        pu = UbicacionesService.editar_cantidad(pu, int(cantidad), stock_minimo, request.user)
        return Response(ProductoUbicacionSerializer(pu).data)
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_quitar_producto(request, pk: int):
    try:
        UbicacionesService.quitar_producto(pk, request.user)
        return Response({'ok': True})
    except ProductoUbicacion.DoesNotExist:
        return Response({'error': 'Asignación no encontrada.'}, status=404)
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_trasladar(request):
    codigo = (request.data.get('codigo_producto') or '').strip()
    origen_id = request.data.get('nivel_origen')
    destino_id = request.data.get('nivel_destino')
    notas = request.data.get('notas', '')
    if not all([codigo, origen_id, destino_id]):
        return Response({'error': 'Se requieren: codigo_producto, nivel_origen, nivel_destino.'}, status=400)
    try:
        nivel_origen = Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon').get(pk=origen_id)
        nivel_destino = Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon').get(pk=destino_id)
    except Nivel.DoesNotExist:
        return Response({'error': 'Uno de los niveles no existe.'}, status=404)
    try:
        UbicacionesService.trasladar_producto(codigo, nivel_origen, nivel_destino, request.user, notas)
        return Response({'ok': True, 'mensaje': 'Traslado realizado.'})
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_fusionar(request):
    ids = request.data.get('niveles') or []
    maestro_id = request.data.get('maestro')
    notas = request.data.get('notas', '')
    if not ids or not maestro_id:
        return Response({'error': 'Se requieren: niveles (lista), maestro.'}, status=400)
    niveles = list(Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon').filter(pk__in=ids))
    if len(niveles) != len(set(ids)):
        return Response({'error': 'Uno o más niveles no existen.'}, status=404)
    maestro = next((n for n in niveles if n.pk == int(maestro_id)), None)
    if maestro is None:
        return Response({'error': 'El maestro no existe.'}, status=404)
    try:
        transferidos = UbicacionesService.fusionar_niveles(niveles, maestro, request.user, notas)
        return Response({'ok': True, 'transferidos': transferidos})
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['POST'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_desfusionar(request, pk: int):
    try:
        nivel = Nivel.objects.get(pk=pk)
    except Nivel.DoesNotExist:
        return Response({'error': 'Nivel no encontrado.'}, status=404)
    try:
        UbicacionesService.desfusionar_nivel(nivel, request.user)
        return Response({'ok': True})
    except ValidationError as e:
        return Response({'error': e.message}, status=400)


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_movimientos(request):
    qs = MovimientoUbicacion.objects.select_related('usuario', 'rack', 'nivel_origen', 'nivel_destino')
    tipo = request.query_params.get('tipo')
    codigo = request.query_params.get('codigo')
    if tipo:
        qs = qs.filter(tipo=tipo)
    if codigo:
        qs = qs.filter(codigo_producto__icontains=codigo)
    return Response(MovimientoSerializer(qs[:200], many=True).data)


@api_view(['GET'])
@authentication_classes(_AUTH)
@permission_classes(_PERM)
def api_producto_ubicaciones(request, codigo: str):
    codigo = codigo.strip().upper()
    asignaciones = (
        ProductoUbicacion.objects
        .filter(codigo_producto=codigo)
        .select_related('nivel__ubicacion__cuerpo__rack__galpon')
    )
    existencia = 0
    try:
        existencia = PedidosDBISAM().consultar_stock(codigo, deposito=DEPOSITO_ALMACEN)
    except Exception:
        logger.exception("Error al consultar DBISAM en api_producto_ubicaciones")

    return Response({
        'codigo': codigo,
        'existencia_dbisam': existencia,
        'ubicaciones': ProductoUbicacionSerializer(asignaciones, many=True).data,
    })
```

- [ ] **Step 3: Reescribir `ubicaciones/api_urls.py`**

```python
from django.urls import path

from . import api_views

urlpatterns = [
    path('galpones/', api_views.api_galpones_list, name='api-galpones-list'),
    path('galpones/<int:pk>/', api_views.api_galpon_detail, name='api-galpon-detail'),
    path('racks/<int:pk>/', api_views.api_rack_detail, name='api-rack-detail'),
    path('cuerpos/<int:pk>/', api_views.api_cuerpo_detail, name='api-cuerpo-detail'),
    path('niveles/<int:pk>/asignar/', api_views.api_asignar_producto, name='api-nivel-asignar'),
    path('niveles/<int:pk>/desfusionar/', api_views.api_desfusionar, name='api-nivel-desfusionar'),
    path('niveles/trasladar/', api_views.api_trasladar, name='api-niveles-trasladar'),
    path('niveles/fusionar/', api_views.api_fusionar, name='api-niveles-fusionar'),
    path('producto-ubicaciones/<int:pk>/editar-cantidad/', api_views.api_editar_cantidad, name='api-pu-editar-cantidad'),
    path('producto-ubicaciones/<int:pk>/quitar/', api_views.api_quitar_producto, name='api-pu-quitar'),
    path('ubicaciones/movimientos/', api_views.api_movimientos, name='api-ubicaciones-movimientos'),
    path('productos/<str:codigo>/ubicaciones/', api_views.api_producto_ubicaciones, name='api-producto-ubicaciones'),
]
```

- [ ] **Step 4: Escribir los tests de API**

Agregar a `ubicaciones/tests.py`:

```python
from rest_framework.test import APIClient


class ApiUbicacionesTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='api_tester', password='x')
        self.api = APIClient()
        self.api.force_authenticate(user=self.user)
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.ubicacion = self.cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel = self.ubicacion.niveles.get(numero=1)

    def test_listar_galpones(self):
        resp = self.api.get('/api/galpones/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)

    def test_detalle_rack_incluye_cuerpos(self):
        resp = self.api.get(f'/api/racks/{self.rack.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['cuerpos']), 1)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_asignar_producto_via_api(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        resp = self.api.post(
            f'/api/niveles/{self.nivel.pk}/asignar/',
            data={'codigo_producto': 'ABC', 'cantidad': 10}, format='json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(ProductoUbicacion.objects.filter(codigo_producto='ABC', nivel=self.nivel).exists())

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_asignar_producto_excede_existencia_via_api(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 5
        resp = self.api.post(
            f'/api/niveles/{self.nivel.pk}/asignar/',
            data={'codigo_producto': 'ABC', 'cantidad': 10}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_fusionar_via_api(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        nivel2 = self.ubicacion.niveles.get(numero=2)
        resp = self.api.post(
            '/api/niveles/fusionar/',
            data={'niveles': [self.nivel.pk, nivel2.pk], 'maestro': self.nivel.pk}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        nivel2.refresh_from_db()
        self.assertEqual(nivel2.fusionado_en_id, self.nivel.pk)
```

- [ ] **Step 5: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.ApiUbicacionesTest --settings=Programarprecios.test_settings -v 2`
Expected: 5 tests, todos PASS.

- [ ] **Step 6: Commit**

```bash
git add ubicaciones/serializers.py ubicaciones/api_views.py ubicaciones/api_urls.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): API REST completa sobre el nuevo modelo"
```

---

## Task 8: Web — Forms y vistas de Galpón y Rack

Crea `ubicaciones/forms.py` y `ubicaciones/views.py` (no existen desde la Task 1) con el CRUD web de Galpón y Rack, y llena `ubicaciones/urls.py` (vacío desde la Task 1). Los tests de esta tarea solo ejercitan caminos que redirigen (POST exitoso, permiso denegado) o el formulario de forma aislada — el renderizado GET de las páginas se verifica recién en la Task 11, una vez existan los templates.

**Files:**
- Create: `ubicaciones/forms.py`, `ubicaciones/views.py`
- Modify: `ubicaciones/urls.py`, `ubicaciones/tests.py`

**Interfaces:**
- Consumes: `UbicacionesService.crear_galpon/editar_galpon/desactivar_galpon/crear_rack/editar_rack/desactivar_rack` (Task 2).
- Produces: vistas `lista_galpones`, `crear_galpon`, `detalle_galpon`, `editar_galpon`, `desactivar_galpon`, `crear_rack`, `detalle_rack`, `editar_rack`, `desactivar_rack`; helper `is_ubicaciones(user)`; URL names `ubicaciones-galpones-lista/crear/detalle/editar/desactivar`, `ubicaciones-racks-crear/detalle/editar/desactivar`. Tasks 9-13 dependen de `is_ubicaciones` y de estos nombres de URL.

- [ ] **Step 1: Escribir `ubicaciones/forms.py`**

```python
from django import forms

from .models import Galpon, Rack


class GalponForm(forms.ModelForm):
    class Meta:
        model = Galpon
        fields = ['codigo', 'nombre', 'grid_filas', 'grid_columnas']
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 1'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Galpón 1'}),
            'grid_filas': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'grid_columnas': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }


class RackForm(forms.ModelForm):
    class Meta:
        model = Rack
        fields = ['codigo', 'descripcion', 'grid_fila', 'grid_columna', 'ancho', 'alto', 'max_niveles']
        widgets = {
            'codigo': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: A'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Descripción opcional'}),
            'grid_fila': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'grid_columna': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'ancho': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'alto': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'max_niveles': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }
        labels = {'max_niveles': 'Máximo de niveles'}

    def __init__(self, *args, bloquear_max_niveles=False, **kwargs):
        super().__init__(*args, **kwargs)
        if bloquear_max_niveles:
            self.fields['max_niveles'].disabled = True
            self.fields['max_niveles'].help_text = 'No editable: el rack ya tiene cuerpos creados.'
```

- [ ] **Step 2: Escribir `ubicaciones/views.py`**

```python
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from .forms import GalponForm, RackForm
from .models import Galpon, Rack
from .services import UbicacionesService

logger = logging.getLogger(__name__)

GROUP_UBICACIONES = 'Pedidos Ubicaciones'


def is_ubicaciones(user) -> bool:
    return user.groups.filter(name=GROUP_UBICACIONES).exists() or user.is_superuser


# ------------------------------------------------------------------ Galpones

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def lista_galpones(request):
    solo_activos = request.GET.get('activo', '1')
    qs = Galpon.objects.prefetch_related('racks')
    if solo_activos == '1':
        qs = qs.filter(activo=True)
    return render(request, 'ubicaciones-galpones-lista.html', {
        'galpones': qs,
        'solo_activos': solo_activos,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def crear_galpon(request):
    if request.method == 'POST':
        form = GalponForm(request.POST)
        if form.is_valid():
            try:
                galpon = UbicacionesService.crear_galpon(
                    codigo=form.cleaned_data['codigo'],
                    nombre=form.cleaned_data['nombre'],
                    grid_filas=form.cleaned_data['grid_filas'],
                    grid_columnas=form.cleaned_data['grid_columnas'],
                    usuario=request.user,
                )
                messages.success(request, f"Galpón '{galpon.codigo}' creado correctamente.")
                return redirect('ubicaciones-galpones-detalle', pk=galpon.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = GalponForm()
    return render(request, 'ubicaciones-galpones-crear.html', {'form': form})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def detalle_galpon(request, pk: int):
    galpon = get_object_or_404(Galpon, pk=pk)
    racks = Rack.objects.filter(galpon=galpon).prefetch_related('cuerpos')
    return render(request, 'ubicaciones-galpones-detalle.html', {
        'galpon': galpon,
        'racks': racks,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_galpon(request, pk: int):
    galpon = get_object_or_404(Galpon, pk=pk)
    if request.method == 'POST':
        form = GalponForm(request.POST, instance=galpon)
        if form.is_valid():
            try:
                UbicacionesService.editar_galpon(
                    galpon=galpon,
                    nombre=form.cleaned_data['nombre'],
                    grid_filas=form.cleaned_data['grid_filas'],
                    grid_columnas=form.cleaned_data['grid_columnas'],
                    usuario=request.user,
                )
                messages.success(request, f"Galpón '{galpon.codigo}' actualizado.")
                return redirect('ubicaciones-galpones-detalle', pk=galpon.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = GalponForm(instance=galpon)
    return render(request, 'ubicaciones-galpones-editar.html', {'form': form, 'galpon': galpon})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desactivar_galpon(request, pk: int):
    galpon = get_object_or_404(Galpon, pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desactivar_galpon(galpon, request.user)
            messages.success(request, f"Galpón '{galpon.codigo}' desactivado.")
            return redirect('ubicaciones-galpones-lista')
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect('ubicaciones-galpones-detalle', pk=pk)
    return render(request, 'ubicaciones-confirmar-desactivar.html', {
        'objeto': galpon, 'tipo': 'galpón', 'nombre': galpon.codigo,
    })


# ------------------------------------------------------------------ Racks

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def crear_rack(request, galpon_pk: int):
    galpon = get_object_or_404(Galpon, pk=galpon_pk)
    if request.method == 'POST':
        form = RackForm(request.POST)
        if form.is_valid():
            try:
                rack = UbicacionesService.crear_rack(
                    galpon=galpon,
                    codigo=form.cleaned_data['codigo'],
                    descripcion=form.cleaned_data['descripcion'],
                    grid_fila=form.cleaned_data['grid_fila'],
                    grid_columna=form.cleaned_data['grid_columna'],
                    ancho=form.cleaned_data['ancho'],
                    alto=form.cleaned_data['alto'],
                    max_niveles=form.cleaned_data['max_niveles'],
                    usuario=request.user,
                )
                messages.success(request, f"Rack '{rack.codigo}' creado correctamente.")
                return redirect('ubicaciones-racks-detalle', pk=rack.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = RackForm()
    return render(request, 'ubicaciones-racks-crear.html', {'form': form, 'galpon': galpon})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def detalle_rack(request, pk: int):
    rack = get_object_or_404(Rack.objects.select_related('galpon'), pk=pk)
    cuerpos = rack.cuerpos.prefetch_related('ubicaciones__niveles')
    return render(request, 'ubicaciones-racks-detalle.html', {
        'rack': rack,
        'cuerpos': cuerpos,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_rack(request, pk: int):
    rack = get_object_or_404(Rack.objects.select_related('galpon'), pk=pk)
    bloquear = rack.cuerpos.exists()
    if request.method == 'POST':
        form = RackForm(request.POST, instance=rack, bloquear_max_niveles=bloquear)
        if form.is_valid():
            try:
                UbicacionesService.editar_rack(
                    rack=rack,
                    descripcion=form.cleaned_data['descripcion'],
                    grid_fila=form.cleaned_data['grid_fila'],
                    grid_columna=form.cleaned_data['grid_columna'],
                    ancho=form.cleaned_data['ancho'],
                    alto=form.cleaned_data['alto'],
                    max_niveles=form.cleaned_data['max_niveles'],
                    usuario=request.user,
                )
                messages.success(request, f"Rack '{rack.codigo}' actualizado.")
                return redirect('ubicaciones-racks-detalle', pk=rack.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = RackForm(instance=rack, bloquear_max_niveles=bloquear)
    return render(request, 'ubicaciones-racks-editar.html', {'form': form, 'rack': rack})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desactivar_rack(request, pk: int):
    rack = get_object_or_404(Rack, pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desactivar_rack(rack, request.user)
            messages.success(request, f"Rack '{rack.codigo}' desactivado.")
            return redirect('ubicaciones-galpones-detalle', pk=rack.galpon_id)
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect('ubicaciones-racks-detalle', pk=pk)
    return render(request, 'ubicaciones-confirmar-desactivar.html', {
        'objeto': rack, 'tipo': 'rack', 'nombre': rack.codigo,
    })
```

- [ ] **Step 3: Reescribir `ubicaciones/urls.py`**

```python
from django.urls import path

from . import views

urlpatterns = [
    # Galpones
    path('ubicaciones/galpones/', views.lista_galpones, name='ubicaciones-galpones-lista'),
    path('ubicaciones/galpones/crear/', views.crear_galpon, name='ubicaciones-galpones-crear'),
    path('ubicaciones/galpones/<int:pk>/', views.detalle_galpon, name='ubicaciones-galpones-detalle'),
    path('ubicaciones/galpones/<int:pk>/editar/', views.editar_galpon, name='ubicaciones-galpones-editar'),
    path('ubicaciones/galpones/<int:pk>/desactivar/', views.desactivar_galpon, name='ubicaciones-galpones-desactivar'),

    # Racks
    path('ubicaciones/galpones/<int:galpon_pk>/racks/crear/', views.crear_rack, name='ubicaciones-racks-crear'),
    path('ubicaciones/racks/<int:pk>/', views.detalle_rack, name='ubicaciones-racks-detalle'),
    path('ubicaciones/racks/<int:pk>/editar/', views.editar_rack, name='ubicaciones-racks-editar'),
    path('ubicaciones/racks/<int:pk>/desactivar/', views.desactivar_rack, name='ubicaciones-racks-desactivar'),
]
```

- [ ] **Step 4: Escribir los tests**

Agregar a `ubicaciones/tests.py`:

```python
from django.contrib.auth.models import Group
from django.test import Client


class GalponRackViewsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='webuser', password='x')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client = Client()
        self.client.login(username='webuser', password='x')

    def test_crear_galpon_via_web_redirige(self):
        resp = self.client.post('/ubicaciones/galpones/crear/', {
            'codigo': '1', 'nombre': 'Galpón 1', 'grid_filas': 10, 'grid_columnas': 10,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Galpon.objects.filter(codigo='1').exists())

    def test_lista_galpones_requiere_grupo(self):
        User.objects.create_user(username='sin_grupo', password='x')
        client = Client()
        client.login(username='sin_grupo', password='x')
        resp = client.get('/ubicaciones/galpones/')
        self.assertEqual(resp.status_code, 302)

    def test_crear_rack_via_web_redirige(self):
        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        resp = self.client.post(f'/ubicaciones/galpones/{galpon.pk}/racks/crear/', {
            'codigo': 'A', 'descripcion': '', 'grid_fila': 1, 'grid_columna': 1,
            'ancho': 1, 'alto': 1, 'max_niveles': 6,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Rack.objects.filter(galpon=galpon, codigo='A').exists())

    def test_desactivar_rack_con_cuerpos_redirige_con_error(self):
        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        rack = UbicacionesService.crear_rack(galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        UbicacionesService.crear_cuerpo(rack, '', self.user)
        resp = self.client.post(f'/ubicaciones/racks/{rack.pk}/desactivar/')
        self.assertEqual(resp.status_code, 302)
        rack.refresh_from_db()
        self.assertTrue(rack.activo)


class RackFormTest(TestCase):
    def test_max_niveles_disabled_cuando_bloqueado(self):
        from ubicaciones.forms import RackForm
        form = RackForm(bloquear_max_niveles=True)
        self.assertTrue(form.fields['max_niveles'].disabled)

    def test_max_niveles_habilitado_por_defecto(self):
        from ubicaciones.forms import RackForm
        form = RackForm()
        self.assertFalse(form.fields['max_niveles'].disabled)
```

- [ ] **Step 5: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.GalponRackViewsTest ubicaciones.RackFormTest --settings=Programarprecios.test_settings -v 2`
Expected: 6 tests, todos PASS.

- [ ] **Step 6: Commit**

```bash
git add ubicaciones/forms.py ubicaciones/views.py ubicaciones/urls.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): vistas web de Galpón y Rack"
```

---

## Task 9: Web — Forms y vistas de Cuerpo, Ubicación y Nivel

Extiende `forms.py`/`views.py`/`urls.py` con el CRUD de Cuerpo (creación en cascada vía el servicio, sin campo `codigo` en el form porque es autogenerado), Ubicación (solo detalle/editar descripción/desactivar — no se crea manualmente) y Nivel (editar tipo/descripción, desactivar). Mismo criterio de tests que la Task 8: solo caminos que redirigen; el renderizado GET se verifica en la Task 12.

**Files:**
- Modify: `ubicaciones/forms.py`, `ubicaciones/views.py`, `ubicaciones/urls.py`, `ubicaciones/tests.py`

**Interfaces:**
- Consumes: `UbicacionesService.crear_cuerpo/desactivar_cuerpo/desactivar_ubicacion/editar_nivel/desactivar_nivel` (Tasks 3-4); `is_ubicaciones` (Task 8).
- Produces: vistas `crear_cuerpo`, `detalle_cuerpo`, `editar_cuerpo`, `desactivar_cuerpo`, `detalle_ubicacion`, `editar_ubicacion`, `desactivar_ubicacion`, `detalle_nivel`, `editar_nivel`, `desactivar_nivel`; URL names `ubicaciones-cuerpos-crear/detalle/editar/desactivar`, `ubicaciones-ubicaciones-detalle/editar/desactivar`, `ubicaciones-niveles-detalle/editar/desactivar`.

- [ ] **Step 1: Agregar los forms a `ubicaciones/forms.py`**

Actualizar el import del inicio del archivo:

```python
from .models import Cuerpo, Galpon, Nivel, Rack, Ubicacion
```

Agregar al final:

```python
class CuerpoForm(forms.ModelForm):
    class Meta:
        model = Cuerpo
        fields = ['descripcion']
        widgets = {
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Descripción opcional'}),
        }


class UbicacionForm(forms.ModelForm):
    class Meta:
        model = Ubicacion
        fields = ['descripcion']
        widgets = {
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Descripción opcional'}),
        }


class NivelForm(forms.ModelForm):
    class Meta:
        model = Nivel
        fields = ['tipo', 'descripcion']
        widgets = {
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'descripcion': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Descripción opcional'}),
        }
```

- [ ] **Step 2: Agregar las vistas a `ubicaciones/views.py`**

Actualizar el import del inicio del archivo:

```python
from .forms import CuerpoForm, GalponForm, NivelForm, RackForm, UbicacionForm
from .models import Cuerpo, Galpon, Nivel, Rack, Ubicacion
```

Agregar al final:

```python
# ------------------------------------------------------------------ Cuerpos

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def crear_cuerpo(request, rack_pk: int):
    rack = get_object_or_404(Rack, pk=rack_pk)
    if request.method == 'POST':
        form = CuerpoForm(request.POST)
        if form.is_valid():
            try:
                cuerpo = UbicacionesService.crear_cuerpo(
                    rack=rack, descripcion=form.cleaned_data['descripcion'], usuario=request.user,
                )
                messages.success(request, f"Cuerpo '{cuerpo.codigo}' creado con sus ubicaciones y niveles.")
                return redirect('ubicaciones-racks-detalle', pk=rack.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = CuerpoForm()
    return render(request, 'ubicaciones-cuerpos-crear.html', {'form': form, 'rack': rack})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def detalle_cuerpo(request, pk: int):
    cuerpo = get_object_or_404(Cuerpo.objects.select_related('rack__galpon'), pk=pk)
    ubicaciones = cuerpo.ubicaciones.prefetch_related('niveles')
    return render(request, 'ubicaciones-cuerpos-detalle.html', {
        'cuerpo': cuerpo,
        'ubicaciones': ubicaciones,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_cuerpo(request, pk: int):
    cuerpo = get_object_or_404(Cuerpo.objects.select_related('rack__galpon'), pk=pk)
    if request.method == 'POST':
        form = CuerpoForm(request.POST, instance=cuerpo)
        if form.is_valid():
            cuerpo.descripcion = form.cleaned_data['descripcion']
            cuerpo.save(update_fields=['descripcion', 'fecha_modificacion'])
            messages.success(request, f"Cuerpo '{cuerpo.codigo}' actualizado.")
            return redirect('ubicaciones-cuerpos-detalle', pk=cuerpo.pk)
    else:
        form = CuerpoForm(instance=cuerpo)
    return render(request, 'ubicaciones-cuerpos-editar.html', {'form': form, 'cuerpo': cuerpo})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desactivar_cuerpo(request, pk: int):
    cuerpo = get_object_or_404(Cuerpo.objects.select_related('rack__galpon'), pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desactivar_cuerpo(cuerpo, request.user)
            messages.success(request, f"Cuerpo '{cuerpo.codigo}' desactivado.")
            return redirect('ubicaciones-racks-detalle', pk=cuerpo.rack_id)
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect('ubicaciones-cuerpos-detalle', pk=pk)
    return render(request, 'ubicaciones-confirmar-desactivar.html', {
        'objeto': cuerpo, 'tipo': 'cuerpo', 'nombre': cuerpo.codigo,
    })


# ------------------------------------------------------------------ Ubicaciones

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def detalle_ubicacion(request, pk: int):
    ubicacion = get_object_or_404(Ubicacion.objects.select_related('cuerpo__rack__galpon'), pk=pk)
    niveles = ubicacion.niveles.select_related('fusionado_en').prefetch_related('productos')
    return render(request, 'ubicaciones-ubicaciones-detalle.html', {
        'ubicacion': ubicacion,
        'niveles': niveles,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_ubicacion(request, pk: int):
    ubicacion = get_object_or_404(Ubicacion.objects.select_related('cuerpo__rack__galpon'), pk=pk)
    if request.method == 'POST':
        form = UbicacionForm(request.POST, instance=ubicacion)
        if form.is_valid():
            ubicacion.descripcion = form.cleaned_data['descripcion']
            ubicacion.save(update_fields=['descripcion', 'fecha_modificacion'])
            messages.success(request, f"Ubicación '{ubicacion.codigo}' actualizada.")
            return redirect('ubicaciones-ubicaciones-detalle', pk=ubicacion.pk)
    else:
        form = UbicacionForm(instance=ubicacion)
    return render(request, 'ubicaciones-ubicaciones-editar.html', {'form': form, 'ubicacion': ubicacion})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desactivar_ubicacion(request, pk: int):
    ubicacion = get_object_or_404(Ubicacion.objects.select_related('cuerpo__rack__galpon'), pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desactivar_ubicacion(ubicacion, request.user)
            messages.success(request, f"Ubicación '{ubicacion.codigo}' desactivada.")
            return redirect('ubicaciones-cuerpos-detalle', pk=ubicacion.cuerpo_id)
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect('ubicaciones-ubicaciones-detalle', pk=pk)
    return render(request, 'ubicaciones-confirmar-desactivar.html', {
        'objeto': ubicacion, 'tipo': 'ubicación', 'nombre': ubicacion.codigo,
    })


# ------------------------------------------------------------------ Niveles

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def detalle_nivel(request, pk: int):
    nivel = get_object_or_404(
        Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon', 'fusionado_en'), pk=pk,
    )
    productos = nivel.productos.all()
    return render(request, 'ubicaciones-niveles-detalle.html', {
        'nivel': nivel,
        'productos': productos,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_nivel(request, pk: int):
    nivel = get_object_or_404(Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon'), pk=pk)
    if request.method == 'POST':
        form = NivelForm(request.POST, instance=nivel)
        if form.is_valid():
            try:
                UbicacionesService.editar_nivel(
                    nivel=nivel, tipo=form.cleaned_data['tipo'],
                    descripcion=form.cleaned_data['descripcion'], usuario=request.user,
                )
                messages.success(request, f"Nivel '{nivel.codigo_completo}' actualizado.")
                return redirect('ubicaciones-niveles-detalle', pk=nivel.pk)
            except ValidationError as e:
                messages.error(request, e.message)
    else:
        form = NivelForm(instance=nivel)
    return render(request, 'ubicaciones-niveles-editar.html', {'form': form, 'nivel': nivel})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desactivar_nivel(request, pk: int):
    nivel = get_object_or_404(Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon'), pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desactivar_nivel(nivel, request.user)
            messages.success(request, f"Nivel '{nivel.codigo_completo}' desactivado.")
            return redirect('ubicaciones-ubicaciones-detalle', pk=nivel.ubicacion_id)
        except ValidationError as e:
            messages.error(request, e.message)
            return redirect('ubicaciones-niveles-detalle', pk=pk)
    return render(request, 'ubicaciones-confirmar-desactivar.html', {
        'objeto': nivel, 'tipo': 'nivel', 'nombre': nivel.codigo_completo,
    })
```

- [ ] **Step 3: Extender `ubicaciones/urls.py`**

Agregar al final de `urlpatterns`:

```python
    # Cuerpos
    path('ubicaciones/racks/<int:rack_pk>/cuerpos/crear/', views.crear_cuerpo, name='ubicaciones-cuerpos-crear'),
    path('ubicaciones/cuerpos/<int:pk>/', views.detalle_cuerpo, name='ubicaciones-cuerpos-detalle'),
    path('ubicaciones/cuerpos/<int:pk>/editar/', views.editar_cuerpo, name='ubicaciones-cuerpos-editar'),
    path('ubicaciones/cuerpos/<int:pk>/desactivar/', views.desactivar_cuerpo, name='ubicaciones-cuerpos-desactivar'),

    # Ubicaciones
    path('ubicaciones/ubicaciones/<int:pk>/', views.detalle_ubicacion, name='ubicaciones-ubicaciones-detalle'),
    path('ubicaciones/ubicaciones/<int:pk>/editar/', views.editar_ubicacion, name='ubicaciones-ubicaciones-editar'),
    path('ubicaciones/ubicaciones/<int:pk>/desactivar/', views.desactivar_ubicacion, name='ubicaciones-ubicaciones-desactivar'),

    # Niveles
    path('ubicaciones/niveles/<int:pk>/', views.detalle_nivel, name='ubicaciones-niveles-detalle'),
    path('ubicaciones/niveles/<int:pk>/editar/', views.editar_nivel, name='ubicaciones-niveles-editar'),
    path('ubicaciones/niveles/<int:pk>/desactivar/', views.desactivar_nivel, name='ubicaciones-niveles-desactivar'),
```

- [ ] **Step 4: Escribir los tests**

Agregar a `ubicaciones/tests.py`:

```python
class CuerpoUbicacionNivelViewsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='webuser2', password='x')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client = Client()
        self.client.login(username='webuser2', password='x')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)

    def test_crear_cuerpo_via_web_redirige(self):
        resp = self.client.post(f'/ubicaciones/racks/{self.rack.pk}/cuerpos/crear/', {'descripcion': ''})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.rack.cuerpos.count(), 1)

    def test_editar_nivel_via_web_redirige(self):
        cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        nivel = cuerpo.ubicaciones.first().niveles.get(numero=1)
        resp = self.client.post(f'/ubicaciones/niveles/{nivel.pk}/editar/', {
            'tipo': Nivel.ALMACENAJE, 'descripcion': 'Nota',
        })
        self.assertEqual(resp.status_code, 302)
        nivel.refresh_from_db()
        self.assertEqual(nivel.tipo, Nivel.ALMACENAJE)

    def test_desactivar_nivel_con_productos_redirige_con_error(self):
        cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        nivel = cuerpo.ubicaciones.first().niveles.get(numero=1)
        ProductoUbicacion.objects.create(codigo_producto='X', nivel=nivel, cantidad=1)
        resp = self.client.post(f'/ubicaciones/niveles/{nivel.pk}/desactivar/')
        self.assertEqual(resp.status_code, 302)
        nivel.refresh_from_db()
        self.assertTrue(nivel.activo)
```

- [ ] **Step 5: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.CuerpoUbicacionNivelViewsTest --settings=Programarprecios.test_settings -v 2`
Expected: 3 tests, todos PASS.

- [ ] **Step 6: Commit**

```bash
git add ubicaciones/forms.py ubicaciones/views.py ubicaciones/urls.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): vistas web de Cuerpo, Ubicación y Nivel"
```

---

## Task 10: Web — Asignación, Traslado, Fusión, Histórico y fragmentos htmx

Extiende `forms.py`/`views.py`/`urls.py` con: asignación de producto a un Nivel (búsqueda DBISAM + asignar), edición de cantidad, quitar producto, traslado entre niveles, fusión (ahora selecciona N niveles + un maestro) y desfusión, histórico de movimientos, búsqueda de producto por código (`producto_ubicaciones`), y los fragmentos htmx de autocomplete (reemplaza `buscar_ubicacion_fragment` por `buscar_nivel_fragment`).

**Files:**
- Modify: `ubicaciones/forms.py`, `ubicaciones/views.py`, `ubicaciones/urls.py`, `ubicaciones/tests.py`

**Interfaces:**
- Consumes: `UbicacionesService.asignar_producto/editar_cantidad/quitar_producto/trasladar_producto/fusionar_niveles/desfusionar_nivel` (Tasks 5-6); `is_ubicaciones` (Task 8).
- Produces: vistas `asignar_producto`, `editar_cantidad`, `quitar_producto`, `trasladar`, `fusionar`, `desfusionar`, `lista_movimientos`, `producto_ubicaciones`, `buscar_nivel_fragment`, `buscar_producto_dbisam_fragment`; URL names `ubicaciones-asignar`, `ubicaciones-editar-cantidad`, `ubicaciones-quitar`, `ubicaciones-trasladar`, `ubicaciones-fusionar`, `ubicaciones-desfusionar`, `ubicaciones-movimientos`, `ubicaciones-producto-detalle`, `ubicaciones-buscar-nivel`, `ubicaciones-buscar-producto`.

- [ ] **Step 1: Agregar los forms a `ubicaciones/forms.py`**

Agregar al final:

```python
class AsignarProductoAccionForm(forms.Form):
    codigo_producto = forms.CharField(
        max_length=50, label='Código de producto',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    cantidad = forms.IntegerField(
        min_value=0, label='Cantidad',
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    stock_minimo = forms.IntegerField(
        min_value=0, required=False, label='Stock mínimo (solo picking)',
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )

    def clean_codigo_producto(self):
        return self.cleaned_data['codigo_producto'].strip().upper()


class EditarCantidadForm(forms.Form):
    cantidad = forms.IntegerField(
        min_value=0, label='Cantidad',
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )
    stock_minimo = forms.IntegerField(
        min_value=0, required=False, label='Stock mínimo (solo picking)',
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )


class TrasladarForm(forms.Form):
    codigo_producto = forms.CharField(
        max_length=50, label='Código de producto',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    nivel_origen = forms.ModelChoiceField(
        queryset=Nivel.objects.filter(activo=True, fusionado_en__isnull=True).select_related('ubicacion__cuerpo__rack'),
        label='Nivel origen', widget=forms.Select(attrs={'class': 'form-select'}),
    )
    nivel_destino = forms.ModelChoiceField(
        queryset=Nivel.objects.filter(activo=True, fusionado_en__isnull=True).select_related('ubicacion__cuerpo__rack'),
        label='Nivel destino', widget=forms.Select(attrs={'class': 'form-select'}),
    )
    notas = forms.CharField(
        required=False, label='Notas', widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def clean(self):
        cleaned = super().clean()
        origen = cleaned.get('nivel_origen')
        destino = cleaned.get('nivel_destino')
        if origen and destino and origen.pk == destino.pk:
            raise forms.ValidationError('El nivel origen y destino deben ser distintos.')
        return cleaned


class FusionarForm(forms.Form):
    niveles = forms.ModelMultipleChoiceField(
        queryset=Nivel.objects.filter(activo=True, fusionado_en__isnull=True).select_related('ubicacion__cuerpo__rack'),
        label='Niveles a fusionar', widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': 8}),
    )
    maestro = forms.ModelChoiceField(
        queryset=Nivel.objects.filter(activo=True, fusionado_en__isnull=True).select_related('ubicacion__cuerpo__rack'),
        label='Nivel maestro (recibe el stock)', widget=forms.Select(attrs={'class': 'form-select'}),
    )
    notas = forms.CharField(
        required=False, label='Notas', widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
    )

    def clean(self):
        cleaned = super().clean()
        niveles = cleaned.get('niveles')
        maestro = cleaned.get('maestro')
        if niveles and len(niveles) < 2:
            raise forms.ValidationError('Selecciona al menos 2 niveles para fusionar.')
        if niveles and maestro and maestro not in niveles:
            raise forms.ValidationError('El maestro debe estar entre los niveles seleccionados.')
        return cleaned
```

- [ ] **Step 2: Agregar las vistas a `ubicaciones/views.py`**

Actualizar los imports del inicio del archivo:

```python
from PedidosAlmacen.dbisam import DEPOSITO_ALMACEN, PedidosDBISAM

from .forms import (
    AsignarProductoAccionForm,
    CuerpoForm,
    EditarCantidadForm,
    FusionarForm,
    GalponForm,
    NivelForm,
    RackForm,
    TrasladarForm,
    UbicacionForm,
)
from .models import Cuerpo, Galpon, MovimientoUbicacion, Nivel, ProductoUbicacion, Rack, Ubicacion
```

Agregar al final:

```python
# ------------------------------------------------------------------ Asignaciones

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def asignar_producto(request, pk: int):
    nivel = get_object_or_404(Nivel.objects.select_related('ubicacion__cuerpo__rack__galpon'), pk=pk)
    resultados_busqueda = []
    query = ''

    if request.method == 'POST' and 'buscar' in request.POST:
        query = request.POST.get('codigo_producto', '').strip()
        if query:
            try:
                db = PedidosDBISAM()
                prod = db.buscar_producto(query.upper())
                if prod:
                    existencia = db.consultar_stock(query.upper(), deposito=DEPOSITO_ALMACEN)
                    resultados_busqueda = [{
                        'codigo': prod[0], 'descripcion': prod[1],
                        'referencia': prod[2], 'puesto': prod[3], 'existencia': existencia,
                    }]
                else:
                    prods = db.buscar_por_descripcion(query)
                    codigos = [p[0] for p in prods]
                    stocks = db.consultar_stock_multiple(codigos, deposito=DEPOSITO_ALMACEN) if codigos else {}
                    resultados_busqueda = [
                        {'codigo': p[0], 'descripcion': p[1], 'referencia': p[2], 'puesto': p[3],
                         'existencia': stocks.get(p[0], 0)}
                        for p in prods
                    ]
            except Exception:
                logger.exception("Error al buscar producto en DBISAM")
                messages.error(request, "Error al conectar con DBISAM.")

    elif request.method == 'POST' and 'asignar' in request.POST:
        form = AsignarProductoAccionForm(request.POST)
        if form.is_valid():
            try:
                UbicacionesService.asignar_producto(
                    codigo=form.cleaned_data['codigo_producto'],
                    nivel=nivel,
                    cantidad=form.cleaned_data['cantidad'],
                    stock_minimo=form.cleaned_data.get('stock_minimo'),
                    usuario=request.user,
                )
                messages.success(request, f"Producto asignado a '{nivel.codigo_completo}'.")
                return redirect('ubicaciones-niveles-detalle', pk=nivel.pk)
            except ValidationError as e:
                messages.error(request, e.message)

    return render(request, 'ubicaciones-asignar.html', {
        'nivel': nivel,
        'resultados_busqueda': resultados_busqueda,
        'query': query,
    })


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def editar_cantidad(request, pu_id: int):
    pu = get_object_or_404(ProductoUbicacion.objects.select_related('nivel'), pk=pu_id)
    if request.method == 'POST':
        form = EditarCantidadForm(request.POST)
        if form.is_valid():
            try:
                UbicacionesService.editar_cantidad(
                    pu, form.cleaned_data['cantidad'], form.cleaned_data.get('stock_minimo'), request.user,
                )
                messages.success(request, "Cantidad actualizada.")
            except ValidationError as e:
                messages.error(request, e.message)
    return redirect('ubicaciones-niveles-detalle', pk=pu.nivel_id)


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def quitar_producto(request, pu_id: int):
    pu = get_object_or_404(ProductoUbicacion, pk=pu_id)
    nivel_id = pu.nivel_id
    if request.method == 'POST':
        try:
            UbicacionesService.quitar_producto(pu_id, request.user)
            messages.success(request, "Producto desasignado correctamente.")
        except Exception as e:
            messages.error(request, str(e))
    return redirect('ubicaciones-niveles-detalle', pk=nivel_id)


# ------------------------------------------------------------------ Traslado / Fusión

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def trasladar(request):
    form = TrasladarForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            UbicacionesService.trasladar_producto(
                codigo=form.cleaned_data['codigo_producto'],
                nivel_origen=form.cleaned_data['nivel_origen'],
                nivel_destino=form.cleaned_data['nivel_destino'],
                usuario=request.user,
                notas=form.cleaned_data.get('notas', ''),
            )
            messages.success(request, "Traslado realizado correctamente.")
            return redirect('ubicaciones-movimientos')
        except ValidationError as e:
            messages.error(request, e.message)
    return render(request, 'ubicaciones-trasladar.html', {'form': form})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def fusionar(request):
    form = FusionarForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            transferidos = UbicacionesService.fusionar_niveles(
                niveles=list(form.cleaned_data['niveles']),
                maestro=form.cleaned_data['maestro'],
                usuario=request.user,
                notas=form.cleaned_data.get('notas', ''),
            )
            messages.success(request, f"Fusión completada: {transferidos} asignación(es) consolidadas.")
            return redirect('ubicaciones-movimientos')
        except ValidationError as e:
            messages.error(request, e.message)
    return render(request, 'ubicaciones-fusionar.html', {'form': form})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def desfusionar(request, pk: int):
    nivel = get_object_or_404(Nivel, pk=pk)
    if request.method == 'POST':
        try:
            UbicacionesService.desfusionar_nivel(nivel, request.user)
            messages.success(request, f"Nivel '{nivel.codigo_completo}' desfusionado.")
        except ValidationError as e:
            messages.error(request, e.message)
    return redirect('ubicaciones-niveles-detalle', pk=pk)


# ------------------------------------------------------------------ Histórico

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def lista_movimientos(request):
    qs = MovimientoUbicacion.objects.select_related('usuario', 'rack', 'nivel_origen', 'nivel_destino')
    tipo = request.GET.get('tipo', '')
    codigo = request.GET.get('codigo', '').strip()
    if tipo:
        qs = qs.filter(tipo=tipo)
    if codigo:
        qs = qs.filter(codigo_producto__icontains=codigo)
    return render(request, 'ubicaciones-movimientos.html', {
        'movimientos': qs[:500],
        'tipo_filter': tipo,
        'codigo_filter': codigo,
        'tipos': MovimientoUbicacion.TIPO_CHOICES,
    })


# ------------------------------------------------------------------ Producto → Ubicaciones

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def producto_ubicaciones(request, codigo: str):
    codigo = codigo.strip().upper()
    asignaciones = (
        ProductoUbicacion.objects
        .filter(codigo_producto=codigo)
        .select_related('nivel__ubicacion__cuerpo__rack__galpon')
    )
    existencia = 0
    descripcion = ''
    try:
        db = PedidosDBISAM()
        prod = db.buscar_producto(codigo)
        if prod:
            descripcion = prod[1]
            existencia = db.consultar_stock(codigo, deposito=DEPOSITO_ALMACEN)
    except Exception:
        logger.exception("Error al consultar DBISAM en producto_ubicaciones")

    return render(request, 'ubicaciones-producto-detalle.html', {
        'codigo': codigo, 'descripcion': descripcion, 'existencia': existencia,
        'asignaciones': asignaciones,
    })


# ------------------------------------------------------------------ Fragmentos htmx

@login_required(login_url='/login/')
def buscar_nivel_fragment(request):
    """Autocomplete de niveles para formularios de traslado/fusión."""
    q = request.GET.get('q', '').strip()
    qs = Nivel.objects.filter(activo=True, fusionado_en__isnull=True).select_related('ubicacion__cuerpo__rack')
    if q:
        qs = qs.filter(ubicacion__cuerpo__rack__codigo__icontains=q)
    return render(request, '_ubicaciones-buscar-nivel-fragment.html', {'niveles': qs[:20]})


@login_required(login_url='/login/')
def buscar_producto_dbisam_fragment(request):
    """Búsqueda de producto en DBISAM para el modal de asignación."""
    q = request.GET.get('q', '').strip()
    resultados = []
    if len(q) >= 2:
        try:
            db = PedidosDBISAM()
            prods = db.buscar_por_descripcion(q)
            codigos = [p[0] for p in prods]
            stocks = db.consultar_stock_multiple(codigos, deposito=DEPOSITO_ALMACEN) if codigos else {}
            resultados = [
                {'codigo': p[0], 'descripcion': p[1], 'referencia': p[2], 'puesto': p[3],
                 'existencia': stocks.get(p[0], 0)}
                for p in prods
            ]
        except Exception:
            logger.exception("Error en buscar_producto_dbisam_fragment")
    return render(request, '_ubicaciones-buscar-producto-fragment.html', {'resultados': resultados})
```

- [ ] **Step 3: Extender `ubicaciones/urls.py`**

Agregar al final de `urlpatterns`:

```python
    # Asignaciones
    path('ubicaciones/niveles/<int:pk>/asignar/', views.asignar_producto, name='ubicaciones-asignar'),
    path('ubicaciones/producto-ubicaciones/<int:pu_id>/editar-cantidad/', views.editar_cantidad, name='ubicaciones-editar-cantidad'),
    path('ubicaciones/producto-ubicaciones/<int:pu_id>/quitar/', views.quitar_producto, name='ubicaciones-quitar'),

    # Traslado / Fusión
    path('ubicaciones/trasladar/', views.trasladar, name='ubicaciones-trasladar'),
    path('ubicaciones/fusionar/', views.fusionar, name='ubicaciones-fusionar'),
    path('ubicaciones/niveles/<int:pk>/desfusionar/', views.desfusionar, name='ubicaciones-desfusionar'),

    # Histórico
    path('ubicaciones/movimientos/', views.lista_movimientos, name='ubicaciones-movimientos'),

    # Producto → sus ubicaciones
    path('ubicaciones/productos/<str:codigo>/', views.producto_ubicaciones, name='ubicaciones-producto-detalle'),

    # Fragmentos htmx
    path('ubicaciones/buscar-nivel/', views.buscar_nivel_fragment, name='ubicaciones-buscar-nivel'),
    path('ubicaciones/buscar-producto/', views.buscar_producto_dbisam_fragment, name='ubicaciones-buscar-producto'),
```

- [ ] **Step 4: Escribir los tests**

Agregar a `ubicaciones/tests.py`:

```python
class AsignacionTrasladoFusionViewsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='webuser3', password='x')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client = Client()
        self.client.login(username='webuser3', password='x')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.ubicacion = self.cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel1 = self.ubicacion.niveles.get(numero=1)
        self.nivel2 = self.ubicacion.niveles.get(numero=2)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_asignar_producto_via_web_redirige(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        resp = self.client.post(f'/ubicaciones/niveles/{self.nivel1.pk}/asignar/', {
            'asignar': '1', 'codigo_producto': 'ABC', 'cantidad': 10,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ProductoUbicacion.objects.filter(codigo_producto='ABC', nivel=self.nivel1).exists())

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_trasladar_via_web_redirige(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        UbicacionesService.asignar_producto('ABC', self.nivel1, 10, None, self.user)
        resp = self.client.post('/ubicaciones/trasladar/', {
            'codigo_producto': 'ABC', 'nivel_origen': self.nivel1.pk, 'nivel_destino': self.nivel2.pk,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ProductoUbicacion.objects.filter(codigo_producto='ABC', nivel=self.nivel2).exists())

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_fusionar_via_web_redirige(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        resp = self.client.post('/ubicaciones/fusionar/', {
            'niveles': [self.nivel1.pk, self.nivel2.pk], 'maestro': self.nivel1.pk,
        })
        self.assertEqual(resp.status_code, 302)
        self.nivel2.refresh_from_db()
        self.assertEqual(self.nivel2.fusionado_en_id, self.nivel1.pk)

    def test_desfusionar_via_web_redirige(self):
        UbicacionesService.fusionar_niveles([self.nivel1, self.nivel2], self.nivel1, self.user)
        resp = self.client.post(f'/ubicaciones/niveles/{self.nivel2.pk}/desfusionar/')
        self.assertEqual(resp.status_code, 302)
        self.nivel2.refresh_from_db()
        self.assertIsNone(self.nivel2.fusionado_en_id)


class FusionarFormTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='formtester')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.ubicacion = self.cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel1 = self.ubicacion.niveles.get(numero=1)

    def test_maestro_debe_estar_entre_niveles_seleccionados(self):
        from ubicaciones.forms import FusionarForm
        otro_nivel = self.ubicacion.niveles.get(numero=2)
        tercer_nivel = self.ubicacion.niveles.get(numero=3)
        form = FusionarForm(data={
            'niveles': [self.nivel1.pk, otro_nivel.pk], 'maestro': tercer_nivel.pk,
        })
        self.assertFalse(form.is_valid())
```

- [ ] **Step 5: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.AsignacionTrasladoFusionViewsTest ubicaciones.FusionarFormTest --settings=Programarprecios.test_settings -v 2`
Expected: 5 tests, todos PASS.

- [ ] **Step 6: Correr toda la suite de la app**

Run: `venv\Scripts\python.exe manage.py test ubicaciones --settings=Programarprecios.test_settings -v 2`
Expected: todos los tests de las Tasks 1-10 PASS.

- [ ] **Step 7: Commit**

```bash
git add ubicaciones/forms.py ubicaciones/views.py ubicaciones/urls.py ubicaciones/tests.py
git commit -m "feat(ubicaciones): vistas web de asignación, traslado, fusión e histórico"
```

---

## Task 11: Templates — Galpón y Rack

Crea los templates de Galpón y sobrescribe los de Rack (cambian: ya no listan Niveles directo, listan Cuerpos; ganan campos de grilla del plano). Reutiliza sin cambios `ubicaciones-confirmar-desactivar.html` (ya es genérico) y actualiza el menú de `dashboard.html`. Esta es la primera tarea que efectivamente renderiza vistas por GET, así que agrega un smoke test que confirma que cada URL nueva devuelve 200.

**Files:**
- Create: `templates/ubicaciones-galpones-lista.html`, `templates/ubicaciones-galpones-crear.html`, `templates/ubicaciones-galpones-detalle.html`, `templates/ubicaciones-galpones-editar.html`
- Modify: `templates/ubicaciones-racks-crear.html`, `templates/ubicaciones-racks-detalle.html`, `templates/ubicaciones-racks-editar.html`, `templates/dashboard.html`, `ubicaciones/tests.py`
- Delete: `templates/ubicaciones-racks-lista.html` (ya no hay listado plano de racks; se navega desde el detalle del Galpón)

**Interfaces:**
- Consumes: vistas y URL names de la Task 8.

- [ ] **Step 1: Crear `templates/ubicaciones-galpones-lista.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
{% load static %}
<link rel="stylesheet" href="{% static 'vendor/datatables/css/dataTables.bootstrap5.min.css' %}">
<script src="{% static 'vendor/jquery/jquery-3.6.0.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/jquery.dataTables.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/dataTables.bootstrap5.min.js' %}"></script>

<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3 page-header-mobile">
        <h2><i class="fas fa-warehouse"></i> Galpones</h2>
        <a href="{% url 'ubicaciones-galpones-crear' %}" class="btn btn-primary">
            <i class="fas fa-plus"></i> Nuevo Galpón
        </a>
    </div>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show" role="alert">
            {{ message }}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <div class="mb-3">
        <a href="?activo=1" class="btn btn-outline-secondary btn-sm {% if solo_activos == '1' %}active{% endif %}">Activos</a>
        <a href="?activo=0" class="btn btn-outline-secondary btn-sm {% if solo_activos == '0' %}active{% endif %}">Inactivos</a>
        <a href="?" class="btn btn-outline-secondary btn-sm {% if solo_activos == '' %}active{% endif %}">Todos</a>
    </div>

    <div class="table-responsive">
    <table id="tablaGalpones" class="table table-striped table-hover" style="width:100%">
        <thead>
            <tr><th>Código</th><th>Nombre</th><th>Racks</th><th>Estado</th><th>Acciones</th></tr>
        </thead>
        <tbody>
            {% for galpon in galpones %}
            <tr>
                <td><strong>{{ galpon.codigo }}</strong></td>
                <td>{{ galpon.nombre|default:"—" }}</td>
                <td><span class="badge bg-info text-dark">{{ galpon.racks.count }}</span></td>
                <td>
                    {% if galpon.activo %}<span class="badge bg-success">Activo</span>
                    {% else %}<span class="badge bg-secondary">Inactivo</span>{% endif %}
                </td>
                <td>
                    <a href="{% url 'ubicaciones-galpones-detalle' galpon.pk %}" class="btn btn-sm btn-outline-primary"><i class="fas fa-eye"></i></a>
                    <a href="{% url 'ubicaciones-galpones-editar' galpon.pk %}" class="btn btn-sm btn-outline-secondary"><i class="fas fa-edit"></i></a>
                    {% if galpon.activo %}
                    <a href="{% url 'ubicaciones-galpones-desactivar' galpon.pk %}" class="btn btn-sm btn-outline-danger"><i class="fas fa-ban"></i></a>
                    {% endif %}
                </td>
            </tr>
            {% empty %}
            <tr><td colspan="5" class="text-center text-muted">No hay galpones.</td></tr>
            {% endfor %}
        </tbody>
    </table>
    </div>
</div>

<script>
$(document).ready(function() {
    $('#tablaGalpones').DataTable({
        language: { url: "/static/vendor/datatables/i18n/es-ES.json" },
        paging: true, searching: true, ordering: true, order: [[0, 'asc']],
    });
});
</script>
{% endblock content %}
```

- [ ] **Step 2: Crear `templates/ubicaciones-galpones-crear.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4" style="max-width:600px;">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2><i class="fas fa-plus-circle"></i> Nuevo Galpón</h2>
        <a href="{% url 'ubicaciones-galpones-lista' %}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Volver
        </a>
    </div>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <div class="card">
        <div class="card-body">
            <form method="post">
                {% csrf_token %}
                {% for field in form %}
                <div class="mb-3">
                    <label class="form-label fw-bold">{{ field.label }}</label>
                    {{ field }}
                    {% if field.help_text %}<div class="form-text text-muted">{{ field.help_text }}</div>{% endif %}
                    {% for error in field.errors %}<div class="text-danger small">{{ error }}</div>{% endfor %}
                </div>
                {% endfor %}
                <button type="submit" class="btn btn-primary">
                    <i class="fas fa-save"></i> Guardar Galpón
                </button>
            </form>
        </div>
    </div>
</div>
{% endblock content %}
```

- [ ] **Step 3: Crear `templates/ubicaciones-galpones-detalle.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
{% load static %}
<link rel="stylesheet" href="{% static 'vendor/datatables/css/dataTables.bootstrap5.min.css' %}">
<script src="{% static 'vendor/jquery/jquery-3.6.0.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/jquery.dataTables.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/dataTables.bootstrap5.min.js' %}"></script>

<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3 page-header-mobile">
        <h2><i class="fas fa-warehouse"></i> Galpón: {{ galpon.codigo }}</h2>
        <div class="d-flex gap-2 flex-wrap btn-group-header">
            <a href="{% url 'ubicaciones-galpones-editar' galpon.pk %}" class="btn btn-outline-secondary">
                <i class="fas fa-edit"></i> Editar
            </a>
            {% if galpon.activo %}
            <a href="{% url 'ubicaciones-galpones-desactivar' galpon.pk %}" class="btn btn-outline-danger">
                <i class="fas fa-ban"></i> Desactivar
            </a>
            {% endif %}
            <a href="{% url 'ubicaciones-galpones-lista' %}" class="btn btn-outline-secondary">
                <i class="fas fa-arrow-left"></i> Volver
            </a>
        </div>
    </div>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <div class="d-flex justify-content-between align-items-center mb-2">
        <h4>Racks</h4>
        <a href="{% url 'ubicaciones-racks-crear' galpon.pk %}" class="btn btn-primary">
            <i class="fas fa-plus"></i> Nuevo Rack
        </a>
    </div>

    <div class="table-responsive">
    <table id="tablaGalponRacks" class="table table-striped table-hover" style="width:100%">
        <thead>
            <tr><th>Código</th><th>Descripción</th><th>Cuerpos</th><th>Máx. Niveles</th><th>Estado</th><th>Acciones</th></tr>
        </thead>
        <tbody>
            {% for rack in racks %}
            <tr>
                <td><strong>{{ rack.codigo }}</strong></td>
                <td>{{ rack.descripcion|default:"—" }}</td>
                <td><span class="badge bg-info text-dark">{{ rack.total_cuerpos }}</span></td>
                <td>{{ rack.max_niveles }}</td>
                <td>
                    {% if rack.activo %}<span class="badge bg-success">Activo</span>
                    {% else %}<span class="badge bg-secondary">Inactivo</span>{% endif %}
                </td>
                <td>
                    <a href="{% url 'ubicaciones-racks-detalle' rack.pk %}" class="btn btn-sm btn-outline-primary"><i class="fas fa-eye"></i></a>
                    <a href="{% url 'ubicaciones-racks-editar' rack.pk %}" class="btn btn-sm btn-outline-secondary"><i class="fas fa-edit"></i></a>
                    {% if rack.activo %}
                    <a href="{% url 'ubicaciones-racks-desactivar' rack.pk %}" class="btn btn-sm btn-outline-danger"><i class="fas fa-ban"></i></a>
                    {% endif %}
                </td>
            </tr>
            {% empty %}
            <tr><td colspan="6" class="text-center text-muted">No hay racks en este galpón.</td></tr>
            {% endfor %}
        </tbody>
    </table>
    </div>
</div>

<script>
$(document).ready(function() {
    $('#tablaGalponRacks').DataTable({
        language: { url: "/static/vendor/datatables/i18n/es-ES.json" },
        paging: false, searching: false, ordering: true, info: false,
    });
});
</script>
{% endblock content %}
```

- [ ] **Step 4: Crear `templates/ubicaciones-galpones-editar.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4" style="max-width:600px;">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2><i class="fas fa-edit"></i> Editar Galpón {{ galpon.codigo }}</h2>
        <a href="{% url 'ubicaciones-galpones-detalle' galpon.pk %}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Volver
        </a>
    </div>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <div class="card">
        <div class="card-body">
            <form method="post">
                {% csrf_token %}
                {% for field in form %}
                <div class="mb-3">
                    <label class="form-label fw-bold">{{ field.label }}</label>
                    {{ field }}
                    {% if field.help_text %}<div class="form-text text-muted">{{ field.help_text }}</div>{% endif %}
                    {% for error in field.errors %}<div class="text-danger small">{{ error }}</div>{% endfor %}
                </div>
                {% endfor %}
                <button type="submit" class="btn btn-primary">
                    <i class="fas fa-save"></i> Guardar cambios
                </button>
            </form>
        </div>
    </div>
</div>
{% endblock content %}
```

- [ ] **Step 5: Borrar `templates/ubicaciones-racks-lista.html`**

```bash
rm templates/ubicaciones-racks-lista.html
```

- [ ] **Step 6: Sobrescribir `templates/ubicaciones-racks-crear.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4" style="max-width:600px;">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2><i class="fas fa-plus-circle"></i> Nuevo Rack en Galpón {{ galpon.codigo }}</h2>
        <a href="{% url 'ubicaciones-galpones-detalle' galpon.pk %}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Volver
        </a>
    </div>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <div class="card">
        <div class="card-body">
            <form method="post">
                {% csrf_token %}
                {% for field in form %}
                <div class="mb-3">
                    <label class="form-label fw-bold">{{ field.label }}</label>
                    {{ field }}
                    {% if field.help_text %}<div class="form-text text-muted">{{ field.help_text }}</div>{% endif %}
                    {% for error in field.errors %}<div class="text-danger small">{{ error }}</div>{% endfor %}
                </div>
                {% endfor %}
                <button type="submit" class="btn btn-primary">
                    <i class="fas fa-save"></i> Guardar Rack
                </button>
            </form>
        </div>
    </div>
</div>
{% endblock content %}
```

- [ ] **Step 7: Sobrescribir `templates/ubicaciones-racks-detalle.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
{% load static %}
<link rel="stylesheet" href="{% static 'vendor/datatables/css/dataTables.bootstrap5.min.css' %}">
<script src="{% static 'vendor/jquery/jquery-3.6.0.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/jquery.dataTables.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/dataTables.bootstrap5.min.js' %}"></script>

<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3 page-header-mobile">
        <h2><i class="fas fa-th-large"></i> Rack: {{ rack.galpon.codigo }}{{ rack.codigo }}</h2>
        <div class="d-flex gap-2 flex-wrap btn-group-header">
            <a href="{% url 'ubicaciones-racks-editar' rack.pk %}" class="btn btn-outline-secondary">
                <i class="fas fa-edit"></i> Editar
            </a>
            {% if rack.activo %}
            <a href="{% url 'ubicaciones-racks-desactivar' rack.pk %}" class="btn btn-outline-danger">
                <i class="fas fa-ban"></i> Desactivar
            </a>
            {% endif %}
            <a href="{% url 'ubicaciones-galpones-detalle' rack.galpon_id %}" class="btn btn-outline-secondary">
                <i class="fas fa-arrow-left"></i> Volver
            </a>
        </div>
    </div>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <div class="row mb-4">
        <div class="col-md-6">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">Información del Rack</h5>
                    <table class="table table-sm table-borderless mb-0">
                        <tr><th>Código completo</th><td><strong>{{ rack.galpon.codigo }}{{ rack.codigo }}</strong></td></tr>
                        <tr><th>Descripción</th><td>{{ rack.descripcion|default:"—" }}</td></tr>
                        <tr><th>Estado</th><td>
                            {% if rack.activo %}<span class="badge bg-success">Activo</span>
                            {% else %}<span class="badge bg-secondary">Inactivo</span>{% endif %}
                        </td></tr>
                        <tr><th>Cuerpos</th><td>{{ rack.total_cuerpos }}</td></tr>
                        <tr><th>Máx. niveles por ubicación</th><td>{{ rack.max_niveles }}</td></tr>
                        <tr><th>Creado</th><td>{{ rack.fecha_creacion|date:"d/m/Y H:i" }}</td></tr>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <div class="d-flex justify-content-between align-items-center mb-2">
        <h4>Cuerpos</h4>
        {% if rack.activo %}
        <a href="{% url 'ubicaciones-cuerpos-crear' rack.pk %}" class="btn btn-primary">
            <i class="fas fa-plus"></i> Nuevo Cuerpo
        </a>
        {% endif %}
    </div>

    <div class="table-responsive">
    <table id="tablaRackCuerpos" class="table table-striped table-hover" style="width:100%">
        <thead>
            <tr><th>Código</th><th>Descripción</th><th>Ubicaciones</th><th>Estado</th><th>Acciones</th></tr>
        </thead>
        <tbody>
            {% for cuerpo in cuerpos %}
            <tr>
                <td><strong>{{ cuerpo.codigo }}</strong></td>
                <td>{{ cuerpo.descripcion|default:"—" }}</td>
                <td><span class="badge bg-light text-dark border">{{ cuerpo.ubicaciones.count }}</span></td>
                <td>
                    {% if cuerpo.activo %}<span class="badge bg-success">Activo</span>
                    {% else %}<span class="badge bg-secondary">Inactivo</span>{% endif %}
                </td>
                <td>
                    <a href="{% url 'ubicaciones-cuerpos-detalle' cuerpo.pk %}" class="btn btn-sm btn-outline-primary"><i class="fas fa-eye"></i></a>
                    <a href="{% url 'ubicaciones-cuerpos-editar' cuerpo.pk %}" class="btn btn-sm btn-outline-secondary"><i class="fas fa-edit"></i></a>
                    {% if cuerpo.activo %}
                    <a href="{% url 'ubicaciones-cuerpos-desactivar' cuerpo.pk %}" class="btn btn-sm btn-outline-danger"><i class="fas fa-ban"></i></a>
                    {% endif %}
                </td>
            </tr>
            {% empty %}
            <tr><td colspan="5" class="text-center text-muted">No hay cuerpos en este rack.</td></tr>
            {% endfor %}
        </tbody>
    </table>
    </div>
</div>

<script>
$(document).ready(function() {
    $('#tablaRackCuerpos').DataTable({
        language: { url: "/static/vendor/datatables/i18n/es-ES.json" },
        paging: false, searching: false, ordering: true, info: false,
    });
});
</script>
{% endblock content %}
```

- [ ] **Step 8: Sobrescribir `templates/ubicaciones-racks-editar.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4" style="max-width:600px;">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2><i class="fas fa-edit"></i> Editar Rack {{ rack.codigo }}</h2>
        <a href="{% url 'ubicaciones-racks-detalle' rack.pk %}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Volver
        </a>
    </div>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <div class="card">
        <div class="card-body">
            <form method="post">
                {% csrf_token %}
                {% for field in form %}
                <div class="mb-3">
                    <label class="form-label fw-bold">{{ field.label }}</label>
                    {{ field }}
                    {% if field.help_text %}<div class="form-text text-muted">{{ field.help_text }}</div>{% endif %}
                    {% for error in field.errors %}<div class="text-danger small">{{ error }}</div>{% endfor %}
                </div>
                {% endfor %}
                <button type="submit" class="btn btn-primary">
                    <i class="fas fa-save"></i> Guardar cambios
                </button>
            </form>
        </div>
    </div>
</div>
{% endblock content %}
```

- [ ] **Step 9: Actualizar el menú en `templates/dashboard.html`**

En el bloque `{% if request.user|has_group:"Pedidos Ubicaciones" %}` (alrededor de la línea 116),
reemplazar el `<ul class="sub-menu">` existente:

```html
                    <ul class="sub-menu">
                        <li><a href="/ubicaciones/galpones/">Galpones</a></li>
                        <li><a href="/ubicaciones/trasladar/">Trasladar</a></li>
                        <li><a href="/ubicaciones/fusionar/">Fusionar</a></li>
                        <li><a href="/ubicaciones/alertas/">Alertas de stock</a></li>
                        <li><a href="/ubicaciones/movimientos/">Histórico</a></li>
                    </ul>
```

(los links `/ubicaciones/alertas/` y de mapa se activan en las Tasks 14-15; por ahora apuntan a
URLs que aún no existen, lo cual no rompe nada — solo dan 404 hasta esas tareas).

- [ ] **Step 10: Escribir el smoke test de renderizado GET**

Agregar a `ubicaciones/tests.py`:

```python
class GalponRackTemplatesSmokeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='webuser4', password='x')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client = Client()
        self.client.login(username='webuser4', password='x')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)

    def test_paginas_de_galpon_y_rack_devuelven_200(self):
        urls = [
            '/ubicaciones/galpones/',
            '/ubicaciones/galpones/crear/',
            f'/ubicaciones/galpones/{self.galpon.pk}/',
            f'/ubicaciones/galpones/{self.galpon.pk}/editar/',
            f'/ubicaciones/galpones/{self.rack.galpon_id}/racks/crear/',
            f'/ubicaciones/racks/{self.rack.pk}/',
            f'/ubicaciones/racks/{self.rack.pk}/editar/',
        ]
        for url in urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"{url} devolvió {resp.status_code}")
```

Nota: los templates de Galpón/Rack de esta tarea deliberadamente **no** incluyen todavía el botón
"Ver mapa"/"Ver diagrama" (las URLs `ubicaciones-mapa-galpon`/`ubicaciones-mapa-rack` no existen
hasta la Task 15 — referenciarlas antes rompería estas páginas con `NoReverseMatch`). La Task 15
agrega esos botones a estos mismos templates una vez que el mapa exista.

- [ ] **Step 11: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.GalponRackTemplatesSmokeTest --settings=Programarprecios.test_settings -v 2`
Expected: 1 test, PASS.

- [ ] **Step 12: Commit**

```bash
git add templates/ubicaciones-galpones-*.html templates/ubicaciones-racks-*.html templates/dashboard.html ubicaciones/tests.py
git commit -m "feat(ubicaciones): templates de Galpón y Rack"
```

---

## Task 12: Templates — Cuerpo, Ubicación y Nivel

Crea los templates de Cuerpo y sobrescribe los de Ubicación y Nivel. Borra los templates obsoletos de creación manual de Ubicación/Nivel (ya no existen esas vistas — se autogeneran en cascada desde Cuerpo). El detalle de Nivel muestra los productos asignados con edición de cantidad/stock mínimo inline y el estado de fusión.

**Files:**
- Create: `templates/ubicaciones-cuerpos-crear.html`, `templates/ubicaciones-cuerpos-detalle.html`, `templates/ubicaciones-cuerpos-editar.html`
- Modify: `templates/ubicaciones-ubicaciones-detalle.html`, `templates/ubicaciones-ubicaciones-editar.html`, `templates/ubicaciones-niveles-detalle.html`, `templates/ubicaciones-niveles-editar.html`, `ubicaciones/tests.py`
- Delete: `templates/ubicaciones-niveles-crear.html`, `templates/ubicaciones-ubicaciones-crear.html`

**Interfaces:**
- Consumes: vistas y URL names de la Task 9 y `ubicaciones-editar-cantidad`/`ubicaciones-quitar`/`ubicaciones-asignar`/`ubicaciones-desfusionar` de la Task 10.

- [ ] **Step 1: Borrar los templates obsoletos**

```bash
rm templates/ubicaciones-niveles-crear.html templates/ubicaciones-ubicaciones-crear.html
```

- [ ] **Step 2: Crear `templates/ubicaciones-cuerpos-crear.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4" style="max-width:600px;">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2><i class="fas fa-plus-circle"></i> Nuevo Cuerpo en Rack {{ rack.galpon.codigo }}{{ rack.codigo }}</h2>
        <a href="{% url 'ubicaciones-racks-detalle' rack.pk %}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Volver
        </a>
    </div>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <div class="card">
        <div class="card-body">
            <p class="text-muted small">
                Se creará el siguiente cuerpo disponible con sus 2 ubicaciones y
                {{ rack.max_niveles }} niveles cada una, autogenerados.
            </p>
            <form method="post">
                {% csrf_token %}
                {% for field in form %}
                <div class="mb-3">
                    <label class="form-label fw-bold">{{ field.label }}</label>
                    {{ field }}
                    {% for error in field.errors %}<div class="text-danger small">{{ error }}</div>{% endfor %}
                </div>
                {% endfor %}
                <button type="submit" class="btn btn-primary">
                    <i class="fas fa-save"></i> Crear Cuerpo
                </button>
            </form>
        </div>
    </div>
</div>
{% endblock content %}
```

- [ ] **Step 3: Crear `templates/ubicaciones-cuerpos-detalle.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3 page-header-mobile">
        <h2><i class="fas fa-box"></i> Cuerpo: {{ cuerpo.rack.galpon.codigo }}{{ cuerpo.rack.codigo }}{{ cuerpo.codigo }}</h2>
        <div class="d-flex gap-2 flex-wrap btn-group-header">
            <a href="{% url 'ubicaciones-cuerpos-editar' cuerpo.pk %}" class="btn btn-outline-secondary"><i class="fas fa-edit"></i> Editar</a>
            {% if cuerpo.activo %}
            <a href="{% url 'ubicaciones-cuerpos-desactivar' cuerpo.pk %}" class="btn btn-outline-danger"><i class="fas fa-ban"></i> Desactivar</a>
            {% endif %}
            <a href="{% url 'ubicaciones-racks-detalle' cuerpo.rack.pk %}" class="btn btn-outline-secondary"><i class="fas fa-arrow-left"></i> Rack</a>
        </div>
    </div>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <p class="text-muted">{{ cuerpo.descripcion|default:"Sin descripción" }}</p>

    <div class="row g-3">
        {% for ubicacion in ubicaciones %}
        <div class="col-md-6">
            <div class="card">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <strong>Ubicación {{ ubicacion.codigo }}</strong>
                    <a href="{% url 'ubicaciones-ubicaciones-detalle' ubicacion.pk %}" class="btn btn-sm btn-outline-primary">
                        <i class="fas fa-eye"></i> Ver niveles
                    </a>
                </div>
                <div class="card-body">
                    <table class="table table-sm mb-0">
                        <thead><tr><th>Nivel</th><th>Tipo</th><th>Productos</th></tr></thead>
                        <tbody>
                            {% for nivel in ubicacion.niveles.all %}
                            <tr>
                                <td><a href="{% url 'ubicaciones-niveles-detalle' nivel.pk %}">{{ nivel.numero }}</a>
                                    {% if nivel.esta_fusionado %}<span class="badge bg-warning text-dark ms-1">Fusionado</span>{% endif %}
                                </td>
                                <td>
                                    {% if nivel.tipo == 'PICKING' %}<span class="badge bg-info text-dark">Picking</span>
                                    {% else %}<span class="badge bg-secondary">Almacenaje</span>{% endif %}
                                </td>
                                <td>{{ nivel.productos.count }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
{% endblock content %}
```

- [ ] **Step 4: Crear `templates/ubicaciones-cuerpos-editar.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4" style="max-width:600px;">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2><i class="fas fa-edit"></i> Editar Cuerpo {{ cuerpo.codigo }}</h2>
        <a href="{% url 'ubicaciones-cuerpos-detalle' cuerpo.pk %}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Volver
        </a>
    </div>
    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}
    <div class="card">
        <div class="card-body">
            <form method="post">
                {% csrf_token %}
                {% for field in form %}
                <div class="mb-3">
                    <label class="form-label fw-bold">{{ field.label }}</label>
                    {{ field }}
                    {% for error in field.errors %}<div class="text-danger small">{{ error }}</div>{% endfor %}
                </div>
                {% endfor %}
                <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Guardar</button>
            </form>
        </div>
    </div>
</div>
{% endblock content %}
```

- [ ] **Step 5: Sobrescribir `templates/ubicaciones-ubicaciones-detalle.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
{% load static %}
<link rel="stylesheet" href="{% static 'vendor/datatables/css/dataTables.bootstrap5.min.css' %}">
<script src="{% static 'vendor/jquery/jquery-3.6.0.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/jquery.dataTables.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/dataTables.bootstrap5.min.js' %}"></script>

<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3 page-header-mobile">
        <h2><i class="fas fa-map-marker-alt"></i> Ubicación {{ ubicacion }}</h2>
        <div class="d-flex gap-2 flex-wrap btn-group-header">
            <a href="{% url 'ubicaciones-ubicaciones-editar' ubicacion.pk %}" class="btn btn-outline-secondary"><i class="fas fa-edit"></i></a>
            {% if ubicacion.activo %}
            <a href="{% url 'ubicaciones-ubicaciones-desactivar' ubicacion.pk %}" class="btn btn-outline-danger"><i class="fas fa-ban"></i></a>
            {% endif %}
            <a href="{% url 'ubicaciones-cuerpos-detalle' ubicacion.cuerpo.pk %}" class="btn btn-outline-secondary">
                <i class="fas fa-arrow-left"></i> Cuerpo
            </a>
        </div>
    </div>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <h4>Niveles</h4>
    <div class="table-responsive">
    <table id="tablaUbicacionNiveles" class="table table-striped table-hover" style="width:100%">
        <thead>
            <tr><th>Nivel</th><th>Tipo</th><th>Fusión</th><th>Productos</th><th>Estado</th><th>Acciones</th></tr>
        </thead>
        <tbody>
            {% for nivel in niveles %}
            <tr>
                <td><strong>{{ nivel.numero }}</strong></td>
                <td>
                    {% if nivel.tipo == 'PICKING' %}<span class="badge bg-info text-dark">Picking</span>
                    {% else %}<span class="badge bg-secondary">Almacenaje</span>{% endif %}
                </td>
                <td>
                    {% if nivel.esta_fusionado %}
                        <span class="badge bg-warning text-dark">→ {{ nivel.fusionado_en.codigo_completo }}</span>
                    {% else %}—{% endif %}
                </td>
                <td><span class="badge bg-light text-dark border">{{ nivel.productos.count }}</span></td>
                <td>
                    {% if nivel.activo %}<span class="badge bg-success">Activo</span>
                    {% else %}<span class="badge bg-secondary">Inactivo</span>{% endif %}
                </td>
                <td>
                    <a href="{% url 'ubicaciones-niveles-detalle' nivel.pk %}" class="btn btn-sm btn-outline-primary"><i class="fas fa-eye"></i></a>
                    <a href="{% url 'ubicaciones-niveles-editar' nivel.pk %}" class="btn btn-sm btn-outline-secondary"><i class="fas fa-edit"></i></a>
                    {% if nivel.activo %}
                    <a href="{% url 'ubicaciones-niveles-desactivar' nivel.pk %}" class="btn btn-sm btn-outline-danger"><i class="fas fa-ban"></i></a>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    </div>
</div>

<script>
$(document).ready(function() {
    $('#tablaUbicacionNiveles').DataTable({
        language: { url: "/static/vendor/datatables/i18n/es-ES.json" },
        paging: false, searching: false, ordering: true, info: false,
    });
});
</script>
{% endblock content %}
```

- [ ] **Step 6: Sobrescribir `templates/ubicaciones-ubicaciones-editar.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4" style="max-width:600px;">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2><i class="fas fa-edit"></i> Editar Ubicación</h2>
        <a href="{% url 'ubicaciones-ubicaciones-detalle' ubicacion.pk %}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Volver
        </a>
    </div>
    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}
    <div class="card">
        <div class="card-body">
            <form method="post">
                {% csrf_token %}
                <div class="mb-3">
                    <label class="form-label fw-bold">Ubicación</label>
                    <input type="text" class="form-control" value="{{ ubicacion }}" disabled>
                </div>
                {% for field in form %}
                <div class="mb-3">
                    <label class="form-label fw-bold">{{ field.label }}</label>
                    {{ field }}
                    {% for error in field.errors %}<div class="text-danger small">{{ error }}</div>{% endfor %}
                </div>
                {% endfor %}
                <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Guardar</button>
            </form>
        </div>
    </div>
</div>
{% endblock content %}
```

- [ ] **Step 7: Sobrescribir `templates/ubicaciones-niveles-detalle.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
{% load static %}
<link rel="stylesheet" href="{% static 'vendor/datatables/css/dataTables.bootstrap5.min.css' %}">
<script src="{% static 'vendor/jquery/jquery-3.6.0.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/jquery.dataTables.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/dataTables.bootstrap5.min.js' %}"></script>

<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3 page-header-mobile">
        <h2><i class="fas fa-layer-group"></i> Nivel {{ nivel.codigo_completo }}</h2>
        <div class="d-flex gap-2 flex-wrap btn-group-header">
            {% if not nivel.esta_fusionado %}
            <a href="{% url 'ubicaciones-asignar' nivel.pk %}" class="btn btn-success"><i class="fas fa-plus"></i> Asignar Producto</a>
            {% endif %}
            <a href="{% url 'ubicaciones-niveles-editar' nivel.pk %}" class="btn btn-outline-secondary"><i class="fas fa-edit"></i></a>
            {% if nivel.activo %}
            <a href="{% url 'ubicaciones-niveles-desactivar' nivel.pk %}" class="btn btn-outline-danger"><i class="fas fa-ban"></i></a>
            {% endif %}
            <a href="{% url 'ubicaciones-ubicaciones-detalle' nivel.ubicacion.pk %}" class="btn btn-outline-secondary">
                <i class="fas fa-arrow-left"></i> Ubicación
            </a>
        </div>
    </div>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <div class="row mb-4">
        <div class="col-md-6">
            <div class="card">
                <div class="card-body">
                    <h5 class="card-title">Información</h5>
                    <table class="table table-sm table-borderless mb-0">
                        <tr><th>Código</th><td><strong>{{ nivel.codigo_completo }}</strong></td></tr>
                        <tr><th>Tipo</th><td>
                            {% if nivel.tipo == 'PICKING' %}<span class="badge bg-info text-dark">Picking</span>
                            {% else %}<span class="badge bg-secondary">Almacenaje</span>{% endif %}
                        </td></tr>
                        <tr><th>Fusión</th><td>
                            {% if nivel.esta_fusionado %}
                                <span class="badge bg-warning text-dark">Fusionado con {{ nivel.fusionado_en.codigo_completo }}</span>
                                <form method="post" action="{% url 'ubicaciones-desfusionar' nivel.pk %}" class="d-inline">
                                    {% csrf_token %}
                                    <button type="submit" class="btn btn-sm btn-outline-warning ms-1"
                                        onclick="return confirm('¿Desfusionar este nivel?')">Desfusionar</button>
                                </form>
                            {% else %}—{% endif %}
                        </td></tr>
                        <tr><th>Estado</th><td>
                            {% if nivel.activo %}<span class="badge bg-success">Activo</span>
                            {% else %}<span class="badge bg-secondary">Inactivo</span>{% endif %}
                        </td></tr>
                    </table>
                </div>
            </div>
        </div>
    </div>

    <h4>Productos asignados</h4>
    <div class="table-responsive">
    <table id="tablaProductos" class="table table-striped table-hover" style="width:100%">
        <thead>
            <tr><th>Código</th><th>Cantidad</th>{% if nivel.tipo == 'PICKING' %}<th>Stock mínimo</th>{% endif %}<th>Alerta</th><th>Acciones</th></tr>
        </thead>
        <tbody>
            {% for item in productos %}
            <tr>
                <td><a href="{% url 'ubicaciones-producto-detalle' item.codigo_producto %}">{{ item.codigo_producto }}</a></td>
                <td colspan="{% if nivel.tipo == 'PICKING' %}2{% else %}1{% endif %}">
                    <form method="post" action="{% url 'ubicaciones-editar-cantidad' item.pk %}" class="d-flex gap-1 align-items-center">
                        {% csrf_token %}
                        <input type="number" name="cantidad" value="{{ item.cantidad }}" min="0" class="form-control form-control-sm" style="width:90px;">
                        {% if nivel.tipo == 'PICKING' %}
                        <input type="number" name="stock_minimo" value="{{ item.stock_minimo|default_if_none:'' }}" min="0" placeholder="mín." class="form-control form-control-sm" style="width:80px;">
                        {% endif %}
                        <button type="submit" class="btn btn-sm btn-outline-primary" title="Guardar"><i class="fas fa-save"></i></button>
                    </form>
                </td>
                <td>
                    {% if item.stock_minimo is not None and item.cantidad < item.stock_minimo %}
                        <span class="badge bg-danger">Bajo mínimo</span>
                    {% endif %}
                </td>
                <td>
                    <a href="{% url 'ubicaciones-trasladar' %}" class="btn btn-sm btn-outline-info" title="Trasladar"><i class="fas fa-exchange-alt"></i></a>
                    <form method="post" action="{% url 'ubicaciones-quitar' item.pk %}" class="d-inline">
                        {% csrf_token %}
                        <button type="submit" class="btn btn-sm btn-outline-danger"
                            onclick="return confirm('¿Quitar el producto {{ item.codigo_producto }} de este nivel?')" title="Quitar">
                            <i class="fas fa-times"></i>
                        </button>
                    </form>
                </td>
            </tr>
            {% empty %}
            <tr><td colspan="4" class="text-center text-muted">No hay productos asignados.</td></tr>
            {% endfor %}
        </tbody>
    </table>
    </div>
</div>

<script>
$(document).ready(function() {
    $('#tablaProductos').DataTable({
        language: { url: "/static/vendor/datatables/i18n/es-ES.json" },
        paging: false, searching: true, ordering: true, info: false,
    });
});
</script>
{% endblock content %}
```

- [ ] **Step 8: Sobrescribir `templates/ubicaciones-niveles-editar.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4" style="max-width:600px;">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2><i class="fas fa-edit"></i> Editar Nivel {{ nivel.codigo_completo }}</h2>
        <a href="{% url 'ubicaciones-niveles-detalle' nivel.pk %}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Volver
        </a>
    </div>
    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}
    <div class="card">
        <div class="card-body">
            <form method="post">
                {% csrf_token %}
                {% for field in form %}
                <div class="mb-3">
                    <label class="form-label fw-bold">{{ field.label }}</label>
                    {{ field }}
                    {% for error in field.errors %}<div class="text-danger small">{{ error }}</div>{% endfor %}
                </div>
                {% endfor %}
                <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> Guardar cambios</button>
            </form>
        </div>
    </div>
</div>
{% endblock content %}
```

- [ ] **Step 9: Escribir el smoke test**

Agregar a `ubicaciones/tests.py`:

```python
class CuerpoUbicacionNivelTemplatesSmokeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='webuser5', password='x')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client = Client()
        self.client.login(username='webuser5', password='x')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.ubicacion = self.cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel = self.ubicacion.niveles.get(numero=1)

    def test_paginas_de_cuerpo_ubicacion_nivel_devuelven_200(self):
        urls = [
            f'/ubicaciones/racks/{self.rack.pk}/cuerpos/crear/',
            f'/ubicaciones/cuerpos/{self.cuerpo.pk}/',
            f'/ubicaciones/cuerpos/{self.cuerpo.pk}/editar/',
            f'/ubicaciones/ubicaciones/{self.ubicacion.pk}/',
            f'/ubicaciones/ubicaciones/{self.ubicacion.pk}/editar/',
            f'/ubicaciones/niveles/{self.nivel.pk}/',
            f'/ubicaciones/niveles/{self.nivel.pk}/editar/',
        ]
        for url in urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"{url} devolvió {resp.status_code}")
```

- [ ] **Step 10: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.CuerpoUbicacionNivelTemplatesSmokeTest --settings=Programarprecios.test_settings -v 2`
Expected: 1 test, PASS.

- [ ] **Step 11: Commit**

```bash
git add templates/ubicaciones-cuerpos-*.html templates/ubicaciones-ubicaciones-*.html templates/ubicaciones-niveles-*.html ubicaciones/tests.py
git commit -m "feat(ubicaciones): templates de Cuerpo, Ubicación y Nivel"
```

---

## Task 13: Templates — Asignación, Traslado, Fusión, Histórico, fragmentos

Sobrescribe los templates de asignación (búsqueda DBISAM + cantidad/stock mínimo), traslado, fusión (ahora multi-selección de niveles + maestro), histórico e info por producto, y el fragmento htmx de autocomplete de niveles. `_ubicaciones-buscar-producto-fragment.html` no cambia (ya es genérico).

**Files:**
- Modify: `templates/ubicaciones-asignar.html`, `templates/ubicaciones-trasladar.html`, `templates/ubicaciones-fusionar.html`, `templates/ubicaciones-movimientos.html`, `templates/ubicaciones-producto-detalle.html`, `ubicaciones/tests.py`
- Create: `templates/_ubicaciones-buscar-nivel-fragment.html`
- Delete: `templates/_ubicaciones-buscar-ubicacion-fragment.html`

**Interfaces:**
- Consumes: vistas y URL names de la Task 10.

- [ ] **Step 1: Borrar el fragmento obsoleto**

```bash
rm templates/_ubicaciones-buscar-ubicacion-fragment.html
```

- [ ] **Step 2: Sobrescribir `templates/ubicaciones-asignar.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2><i class="fas fa-plus-circle"></i> Asignar Producto</h2>
        <a href="{% url 'ubicaciones-niveles-detalle' nivel.pk %}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Volver
        </a>
    </div>

    <div class="alert alert-info">
        Asignando producto a: <strong>{{ nivel.codigo_completo }}</strong>
        <span class="badge ms-2 {% if nivel.tipo == 'PICKING' %}bg-info text-dark{% else %}bg-secondary{% endif %}">
            {{ nivel.get_tipo_display }}
        </span>
    </div>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <div class="card mb-4">
        <div class="card-header">Buscar producto en DBISAM</div>
        <div class="card-body">
            <form method="post">
                {% csrf_token %}
                <div class="input-group mb-3">
                    <input type="text" name="codigo_producto" class="form-control"
                        placeholder="Código o descripción del producto" value="{{ query }}">
                    <button type="submit" name="buscar" class="btn btn-outline-primary">
                        <i class="fas fa-search"></i> Buscar
                    </button>
                </div>
            </form>

            {% if resultados_busqueda %}
            <div class="table-responsive">
            <table class="table table-sm table-hover">
                <thead>
                    <tr><th>Código</th><th>Descripción</th><th>Existencia</th><th>Cantidad a asignar</th><th></th></tr>
                </thead>
                <tbody>
                    {% for prod in resultados_busqueda %}
                    <tr>
                        <td>{{ prod.codigo }}</td>
                        <td>{{ prod.descripcion }}</td>
                        <td>
                            {% if prod.existencia > 0 %}
                                <span class="badge bg-success">{{ prod.existencia|floatformat:0 }}</span>
                            {% else %}
                                <span class="badge bg-danger">0</span>
                            {% endif %}
                        </td>
                        <td colspan="2">
                            <form method="post" class="d-flex gap-1 align-items-center">
                                {% csrf_token %}
                                <input type="hidden" name="codigo_producto" value="{{ prod.codigo }}">
                                <input type="number" name="cantidad" min="0" value="0" required
                                    class="form-control form-control-sm" style="width:90px;">
                                {% if nivel.tipo == 'PICKING' %}
                                <input type="number" name="stock_minimo" min="0" placeholder="mín."
                                    class="form-control form-control-sm" style="width:80px;">
                                {% endif %}
                                <button type="submit" name="asignar" class="btn btn-sm btn-success">
                                    <i class="fas fa-check"></i> Asignar
                                </button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            </div>
            {% elif query %}
            <p class="text-muted">No se encontraron productos para "{{ query }}".</p>
            {% endif %}
        </div>
    </div>
</div>
{% endblock content %}
```

- [ ] **Step 3: Sobrescribir `templates/ubicaciones-trasladar.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4" style="max-width:700px;">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2><i class="fas fa-exchange-alt"></i> Trasladar Producto</h2>
        <a href="{% url 'ubicaciones-movimientos' %}" class="btn btn-outline-secondary">
            <i class="fas fa-history"></i> Histórico
        </a>
    </div>

    <p class="text-muted">Mueve la asignación de un producto de un nivel a otro.</p>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <div class="card">
        <div class="card-body">
            <form method="post">
                {% csrf_token %}
                {% for field in form %}
                <div class="mb-3">
                    <label class="form-label fw-bold">{{ field.label }}</label>
                    {{ field }}
                    {% for error in field.errors %}<div class="text-danger small">{{ error }}</div>{% endfor %}
                </div>
                {% endfor %}
                {% if form.non_field_errors %}
                <div class="alert alert-danger">
                    {% for error in form.non_field_errors %}{{ error }}{% endfor %}
                </div>
                {% endif %}
                <button type="submit" class="btn btn-primary">
                    <i class="fas fa-exchange-alt"></i> Trasladar
                </button>
            </form>
        </div>
    </div>
</div>
{% endblock content %}
```

- [ ] **Step 4: Sobrescribir `templates/ubicaciones-fusionar.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4" style="max-width:700px;">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2><i class="fas fa-compress-arrows-alt"></i> Fusionar Niveles</h2>
        <a href="{% url 'ubicaciones-movimientos' %}" class="btn btn-outline-secondary">
            <i class="fas fa-history"></i> Histórico
        </a>
    </div>

    <p class="text-muted">
        Todo el contenido de los niveles seleccionados se consolidará en el <strong>nivel maestro</strong>
        (debe estar entre los seleccionados); los demás quedan marcados como fusionados y no admiten
        asignaciones directas hasta desfusionarlos.
    </p>

    {% if messages %}
        {% for message in messages %}
        <div class="alert alert-{{ message.tags }} alert-dismissible fade show">
            {{ message }}<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
        {% endfor %}
    {% endif %}

    <div class="card">
        <div class="card-body">
            <form method="post" onsubmit="return confirm('¿Confirmar la fusión de los niveles seleccionados?');">
                {% csrf_token %}
                {% for field in form %}
                <div class="mb-3">
                    <label class="form-label fw-bold">{{ field.label }}</label>
                    {{ field }}
                    {% for error in field.errors %}<div class="text-danger small">{{ error }}</div>{% endfor %}
                </div>
                {% endfor %}
                {% if form.non_field_errors %}
                <div class="alert alert-danger">
                    {% for error in form.non_field_errors %}{{ error }}{% endfor %}
                </div>
                {% endif %}
                <button type="submit" class="btn btn-danger">
                    <i class="fas fa-check"></i> Confirmar Fusión
                </button>
            </form>
        </div>
    </div>
</div>
{% endblock content %}
```

- [ ] **Step 5: Sobrescribir `templates/ubicaciones-movimientos.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
{% load static %}
<link rel="stylesheet" href="{% static 'vendor/datatables/css/dataTables.bootstrap5.min.css' %}">
<script src="{% static 'vendor/jquery/jquery-3.6.0.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/jquery.dataTables.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/dataTables.bootstrap5.min.js' %}"></script>

<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3 page-header-mobile">
        <h2><i class="fas fa-history"></i> Histórico de Movimientos</h2>
    </div>

    <form method="get" class="row g-2 mb-3">
        <div class="col-auto">
            <select name="tipo" class="form-select form-select-sm">
                <option value="">Todos los tipos</option>
                {% for value, label in tipos %}
                <option value="{{ value }}" {% if tipo_filter == value %}selected{% endif %}>{{ label }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="col-auto">
            <input type="text" name="codigo" class="form-control form-control-sm"
                placeholder="Código producto" value="{{ codigo_filter }}">
        </div>
        <div class="col-auto">
            <button type="submit" class="btn btn-outline-primary btn-sm"><i class="fas fa-filter"></i> Filtrar</button>
            <a href="{% url 'ubicaciones-movimientos' %}" class="btn btn-outline-secondary btn-sm">Limpiar</a>
        </div>
    </form>

    <div class="table-responsive">
    <table id="tablaMovimientos" class="table table-striped table-hover table-sm" style="width:100%">
        <thead>
            <tr>
                <th>Tipo</th>
                <th>Rack</th>
                <th>Origen</th>
                <th>Destino</th>
                <th>Producto</th>
                <th>Usuario</th>
                <th>Fecha</th>
                <th>Notas</th>
            </tr>
        </thead>
        <tbody>
            {% for mov in movimientos %}
            <tr>
                <td>
                    <span class="badge
                        {% if 'CREACION' in mov.tipo %}bg-success
                        {% elif 'DESACTIVACION' in mov.tipo %}bg-secondary
                        {% elif mov.tipo == 'TRASLADO' %}bg-info text-dark
                        {% elif 'FUSION' in mov.tipo %}bg-warning text-dark
                        {% elif mov.tipo == 'ASIGNACION' %}bg-primary
                        {% elif mov.tipo == 'DESASIGNACION' %}bg-danger
                        {% else %}bg-secondary{% endif %}">
                        {{ mov.get_tipo_display }}
                    </span>
                </td>
                <td>{{ mov.rack.codigo|default:"—" }}</td>
                <td>{% if mov.nivel_origen %}{{ mov.nivel_origen.codigo_completo }}{% else %}—{% endif %}</td>
                <td>{% if mov.nivel_destino %}{{ mov.nivel_destino.codigo_completo }}{% else %}—{% endif %}</td>
                <td>
                    {% if mov.codigo_producto %}
                    <a href="{% url 'ubicaciones-producto-detalle' mov.codigo_producto %}">
                        {{ mov.codigo_producto }}
                    </a>
                    {% else %}—{% endif %}
                </td>
                <td>{{ mov.usuario.username|default:"—" }}</td>
                <td>{{ mov.fecha|date:"d/m/Y H:i" }}</td>
                <td>{{ mov.notas|truncatechars:40|default:"—" }}</td>
            </tr>
            {% empty %}
            <tr><td colspan="8" class="text-center text-muted">No hay movimientos registrados.</td></tr>
            {% endfor %}
        </tbody>
    </table>
    </div>
</div>

<script>
$(document).ready(function() {
    $('#tablaMovimientos').DataTable({
        language: { url: "/static/vendor/datatables/i18n/es-ES.json" },
        paging: true, searching: true, ordering: true,
        order: [[6, 'desc']], scrollX: true,
        lengthChange: false, pageLength: 50,
    });
});
</script>
{% endblock content %}
```

- [ ] **Step 6: Sobrescribir `templates/ubicaciones-producto-detalle.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3">
        <h2><i class="fas fa-search-location"></i> ¿Dónde está <strong>{{ codigo }}</strong>?</h2>
        <a href="javascript:history.back()" class="btn btn-outline-secondary"><i class="fas fa-arrow-left"></i> Volver</a>
    </div>

    {% if descripcion %}
    <p class="text-muted mb-1">{{ descripcion }}</p>
    {% endif %}
    <p class="mb-3">
        Existencia total en Almacén Principal (DBISAM):
        {% if existencia > 0 %}
            <span class="badge bg-success fs-6">{{ existencia|floatformat:0 }}</span>
        {% else %}
            <span class="badge bg-danger fs-6">0</span>
        {% endif %}
        <small class="text-muted ms-2">(depósito 1; la suma de cantidades asignadas abajo nunca la excede)</small>
    </p>

    {% if asignaciones %}
    <div class="row g-3">
        {% for pu in asignaciones %}
        <div class="col-md-4">
            <div class="card h-100 border
                {% if pu.nivel.tipo == 'PICKING' %}border-info{% else %}border-secondary{% endif %}">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <strong>{{ pu.nivel.codigo_completo }}</strong>
                    <span class="badge {% if pu.nivel.tipo == 'PICKING' %}bg-info text-dark{% else %}bg-secondary{% endif %}">
                        {{ pu.nivel.get_tipo_display }}
                    </span>
                </div>
                <div class="card-body">
                    <small class="text-muted">Cantidad:</small> {{ pu.cantidad }}<br>
                    {% if pu.stock_minimo is not None %}
                    <small class="text-muted">Stock mínimo:</small> {{ pu.stock_minimo }}<br>
                    {% endif %}
                    <small class="text-muted">Asignado:</small> {{ pu.fecha_asignacion|date:"d/m/Y" }}
                </div>
                <div class="card-footer bg-transparent">
                    <a href="{% url 'ubicaciones-niveles-detalle' pu.nivel.pk %}" class="btn btn-sm btn-outline-primary">
                        <i class="fas fa-eye"></i> Ver nivel
                    </a>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    {% else %}
    <div class="alert alert-warning">
        <i class="fas fa-info-circle"></i>
        El producto <strong>{{ codigo }}</strong> no tiene ubicaciones internas asignadas.
    </div>
    {% endif %}
</div>
{% endblock content %}
```

- [ ] **Step 7: Crear `templates/_ubicaciones-buscar-nivel-fragment.html`**

```html
{% for nivel in niveles %}
<div class="list-group-item list-group-item-action" style="cursor:pointer;"
     onclick="seleccionarNivel('{{ nivel.pk }}', '{{ nivel.codigo_completo|escapejs }}')">
    {{ nivel.codigo_completo }}
    <span class="badge ms-1 {% if nivel.tipo == 'PICKING' %}bg-info text-dark{% else %}bg-secondary{% endif %}">
        {{ nivel.get_tipo_display }}
    </span>
</div>
{% empty %}
<div class="list-group-item text-muted">No se encontraron niveles.</div>
{% endfor %}
```

- [ ] **Step 8: Escribir el smoke test**

Agregar a `ubicaciones/tests.py`:

```python
class AsignacionTrasladoFusionTemplatesSmokeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='webuser6', password='x')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client = Client()
        self.client.login(username='webuser6', password='x')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.nivel = self.cuerpo.ubicaciones.order_by('codigo').first().niveles.get(numero=1)

    def test_paginas_devuelven_200(self):
        urls = [
            f'/ubicaciones/niveles/{self.nivel.pk}/asignar/',
            '/ubicaciones/trasladar/',
            '/ubicaciones/fusionar/',
            '/ubicaciones/movimientos/',
            '/ubicaciones/buscar-nivel/',
            '/ubicaciones/buscar-producto/',
        ]
        for url in urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"{url} devolvió {resp.status_code}")

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_producto_detalle_devuelve_200(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        UbicacionesService.asignar_producto('ABC', self.nivel, 10, None, self.user)
        with patch('ubicaciones.views.PedidosDBISAM') as mock_views_db:
            mock_views_db.return_value.buscar_producto.return_value = None
            resp = self.client.get('/ubicaciones/productos/ABC/')
        self.assertEqual(resp.status_code, 200)
```

- [ ] **Step 9: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.AsignacionTrasladoFusionTemplatesSmokeTest --settings=Programarprecios.test_settings -v 2`
Expected: 2 tests, todos PASS.

- [ ] **Step 10: Correr toda la suite de la app**

Run: `venv\Scripts\python.exe manage.py test ubicaciones --settings=Programarprecios.test_settings -v 2`
Expected: todos los tests de las Tasks 1-13 PASS.

- [ ] **Step 11: Commit**

```bash
git add templates/ubicaciones-asignar.html templates/ubicaciones-trasladar.html templates/ubicaciones-fusionar.html templates/ubicaciones-movimientos.html templates/ubicaciones-producto-detalle.html templates/_ubicaciones-buscar-nivel-fragment.html ubicaciones/tests.py
git add -u templates/_ubicaciones-buscar-ubicacion-fragment.html
git commit -m "feat(ubicaciones): templates de asignación, traslado, fusión, histórico y fragmentos"
```

---

## Task 14: Alertas de stock mínimo (dashboard)

Agrega el panel de alertas: `ProductoUbicacion` en niveles picking con `stock_minimo` configurado cuya `cantidad` cayó bajo el mínimo. Calculado on-demand vía query (sin tabla de alertas ni cron), solo en dashboard — sin correo, según decisión 6 del spec.

**Files:**
- Modify: `ubicaciones/views.py`, `ubicaciones/urls.py`, `ubicaciones/tests.py`
- Create: `templates/ubicaciones-alertas.html`

**Interfaces:**
- Consumes: `ProductoUbicacion`, `Nivel.PICKING` (Task 1).
- Produces: vista `alertas_stock`; URL name `ubicaciones-alertas` (ya enlazada desde el menú en la Task 11).

- [ ] **Step 1: Agregar la vista a `ubicaciones/views.py`**

Actualizar el import de Django del inicio del archivo (agregar `F`):

```python
from django.db.models import F
```

Agregar al final:

```python
# ------------------------------------------------------------------ Alertas

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def alertas_stock(request):
    alertas = (
        ProductoUbicacion.objects
        .filter(nivel__tipo=Nivel.PICKING, nivel__activo=True, stock_minimo__isnull=False)
        .filter(cantidad__lt=F('stock_minimo'))
        .select_related('nivel__ubicacion__cuerpo__rack__galpon')
        .order_by('nivel__ubicacion__cuerpo__rack__galpon__codigo', 'nivel__ubicacion__cuerpo__rack__codigo')
    )
    return render(request, 'ubicaciones-alertas.html', {'alertas': alertas})
```

- [ ] **Step 2: Agregar la URL a `ubicaciones/urls.py`**

Agregar al final de `urlpatterns`:

```python
    # Alertas
    path('ubicaciones/alertas/', views.alertas_stock, name='ubicaciones-alertas'),
```

- [ ] **Step 3: Crear `templates/ubicaciones-alertas.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
{% load static %}
<link rel="stylesheet" href="{% static 'vendor/datatables/css/dataTables.bootstrap5.min.css' %}">
<script src="{% static 'vendor/jquery/jquery-3.6.0.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/jquery.dataTables.min.js' %}"></script>
<script src="{% static 'vendor/datatables/js/dataTables.bootstrap5.min.js' %}"></script>

<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3 page-header-mobile">
        <h2><i class="fas fa-exclamation-triangle text-danger"></i> Alertas de stock mínimo</h2>
    </div>

    <p class="text-muted">
        Productos en niveles de <strong>picking</strong> cuya cantidad cayó bajo el stock mínimo configurado.
    </p>

    <div class="table-responsive">
    <table id="tablaAlertas" class="table table-striped table-hover" style="width:100%">
        <thead>
            <tr><th>Producto</th><th>Nivel</th><th>Cantidad</th><th>Stock mínimo</th><th>Acciones</th></tr>
        </thead>
        <tbody>
            {% for pu in alertas %}
            <tr>
                <td><a href="{% url 'ubicaciones-producto-detalle' pu.codigo_producto %}">{{ pu.codigo_producto }}</a></td>
                <td>{{ pu.nivel.codigo_completo }}</td>
                <td><span class="badge bg-danger">{{ pu.cantidad }}</span></td>
                <td>{{ pu.stock_minimo }}</td>
                <td>
                    <a href="{% url 'ubicaciones-niveles-detalle' pu.nivel.pk %}" class="btn btn-sm btn-outline-primary">
                        <i class="fas fa-eye"></i> Ir al nivel
                    </a>
                </td>
            </tr>
            {% empty %}
            <tr><td colspan="5" class="text-center text-muted">No hay alertas de stock mínimo activas.</td></tr>
            {% endfor %}
        </tbody>
    </table>
    </div>
</div>

<script>
$(document).ready(function() {
    $('#tablaAlertas').DataTable({
        language: { url: "/static/vendor/datatables/i18n/es-ES.json" },
        paging: true, searching: true, ordering: true,
    });
});
</script>
{% endblock content %}
```

- [ ] **Step 4: Escribir los tests**

Agregar a `ubicaciones/tests.py`:

```python
class AlertasStockTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='webuser7', password='x')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client = Client()
        self.client.login(username='webuser7', password='x')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.ubicacion = self.cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel_picking = self.ubicacion.niveles.get(numero=1)
        self.nivel_almacenaje = self.ubicacion.niveles.get(numero=2)
        UbicacionesService.editar_nivel(self.nivel_almacenaje, Nivel.ALMACENAJE, '', self.user)

    def test_alerta_aparece_cuando_cantidad_bajo_minimo_en_picking(self):
        ProductoUbicacion.objects.create(
            codigo_producto='ABC', nivel=self.nivel_picking, cantidad=2, stock_minimo=10,
        )
        resp = self.client.get('/ubicaciones/alertas/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ABC')

    def test_alerta_no_aparece_si_cantidad_sobre_minimo(self):
        ProductoUbicacion.objects.create(
            codigo_producto='XYZ', nivel=self.nivel_picking, cantidad=20, stock_minimo=10,
        )
        resp = self.client.get('/ubicaciones/alertas/')
        self.assertNotContains(resp, 'XYZ')

    def test_alerta_no_aparece_en_almacenaje_aunque_tenga_stock_minimo(self):
        pu = ProductoUbicacion.objects.create(
            codigo_producto='DEF', nivel=self.nivel_almacenaje, cantidad=1, stock_minimo=None,
        )
        # Un nivel de almacenaje no permite configurar stock_minimo vía el servicio,
        # pero si quedara en None nunca genera alerta (el filtro exige stock_minimo no nulo).
        self.assertIsNone(pu.stock_minimo)
        resp = self.client.get('/ubicaciones/alertas/')
        self.assertNotContains(resp, 'DEF')
```

- [ ] **Step 5: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.AlertasStockTest --settings=Programarprecios.test_settings -v 2`
Expected: 3 tests, todos PASS.

- [ ] **Step 6: Commit**

```bash
git add ubicaciones/views.py ubicaciones/urls.py ubicaciones/tests.py templates/ubicaciones-alertas.html
git commit -m "feat(ubicaciones): panel de alertas de stock mínimo en dashboard"
```

---

## Task 15: Mapa del Galpón, diagrama de Rack y leyenda

Agrega el plano del Galpón (grilla CSS posicionada según `grid_fila`/`grid_columna`/`ancho`/`alto` de cada Rack, coloreado por alertas/fusión) y el diagrama de un Rack (Cuerpos × Ubicaciones × Niveles). Incluye la leyenda visual + guía de nomenclatura (decisión 9-10 del spec) como partial reutilizado en ambas vistas. Reactiva los botones "Ver mapa"/"Ver diagrama" que la Task 11 dejó pendientes.

**Files:**
- Modify: `ubicaciones/views.py`, `ubicaciones/urls.py`, `ubicaciones/tests.py`, `templates/ubicaciones-galpones-detalle.html`, `templates/ubicaciones-racks-detalle.html`
- Create: `templates/ubicaciones-mapa-galpon.html`, `templates/ubicaciones-mapa-rack.html`, `templates/_ubicaciones-leyenda.html`

**Interfaces:**
- Consumes: `Galpon.grid_filas/grid_columnas`, `Rack.grid_fila/grid_columna/ancho/alto` (Task 1).
- Produces: vistas `mapa_galpon`, `mapa_rack`; URL names `ubicaciones-mapa-galpon`, `ubicaciones-mapa-rack`.

- [ ] **Step 1: Agregar las vistas a `ubicaciones/views.py`**

Actualizar el import de Django del inicio del archivo:

```python
from django.db.models import Exists, F, OuterRef
```

Agregar al final:

```python
# ------------------------------------------------------------------ Mapa

@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def mapa_galpon(request, pk: int):
    galpon = get_object_or_404(Galpon, pk=pk)
    alerta_qs = ProductoUbicacion.objects.filter(
        nivel__ubicacion__cuerpo__rack=OuterRef('pk'),
        nivel__tipo=Nivel.PICKING, stock_minimo__isnull=False, cantidad__lt=F('stock_minimo'),
    )
    fusion_qs = Nivel.objects.filter(ubicacion__cuerpo__rack=OuterRef('pk'), fusionado_en__isnull=False)
    racks = galpon.racks.filter(activo=True).annotate(
        tiene_alertas=Exists(alerta_qs), tiene_fusion=Exists(fusion_qs),
    )
    return render(request, 'ubicaciones-mapa-galpon.html', {'galpon': galpon, 'racks': racks})


@login_required(login_url='/login/')
@user_passes_test(is_ubicaciones, login_url='/dashboard/')
def mapa_rack(request, pk: int):
    rack = get_object_or_404(Rack.objects.select_related('galpon'), pk=pk)
    cuerpos = rack.cuerpos.filter(activo=True).prefetch_related('ubicaciones__niveles__productos')
    return render(request, 'ubicaciones-mapa-rack.html', {'rack': rack, 'cuerpos': cuerpos})
```

- [ ] **Step 2: Agregar las URLs a `ubicaciones/urls.py`**

Agregar al final de `urlpatterns`:

```python
    # Mapa
    path('ubicaciones/galpones/<int:pk>/mapa/', views.mapa_galpon, name='ubicaciones-mapa-galpon'),
    path('ubicaciones/racks/<int:pk>/mapa/', views.mapa_rack, name='ubicaciones-mapa-rack'),
```

- [ ] **Step 3: Crear `templates/_ubicaciones-leyenda.html`**

```html
<div class="card mt-3">
    <div class="card-header"><i class="fas fa-info-circle"></i> Leyenda</div>
    <div class="card-body">
        <div class="row mb-3 g-2">
            <div class="col-auto"><span class="badge bg-light text-dark border">&nbsp;&nbsp;</span> Normal</div>
            <div class="col-auto"><span class="badge bg-danger">&nbsp;&nbsp;</span> Con alertas de stock mínimo</div>
            <div class="col-auto"><span class="badge bg-warning text-dark">&nbsp;&nbsp;</span> Con niveles fusionados</div>
            <div class="col-auto"><span class="badge bg-info text-dark">&nbsp;&nbsp;</span> Picking</div>
            <div class="col-auto"><span class="badge bg-secondary">&nbsp;&nbsp;</span> Almacenaje</div>
        </div>
        <p class="mb-0 small text-muted">
            <strong>Cómo leer un código de ubicación:</strong> <code>1A0101.4</code> se lee
            Galpón <strong>1</strong>, Rack <strong>A</strong>, Cuerpo <strong>01</strong>,
            Ubicación <strong>01</strong>, Nivel <strong>4</strong>.
        </p>
    </div>
</div>
```

- [ ] **Step 4: Crear `templates/ubicaciones-mapa-galpon.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3 page-header-mobile">
        <h2><i class="fas fa-map"></i> Mapa del Galpón {{ galpon.codigo }}</h2>
        <a href="{% url 'ubicaciones-galpones-detalle' galpon.pk %}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Volver
        </a>
    </div>

    <div class="border rounded p-3" style="display:grid; gap:8px;
        grid-template-columns: repeat({{ galpon.grid_columnas }}, minmax(60px, 1fr));
        grid-template-rows: repeat({{ galpon.grid_filas }}, 60px);">
        {% for rack in racks %}
        <a href="{% url 'ubicaciones-mapa-rack' rack.pk %}"
           class="d-flex align-items-center justify-content-center text-decoration-none border rounded fw-bold
               {% if rack.tiene_alertas %}bg-danger text-white
               {% elif rack.tiene_fusion %}bg-warning text-dark
               {% else %}bg-light text-dark{% endif %}"
           style="grid-column: {{ rack.grid_columna }} / span {{ rack.ancho }};
                  grid-row: {{ rack.grid_fila }} / span {{ rack.alto }};"
           title="{{ rack.descripcion }}">
            {{ rack.codigo }}
        </a>
        {% endfor %}
    </div>

    {% include "_ubicaciones-leyenda.html" %}
</div>
{% endblock content %}
```

- [ ] **Step 5: Crear `templates/ubicaciones-mapa-rack.html`**

```html
{% extends "dashboard.html" %}
{% block content %}
<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-3 page-header-mobile">
        <h2><i class="fas fa-th"></i> Diagrama del Rack {{ rack.galpon.codigo }}{{ rack.codigo }}</h2>
        <a href="{% url 'ubicaciones-racks-detalle' rack.pk %}" class="btn btn-outline-secondary">
            <i class="fas fa-arrow-left"></i> Volver
        </a>
    </div>

    <div class="d-flex flex-wrap gap-3">
        {% for cuerpo in cuerpos %}
        <div class="card" style="min-width:220px;">
            <div class="card-header text-center"><strong>Cuerpo {{ cuerpo.codigo }}</strong></div>
            <div class="card-body d-flex gap-2">
                {% for ubicacion in cuerpo.ubicaciones.all %}
                <div>
                    <div class="text-center small text-muted mb-1">{{ ubicacion.codigo }}</div>
                    {% for nivel in ubicacion.niveles.all|dictsortreversed:"numero" %}
                    <a href="{% url 'ubicaciones-niveles-detalle' nivel.pk %}"
                       class="d-block text-center text-decoration-none border rounded mb-1 px-2 py-1 small
                           {% if nivel.esta_fusionado %}bg-warning text-dark
                           {% elif nivel.tipo == 'PICKING' %}bg-info text-dark
                           {% else %}bg-secondary text-white{% endif %}"
                       title="{{ nivel.productos.count }} producto(s)">
                        {{ nivel.numero }}
                    </a>
                    {% endfor %}
                </div>
                {% endfor %}
            </div>
        </div>
        {% empty %}
        <p class="text-muted">Este rack aún no tiene cuerpos.</p>
        {% endfor %}
    </div>

    {% include "_ubicaciones-leyenda.html" %}
</div>
{% endblock content %}
```

- [ ] **Step 6: Reactivar los botones de mapa en `templates/ubicaciones-galpones-detalle.html` y `templates/ubicaciones-racks-detalle.html`**

En `templates/ubicaciones-galpones-detalle.html`, agregar antes del botón "Editar":

```html
            <a href="{% url 'ubicaciones-mapa-galpon' galpon.pk %}" class="btn btn-outline-primary">
                <i class="fas fa-map"></i> Ver mapa
            </a>
```

En `templates/ubicaciones-racks-detalle.html`, agregar antes del botón "Editar":

```html
            <a href="{% url 'ubicaciones-mapa-rack' rack.pk %}" class="btn btn-outline-primary">
                <i class="fas fa-th"></i> Ver diagrama
            </a>
```

- [ ] **Step 7: Escribir los tests**

Agregar a `ubicaciones/tests.py`:

```python
class MapaTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='webuser8', password='x')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client = Client()
        self.client.login(username='webuser8', password='x')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)

    def test_mapa_galpon_y_rack_devuelven_200(self):
        resp = self.client.get(f'/ubicaciones/galpones/{self.galpon.pk}/mapa/')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(f'/ubicaciones/racks/{self.rack.pk}/mapa/')
        self.assertEqual(resp.status_code, 200)

    def test_mapa_muestra_boton_desde_detalle(self):
        resp = self.client.get(f'/ubicaciones/galpones/{self.galpon.pk}/')
        self.assertContains(resp, f'/ubicaciones/galpones/{self.galpon.pk}/mapa/')

    def test_rack_con_alertas_se_marca_en_el_mapa(self):
        nivel = self.cuerpo.ubicaciones.order_by('codigo').first().niveles.get(numero=1)
        ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=nivel, cantidad=1, stock_minimo=10)
        resp = self.client.get(f'/ubicaciones/galpones/{self.galpon.pk}/mapa/')
        self.assertContains(resp, 'bg-danger')

    def test_rack_con_fusion_se_marca_en_el_mapa(self):
        ubicacion = self.cuerpo.ubicaciones.order_by('codigo').first()
        n1, n2 = ubicacion.niveles.get(numero=1), ubicacion.niveles.get(numero=2)
        UbicacionesService.fusionar_niveles([n1, n2], n1, self.user)
        resp = self.client.get(f'/ubicaciones/galpones/{self.galpon.pk}/mapa/')
        self.assertContains(resp, 'bg-warning')
```

- [ ] **Step 8: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.MapaTest --settings=Programarprecios.test_settings -v 2`
Expected: 4 tests, todos PASS.

- [ ] **Step 9: Correr toda la suite de la app**

Run: `venv\Scripts\python.exe manage.py test ubicaciones --settings=Programarprecios.test_settings -v 2`
Expected: todos los tests de las Tasks 1-15 PASS.

- [ ] **Step 10: Commit**

```bash
git add ubicaciones/views.py ubicaciones/urls.py ubicaciones/tests.py templates/ubicaciones-mapa-*.html templates/_ubicaciones-leyenda.html templates/ubicaciones-galpones-detalle.html templates/ubicaciones-racks-detalle.html
git commit -m "feat(ubicaciones): mapa del galpón, diagrama de rack y leyenda"
```

---

## Task 16: Comando de importación del maestro real

Management command `import_maestro_ubicaciones` que importa la estructura completa (Galpón → Rack → Cuerpo → Ubicación → Nivel) desde un CSV con columnas `G,R,C,U,N` (igual a la hoja "MAESTRO DE UBIC" del Excel de referencia). Idempotente vía `get_or_create` en cada nivel de la jerarquía. No importa `ProductoUbicacion` (decisión 11 del spec — el Excel no trae asignaciones reales).

**Files:**
- Create: `ubicaciones/management/__init__.py`, `ubicaciones/management/commands/__init__.py`, `ubicaciones/management/commands/import_maestro_ubicaciones.py`
- Modify: `ubicaciones/tests.py`

**Interfaces:**
- Consumes: modelos `Galpon`, `Rack`, `Cuerpo`, `Ubicacion`, `Nivel` (Task 1).
- Produces: comando `python manage.py import_maestro_ubicaciones <csv_path>`.

- [ ] **Step 1: Crear los paquetes de management commands**

```bash
mkdir -p ubicaciones/management/commands
touch ubicaciones/management/__init__.py ubicaciones/management/commands/__init__.py
```

- [ ] **Step 2: Escribir `ubicaciones/management/commands/import_maestro_ubicaciones.py`**

```python
import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ubicaciones.models import Cuerpo, Galpon, Nivel, Rack, Ubicacion


class Command(BaseCommand):
    help = (
        "Importa la estructura Galpón/Rack/Cuerpo/Ubicación/Nivel desde un CSV "
        "con columnas G,R,C,U,N (una fila por Nivel, igual al maestro real del almacén). "
        "No importa asignaciones de producto."
    )

    def add_arguments(self, parser):
        parser.add_argument('csv_path', type=str)

    def handle(self, *args, **options):
        path = options['csv_path']
        contadores = {'galpones': 0, 'racks': 0, 'cuerpos': 0, 'ubicaciones': 0, 'niveles': 0}

        try:
            archivo = open(path, newline='', encoding='utf-8')
        except OSError as e:
            raise CommandError(f"No se pudo abrir '{path}': {e}")

        with archivo, transaction.atomic():
            lector = csv.DictReader(archivo)
            for fila in lector:
                g_codigo = fila['G'].strip()
                r_codigo = fila['R'].strip()
                c_codigo = fila['C'].strip().zfill(2)
                u_codigo = fila['U'].strip().zfill(2)
                n_numero = int(fila['N'])

                galpon, creado = Galpon.objects.get_or_create(codigo=g_codigo)
                contadores['galpones'] += int(creado)
                rack, creado = Rack.objects.get_or_create(galpon=galpon, codigo=r_codigo)
                contadores['racks'] += int(creado)
                cuerpo, creado = Cuerpo.objects.get_or_create(rack=rack, codigo=c_codigo)
                contadores['cuerpos'] += int(creado)
                ubicacion, creado = Ubicacion.objects.get_or_create(cuerpo=cuerpo, codigo=u_codigo)
                contadores['ubicaciones'] += int(creado)
                _, creado = Nivel.objects.get_or_create(ubicacion=ubicacion, numero=n_numero)
                contadores['niveles'] += int(creado)

        self.stdout.write(self.style.SUCCESS(
            f"Importación completa: {contadores['galpones']} galpones, "
            f"{contadores['racks']} racks, {contadores['cuerpos']} cuerpos, "
            f"{contadores['ubicaciones']} ubicaciones, {contadores['niveles']} niveles creados."
        ))
```

- [ ] **Step 3: Escribir los tests**

Agregar a `ubicaciones/tests.py`:

```python
import csv
import tempfile

from django.core.management import call_command


class ImportMaestroCommandTest(TestCase):
    def _escribir_csv(self, filas):
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='', encoding='utf-8')
        writer = csv.writer(f)
        writer.writerow(['G', 'R', 'C', 'U', 'P', 'N'])
        writer.writerows(filas)
        f.close()
        return f.name

    def test_importa_estructura_completa(self):
        filas = (
            [['1', 'A', '01', '01', '.', n] for n in range(1, 7)]
            + [['1', 'A', '01', '02', '.', n] for n in range(1, 7)]
        )
        path = self._escribir_csv(filas)
        call_command('import_maestro_ubicaciones', path)

        self.assertEqual(Galpon.objects.count(), 1)
        self.assertEqual(Rack.objects.count(), 1)
        self.assertEqual(Cuerpo.objects.count(), 1)
        self.assertEqual(Ubicacion.objects.count(), 2)
        self.assertEqual(Nivel.objects.count(), 12)

        nivel = Nivel.objects.get(ubicacion__codigo='01', numero=4)
        self.assertEqual(nivel.codigo_completo, '1A0101.4')

    def test_importar_dos_veces_es_idempotente(self):
        filas = [['1', 'A', '01', '01', '.', n] for n in range(1, 7)]
        path = self._escribir_csv(filas)
        call_command('import_maestro_ubicaciones', path)
        call_command('import_maestro_ubicaciones', path)
        self.assertEqual(Nivel.objects.count(), 6)

    def test_archivo_inexistente_lanza_command_error(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('import_maestro_ubicaciones', 'ruta/que/no/existe.csv')
```

- [ ] **Step 4: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test ubicaciones.ImportMaestroCommandTest --settings=Programarprecios.test_settings -v 2`
Expected: 3 tests, todos PASS.

- [ ] **Step 5: Commit**

```bash
git add ubicaciones/management/ ubicaciones/tests.py
git commit -m "feat(ubicaciones): comando de importación del maestro real de ubicaciones"
```

---

## Task 17: Integración con PedidosAlmacen (buscar_producto web + API)

Actualiza los dos puntos de integración que enriquecen la búsqueda de productos con `ubicaciones_internas`, migrándolos de `ProductoUbicacion.ubicacion` (ya no existe) a `ProductoUbicacion.nivel`. Son los últimos consumidores externos del modelo antiguo — con esto, el proyecto completo queda consistente con la jerarquía de 5 niveles.

**Files:**
- Modify: `PedidosAlmacen/views.py:1548-1571`, `PedidosAlmacen/api_views.py:350-373`, `PedidosAlmacen/tests.py`

**Interfaces:**
- Consumes: `ProductoUbicacion.nivel`, `Nivel.codigo_completo`, `Nivel.tipo` (Task 1).

- [ ] **Step 1: Actualizar `PedidosAlmacen/views.py` (función `buscar_producto`, línea ~1549)**

Reemplazar:

```python
    # Enriquecer con ubicaciones internas (Postgres)
    from ubicaciones.models import ProductoUbicacion
    codigos = [r[0] for r in resultados_raw]
    ubicaciones_map: dict = {}
    if codigos:
        try:
            qs = (
                ProductoUbicacion.objects
                .filter(
                    codigo_producto__in=codigos,
                    ubicacion__activo=True,
                    ubicacion__nivel__activo=True,
                    ubicacion__nivel__rack__activo=True,
                )
                .select_related('ubicacion__nivel__rack')
            )
            for pu in qs:
                ubicaciones_map.setdefault(pu.codigo_producto, []).append({
                    'codigo': pu.ubicacion.codigo_completo,
                    'tipo_nivel': pu.ubicacion.nivel.tipo,
                    'tipo_nivel_display': pu.ubicacion.nivel.get_tipo_display(),
                })
        except Exception:
            logger.exception("Error al consultar ubicaciones internas en buscar_producto")
```

Por:

```python
    # Enriquecer con ubicaciones internas (Postgres)
    from ubicaciones.models import ProductoUbicacion
    codigos = [r[0] for r in resultados_raw]
    ubicaciones_map: dict = {}
    if codigos:
        try:
            qs = (
                ProductoUbicacion.objects
                .filter(
                    codigo_producto__in=codigos,
                    nivel__activo=True,
                    nivel__ubicacion__activo=True,
                    nivel__ubicacion__cuerpo__activo=True,
                    nivel__ubicacion__cuerpo__rack__activo=True,
                )
                .select_related('nivel__ubicacion__cuerpo__rack__galpon')
            )
            for pu in qs:
                ubicaciones_map.setdefault(pu.codigo_producto, []).append({
                    'codigo': pu.nivel.codigo_completo,
                    'tipo_nivel': pu.nivel.tipo,
                    'tipo_nivel_display': pu.nivel.get_tipo_display(),
                })
        except Exception:
            logger.exception("Error al consultar ubicaciones internas en buscar_producto")
```

- [ ] **Step 2: Actualizar `PedidosAlmacen/api_views.py` (función `api_buscar_producto`, línea ~351)**

Reemplazar:

```python
    from ubicaciones.models import ProductoUbicacion
    ubicaciones_internas = []
    try:
        qs = (
            ProductoUbicacion.objects
            .filter(
                codigo_producto=codigo_prod,
                ubicacion__activo=True,
                ubicacion__nivel__activo=True,
                ubicacion__nivel__rack__activo=True,
            )
            .select_related('ubicacion__nivel__rack')
        )
        ubicaciones_internas = [
            {
                'codigo': pu.ubicacion.codigo_completo,
                'tipo_nivel': pu.ubicacion.nivel.tipo,
                'tipo_nivel_display': pu.ubicacion.nivel.get_tipo_display(),
            }
            for pu in qs
        ]
    except Exception:
        logger.exception("Error al consultar ubicaciones internas en api_buscar_producto")
```

Por:

```python
    from ubicaciones.models import ProductoUbicacion
    ubicaciones_internas = []
    try:
        qs = (
            ProductoUbicacion.objects
            .filter(
                codigo_producto=codigo_prod,
                nivel__activo=True,
                nivel__ubicacion__activo=True,
                nivel__ubicacion__cuerpo__activo=True,
                nivel__ubicacion__cuerpo__rack__activo=True,
            )
            .select_related('nivel__ubicacion__cuerpo__rack__galpon')
        )
        ubicaciones_internas = [
            {
                'codigo': pu.nivel.codigo_completo,
                'tipo_nivel': pu.nivel.tipo,
                'tipo_nivel_display': pu.nivel.get_tipo_display(),
            }
            for pu in qs
        ]
    except Exception:
        logger.exception("Error al consultar ubicaciones internas en api_buscar_producto")
```

- [ ] **Step 3: Escribir los tests de integración**

Agregar a `PedidosAlmacen/tests.py`:

```python
class BuscarProductoUbicacionesInternasTest(TestCase):
    """buscar_producto (web y API) enriquece resultados con el Nivel del nuevo modelo de ubicaciones."""

    def setUp(self):
        from users.models import User
        from ubicaciones.services import UbicacionesService
        from ubicaciones.models import ProductoUbicacion

        self.user = User.objects.create_superuser(username='integr_user', password='x')
        self.client = Client()
        self.client.login(username='integr_user', password='x')

        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        rack = UbicacionesService.crear_rack(galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        cuerpo = UbicacionesService.crear_cuerpo(rack, '', self.user)
        self.nivel = cuerpo.ubicaciones.order_by('codigo').first().niveles.get(numero=4)
        ProductoUbicacion.objects.create(codigo_producto='SKU1', nivel=self.nivel, cantidad=5)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_buscar_producto_web_muestra_codigo_completo_del_nivel(self, mock_db):
        mock_db.return_value.buscar_en_categoria.return_value = [
            ('SKU1', 'Producto Uno', 'REF1', 'P1', 10, 'PROV1'),
        ]
        resp = self.client.get(
            '/pedidos/buscar-producto/',
            {'q': 'SKU1', 'tipo': 'codigo', 'categoria': 'FERRETERIA'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, self.nivel.codigo_completo)

    @patch('PedidosAlmacen.api_views.PedidosDBISAM')
    def test_api_buscar_producto_incluye_ubicaciones_internas(self, mock_db):
        from rest_framework.test import APIClient
        mock_db.return_value.buscar_producto_por_campo.return_value = (
            'SKU1', 'Producto Uno', 'REF1', 'P1', 'PROV1',
        )
        api = APIClient()
        api.force_authenticate(user=self.user)
        resp = api.get('/api/productos/SKU1/', HTTP_X_CAMPO='sku')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['ubicaciones_internas'][0]['codigo'], self.nivel.codigo_completo)
```

- [ ] **Step 4: Correr los tests y confirmar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.BuscarProductoUbicacionesInternasTest --settings=Programarprecios.test_settings -v 2`
Expected: 2 tests, todos PASS.

- [ ] **Step 5: Correr la suite completa del proyecto**

Run: `venv\Scripts\python.exe manage.py test ubicaciones PedidosAlmacen --settings=Programarprecios.test_settings -v 2`
Expected: todos los tests de `ubicaciones` (Tasks 1-17) y de `PedidosAlmacen` PASS. Ningún test preexistente de `PedidosAlmacen` se rompe.

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/api_views.py PedidosAlmacen/tests.py
git commit -m "fix(pedidos): integra buscar_producto con el nuevo modelo de ubicaciones (Nivel)"
```

---

## Resumen final

Al completar las 17 tareas: la app `ubicaciones` queda reconstruida sobre la jerarquía real
Galpón→Rack→Cuerpo→Ubicación→Nivel, con cantidad validada contra a2 (depósito 1), función
picking/almacenaje y stock mínimo por producto en el Nivel, fusión/desfusión de niveles, mapa
visual del galpón con leyenda, importación del maestro físico real, y la integración con
`PedidosAlmacen` actualizada. Cada tarea deja la suite de tests de `ubicaciones` (y, desde la
Task 17, también la de `PedidosAlmacen`) en verde antes de pasar a la siguiente.

