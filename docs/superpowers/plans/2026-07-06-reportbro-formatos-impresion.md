# Formatos de impresión editables con ReportBro — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un superusuario edita visualmente los formatos PDF de despacho y pedido desde la app (sección "Formatos de impresión"); la generación real usa la plantilla activa con fallback al reportlab actual.

**Architecture:** App Django nueva `formatos` con modelo singleton-por-tipo `PlantillaImpresion` (JSON de ReportBro en PostgreSQL), contrato de datos en `formatos/contratos.py` (única fuente para generación real y preview), diseñador `reportbro-designer` self-hosted servido en una página propia, endpoint `report/run` para previews (protocolo estándar del diseñador) y `formatos/generacion.py` con `generar_pdf()` que devuelve `None` ante cualquier fallo para que las vistas de PedidosAlmacen caigan al generador reportlab intacto.

**Tech Stack:** Django 5.2, reportbro-lib (~3.12, PyPI), reportbro-designer (JS self-hosted), PostgreSQL (SQLite en tests), reportlab 4.4.5 (fallback existente).

**Spec:** `docs/superpowers/specs/2026-07-06-reportbro-formatos-impresion-design.md`

**Referencia de integración:** demo oficial [jobsta/albumapp-django](https://github.com/jobsta/albumapp-django) (los archivos clave están descargados en el scratchpad de la sesión, carpeta `albumapp/`).

## Global Constraints

- **No modificar `PedidosAlmacen/pdf.py`** — es el fallback y debe quedar intacto.
- Solo **superusuarios** acceden a cualquier vista de `formatos` (patrón: `user_passes_test(lambda u: u.is_superuser, login_url='dashboard')`).
- Licencia elegida: **AGPLv3** (uso interno). No instalar componentes "PLUS".
- `requirements.txt` está codificado en **UTF-16 LE**; editarlo conservando esa codificación.
- Python del proyecto: `venv\Scripts\python.exe` (Windows, PowerShell 5.1 — sin `&&`).
- Tests: el usuario PostgreSQL no tiene CREATEDB. Ejecutar SIEMPRE con SQLite en memoria:
  `$env:PYTHONPATH='C:\Users\arang\AppData\Local\Temp\claude\C--Proyectos-Python-Precios-KsaHome\1b824e4c-0f5a-475a-b877-3e9ddc5c2f1c\scratchpad'; venv\Scripts\python.exe manage.py test formatos --settings=test_settings_sqlite`
  Si `test_settings_sqlite.py` no existe en esa carpeta, crearlo con:

  ```python
  from Programarprecios.settings import *  # noqa: F401,F403

  DATABASES = {
      'default': {
          'ENGINE': 'django.db.backends.sqlite3',
          'NAME': ':memory:',
      }
  }
  ```
- Convenciones del proyecto: PEP 8, type hints, docstrings Google, nombres en español (patrón existente).
- Decisión de alcance: la plantilla ReportBro de pedido aplica solo a la vista `todos` de `exportar_pedido_pdf`; las variantes filtradas (`despachado`, `back_order`, `recibido`, `parcial`) siguen saliendo por reportlab.
- Nota de implementación vs spec: las plantillas semilla se construyen en `formatos/semillas.py` (dicts Python compactos y testeables) en lugar de archivos JSON estáticos; el resultado sembrado es el mismo JSON.
- Nota de implementación vs spec (CSRF): el guardado sí envía `X-CSRFToken`, pero el PUT interno del diseñador a `report/run` no envía token — ese endpoint usa `csrf_exempt` protegido por sesión de superusuario (mismo patrón del demo oficial).

---

### Task 1: App `formatos` con modelos y dependencia reportbro-lib

**Files:**
- Create: `formatos/` (startapp: `__init__.py`, `apps.py`, `models.py`, `tests.py`, `migrations/`)
- Modify: `Programarprecios/settings.py:117` (INSTALLED_APPS), `requirements.txt`
- Test: `formatos/tests.py`

**Interfaces:**
- Produces: modelo `formatos.models.PlantillaImpresion` con campos `tipo` (str, choices `'despacho'|'pedido'`, unique), `definicion` (dict), `definicion_anterior` (dict|None), `activa` (bool), `actualizado_por` (User|None), `fecha_actualizacion`; métodos `actualizar_definicion(definicion: dict, usuario) -> None` y `restaurar() -> bool`. Modelo `formatos.models.ReportePreview` con `key` (str 36, unique), `pdf` (bytes), `creado` (datetime auto). Constante `formatos.models.TIPOS_VALIDOS = ('despacho', 'pedido')`.

- [ ] **Step 1: Instalar reportbro-lib y registrar la dependencia**

```powershell
venv\Scripts\python.exe -m pip install reportbro-lib
venv\Scripts\python.exe -c "import reportbro; print(reportbro.__version__ if hasattr(reportbro,'__version__') else 'ok')"
```

Añadir a `requirements.txt` (conservando UTF-16 LE; añadir la línea con la versión que instaló pip, ej. `reportbro-lib==3.12.2`):

```powershell
$v = venv\Scripts\python.exe -m pip show reportbro-lib | Select-String '^Version:' | ForEach-Object { $_.ToString().Split(' ')[1] }
Add-Content -Path requirements.txt -Value "reportbro-lib==$v" -Encoding Unicode
```

- [ ] **Step 2: Crear la app y registrarla**

```powershell
venv\Scripts\python.exe manage.py startapp formatos
```

En `Programarprecios/settings.py`, INSTALLED_APPS (línea ~117), añadir después de `'ubicaciones',`:

```python
    'formatos',
```

- [ ] **Step 3: Escribir los tests que fallan**

Reemplazar `formatos/tests.py` con:

```python
from django.db import IntegrityError
from django.test import TestCase

from users.models import User

from .models import PlantillaImpresion, TIPOS_VALIDOS


class PlantillaImpresionModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='fmt_admin', password='x')

    def test_tipos_validos(self):
        self.assertEqual(TIPOS_VALIDOS, ('despacho', 'pedido'))

    def test_tipo_es_unico(self):
        PlantillaImpresion.objects.create(tipo='despacho', definicion={'version': 4})
        with self.assertRaises(IntegrityError):
            PlantillaImpresion.objects.create(tipo='despacho', definicion={'version': 4})

    def test_actualizar_definicion_rota_version_anterior(self):
        p = PlantillaImpresion.objects.create(tipo='despacho', definicion={'v': 1})
        p.actualizar_definicion({'v': 2}, self.user)
        p.refresh_from_db()
        self.assertEqual(p.definicion, {'v': 2})
        self.assertEqual(p.definicion_anterior, {'v': 1})
        self.assertEqual(p.actualizado_por, self.user)

    def test_restaurar_intercambia_versiones(self):
        p = PlantillaImpresion.objects.create(
            tipo='pedido', definicion={'v': 2}, definicion_anterior={'v': 1})
        self.assertTrue(p.restaurar())
        p.refresh_from_db()
        self.assertEqual(p.definicion, {'v': 1})
        self.assertEqual(p.definicion_anterior, {'v': 2})

    def test_restaurar_sin_version_anterior_devuelve_false(self):
        p = PlantillaImpresion.objects.create(tipo='pedido', definicion={'v': 1})
        self.assertFalse(p.restaurar())
```

- [ ] **Step 4: Ejecutar los tests y verificar que fallan**

Run: `$env:PYTHONPATH='C:\Users\arang\AppData\Local\Temp\claude\C--Proyectos-Python-Precios-KsaHome\1b824e4c-0f5a-475a-b877-3e9ddc5c2f1c\scratchpad'; venv\Scripts\python.exe manage.py test formatos --settings=test_settings_sqlite -v 2`

Expected: FAIL/ERROR con `ImportError` (PlantillaImpresion no existe).

- [ ] **Step 5: Implementación mínima**

Reemplazar `formatos/models.py` con:

```python
from django.db import models

TIPOS_VALIDOS = ('despacho', 'pedido')


class PlantillaImpresion(models.Model):
    """Plantilla ReportBro de un tipo de documento (una fila por tipo)."""

    TIPO_CHOICES = [('despacho', 'Despacho'), ('pedido', 'Pedido')]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, unique=True)
    definicion = models.JSONField(help_text="Definición JSON producida por ReportBro Designer.")
    definicion_anterior = models.JSONField(null=True, blank=True)
    activa = models.BooleanField(default=False)
    actualizado_por = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='plantillas_actualizadas',
    )
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Plantilla de impresión'
        verbose_name_plural = 'Plantillas de impresión'

    def __str__(self):
        estado = 'activa' if self.activa else 'inactiva'
        return f"Plantilla {self.get_tipo_display()} ({estado})"

    def actualizar_definicion(self, definicion: dict, usuario) -> None:
        """Guarda una nueva definición rotando la actual a definicion_anterior."""
        self.definicion_anterior = self.definicion
        self.definicion = definicion
        self.actualizado_por = usuario
        self.save()

    def restaurar(self) -> bool:
        """Intercambia definicion y definicion_anterior. False si no hay anterior."""
        if self.definicion_anterior is None:
            return False
        self.definicion, self.definicion_anterior = self.definicion_anterior, self.definicion
        self.save()
        return True


class ReportePreview(models.Model):
    """PDF efímero generado para el preview del diseñador (patrón albumapp-django)."""

    key = models.CharField(max_length=36, unique=True)
    pdf = models.BinaryField()
    creado = models.DateTimeField(auto_now_add=True)
```

Crear la migración:

```powershell
venv\Scripts\python.exe manage.py makemigrations formatos
```

- [ ] **Step 6: Ejecutar los tests y verificar que pasan**

Run: mismo comando del Step 4. Expected: `OK` (5 tests).

- [ ] **Step 7: Aplicar la migración a la BD real y commit**

```powershell
venv\Scripts\python.exe manage.py migrate formatos
git add formatos/ Programarprecios/settings.py requirements.txt
git commit -m "feat(formatos): app de plantillas de impresion con modelos base"
```

---

### Task 2: Contrato de datos (`formatos/contratos.py`)

**Files:**
- Create: `formatos/contratos.py`
- Test: `formatos/tests.py` (añadir clase)

**Interfaces:**
- Consumes: modelos `PedidosAlmacen.models.Pedido/PedidoItem/Despacho/DespachoItem` (campos reales verificados: `PedidoItem.codigo/descripcion/referencia/puesto/ref_proveedor/cantidad_solicitada/cantidad_despachada/cantidad_back_order/cantidad_recibida/estado/observacion`; `DespachoItem.pedido_item` es **nullable** — SKU no contemplado usa `codigo_real`/`descripcion_real`).
- Produces: `datos_despacho(despacho, items) -> dict`, `datos_pedido(pedido, items) -> dict`, `datos_ejemplo(tipo: str) -> dict` (lanza `ValueError` con tipo desconocido). Claves de despacho: `numero_despacho, numero_pedido, estado, condicion, deposito, solicitante, despachador, picker, receptor, fecha_despacho, fecha_recepcion, observaciones, items, total_items, total_despachado`. Claves de pedido: `numero_pedido, estado, condicion, deposito, categoria, solicitante, despachador, picker, fecha_creacion, fecha_despacho, fecha_recepcion, observaciones, items, total_items, total_solicitado`. Fechas como str `dd/mm/YYYY HH:MM` (vacía si None); usuarios como username.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir a `formatos/tests.py`:

```python
CLAVES_DESPACHO = {
    'numero_despacho', 'numero_pedido', 'estado', 'condicion', 'deposito',
    'solicitante', 'despachador', 'picker', 'receptor', 'fecha_despacho',
    'fecha_recepcion', 'observaciones', 'items', 'total_items', 'total_despachado',
}
CLAVES_PEDIDO = {
    'numero_pedido', 'estado', 'condicion', 'deposito', 'categoria',
    'solicitante', 'despachador', 'picker', 'fecha_creacion', 'fecha_despacho',
    'fecha_recepcion', 'observaciones', 'items', 'total_items', 'total_solicitado',
}
CLAVES_ITEM_DESPACHO = {
    'codigo', 'descripcion', 'referencia', 'puesto', 'ref_proveedor',
    'cantidad_solicitada', 'cantidad_despachada', 'cantidad_recibida', 'observacion',
}
CLAVES_ITEM_PEDIDO = CLAVES_ITEM_DESPACHO - {'cantidad_recibida'} | {
    'cantidad_back_order', 'cantidad_recibida', 'estado',
}


class ContratosDatosTest(TestCase):
    def setUp(self):
        from PedidosAlmacen.models import Pedido, PedidoItem, Despacho, DespachoItem
        self.user = User.objects.create_superuser(username='fmt_datos', password='x')
        self.pedido = Pedido.objects.create(
            solicitante=self.user, deposito='Tienda Centro', condicion='URGENTE')
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='A1', descripcion='Taza', referencia='R1',
            puesto='P1', ref_proveedor='RP1', cantidad_solicitada=10,
            cantidad_despachada=8, observacion='obs item')
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='ENVIADO')
        self.ditem = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item, cantidad_despachada=8)

    def test_datos_despacho_devuelve_claves_prometidas(self):
        from .contratos import datos_despacho
        datos = datos_despacho(self.despacho, self.despacho.items.all())
        self.assertEqual(set(datos.keys()), CLAVES_DESPACHO)
        self.assertEqual(set(datos['items'][0].keys()), CLAVES_ITEM_DESPACHO)
        self.assertEqual(datos['total_despachado'], 8)
        self.assertEqual(datos['condicion'], 'Urgente')

    def test_datos_despacho_item_sin_pedido_item_usa_codigo_real(self):
        from PedidosAlmacen.models import DespachoItem
        from .contratos import datos_despacho
        DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=None, cantidad_despachada=2,
            tipo_incidencia='SKU_NO_CONTEMPLADO', codigo_real='X9',
            descripcion_real='SKU extra')
        datos = datos_despacho(self.despacho, self.despacho.items.all())
        fila = [f for f in datos['items'] if f['codigo'] == 'X9'][0]
        self.assertEqual(fila['descripcion'], 'SKU extra')
        self.assertEqual(fila['cantidad_solicitada'], 0)

    def test_datos_pedido_devuelve_claves_prometidas(self):
        from .contratos import datos_pedido
        datos = datos_pedido(self.pedido, self.pedido.items.all())
        self.assertEqual(set(datos.keys()), CLAVES_PEDIDO)
        self.assertEqual(set(datos['items'][0].keys()), CLAVES_ITEM_PEDIDO)
        self.assertEqual(datos['total_solicitado'], 10)

    def test_datos_ejemplo_usa_ultimo_registro_real(self):
        from .contratos import datos_ejemplo
        datos = datos_ejemplo('despacho')
        self.assertEqual(datos['numero_despacho'], self.despacho.numero_despacho)

    def test_datos_ejemplo_sin_registros_devuelve_sintetico(self):
        from PedidosAlmacen.models import Despacho, DespachoItem
        from .contratos import datos_ejemplo
        DespachoItem.objects.all().delete()
        Despacho.objects.all().delete()
        datos = datos_ejemplo('despacho')
        self.assertEqual(set(datos.keys()), CLAVES_DESPACHO)
        self.assertTrue(datos['items'])

    def test_datos_ejemplo_tipo_desconocido(self):
        from .contratos import datos_ejemplo
        with self.assertRaises(ValueError):
            datos_ejemplo('factura')
```

- [ ] **Step 2: Ejecutar los tests y verificar que fallan**

Run: `$env:PYTHONPATH='...scratchpad'; venv\Scripts\python.exe manage.py test formatos.tests.ContratosDatosTest --settings=test_settings_sqlite -v 2`

Expected: ERROR `ModuleNotFoundError: No module named 'formatos.contratos'`.

- [ ] **Step 3: Implementación mínima**

Crear `formatos/contratos.py`:

```python
"""Contrato de datos para las plantillas ReportBro.

El código define aquí qué datos puede usar cada plantilla; el diseñador solo
los consume. Estas funciones son la única fuente de datos tanto para la
generación real como para el preview.
"""
from django.utils import timezone


def _fmt_fecha(valor) -> str:
    if not valor:
        return ''
    return timezone.localtime(valor).strftime('%d/%m/%Y %H:%M')


def _usuario(usuario) -> str:
    return usuario.username if usuario else ''


def datos_despacho(despacho, items) -> dict:
    """Arma el diccionario de datos de un despacho para ReportBro.

    Args:
        despacho: Instancia de Despacho.
        items: Iterable de DespachoItem (idealmente select_related('pedido_item')).

    Returns:
        Diccionario con las claves del contrato de despacho.
    """
    pedido = despacho.pedido
    filas = []
    for item in items:
        pi = item.pedido_item
        filas.append({
            'codigo': pi.codigo if pi else item.codigo_real,
            'descripcion': pi.descripcion if pi else item.descripcion_real,
            'referencia': pi.referencia if pi else '',
            'puesto': pi.puesto if pi else '',
            'ref_proveedor': pi.ref_proveedor if pi else '',
            'cantidad_solicitada': pi.cantidad_solicitada if pi else 0,
            'cantidad_despachada': item.cantidad_despachada,
            'cantidad_recibida': item.cantidad_recibida,
            'observacion': item.observacion,
        })
    return {
        'numero_despacho': despacho.numero_despacho,
        'numero_pedido': pedido.numero_pedido,
        'estado': despacho.get_estado_display(),
        'condicion': pedido.get_condicion_display() if pedido.condicion else '',
        'deposito': pedido.deposito,
        'solicitante': _usuario(pedido.solicitante),
        'despachador': _usuario(despacho.despachador),
        'picker': _usuario(despacho.picker),
        'receptor': _usuario(despacho.receptor),
        'fecha_despacho': _fmt_fecha(despacho.fecha_despacho),
        'fecha_recepcion': _fmt_fecha(despacho.fecha_recepcion),
        'observaciones': despacho.observaciones,
        'items': filas,
        'total_items': len(filas),
        'total_despachado': sum(f['cantidad_despachada'] for f in filas),
    }


def datos_pedido(pedido, items) -> dict:
    """Arma el diccionario de datos de un pedido para ReportBro."""
    filas = [{
        'codigo': it.codigo,
        'descripcion': it.descripcion,
        'referencia': it.referencia,
        'puesto': it.puesto,
        'ref_proveedor': it.ref_proveedor,
        'cantidad_solicitada': it.cantidad_solicitada,
        'cantidad_despachada': it.cantidad_despachada,
        'cantidad_back_order': it.cantidad_back_order,
        'cantidad_recibida': it.cantidad_recibida,
        'estado': it.get_estado_display(),
        'observacion': it.observacion,
    } for it in items]
    return {
        'numero_pedido': pedido.numero_pedido,
        'estado': pedido.get_estado_display(),
        'condicion': pedido.get_condicion_display() if pedido.condicion else '',
        'deposito': pedido.deposito,
        'categoria': pedido.categoria_nombre or pedido.categoria,
        'solicitante': _usuario(pedido.solicitante),
        'despachador': _usuario(pedido.despachador),
        'picker': _usuario(pedido.picker),
        'fecha_creacion': _fmt_fecha(pedido.fecha_creacion),
        'fecha_despacho': _fmt_fecha(pedido.fecha_despacho),
        'fecha_recepcion': _fmt_fecha(pedido.fecha_recepcion),
        'observaciones': pedido.observaciones,
        'items': filas,
        'total_items': len(filas),
        'total_solicitado': sum(f['cantidad_solicitada'] for f in filas),
    }


_ITEM_SINTETICO = {
    'codigo': 'ABC123', 'descripcion': 'Producto de ejemplo', 'referencia': 'REF-1',
    'puesto': 'A-01', 'ref_proveedor': 'PROV-9', 'cantidad_solicitada': 10,
    'cantidad_despachada': 8, 'cantidad_recibida': 8, 'observacion': '',
}

_EJEMPLO_DESPACHO = {
    'numero_despacho': 1, 'numero_pedido': 1, 'estado': 'Enviado',
    'condicion': 'Urgente', 'deposito': 'Tienda de ejemplo',
    'solicitante': 'tienda', 'despachador': 'almacen', 'picker': 'picker',
    'receptor': '', 'fecha_despacho': '01/01/2026 08:00', 'fecha_recepcion': '',
    'observaciones': 'Datos de ejemplo', 'items': [dict(_ITEM_SINTETICO)],
    'total_items': 1, 'total_despachado': 8,
}

_EJEMPLO_PEDIDO = {
    'numero_pedido': 1, 'estado': 'Pendiente', 'condicion': 'Surtido',
    'deposito': 'Tienda de ejemplo', 'categoria': 'Hogar',
    'solicitante': 'tienda', 'despachador': '', 'picker': '',
    'fecha_creacion': '01/01/2026 08:00', 'fecha_despacho': '', 'fecha_recepcion': '',
    'observaciones': 'Datos de ejemplo',
    'items': [{**_ITEM_SINTETICO, 'cantidad_back_order': 2, 'estado': 'Pendiente'}],
    'total_items': 1, 'total_solicitado': 10,
}


def datos_ejemplo(tipo: str) -> dict:
    """Datos de prueba para preview/validación: último registro real o sintético.

    Raises:
        ValueError: si el tipo no es 'despacho' ni 'pedido'.
    """
    from PedidosAlmacen.models import Despacho, Pedido

    if tipo == 'despacho':
        despacho = (Despacho.objects.select_related('pedido__solicitante')
                    .order_by('-numero_despacho').first())
        if despacho is not None:
            return datos_despacho(despacho, despacho.items.select_related('pedido_item'))
        return dict(_EJEMPLO_DESPACHO)
    if tipo == 'pedido':
        pedido = (Pedido.objects.select_related('solicitante')
                  .order_by('-numero_pedido').first())
        if pedido is not None:
            return datos_pedido(pedido, pedido.items.all())
        return dict(_EJEMPLO_PEDIDO)
    raise ValueError(f'Tipo de documento desconocido: {tipo}')
```

- [ ] **Step 4: Ejecutar los tests y verificar que pasan**

Run: mismo comando del Step 2. Expected: `OK` (6 tests).

- [ ] **Step 5: Commit**

```powershell
git add formatos/contratos.py formatos/tests.py
git commit -m "feat(formatos): contrato de datos para despacho y pedido"
```

---

### Task 3: Plantillas semilla y `obtener_plantilla`

**Files:**
- Create: `formatos/semillas.py`
- Modify: `formatos/models.py` (añadir `obtener_plantilla`)
- Test: `formatos/tests.py` (añadir clase)

**Interfaces:**
- Consumes: `datos_ejemplo(tipo)` (Task 2), `reportbro.Report`.
- Produces: `formatos.semillas.SEMILLAS: dict[str, dict]` con claves `'despacho'` y `'pedido'` (definiciones ReportBro completas: `docElements`, `parameters`, `styles`, `version`, `documentProperties`); `formatos.models.obtener_plantilla(tipo: str) -> PlantillaImpresion` (obtiene la fila o la crea inactiva con la semilla; `ValueError` si tipo inválido).

- [ ] **Step 1: Escribir los tests que fallan**

Añadir a `formatos/tests.py`:

```python
class SemillasTest(TestCase):
    def test_semillas_definen_ambos_tipos(self):
        from .semillas import SEMILLAS
        self.assertEqual(set(SEMILLAS.keys()), {'despacho', 'pedido'})
        for definicion in SEMILLAS.values():
            self.assertEqual(
                {'docElements', 'parameters', 'styles', 'version', 'documentProperties'},
                set(definicion.keys()) & {'docElements', 'parameters', 'styles',
                                          'version', 'documentProperties'})

    def test_semilla_despacho_genera_pdf_con_datos_ejemplo(self):
        from reportbro import Report
        from .contratos import datos_ejemplo
        from .semillas import SEMILLAS
        report = Report(SEMILLAS['despacho'], datos_ejemplo('despacho'))
        self.assertFalse(report.errors)
        pdf = report.generate_pdf()
        self.assertTrue(bytes(pdf).startswith(b'%PDF'))

    def test_semilla_pedido_genera_pdf_con_datos_ejemplo(self):
        from reportbro import Report
        from .contratos import datos_ejemplo
        from .semillas import SEMILLAS
        report = Report(SEMILLAS['pedido'], datos_ejemplo('pedido'))
        self.assertFalse(report.errors)
        pdf = report.generate_pdf()
        self.assertTrue(bytes(pdf).startswith(b'%PDF'))

    def test_obtener_plantilla_siembra_inactiva(self):
        from .models import PlantillaImpresion, obtener_plantilla
        p = obtener_plantilla('despacho')
        self.assertFalse(p.activa)
        self.assertTrue(p.definicion['parameters'])
        self.assertEqual(PlantillaImpresion.objects.filter(tipo='despacho').count(), 1)
        # segunda llamada no duplica ni pisa
        p.definicion = {'version': 4}
        p.save()
        p2 = obtener_plantilla('despacho')
        self.assertEqual(p2.definicion, {'version': 4})

    def test_obtener_plantilla_tipo_invalido(self):
        from .models import obtener_plantilla
        with self.assertRaises(ValueError):
            obtener_plantilla('factura')
```

- [ ] **Step 2: Ejecutar los tests y verificar que fallan**

Run: `$env:PYTHONPATH='...scratchpad'; venv\Scripts\python.exe manage.py test formatos.tests.SemillasTest --settings=test_settings_sqlite -v 2`

Expected: ERROR `No module named 'formatos.semillas'`.

- [ ] **Step 3: Implementar `formatos/semillas.py`**

La estructura replica la del `report_definition.json` del demo oficial (verificada: `version: 4`; parámetros con `id/name/type/arrayItemType/eval/nullable/pattern/expression/showOnlyNameType/testData` y `children` para arrays; elementos con los campos de estilo; `documentProperties` con formato de página). reportbro-lib y el diseñador toleran campos de estilo omitidos (usan defaults). Crear:

```python
"""Definiciones ReportBro semilla por tipo de documento.

Construidas en Python (compacto y testeable) en lugar de JSON estático; el
resultado sembrado en PlantillaImpresion.definicion es el mismo JSON que
produciría el diseñador. El superusuario parte de un layout básico con todos
los parámetros del contrato ya declarados (ver formatos/contratos.py).
"""


def _param(id_, nombre, tipo='string', children=None):
    p = {
        'id': id_, 'name': nombre, 'type': tipo, 'arrayItemType': 'string',
        'eval': False, 'nullable': True, 'pattern': '', 'expression': '',
        'showOnlyNameType': False, 'testData': '',
    }
    if children is not None:
        p['children'] = children
        p['nullable'] = False
    return p


def _texto(id_, contenido, x, y, ancho, alto, *, container='0_content',
           size=10, bold=False, align='left'):
    return {
        'elementType': 'text', 'id': id_, 'containerId': container,
        'x': x, 'y': y, 'width': ancho, 'height': alto,
        'content': contenido, 'richText': False, 'richTextContent': None,
        'richTextHtml': '', 'eval': False, 'styleId': '',
        'bold': bold, 'italic': False, 'underline': False, 'strikethrough': False,
        'horizontalAlignment': align, 'verticalAlignment': 'middle',
        'textColor': '#000000', 'backgroundColor': '', 'font': 'helvetica',
        'fontSize': size, 'lineSpacing': 1, 'borderColor': '#000000',
        'borderWidth': 1, 'borderAll': False, 'borderLeft': False,
        'borderTop': False, 'borderRight': False, 'borderBottom': False,
        'paddingLeft': 2, 'paddingTop': 2, 'paddingRight': 2, 'paddingBottom': 2,
        'printIf': '', 'removeEmptyElement': False, 'alwaysPrintOnSamePage': True,
        'pattern': '', 'link': '', 'cs_condition': '',
    }


def _celda(id_, contenido, ancho, *, bold=False, align='left', size=8):
    return {
        'elementType': 'table_text', 'id': id_, 'width': ancho,
        'content': contenido, 'eval': False, 'colspan': '', 'styleId': '',
        'bold': bold, 'italic': False, 'underline': False, 'strikethrough': False,
        'horizontalAlignment': align, 'verticalAlignment': 'middle',
        'textColor': '#000000', 'backgroundColor': '', 'font': 'helvetica',
        'fontSize': size, 'lineSpacing': 1,
        'paddingLeft': 2, 'paddingTop': 2, 'paddingRight': 2, 'paddingBottom': 2,
        'pattern': '', 'link': '', 'cs_condition': '', 'printIf': '',
        'growWeight': 0, 'borderWidth': 1,
    }


def _tabla(id_, y, columnas):
    """columnas: lista de (titulo, expresion, ancho, align)."""
    ancho_total = sum(c[2] for c in columnas)
    header = [
        _celda(id_ + 10 + i, titulo, ancho, bold=True, align='center')
        for i, (titulo, _, ancho, _) in enumerate(columnas)
    ]
    contenido = [
        _celda(id_ + 40 + i, expresion, ancho, align=align)
        for i, (_, expresion, ancho, align) in enumerate(columnas)
    ]
    return {
        'elementType': 'table', 'id': id_, 'containerId': '0_content',
        'x': 0, 'y': y, 'width': ancho_total, 'dataSource': '${items}',
        'columns': len(columnas), 'header': True, 'contentRows': '1',
        'footer': False, 'border': 'grid', 'borderColor': '#000000',
        'borderWidth': 0.5, 'printIf': '', 'removeEmptyElement': False,
        'spreadsheet_hide': False, 'spreadsheet_column': '',
        'spreadsheet_addEmptyRow': False,
        'headerData': {'id': id_ + 1, 'height': 20, 'backgroundColor': '#eeeeee',
                       'repeatHeader': True, 'columnData': header},
        'contentDataRows': [{'id': id_ + 2, 'height': 18, 'backgroundColor': '',
                             'alternateBackgroundColor': '', 'groupExpression': '',
                             'printIf': '', 'alwaysPrintOnSamePage': False,
                             'pageBreak': False, 'repeatGroupHeader': False,
                             'columnData': contenido}],
        'footerData': {'id': id_ + 3, 'height': 0, 'backgroundColor': '',
                       'repeatHeader': False, 'columnData': []},
    }


_DOC_PROPS = {
    'pageFormat': 'letter', 'pageWidth': '', 'pageHeight': '', 'unit': 'mm',
    'orientation': 'portrait', 'contentHeight': '',
    'marginLeft': '10', 'marginTop': '10', 'marginRight': '10', 'marginBottom': '10',
    'header': True, 'headerSize': '60', 'headerDisplay': 'always',
    'footer': True, 'footerSize': '25', 'footerDisplay': 'always',
    'patternLocale': 'es', 'patternCurrencySymbol': 'Bs',
    'patternNumberGroupSymbol': '.',
}

_PARAMS_COMUNES = [
    _param(1, 'page_count', 'number'),
    _param(2, 'page_number', 'number'),
]

_CHILDREN_ITEM_BASE = [
    ('codigo', 'string'), ('descripcion', 'string'), ('referencia', 'string'),
    ('puesto', 'string'), ('ref_proveedor', 'string'),
    ('cantidad_solicitada', 'number'), ('cantidad_despachada', 'number'),
    ('cantidad_recibida', 'number'), ('observacion', 'string'),
]


def _children(base_id, campos):
    return [_param(base_id + i, nombre, tipo) for i, (nombre, tipo) in enumerate(campos)]


_PIE = _texto(90, 'Página ${page_number} de ${page_count}', 0, 0, 575, 20,
              container='0_footer', size=8, align='center')

SEMILLA_DESPACHO = {
    'docElements': [
        _texto(101, 'Despacho #${numero_despacho}', 0, 5, 575, 25,
               container='0_header', size=18, bold=True),
        _texto(102, 'Pedido #${numero_pedido} — ${deposito} — ${estado}',
               0, 32, 575, 18, container='0_header', size=10),
        _texto(103, 'Fecha despacho: ${fecha_despacho}    '
                    'Despachador: ${despachador}    Picker: ${picker}',
               0, 5, 575, 16),
        _texto(104, 'Solicitante: ${solicitante}    Condición: ${condicion}',
               0, 23, 575, 16),
        _tabla(200, 45, [
            ('Código', '${codigo}', 60, 'left'),
            ('Descripción', '${descripcion}', 175, 'left'),
            ('Referencia', '${referencia}', 70, 'left'),
            ('Puesto', '${puesto}', 60, 'left'),
            ('Solicitado', '${cantidad_solicitada}', 50, 'right'),
            ('Despachado', '${cantidad_despachada}', 55, 'right'),
            ('Observación', '${observacion}', 105, 'left'),
        ]),
        _texto(105, 'Items: ${total_items}    Total despachado: ${total_despachado}',
               0, 70, 575, 16, bold=True, align='right'),
        _PIE,
    ],
    'parameters': _PARAMS_COMUNES + [
        _param(10, 'numero_despacho', 'number'),
        _param(11, 'numero_pedido', 'number'),
        _param(12, 'estado'), _param(13, 'condicion'), _param(14, 'deposito'),
        _param(15, 'solicitante'), _param(16, 'despachador'),
        _param(17, 'picker'), _param(18, 'receptor'),
        _param(19, 'fecha_despacho'), _param(20, 'fecha_recepcion'),
        _param(21, 'observaciones'),
        _param(22, 'items', 'array', children=_children(30, _CHILDREN_ITEM_BASE)),
        _param(23, 'total_items', 'number'),
        _param(24, 'total_despachado', 'number'),
    ],
    'styles': [],
    'version': 4,
    'documentProperties': dict(_DOC_PROPS),
}

_CHILDREN_ITEM_PEDIDO = _CHILDREN_ITEM_BASE + [
    ('cantidad_back_order', 'number'), ('estado', 'string'),
]

SEMILLA_PEDIDO = {
    'docElements': [
        _texto(101, 'Pedido #${numero_pedido}', 0, 5, 575, 25,
               container='0_header', size=18, bold=True),
        _texto(102, '${deposito} — ${estado} — ${condicion}',
               0, 32, 575, 18, container='0_header', size=10),
        _texto(103, 'Creado: ${fecha_creacion}    Solicitante: ${solicitante}    '
                    'Categoría: ${categoria}',
               0, 5, 575, 16),
        _tabla(200, 27, [
            ('Código', '${codigo}', 60, 'left'),
            ('Descripción', '${descripcion}', 165, 'left'),
            ('Referencia', '${referencia}', 65, 'left'),
            ('Puesto', '${puesto}', 55, 'left'),
            ('Ref. Prov.', '${ref_proveedor}', 65, 'left'),
            ('Solicitado', '${cantidad_solicitada}', 55, 'right'),
            ('Observación', '${observacion}', 110, 'left'),
        ]),
        _texto(105, 'Items: ${total_items}    Total solicitado: ${total_solicitado}',
               0, 52, 575, 16, bold=True, align='right'),
        _PIE,
    ],
    'parameters': _PARAMS_COMUNES + [
        _param(10, 'numero_pedido', 'number'),
        _param(11, 'estado'), _param(12, 'condicion'), _param(13, 'deposito'),
        _param(14, 'categoria'), _param(15, 'solicitante'),
        _param(16, 'despachador'), _param(17, 'picker'),
        _param(18, 'fecha_creacion'), _param(19, 'fecha_despacho'),
        _param(20, 'fecha_recepcion'), _param(21, 'observaciones'),
        _param(22, 'items', 'array', children=_children(30, _CHILDREN_ITEM_PEDIDO)),
        _param(23, 'total_items', 'number'),
        _param(24, 'total_solicitado', 'number'),
    ],
    'styles': [],
    'version': 4,
    'documentProperties': dict(_DOC_PROPS),
}

SEMILLAS = {'despacho': SEMILLA_DESPACHO, 'pedido': SEMILLA_PEDIDO}
```

Añadir al final de `formatos/models.py`:

```python
def obtener_plantilla(tipo: str) -> PlantillaImpresion:
    """Devuelve la plantilla del tipo, creándola inactiva con la semilla si no existe.

    Raises:
        ValueError: si el tipo no está en TIPOS_VALIDOS.
    """
    from .semillas import SEMILLAS

    if tipo not in TIPOS_VALIDOS:
        raise ValueError(f'Tipo de documento desconocido: {tipo}')
    plantilla, _ = PlantillaImpresion.objects.get_or_create(
        tipo=tipo, defaults={'definicion': SEMILLAS[tipo]})
    return plantilla
```

- [ ] **Step 4: Ejecutar los tests y verificar que pasan**

Run: mismo comando del Step 2. Expected: `OK` (5 tests). Si `Report(...)` reporta errores por algún campo de la semilla, ajustar el campo señalado por `report.errors` (el mensaje indica `object_id` y campo) comparando con `scratchpad/albumapp/albums_static_report_definition.json`.

- [ ] **Step 5: Commit**

```powershell
git add formatos/semillas.py formatos/models.py formatos/tests.py
git commit -m "feat(formatos): plantillas semilla y obtener_plantilla"
```

---

### Task 4: Generación con fallback e integración en PedidosAlmacen

**Files:**
- Create: `formatos/generacion.py`
- Modify: `PedidosAlmacen/views.py` (`exportar_despacho_pdf` ~línea 1102, `exportar_pedido_pdf` ~línea 1470)
- Test: `formatos/tests.py` (añadir clase)

**Interfaces:**
- Consumes: `PlantillaImpresion`, `datos_despacho/datos_pedido` (Tasks 1-2), `reportbro.Report`.
- Produces: `formatos.generacion.generar_pdf(tipo: str, datos: dict) -> bytes | None` (None si no hay plantilla activa o si falla) y `formatos.generacion.validar_plantilla(definicion: dict, datos: dict) -> str` ('' si genera bien; mensaje de error si no). Task 5 usa `validar_plantilla` al activar.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir a `formatos/tests.py`:

```python
class GeneracionTest(TestCase):
    def setUp(self):
        from .semillas import SEMILLAS
        self.definicion_ok = SEMILLAS['despacho']
        # plantilla rota: referencia un parámetro inexistente
        self.definicion_rota = {
            **self.definicion_ok,
            'docElements': [dict(self.definicion_ok['docElements'][0],
                                 content='${parametro_inexistente}')],
        }

    def test_sin_plantilla_activa_devuelve_none(self):
        from .contratos import datos_ejemplo
        from .generacion import generar_pdf
        self.assertIsNone(generar_pdf('despacho', datos_ejemplo('despacho')))

    def test_plantilla_activa_genera_pdf(self):
        from .contratos import datos_ejemplo
        from .generacion import generar_pdf
        from .models import PlantillaImpresion
        PlantillaImpresion.objects.create(
            tipo='despacho', definicion=self.definicion_ok, activa=True)
        pdf = generar_pdf('despacho', datos_ejemplo('despacho'))
        self.assertTrue(bytes(pdf).startswith(b'%PDF'))

    def test_plantilla_rota_devuelve_none_sin_lanzar(self):
        from .contratos import datos_ejemplo
        from .generacion import generar_pdf
        from .models import PlantillaImpresion
        PlantillaImpresion.objects.create(
            tipo='despacho', definicion=self.definicion_rota, activa=True)
        self.assertIsNone(generar_pdf('despacho', datos_ejemplo('despacho')))

    def test_validar_plantilla(self):
        from .contratos import datos_ejemplo
        from .generacion import validar_plantilla
        self.assertEqual(
            validar_plantilla(self.definicion_ok, datos_ejemplo('despacho')), '')
        self.assertNotEqual(
            validar_plantilla(self.definicion_rota, datos_ejemplo('despacho')), '')


class ExportarConFallbackTest(TestCase):
    """La vista de exportación usa ReportBro si hay plantilla activa; si no, reportlab."""

    def setUp(self):
        from PedidosAlmacen.models import Pedido, PedidoItem, Despacho, DespachoItem
        self.user = User.objects.create_superuser(username='fmt_export', password='x')
        self.client.force_login(self.user)
        self.pedido = Pedido.objects.create(solicitante=self.user)
        item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='A1', descripcion='Taza',
            cantidad_solicitada=5, cantidad_despachada=5)
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='ENVIADO')
        DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=item, cantidad_despachada=5)
        from django.urls import reverse
        self.url = reverse('pedidos-despacho-pdf',
                           args=[self.pedido.numero_pedido, self.despacho.numero_despacho])

    def test_sin_plantilla_usa_reportlab(self):
        from unittest.mock import patch
        with patch('PedidosAlmacen.views.generar_despacho_pdf',
                   return_value=b'%PDF-fallback') as mock_rl:
            resp = self.client.get(self.url)
        mock_rl.assert_called_once()
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_con_plantilla_activa_usa_reportbro(self):
        from unittest.mock import patch
        from .models import PlantillaImpresion
        from .semillas import SEMILLAS
        PlantillaImpresion.objects.create(
            tipo='despacho', definicion=SEMILLAS['despacho'], activa=True)
        with patch('PedidosAlmacen.views.generar_despacho_pdf') as mock_rl:
            resp = self.client.get(self.url)
        mock_rl.assert_not_called()
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF'))
```

- [ ] **Step 2: Ejecutar los tests y verificar que fallan**

Run: `$env:PYTHONPATH='...scratchpad'; venv\Scripts\python.exe manage.py test formatos.tests.GeneracionTest formatos.tests.ExportarConFallbackTest --settings=test_settings_sqlite -v 2`

Expected: ERROR `No module named 'formatos.generacion'`; `test_con_plantilla_activa_usa_reportbro` FAIL (la vista aún llama a reportlab).

- [ ] **Step 3: Implementación**

Crear `formatos/generacion.py`:

```python
"""Generación de PDFs desde plantillas ReportBro con tolerancia total a fallos."""
import logging

from reportbro import Report

from .models import PlantillaImpresion

logger = logging.getLogger(__name__)


def validar_plantilla(definicion: dict, datos: dict) -> str:
    """Valida que la definición genere un PDF con los datos dados.

    Returns:
        '' si genera bien; mensaje de error legible si no.
    """
    try:
        report = Report(definicion, datos)
        if report.errors:
            return str(report.errors)
        report.generate_pdf()
        return ''
    except Exception as exc:  # noqa: BLE001 — cualquier fallo invalida
        return str(exc)


def generar_pdf(tipo: str, datos: dict) -> bytes | None:
    """Genera el PDF del tipo con su plantilla activa.

    Returns:
        Bytes del PDF, o None si no hay plantilla activa o la generación
        falla (el caller debe caer a su generador de respaldo).
    """
    plantilla = PlantillaImpresion.objects.filter(tipo=tipo, activa=True).first()
    if plantilla is None:
        return None
    try:
        report = Report(plantilla.definicion, datos)
        if report.errors:
            logger.error('Plantilla %s con errores: %s', tipo, report.errors)
            return None
        return bytes(report.generate_pdf())
    except Exception:  # noqa: BLE001 — nunca romper la operación del almacén
        logger.exception('Fallo generando PDF ReportBro para %s', tipo)
        return None
```

En `PedidosAlmacen/views.py`, dentro de `exportar_despacho_pdf` (~línea 1111), reemplazar:

```python
    pdf_bytes = generar_despacho_pdf(despacho, despacho_items)
```

por:

```python
    from formatos.contratos import datos_despacho
    from formatos.generacion import generar_pdf as generar_pdf_formato
    pdf_bytes = generar_pdf_formato('despacho', datos_despacho(despacho, despacho_items))
    if pdf_bytes is None:
        pdf_bytes = generar_despacho_pdf(despacho, despacho_items)
```

En `exportar_pedido_pdf` (~línea 1490), reemplazar:

```python
    pdf_bytes = generar_pedido_pdf(pedido, items, vista=vista, mostrar_cantidades=mostrar_cantidades)
```

por:

```python
    pdf_bytes = None
    if vista == 'todos':
        from formatos.contratos import datos_pedido
        from formatos.generacion import generar_pdf as generar_pdf_formato
        pdf_bytes = generar_pdf_formato('pedido', datos_pedido(pedido, items))
    if pdf_bytes is None:
        pdf_bytes = generar_pedido_pdf(pedido, items, vista=vista, mostrar_cantidades=mostrar_cantidades)
```

(Imports locales dentro de la función: evitan tocar la cabecera del archivo y dejan el acoplamiento en un solo punto.)

- [ ] **Step 4: Ejecutar los tests y verificar que pasan**

Run: mismo comando del Step 2. Expected: `OK` (6 tests).

- [ ] **Step 5: Ejecutar la suite completa (regresiones)**

Run: `$env:PYTHONPATH='...scratchpad'; venv\Scripts\python.exe manage.py test formatos PedidosAlmacen --settings=test_settings_sqlite`

Expected: `OK` (86 de PedidosAlmacen + los nuevos de formatos).

- [ ] **Step 6: Commit**

```powershell
git add formatos/generacion.py formatos/tests.py PedidosAlmacen/views.py
git commit -m "feat(formatos): generacion reportbro con fallback a reportlab"
```

---

### Task 5: Vistas de gestión (lista, guardar, activar/desactivar/restaurar)

**Files:**
- Create: `formatos/views.py` (reemplazar el generado), `formatos/urls.py`, `templates/formatos-lista.html`
- Modify: `Programarprecios/urls.py:41` (include)
- Test: `formatos/tests.py` (añadir clase)

**Interfaces:**
- Consumes: `obtener_plantilla`, `TIPOS_VALIDOS`, `validar_plantilla`, `datos_ejemplo`.
- Produces: URLs con names `formatos-lista` (`/formatos/`), `formatos-guardar` (`/formatos/<tipo>/guardar/`, POST JSON), `formatos-activar`, `formatos-desactivar`, `formatos-restaurar` (POST). Task 6 añade `formatos-disenar` y `formatos-report-run` a este mismo `urls.py`.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir a `formatos/tests.py`:

```python
import json as json_mod


class VistasGestionTest(TestCase):
    def setUp(self):
        from django.urls import reverse
        self.reverse = reverse
        self.admin = User.objects.create_superuser(username='fmt_su', password='x')
        self.normal = User.objects.create_user(username='fmt_normal', password='x')

    def test_no_superusuario_es_redirigido(self):
        self.client.force_login(self.normal)
        for name, args in [('formatos-lista', []), ('formatos-guardar', ['despacho']),
                           ('formatos-activar', ['despacho'])]:
            resp = self.client.get(self.reverse(name, args=args))
            self.assertEqual(resp.status_code, 302, name)

    def test_lista_muestra_ambos_tipos(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self.reverse('formatos-lista'))
        self.assertContains(resp, 'Despacho')
        self.assertContains(resp, 'Pedido')

    def test_guardar_rota_definicion(self):
        from .models import obtener_plantilla
        self.client.force_login(self.admin)
        plantilla = obtener_plantilla('despacho')
        original = plantilla.definicion
        nueva = {**original, 'styles': [{'id': 99}]}
        resp = self.client.post(
            self.reverse('formatos-guardar', args=['despacho']),
            data=json_mod.dumps(nueva), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        plantilla.refresh_from_db()
        self.assertEqual(plantilla.definicion['styles'], [{'id': 99}])
        self.assertEqual(plantilla.definicion_anterior, original)

    def test_guardar_rechaza_json_invalido(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            self.reverse('formatos-guardar', args=['despacho']),
            data=json_mod.dumps({'sin_campos': True}), content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_activar_valida_y_activa(self):
        from .models import obtener_plantilla
        self.client.force_login(self.admin)
        plantilla = obtener_plantilla('despacho')
        resp = self.client.post(self.reverse('formatos-activar', args=['despacho']))
        self.assertEqual(resp.status_code, 302)
        plantilla.refresh_from_db()
        self.assertTrue(plantilla.activa)

    def test_activar_rechaza_plantilla_rota(self):
        from .models import obtener_plantilla
        self.client.force_login(self.admin)
        plantilla = obtener_plantilla('despacho')
        rota = {**plantilla.definicion,
                'docElements': [dict(plantilla.definicion['docElements'][0],
                                     content='${parametro_inexistente}')]}
        plantilla.definicion = rota
        plantilla.save()
        self.client.post(self.reverse('formatos-activar', args=['despacho']))
        plantilla.refresh_from_db()
        self.assertFalse(plantilla.activa)

    def test_desactivar_y_restaurar(self):
        from .models import obtener_plantilla
        self.client.force_login(self.admin)
        plantilla = obtener_plantilla('despacho')
        plantilla.activa = True
        plantilla.actualizar_definicion({**plantilla.definicion, 'styles': [{'id': 5}]},
                                        self.admin)
        self.client.post(self.reverse('formatos-desactivar', args=['despacho']))
        plantilla.refresh_from_db()
        self.assertFalse(plantilla.activa)
        self.client.post(self.reverse('formatos-restaurar', args=['despacho']))
        plantilla.refresh_from_db()
        self.assertEqual(plantilla.definicion['styles'], [])
```

- [ ] **Step 2: Ejecutar los tests y verificar que fallan**

Run: `$env:PYTHONPATH='...scratchpad'; venv\Scripts\python.exe manage.py test formatos.tests.VistasGestionTest --settings=test_settings_sqlite -v 2`

Expected: ERROR `NoReverseMatch` (las URLs no existen).

- [ ] **Step 3: Implementación**

Reemplazar `formatos/views.py`:

```python
"""Vistas de gestión de plantillas de impresión (solo superusuarios)."""
import json
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .contratos import datos_ejemplo
from .generacion import validar_plantilla
from .models import PlantillaImpresion, TIPOS_VALIDOS, obtener_plantilla

logger = logging.getLogger(__name__)

_es_superusuario = user_passes_test(lambda u: u.is_superuser, login_url='dashboard')


def _tipo_o_400(tipo: str):
    return tipo in TIPOS_VALIDOS


@login_required(login_url='/login/')
@_es_superusuario
def lista_formatos(request):
    plantillas = {p.tipo: p for p in PlantillaImpresion.objects.all()}
    filas = [{
        'tipo': tipo,
        'nombre': dict(PlantillaImpresion.TIPO_CHOICES)[tipo],
        'plantilla': plantillas.get(tipo),
    } for tipo in TIPOS_VALIDOS]
    return render(request, 'formatos-lista.html', {'filas': filas})


@login_required(login_url='/login/')
@_es_superusuario
@require_POST
def guardar(request, tipo):
    if not _tipo_o_400(tipo):
        return HttpResponseBadRequest('tipo desconocido')
    try:
        definicion = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponseBadRequest('JSON inválido')
    # Chequeo estructural mínimo (mismo criterio que el demo oficial de ReportBro)
    if not isinstance(definicion, dict) or \
            not isinstance(definicion.get('docElements'), list) or \
            not isinstance(definicion.get('parameters'), list) or \
            not isinstance(definicion.get('styles'), list) or \
            not isinstance(definicion.get('documentProperties'), dict) or \
            not isinstance(definicion.get('version'), int):
        return HttpResponseBadRequest('definición incompleta')
    plantilla = obtener_plantilla(tipo)
    plantilla.actualizar_definicion(definicion, request.user)
    return HttpResponse('ok')


@login_required(login_url='/login/')
@_es_superusuario
@require_POST
def activar(request, tipo):
    if not _tipo_o_400(tipo):
        return HttpResponseBadRequest('tipo desconocido')
    plantilla = obtener_plantilla(tipo)
    error = validar_plantilla(plantilla.definicion, datos_ejemplo(tipo))
    if error:
        messages.error(
            request,
            f'No se activó: la plantilla no genera un PDF válido. Detalle: {error}')
    else:
        plantilla.activa = True
        plantilla.save(update_fields=['activa'])
        messages.success(request, f'Plantilla de {tipo} activada.')
    return redirect('formatos-lista')


@login_required(login_url='/login/')
@_es_superusuario
@require_POST
def desactivar(request, tipo):
    if not _tipo_o_400(tipo):
        return HttpResponseBadRequest('tipo desconocido')
    PlantillaImpresion.objects.filter(tipo=tipo).update(activa=False)
    messages.success(request, f'Plantilla de {tipo} desactivada — los PDFs vuelven '
                              f'al formato clásico.')
    return redirect('formatos-lista')


@login_required(login_url='/login/')
@_es_superusuario
@require_POST
def restaurar(request, tipo):
    if not _tipo_o_400(tipo):
        return HttpResponseBadRequest('tipo desconocido')
    plantilla = obtener_plantilla(tipo)
    if plantilla.restaurar():
        messages.success(request, 'Versión anterior restaurada.')
    else:
        messages.warning(request, 'No hay versión anterior que restaurar.')
    return redirect('formatos-lista')
```

Crear `formatos/urls.py`:

```python
from django.urls import path

from . import views

urlpatterns = [
    path('formatos/', views.lista_formatos, name='formatos-lista'),
    path('formatos/<str:tipo>/guardar/', views.guardar, name='formatos-guardar'),
    path('formatos/<str:tipo>/activar/', views.activar, name='formatos-activar'),
    path('formatos/<str:tipo>/desactivar/', views.desactivar, name='formatos-desactivar'),
    path('formatos/<str:tipo>/restaurar/', views.restaurar, name='formatos-restaurar'),
]
```

En `Programarprecios/urls.py`, añadir tras la línea 41 (`include('ubicaciones.urls')`):

```python
    path('', include('formatos.urls')),
```

Crear `templates/formatos-lista.html` (mismo lenguaje visual que pedidos-lista):

```html
{% extends "dashboard.html" %}
{% block content %}
{% load static %}

<div class="pd-header">
    <div class="pd-header-left">
        <div>
            <span class="pd-header-eyebrow">Configuración</span>
            <div class="pd-header-title-row">
                <h1 class="pd-header-num">Formatos de impresión</h1>
            </div>
        </div>
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

<div class="pl-table-card">
    <table class="table pl-tabla align-middle">
        <thead>
            <tr>
                <th>Documento</th>
                <th>Estado</th>
                <th>Última modificación</th>
                <th>Por</th>
                <th class="text-end">Acciones</th>
            </tr>
        </thead>
        <tbody>
            {% for fila in filas %}
            <tr>
                <td>{{ fila.nombre }}</td>
                <td>
                    {% if fila.plantilla and fila.plantilla.activa %}
                    <span class="pl-chip pl-chip-recibido">Activa</span>
                    {% elif fila.plantilla %}
                    <span class="pl-chip pl-chip-pendiente">Inactiva (fallback clásico)</span>
                    {% else %}
                    <span class="pl-chip pl-chip-todos">Sin personalizar</span>
                    {% endif %}
                </td>
                <td>{{ fila.plantilla.fecha_actualizacion|date:"d/m/Y H:i"|default:"—" }}</td>
                <td>{{ fila.plantilla.actualizado_por.username|default:"—" }}</td>
                <td class="text-end">
                    <a href="{% url 'formatos-disenar' fila.tipo %}" class="btn btn-sm btn-primary">
                        <i class="fas fa-pen"></i> Editar
                    </a>
                    {% if fila.plantilla and fila.plantilla.activa %}
                    <form method="post" action="{% url 'formatos-desactivar' fila.tipo %}" class="d-inline">
                        {% csrf_token %}
                        <button class="btn btn-sm btn-outline-warning">Desactivar</button>
                    </form>
                    {% else %}
                    <form method="post" action="{% url 'formatos-activar' fila.tipo %}" class="d-inline">
                        {% csrf_token %}
                        <button class="btn btn-sm btn-outline-success">Activar</button>
                    </form>
                    {% endif %}
                    {% if fila.plantilla.definicion_anterior %}
                    <form method="post" action="{% url 'formatos-restaurar' fila.tipo %}" class="d-inline">
                        {% csrf_token %}
                        <button class="btn btn-sm btn-outline-secondary">Restaurar anterior</button>
                    </form>
                    {% endif %}
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

Nota: `formatos-disenar` se define en Task 6; para que los tests de esta task pasen antes, añadir en `formatos/urls.py` un placeholder que Task 6 reemplaza:

```python
    path('formatos/<str:tipo>/disenar/', views.lista_formatos, name='formatos-disenar'),
```

- [ ] **Step 4: Ejecutar los tests y verificar que pasan**

Run: mismo comando del Step 2. Expected: `OK` (7 tests).

- [ ] **Step 5: Commit**

```powershell
git add formatos/views.py formatos/urls.py formatos/tests.py templates/formatos-lista.html Programarprecios/urls.py
git commit -m "feat(formatos): vistas de gestion de plantillas de impresion"
```

---

### Task 6: Diseñador incrustado y endpoint de preview `report/run`

**Files:**
- Create: `static/vendor/reportbro/` (estáticos del release), `templates/formatos-disenar.html`
- Modify: `formatos/views.py` (añadir `disenar` y `report_run`), `formatos/urls.py` (reemplazar placeholder, añadir report/run)
- Test: `formatos/tests.py` (añadir clase)

**Interfaces:**
- Consumes: `obtener_plantilla`, `datos_ejemplo`, `ReportePreview`, `reportbro.Report/ReportBroError`.
- Produces: `GET /formatos/<tipo>/disenar/` (name `formatos-disenar`) y `PUT/GET /formatos/<tipo>/report/run` (name `formatos-report-run`). Protocolo del preview (estándar del diseñador, verificado en el demo oficial): PUT body `{report, outputFormat, data, isTestData}` → respuesta `key:<uuid>` o JSON `{"errors": [...]}`; GET `?key=<uuid>&outputFormat=pdf` → PDF inline. **Los datos del preview siempre se sustituyen por `datos_ejemplo(tipo)`** (decisión del spec: preview con datos reales).

- [ ] **Step 1: Descargar y vendorizar reportbro-designer**

```powershell
$meta = Invoke-RestMethod 'https://registry.npmjs.org/reportbro-designer/latest'
$ver = $meta.version
$tmp = Join-Path $env:TEMP "reportbro-designer"
New-Item -ItemType Directory -Force $tmp | Out-Null
Invoke-WebRequest "https://registry.npmjs.org/reportbro-designer/-/reportbro-designer-$ver.tgz" -OutFile "$tmp\rb.tgz"
tar -xzf "$tmp\rb.tgz" -C $tmp
New-Item -ItemType Directory -Force static\vendor\reportbro | Out-Null
Copy-Item "$tmp\package\dist\*" static\vendor\reportbro\ -Recurse -Force
Get-ChildItem static\vendor\reportbro
```

Expected: aparecen al menos `reportbro.js` (o `reportbro.min.js`) y `reportbro.css`. Si el `dist/` trae subcarpetas de assets (fuentes/iconos), se copian tal cual — el CSS las referencia con rutas relativas.

- [ ] **Step 2: Escribir los tests que fallan**

Añadir a `formatos/tests.py`:

```python
class DisenadorYPreviewTest(TestCase):
    def setUp(self):
        from django.urls import reverse
        self.reverse = reverse
        self.admin = User.objects.create_superuser(username='fmt_dis', password='x')
        self.client.force_login(self.admin)

    def test_disenar_carga_definicion(self):
        resp = self.client.get(self.reverse('formatos-disenar', args=['despacho']))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ReportBro(')
        self.assertContains(resp, 'numero_despacho')

    def test_preview_put_devuelve_key_y_get_descarga_pdf(self):
        from .models import obtener_plantilla
        definicion = obtener_plantilla('despacho').definicion
        url = self.reverse('formatos-report-run', args=['despacho'])
        resp = self.client.put(
            url, data=json_mod.dumps({
                'report': definicion, 'outputFormat': 'pdf',
                'data': {}, 'isTestData': True}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        cuerpo = resp.content.decode()
        self.assertTrue(cuerpo.startswith('key:'), cuerpo)
        key = cuerpo[4:]
        resp2 = self.client.get(url, {'key': key, 'outputFormat': 'pdf'})
        self.assertEqual(resp2['Content-Type'], 'application/pdf')
        self.assertTrue(resp2.content.startswith(b'%PDF'))

    def test_preview_reporta_errores_de_plantilla(self):
        from .models import obtener_plantilla
        definicion = obtener_plantilla('despacho').definicion
        rota = {**definicion,
                'docElements': [dict(definicion['docElements'][0],
                                     content='${parametro_inexistente}')]}
        url = self.reverse('formatos-report-run', args=['despacho'])
        resp = self.client.put(
            url, data=json_mod.dumps({
                'report': rota, 'outputFormat': 'pdf',
                'data': {}, 'isTestData': True}),
            content_type='application/json')
        self.assertIn('errors', resp.content.decode())

    def test_preview_requiere_superusuario(self):
        normal = User.objects.create_user(username='fmt_dis_n', password='x')
        self.client.force_login(normal)
        url = self.reverse('formatos-report-run', args=['despacho'])
        resp = self.client.put(url, data='{}', content_type='application/json')
        self.assertEqual(resp.status_code, 403)
```

- [ ] **Step 3: Ejecutar los tests y verificar que fallan**

Run: `$env:PYTHONPATH='...scratchpad'; venv\Scripts\python.exe manage.py test formatos.tests.DisenadorYPreviewTest --settings=test_settings_sqlite -v 2`

Expected: `NoReverseMatch: formatos-report-run` y fallo de contenido en `formatos-disenar` (placeholder).

- [ ] **Step 4: Implementación**

Añadir a `formatos/views.py` (imports adicionales al bloque existente):

```python
import uuid
from datetime import timedelta

from django.http import HttpResponseForbidden
from django.utils import timezone
from django.utils.safestring import SafeString
from django.views.decorators.csrf import csrf_exempt
from reportbro import Report, ReportBroError

from .models import ReportePreview
```

Y las vistas:

```python
@login_required(login_url='/login/')
@_es_superusuario
def disenar(request, tipo):
    if not _tipo_o_400(tipo):
        return HttpResponseBadRequest('tipo desconocido')
    plantilla = obtener_plantilla(tipo)
    return render(request, 'formatos-disenar.html', {
        'tipo': tipo,
        'nombre': dict(PlantillaImpresion.TIPO_CHOICES)[tipo],
        'definicion_json': SafeString(json.dumps(plantilla.definicion)),
    })


@csrf_exempt
def report_run(request, tipo):
    """Preview del diseñador (protocolo ReportBro: PUT genera, GET descarga).

    csrf_exempt porque el diseñador hace el PUT internamente sin token;
    el acceso queda protegido por sesión de superusuario.
    """
    if not request.user.is_authenticated or not request.user.is_superuser:
        return HttpResponseForbidden()
    if not _tipo_o_400(tipo):
        return HttpResponseBadRequest('tipo desconocido')

    if request.method == 'PUT':
        try:
            json_data = json.loads(request.body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return HttpResponseBadRequest('JSON inválido')
        if not isinstance(json_data, dict) or not isinstance(json_data.get('report'), dict):
            return HttpResponseBadRequest('invalid report values')
        if json_data.get('outputFormat') != 'pdf':
            return HttpResponseBadRequest('outputFormat inválido (solo pdf)')

        # Preview siempre con datos reales del último documento (decisión de spec)
        datos = datos_ejemplo(tipo)
        try:
            report = Report(json_data['report'], datos)
        except Exception as exc:  # noqa: BLE001
            return HttpResponseBadRequest(f'failed to initialize report: {exc}')
        if report.errors:
            return HttpResponse(json.dumps({'errors': report.errors}))
        try:
            ReportePreview.objects.filter(
                creado__lt=timezone.now() - timedelta(minutes=10)).delete()
            pdf = report.generate_pdf()
        except ReportBroError as err:
            return HttpResponse(json.dumps({'errors': [err.error]}))
        key = str(uuid.uuid4())
        ReportePreview.objects.create(key=key, pdf=pdf)
        return HttpResponse('key:' + key)

    if request.method == 'GET':
        preview = ReportePreview.objects.filter(key=request.GET.get('key', '')).first()
        if preview is None:
            return HttpResponseBadRequest(
                'preview no encontrado (expiró) — vuelve a generar la vista previa')
        response = HttpResponse(bytes(preview.pdf), content_type='application/pdf')
        response['Content-Disposition'] = 'inline; filename="preview.pdf"'
        return response

    return HttpResponseBadRequest('método no soportado')
```

En `formatos/urls.py`, reemplazar el placeholder de `disenar` y añadir report/run:

```python
    path('formatos/<str:tipo>/disenar/', views.disenar, name='formatos-disenar'),
    path('formatos/<str:tipo>/report/run', views.report_run, name='formatos-report-run'),
```

Crear `templates/formatos-disenar.html` (standalone, pantalla completa; init según el demo oficial `report/edit.html`, guardado con fetch + CSRF):

```html
{% load static %}
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Diseñar formato — {{ nombre }}</title>
    <link rel="stylesheet" href="{% static 'vendor/reportbro/reportbro.css' %}">
    <style>
        html, body { margin: 0; height: 100%; }
        .fmt-topbar {
            display: flex; align-items: center; gap: 12px;
            background: #2e353d; color: #fff; padding: 8px 14px;
            font-family: system-ui, sans-serif; font-size: 14px;
        }
        .fmt-topbar a { color: #9fc5ff; text-decoration: none; }
        #reportbro { height: calc(100% - 40px); }
    </style>
</head>
<body>
    <div class="fmt-topbar">
        <a href="{% url 'formatos-lista' %}">&larr; Formatos</a>
        <strong>Plantilla: {{ nombre }}</strong>
        <span id="fmt-estado"></span>
    </div>
    <div id="reportbro"></div>

    <script src="{% static 'vendor/reportbro/reportbro.js' %}"></script>
    <script>
        function guardarReporte() {
            fetch("{% url 'formatos-guardar' tipo %}", {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': '{{ csrf_token }}',
                },
                body: JSON.stringify(rb.getReport()),
            }).then(function (resp) {
                if (resp.ok) {
                    rb.setModified(false);
                    document.getElementById('fmt-estado').textContent = 'Guardado ✓';
                } else {
                    alert('Error al guardar la plantilla');
                }
            }).catch(function () { alert('Error de red al guardar'); });
        }

        const rb = new ReportBro(document.getElementById('reportbro'), {
            reportServerUrl: "{% url 'formatos-report-run' tipo %}",
            saveCallback: guardarReporte,
        });
        rb.load({{ definicion_json }});
    </script>
</body>
</html>
```

- [ ] **Step 5: Ejecutar los tests y verificar que pasan**

Run: mismo comando del Step 3. Expected: `OK` (4 tests). Luego la suite completa de formatos: `... manage.py test formatos --settings=test_settings_sqlite` → `OK`.

- [ ] **Step 6: Commit**

```powershell
git add formatos/ templates/formatos-disenar.html static/vendor/reportbro/
git commit -m "feat(formatos): disenador reportbro incrustado con preview de datos reales"
```

---

### Task 7: Menú, verificación manual y cierre

**Files:**
- Modify: `templates/dashboard.html` (~línea 104, submenu "Pedidos Almacen")

**Interfaces:**
- Consumes: URL name `formatos-lista`.

- [ ] **Step 1: Entrada de menú (solo superusuario)**

En `templates/dashboard.html`, dentro del `<ul class="sub-menu">` de "Pedidos Almacen", después de la línea `<li><a href="/pedidos/reporte/">Reporte</a></li>` (y de su `{% endif %}` del bloque supervisor), añadir:

```html
                        {% if request.user.is_superuser %}
                        <li><a href="/formatos/">Formatos de Impresión</a></li>
                        {% endif %}
```

- [ ] **Step 2: Suite completa final**

Run: `$env:PYTHONPATH='...scratchpad'; venv\Scripts\python.exe manage.py test formatos PedidosAlmacen --settings=test_settings_sqlite`

Expected: `OK` sin regresiones.

- [ ] **Step 3: Verificación manual (con el servidor corriendo)**

1. Entrar como superusuario → menú "Pedidos Almacen" muestra "Formatos de Impresión"; como usuario normal, no.
2. `/formatos/` lista Despacho y Pedido como "Sin personalizar".
3. "Editar" en Despacho → el diseñador carga con el layout semilla y los parámetros del contrato en el panel derecho.
4. Botón de vista previa del diseñador → PDF con datos del último despacho real.
5. Mover un elemento, Guardar → "Guardado ✓"; recargar → el cambio persiste; `/formatos/` muestra fecha y usuario.
6. "Activar" → chip "Activa". Descargar el PDF de un despacho real (`/pedidos/<pk>/despachos/<id>/pdf/`) → sale con el formato ReportBro.
7. "Desactivar" → el mismo PDF vuelve al formato reportlab clásico.
8. Romper la plantilla a propósito (texto con `${parametro_inexistente}`), guardar → "Activar" la rechaza con mensaje de error.
9. "Restaurar anterior" → vuelve la versión previa.
10. PDF de pedido (`/pedidos/<pk>/pdf/`): con plantilla de pedido activa sale por ReportBro; las variantes (`?vista=despachado` etc.) siguen saliendo por reportlab.

- [ ] **Step 4: Commit final**

```powershell
git add templates/dashboard.html
git commit -m "feat(formatos): entrada de menu formatos de impresion para superusuarios"
```
