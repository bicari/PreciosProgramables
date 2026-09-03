# Reportes Programados Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dejar a un superusuario crear reportes con query SQL propio contra DBISAM, diseñar su formato con ReportBro, y enviarlos automáticamente por correo según una programación recurrente.

**Architecture:** Nueva app Django `reportes`. Reutiliza el scheduler singleton de `tasks` (`get_scheduler()`, arrancado por `manage.py programador`) y los helpers de construcción de definiciones ReportBro de `formatos.semillas`. Un job cron por reporte activo ejecuta el query, aplica una transformación Python opcional, genera el PDF y lo envía por correo; cualquier fallo se reporta por correo al dueño del reporte en vez de propagarse.

**Tech Stack:** Django 5.2, APScheduler + django-apscheduler (ya instalados y en uso por `tasks`), pyodbc (conexión DBISAM), reportbro-lib/reportbro-fpdf2 (ya usados por `formatos`), PostgreSQL (BD principal), SQLite en memoria para tests (`Programarprecios.test_settings`).

**Spec:** `docs/superpowers/specs/2026-09-03-reportes-programados-design.md`

## Global Constraints

- Todas las vistas de gestión requieren `login_required` + superusuario, igual que `formatos`.
- El SQL personalizado debe ser un único `SELECT` (sin DML/DDL, sin múltiples sentencias) — validado con `validar_select` tanto al guardar como antes de ejecutar el job programado.
- La transformación Python opcional corre con `exec()` en un namespace restringido (sin `import`, `open`, `eval`, `exec`, `os`, `sys`) y con timeout vía `threading.Timer` (no `signal.alarm`, no disponible en Windows).
- `dias_semana` se guarda como `CharField` CSV (no `django.contrib.postgres.fields.ArrayField`) porque los tests corren contra SQLite (`Programarprecios/test_settings.py`), que no soporta ese tipo de campo.
- Los tests se corren con: `venv\Scripts\python.exe manage.py test reportes --settings=Programarprecios.test_settings` (ver memoria `project_tests_setup`: el Python del sistema no tiene `reportbro` instalado, y el usuario de Postgres no tiene `CREATEDB`).
- El scheduler real se arranca con `manage.py programador` (proceso aparte), no con `AppConfig.ready()` — ese hook ya fue probado y abandonado en este proyecto (ver `tasks/apps.py`, comentado). La integración de `reportes` debe engancharse dentro de `tasks.scheduler.iniciar_scheduler()`, igual que ya hacen `cargar_tareas_pendientes()` y `programar_correo()`.
- No se agregan dependencias nuevas: `pyodbc`, `reportbro-lib`, `reportbro-fpdf2`, `APScheduler`, `django-apscheduler` ya están en `requirements.txt`.

---

### Task 1: App scaffold, modelo y migración

**Files:**
- Create: `reportes/__init__.py`
- Create: `reportes/apps.py`
- Create: `reportes/models.py`
- Create: `reportes/admin.py`
- Create: `reportes/migrations/__init__.py`
- Modify: `Programarprecios/settings.py` (agregar `'reportes'` a `INSTALLED_APPS`, junto a `'formatos'`)
- Test: `reportes/tests.py`

**Interfaces:**
- Produce: `ReporteProgramado` (modelo) con campos `nombre, query_sql, columnas_detectadas, transformacion_codigo, definicion, definicion_anterior, frecuencia, dias_semana, dia_mes, hora_ejecucion, destinatarios, activo, creado_por, actualizado_por, fecha_creacion, fecha_actualizacion`; constantes de clase `FRECUENCIA_CHOICES`, `DIAS_SEMANA_CHOICES`; métodos `lista_dias_semana() -> list[int]`, `lista_destinatarios() -> list[str]`, `actualizar_definicion(definicion: dict, usuario=None) -> None`, `restaurar() -> bool`.

- [ ] **Step 1: Crear el paquete de la app**

Crear `reportes/__init__.py` (vacío) y `reportes/apps.py`:

```python
from django.apps import AppConfig


class ReportesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reportes'
```

- [ ] **Step 2: Registrar la app en INSTALLED_APPS**

En `Programarprecios/settings.py`, en la lista `INSTALLED_APPS`, agregar `'reportes',` justo después de `'formatos',`.

- [ ] **Step 3: Escribir el modelo**

Crear `reportes/models.py`:

```python
from django.db import models


class ReporteProgramado(models.Model):
    FRECUENCIA_CHOICES = [('diario', 'Diario'), ('semanal', 'Semanal'), ('mensual', 'Mensual')]
    DIAS_SEMANA_CHOICES = [
        (0, 'Lunes'), (1, 'Martes'), (2, 'Miércoles'), (3, 'Jueves'),
        (4, 'Viernes'), (5, 'Sábado'), (6, 'Domingo'),
    ]

    nombre = models.CharField(max_length=150)
    query_sql = models.TextField(help_text='SELECT sobre DBISAM. Solo lectura.')
    columnas_detectadas = models.JSONField(null=True, blank=True)
    transformacion_codigo = models.TextField(
        blank=True, null=True,
        help_text='Función Python opcional transformar(filas) -> filas. '
                   'Corre con privilegios del servidor.')
    definicion = models.JSONField(null=True, blank=True)
    definicion_anterior = models.JSONField(null=True, blank=True)

    frecuencia = models.CharField(max_length=10, choices=FRECUENCIA_CHOICES)
    dias_semana = models.CharField(
        max_length=20, blank=True, default='',
        help_text='CSV de índices 0-6 (0=lunes). Solo aplica si frecuencia=semanal.')
    dia_mes = models.PositiveSmallIntegerField(null=True, blank=True)
    hora_ejecucion = models.TimeField()

    destinatarios = models.TextField(blank=True, default='', help_text='Emails separados por coma')
    activo = models.BooleanField(default=False)

    creado_por = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, related_name='reportes_creados')
    actualizado_por = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reportes_actualizados')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Reporte programado'
        verbose_name_plural = 'Reportes programados'

    def __str__(self):
        return self.nombre

    def lista_dias_semana(self) -> list:
        if not self.dias_semana:
            return []
        return [int(d) for d in self.dias_semana.split(',') if d != '']

    def lista_destinatarios(self) -> list:
        return [e.strip() for e in self.destinatarios.split(',') if e.strip()]

    def actualizar_definicion(self, definicion: dict, usuario=None) -> None:
        self.definicion_anterior = self.definicion
        self.definicion = definicion
        if usuario is not None:
            self.actualizado_por = usuario
        self.save()

    def restaurar(self) -> bool:
        if self.definicion_anterior is None:
            return False
        self.definicion, self.definicion_anterior = self.definicion_anterior, self.definicion
        self.save()
        return True
```

- [ ] **Step 4: Registrar el modelo en admin**

Crear `reportes/admin.py`:

```python
from django.contrib import admin

from .models import ReporteProgramado

admin.site.register(ReporteProgramado)
```

- [ ] **Step 5: Generar la migración**

Run: `venv\Scripts\python.exe manage.py makemigrations reportes`
Expected: crea `reportes/migrations/0001_initial.py` sin errores.

- [ ] **Step 6: Escribir los tests del modelo (fallando primero)**

Crear `reportes/tests.py`:

```python
from django.test import TestCase

from users.models import User

from .models import ReporteProgramado


class ReporteProgramadoModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='rep_admin', password='x')

    def _crear(self, **kwargs):
        datos = dict(nombre='Ventas diarias', query_sql='SELECT 1',
                     frecuencia='diario', hora_ejecucion='08:00',
                     destinatarios='a@test.local,b@test.local', creado_por=self.user)
        datos.update(kwargs)
        return ReporteProgramado.objects.create(**datos)

    def test_str_devuelve_nombre(self):
        reporte = self._crear()
        self.assertEqual(str(reporte), 'Ventas diarias')

    def test_lista_destinatarios_separa_por_coma(self):
        reporte = self._crear(destinatarios='a@test.local, b@test.local ,')
        self.assertEqual(reporte.lista_destinatarios(), ['a@test.local', 'b@test.local'])

    def test_lista_dias_semana_vacio(self):
        reporte = self._crear()
        self.assertEqual(reporte.lista_dias_semana(), [])

    def test_lista_dias_semana_parsea_csv(self):
        reporte = self._crear(frecuencia='semanal', dias_semana='0,2,4')
        self.assertEqual(reporte.lista_dias_semana(), [0, 2, 4])

    def test_actualizar_definicion_rota_version_anterior(self):
        reporte = self._crear()
        reporte.actualizar_definicion({'v': 1}, self.user)
        reporte.refresh_from_db()
        self.assertEqual(reporte.definicion, {'v': 1})
        self.assertIsNone(reporte.definicion_anterior)
        reporte.actualizar_definicion({'v': 2}, self.user)
        reporte.refresh_from_db()
        self.assertEqual(reporte.definicion, {'v': 2})
        self.assertEqual(reporte.definicion_anterior, {'v': 1})

    def test_restaurar_intercambia_versiones(self):
        reporte = self._crear(definicion={'v': 2}, definicion_anterior={'v': 1})
        self.assertTrue(reporte.restaurar())
        reporte.refresh_from_db()
        self.assertEqual(reporte.definicion, {'v': 1})
        self.assertEqual(reporte.definicion_anterior, {'v': 2})

    def test_restaurar_sin_version_anterior_devuelve_false(self):
        reporte = self._crear()
        self.assertFalse(reporte.restaurar())
```

- [ ] **Step 7: Correr los tests**

Run: `venv\Scripts\python.exe manage.py test reportes --settings=Programarprecios.test_settings`
Expected: 7 tests PASS (el modelo ya existe y la migración se aplica sola en la BD de test).

- [ ] **Step 8: Commit**

```bash
git add reportes/__init__.py reportes/apps.py reportes/models.py reportes/admin.py \
        reportes/migrations/ reportes/tests.py Programarprecios/settings.py
git commit -m "feat(reportes): agrega app y modelo ReporteProgramado"
```

---

### Task 2: Validación de SQL (solo SELECT)

**Files:**
- Create: `reportes/validacion_sql.py`
- Test: `reportes/tests.py`

**Interfaces:**
- Produce: `validar_select(query_sql: str) -> str` — `''` si es válido, mensaje de error si no.

- [ ] **Step 1: Escribir los tests (fallando primero)**

Agregar a `reportes/tests.py`:

```python
from .validacion_sql import validar_select


class ValidarSelectTest(TestCase):
    def test_select_simple_es_valido(self):
        self.assertEqual(validar_select('SELECT FI_CODIGO FROM SINVENTARIO'), '')

    def test_select_con_espacios_y_mayusculas_mixtas_es_valido(self):
        self.assertEqual(validar_select('  select FI_CODIGO from SINVENTARIO  '), '')

    def test_vacio_es_invalido(self):
        self.assertNotEqual(validar_select(''), '')
        self.assertNotEqual(validar_select('   '), '')

    def test_no_empieza_con_select_es_invalido(self):
        error = validar_select('UPDATE SINVENTARIO SET FI_DESCRIPCION = 1')
        self.assertIn('SELECT', error)

    def test_multiples_sentencias_es_invalido(self):
        error = validar_select('SELECT 1; DROP TABLE SINVENTARIO')
        self.assertIn(';', error)

    def test_punto_y_coma_final_es_valido(self):
        self.assertEqual(validar_select('SELECT FI_CODIGO FROM SINVENTARIO;'), '')

    def test_palabra_prohibida_en_subquery_es_invalida(self):
        error = validar_select(
            "SELECT * FROM SINVENTARIO WHERE FI_CODIGO IN "
            "(INSERT INTO X VALUES (1))")
        self.assertIn('INSERT', error)

    def test_columna_con_nombre_similar_a_palabra_prohibida_no_falsea(self):
        """FECHA_UPDATE no debe disparar el bloqueo de UPDATE (falso positivo)."""
        self.assertEqual(validar_select('SELECT FECHA_UPDATE FROM SINVENTARIO'), '')
```

- [ ] **Step 2: Correr los tests para confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test reportes.tests.ValidarSelectTest --settings=Programarprecios.test_settings`
Expected: FAIL con `ModuleNotFoundError: No module named 'reportes.validacion_sql'`.

- [ ] **Step 3: Implementar `validar_select`**

Crear `reportes/validacion_sql.py`:

```python
"""Validación defensiva de SQL libre para reportes programados.

No es un parser SQL completo: es una lista negra + verificación de que el
query sea una única sentencia SELECT. El nivel de confianza es el mismo que
ya tienen los superusuarios sobre el diseñador ReportBro de `formatos` y
sobre el propio código del repositorio — esto mitiga descuidos, no ataques
deliberados de alguien con esas credenciales.
"""
import re

_PALABRAS_PROHIBIDAS = (
    'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE', 'TRUNCATE',
    'EXEC', 'EXECUTE', 'GRANT', 'REVOKE',
)


def validar_select(query_sql: str) -> str:
    """Valida que query_sql sea un único SELECT de solo lectura.

    Returns:
        '' si es válido; mensaje de error legible si no.
    """
    if not query_sql or not query_sql.strip():
        return 'El query no puede estar vacío'

    sin_comentarios = re.sub(r'--[^\n]*', '', query_sql)
    sin_comentarios = re.sub(r'/\*.*?\*/', '', sin_comentarios, flags=re.DOTALL).strip()
    if not sin_comentarios:
        return 'El query no puede estar vacío'

    if not re.match(r'(?is)^select\b', sin_comentarios):
        return 'El query debe comenzar con SELECT'

    cuerpo = sin_comentarios[:-1] if sin_comentarios.endswith(';') else sin_comentarios
    if ';' in cuerpo:
        return 'No se permite más de una sentencia (detectado ";" adicional)'

    for palabra in _PALABRAS_PROHIBIDAS:
        if re.search(rf'(?i)\b{palabra}\b', cuerpo):
            return f'No se permite la palabra clave "{palabra}" en el query'

    return ''
```

- [ ] **Step 4: Correr los tests**

Run: `venv\Scripts\python.exe manage.py test reportes.tests.ValidarSelectTest --settings=Programarprecios.test_settings`
Expected: 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add reportes/validacion_sql.py reportes/tests.py
git commit -m "feat(reportes): agrega validacion_sql.validar_select (lista negra SELECT-only)"
```

---

### Task 3: Conexión DBISAM de solo lectura

**Files:**
- Create: `reportes/dbisam.py`
- Test: `reportes/tests.py`

**Interfaces:**
- Consume: `settings.DBISAM_DATABASE['DSN']`, `settings.DBISAM_DATABASE['CatalogName']` (ya definidos en `Programarprecios/settings.py`).
- Produce: `ReportesDBISAM` con `connect(self)` y `ejecutar_query(self, query_sql: str, limite: int | None = None) -> tuple[list[dict], list[dict]]` — devuelve `(columnas, filas)` donde `columnas = [{'nombre': str, 'tipo': 'string'|'number'|'date'|'boolean'}, ...]` y `filas = [{nombre_columna: valor, ...}, ...]`.

- [ ] **Step 1: Escribir los tests (fallando primero)**

Agregar a `reportes/tests.py`:

```python
import datetime
from unittest.mock import patch

from .dbisam import ReportesDBISAM


class ReportesDBISAMTest(TestCase):
    def test_ejecutar_query_devuelve_columnas_y_filas(self):
        db = ReportesDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = (mock_connect.return_value.__enter__.return_value
                      .cursor.return_value.__enter__.return_value)
            cursor.description = [('SKU', str, None, None, None, None, None),
                                   ('PRECIO', float, None, None, None, None, None)]
            cursor.fetchall.return_value = [('A1', 10.5), ('A2', 20.0)]
            columnas, filas = db.ejecutar_query('SELECT SKU, PRECIO FROM SINVENTARIO')
        self.assertEqual(columnas, [
            {'nombre': 'SKU', 'tipo': 'string'},
            {'nombre': 'PRECIO', 'tipo': 'number'},
        ])
        self.assertEqual(filas, [
            {'SKU': 'A1', 'PRECIO': 10.5},
            {'SKU': 'A2', 'PRECIO': 20.0},
        ])
        cursor.execute.assert_called_once_with('SELECT SKU, PRECIO FROM SINVENTARIO')

    def test_ejecutar_query_con_limite_usa_fetchmany(self):
        db = ReportesDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = (mock_connect.return_value.__enter__.return_value
                      .cursor.return_value.__enter__.return_value)
            cursor.description = [('SKU', str, None, None, None, None, None)]
            cursor.fetchmany.return_value = [('A1',)]
            columnas, filas = db.ejecutar_query('SELECT SKU FROM SINVENTARIO', limite=50)
        cursor.fetchmany.assert_called_once_with(50)
        self.assertEqual(filas, [{'SKU': 'A1'}])

    def test_tipos_fecha_y_boolean(self):
        db = ReportesDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = (mock_connect.return_value.__enter__.return_value
                      .cursor.return_value.__enter__.return_value)
            cursor.description = [
                ('FECHA', datetime.date, None, None, None, None, None),
                ('ACTIVO', bool, None, None, None, None, None),
            ]
            cursor.fetchall.return_value = [(datetime.date(2026, 1, 1), True)]
            columnas, _filas = db.ejecutar_query('SELECT FECHA, ACTIVO FROM T')
        self.assertEqual(columnas, [
            {'nombre': 'FECHA', 'tipo': 'date'},
            {'nombre': 'ACTIVO', 'tipo': 'boolean'},
        ])
```

- [ ] **Step 2: Correr los tests para confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test reportes.tests.ReportesDBISAMTest --settings=Programarprecios.test_settings`
Expected: FAIL con `ModuleNotFoundError: No module named 'reportes.dbisam'`.

- [ ] **Step 3: Implementar `ReportesDBISAM`**

Crear `reportes/dbisam.py`:

```python
"""Conexión de solo lectura a DBISAM para reportes programados."""
import datetime
from decimal import Decimal

import pyodbc
from django.conf import settings


class ReportesDBISAM:
    def __init__(self):
        self.dsn = settings.DBISAM_DATABASE['DSN']
        self.catalog = settings.DBISAM_DATABASE['CatalogName']

    def connect(self):
        return pyodbc.connect(f'DSN={self.dsn};CatalogName={self.catalog}')

    def ejecutar_query(self, query_sql: str, limite: int | None = None):
        """Ejecuta query_sql y devuelve (columnas, filas).

        Raises:
            pyodbc.Error: si la conexión o la ejecución fallan.
        """
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(query_sql)
                columnas = [
                    {'nombre': desc[0], 'tipo': _tipo_reportbro(desc[1])}
                    for desc in cursor.description
                ]
                registros = cursor.fetchmany(limite) if limite else cursor.fetchall()
                filas = [
                    {col['nombre']: valor for col, valor in zip(columnas, registro)}
                    for registro in registros
                ]
                return columnas, filas


def _tipo_reportbro(type_code) -> str:
    if type_code in (int, float, Decimal):
        return 'number'
    if type_code in (datetime.date, datetime.datetime):
        return 'date'
    if type_code is bool:
        return 'boolean'
    return 'string'
```

- [ ] **Step 4: Correr los tests**

Run: `venv\Scripts\python.exe manage.py test reportes.tests.ReportesDBISAMTest --settings=Programarprecios.test_settings`
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add reportes/dbisam.py reportes/tests.py
git commit -m "feat(reportes): agrega ReportesDBISAM (conexion de solo lectura + deteccion de columnas)"
```

---

### Task 4: Generador dinámico de plantilla ReportBro

**Files:**
- Modify: `formatos/semillas.py:55-89` (generalizar `_tabla` para aceptar `data_source`)
- Create: `reportes/semilla.py`
- Test: `reportes/tests.py`

**Interfaces:**
- Consume: `formatos.semillas._param`, `_texto`, `_tabla`, `_pie`, `_DOC_PROPS` (helpers ya existentes, reutilizados para no duplicar la construcción de JSON ReportBro).
- Produce: `generar_semilla(columnas: list[dict]) -> dict` — definición ReportBro inicial con un parámetro `array` llamado `filas`, un `child` por columna detectada.

- [ ] **Step 1: Generalizar `_tabla` en `formatos/semillas.py` (sin romper compatibilidad)**

En `formatos/semillas.py`, cambiar la firma y el uso de `dataSource`:

```python
def _tabla(id_, y, columnas, *, data_source='${items}'):
```

Y dentro del `return`, cambiar `'dataSource': '${items}',` por `'dataSource': data_source,`. El resto de la función queda igual. Esto no cambia el comportamiento de las llamadas existentes (`_tabla(200, 45, [...])` en `SEMILLA_DESPACHO`/`SEMILLA_PEDIDO`), que siguen usando `${items}` por default.

- [ ] **Step 2: Confirmar que los tests existentes de `formatos` siguen pasando**

Run: `venv\Scripts\python.exe manage.py test formatos --settings=Programarprecios.test_settings`
Expected: todos los tests de `formatos` PASS (sin regresiones).

- [ ] **Step 3: Escribir los tests de `generar_semilla` (fallando primero)**

Agregar a `reportes/tests.py`:

```python
class GenerarSemillaTest(TestCase):
    def test_estructura_basica(self):
        from .semilla import generar_semilla
        columnas = [{'nombre': 'SKU', 'tipo': 'string'}, {'nombre': 'PRECIO', 'tipo': 'number'}]
        definicion = generar_semilla(columnas)
        claves = {'docElements', 'parameters', 'styles', 'version', 'documentProperties'}
        self.assertEqual(claves, set(definicion.keys()) & claves)
        parametro_filas = next(p for p in definicion['parameters'] if p['name'] == 'filas')
        self.assertEqual(parametro_filas['type'], 'array')
        self.assertEqual({c['name'] for c in parametro_filas['children']}, {'SKU', 'PRECIO'})

    def test_genera_pdf_con_datos_reales(self):
        from reportbro import Report
        from .semilla import generar_semilla
        columnas = [{'nombre': 'SKU', 'tipo': 'string'}, {'nombre': 'PRECIO', 'tipo': 'number'}]
        definicion = generar_semilla(columnas)
        datos = {'filas': [{'SKU': 'A1', 'PRECIO': 10.5}, {'SKU': 'A2', 'PRECIO': 20}]}
        report = Report(definicion, datos)
        self.assertFalse(report.errors)
        pdf = report.generate_pdf()
        self.assertTrue(bytes(pdf).startswith(b'%PDF'))

    def test_sin_columnas_igual_genera_pdf(self):
        from reportbro import Report
        from .semilla import generar_semilla
        definicion = generar_semilla([])
        report = Report(definicion, {'filas': []})
        self.assertFalse(report.errors)
        pdf = report.generate_pdf()
        self.assertTrue(bytes(pdf).startswith(b'%PDF'))
```

- [ ] **Step 4: Correr los tests para confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test reportes.tests.GenerarSemillaTest --settings=Programarprecios.test_settings`
Expected: FAIL con `ModuleNotFoundError: No module named 'reportes.semilla'`.

- [ ] **Step 5: Implementar `generar_semilla`**

Crear `reportes/semilla.py`:

```python
"""Definición ReportBro inicial calculada a partir de las columnas detectadas
del query del reporte (en vez de un contrato fijo, como en formatos.semillas)."""
from formatos.semillas import _DOC_PROPS, _param, _pie, _tabla, _texto


def generar_semilla(columnas: list) -> dict:
    children = [_param(30 + i, col['nombre'], col['tipo']) for i, col in enumerate(columnas)]
    ancho = max(40, 575 // max(len(columnas), 1))
    columnas_tabla = [
        (col['nombre'], '${' + col['nombre'] + '}', ancho,
         'right' if col['tipo'] == 'number' else 'left')
        for col in columnas
    ]

    doc_elements = [
        _texto(101, 'Reporte', 0, 5, 575, 25, container='0_header', size=16, bold=True),
        _pie(),
    ]
    if columnas_tabla:
        doc_elements.insert(1, _tabla(200, 5, columnas_tabla, data_source='${filas}'))

    return {
        'docElements': doc_elements,
        'parameters': [
            _param(1, 'page_count', 'number'),
            _param(2, 'page_number', 'number'),
            _param(22, 'filas', 'array', children=children),
        ],
        'styles': [],
        'version': 4,
        'documentProperties': dict(_DOC_PROPS),
    }
```

- [ ] **Step 6: Correr los tests**

Run: `venv\Scripts\python.exe manage.py test reportes.tests.GenerarSemillaTest --settings=Programarprecios.test_settings`
Expected: 3 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add formatos/semillas.py reportes/semilla.py reportes/tests.py
git commit -m "feat(reportes): agrega generar_semilla y generaliza _tabla para dataSource dinamico"
```

---

### Task 5: Transformación Python opcional (namespace restringido + timeout)

**Files:**
- Create: `reportes/transformacion.py`
- Test: `reportes/tests.py`

**Interfaces:**
- Produce: `ejecutar_transformacion(codigo: str, filas: list, timeout: float = 10.0) -> list` — lanza `ValueError` si el código no define `transformar`, si falla al compilar/ejecutar, o si excede el timeout.

- [ ] **Step 1: Escribir los tests (fallando primero)**

Agregar a `reportes/tests.py`:

```python
from .transformacion import ejecutar_transformacion


class EjecutarTransformacionTest(TestCase):
    def test_transforma_filas_correctamente(self):
        codigo = (
            "def transformar(filas):\n"
            "    return [dict(f, PRECIO_IVA=f['PRECIO'] * 1.16) for f in filas]\n"
        )
        resultado = ejecutar_transformacion(codigo, [{'SKU': 'A1', 'PRECIO': 100}])
        self.assertEqual(resultado[0]['PRECIO_IVA'], 116.0)

    def test_sin_funcion_transformar_lanza_valueerror(self):
        with self.assertRaises(ValueError):
            ejecutar_transformacion('x = 1', [{'SKU': 'A1'}])

    def test_import_a_nivel_modulo_lanza_valueerror(self):
        codigo = "import os\ndef transformar(filas):\n    return filas\n"
        with self.assertRaises(ValueError):
            ejecutar_transformacion(codigo, [{'SKU': 'A1'}])

    def test_import_dentro_de_la_funcion_lanza_valueerror(self):
        codigo = "def transformar(filas):\n    import os\n    return filas\n"
        with self.assertRaises(ValueError):
            ejecutar_transformacion(codigo, [{'SKU': 'A1'}])

    def test_open_no_disponible(self):
        codigo = "def transformar(filas):\n    open('x.txt')\n    return filas\n"
        with self.assertRaises(ValueError):
            ejecutar_transformacion(codigo, [{'SKU': 'A1'}])

    def test_excepcion_en_transformacion_se_reporta(self):
        codigo = "def transformar(filas):\n    return 1 / 0\n"
        with self.assertRaises(ValueError):
            ejecutar_transformacion(codigo, [{'SKU': 'A1'}])

    def test_timeout_por_loop_infinito(self):
        codigo = "def transformar(filas):\n    while True:\n        pass\n"
        with self.assertRaises(ValueError):
            ejecutar_transformacion(codigo, [{'SKU': 'A1'}], timeout=0.2)
```

- [ ] **Step 2: Correr los tests para confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test reportes.tests.EjecutarTransformacionTest --settings=Programarprecios.test_settings`
Expected: FAIL con `ModuleNotFoundError: No module named 'reportes.transformacion'`.

- [ ] **Step 3: Implementar `ejecutar_transformacion`**

Crear `reportes/transformacion.py`:

```python
"""Ejecución de la transformación Python opcional de un reporte.

Mitigación de negligencia (bugs, loops infinitos, imports peligrosos), NO un
sandbox real contra código malicioso deliberado: el namespace restringido
bloquea el acceso directo a `os`/`sys`/`open`/`import`, y el timeout evita
que un loop infinito cuelgue el scheduler. Asume que quien escribe el código
es un superusuario de confianza, igual que ya lo es con el SQL libre.
"""
import threading

_BUILTINS_PERMITIDOS = {
    'len': len, 'range': range, 'str': str, 'int': int, 'float': float,
    'bool': bool, 'sum': sum, 'min': min, 'max': max, 'sorted': sorted,
    'round': round, 'dict': dict, 'list': list, 'enumerate': enumerate,
    'zip': zip, 'abs': abs,
}


def ejecutar_transformacion(codigo: str, filas: list, timeout: float = 10.0) -> list:
    """Ejecuta transformar(filas) definida en `codigo`, con timeout y builtins restringidos.

    Raises:
        ValueError: si el código no define `transformar`, si excede el
            timeout, o si la ejecución lanza una excepción.
    """
    namespace = {'__builtins__': _BUILTINS_PERMITIDOS}
    try:
        exec(codigo, namespace)
    except Exception as exc:
        raise ValueError(f'Error al compilar la transformación: {exc}') from exc

    transformar = namespace.get('transformar')
    if not callable(transformar):
        raise ValueError('El código debe definir una función transformar(filas)')

    resultado = {}
    error = {}

    def _correr():
        try:
            resultado['valor'] = transformar(filas)
        except Exception as exc:  # noqa: BLE001
            error['exc'] = exc

    hilo = threading.Thread(target=_correr, daemon=True)
    hilo.start()
    hilo.join(timeout)
    if hilo.is_alive():
        raise ValueError(f'La transformación excedió el tiempo límite de {timeout}s')
    if 'exc' in error:
        raise ValueError(f'Error al ejecutar la transformación: {error["exc"]}')
    return resultado.get('valor', filas)
```

- [ ] **Step 4: Correr los tests**

Run: `venv\Scripts\python.exe manage.py test reportes.tests.EjecutarTransformacionTest --settings=Programarprecios.test_settings`
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add reportes/transformacion.py reportes/tests.py
git commit -m "feat(reportes): agrega ejecutar_transformacion (namespace restringido + timeout)"
```

---

### Task 6: Scheduler — cálculo de trigger, registro de jobs e integración con `tasks`

**Files:**
- Create: `reportes/scheduler.py`
- Modify: `tasks/scheduler.py:76-81` (llamar a `cargar_reportes_activos` dentro de `iniciar_scheduler`)
- Test: `reportes/tests.py`
- Test: `tasks/tests.py`

**Interfaces:**
- Consume: `tasks.scheduler.get_scheduler()` (ya existente).
- Produce: `calcular_trigger_kwargs(reporte) -> dict`, `registrar_job_reporte(reporte) -> None`, `quitar_job_reporte(reporte_id) -> None`, `cargar_reportes_activos() -> None`.

- [ ] **Step 1: Escribir los tests de `reportes/scheduler.py` (fallando primero)**

Agregar a `reportes/tests.py`:

```python
from datetime import time as dt_time
from unittest.mock import MagicMock, patch


class CalcularTriggerKwargsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='sched_admin', password='x')

    def _crear(self, **kwargs):
        datos = dict(nombre='R', query_sql='SELECT 1', frecuencia='diario',
                     hora_ejecucion=dt_time(8, 30), destinatarios='a@test.local',
                     creado_por=self.user)
        datos.update(kwargs)
        return ReporteProgramado.objects.create(**datos)

    def test_diario(self):
        from .scheduler import calcular_trigger_kwargs
        reporte = self._crear()
        self.assertEqual(calcular_trigger_kwargs(reporte), {'hour': 8, 'minute': 30})

    def test_semanal(self):
        from .scheduler import calcular_trigger_kwargs
        reporte = self._crear(frecuencia='semanal', dias_semana='0,2,4')
        kwargs = calcular_trigger_kwargs(reporte)
        self.assertEqual(kwargs['day_of_week'], '0,2,4')
        self.assertEqual(kwargs['hour'], 8)

    def test_mensual(self):
        from .scheduler import calcular_trigger_kwargs
        reporte = self._crear(frecuencia='mensual', dia_mes=15)
        kwargs = calcular_trigger_kwargs(reporte)
        self.assertEqual(kwargs['day'], 15)


class RegistrarJobReporteTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='sched_admin2', password='x')
        self.reporte = ReporteProgramado.objects.create(
            nombre='R', query_sql='SELECT 1', frecuencia='diario',
            hora_ejecucion=dt_time(8, 0), destinatarios='a@test.local',
            creado_por=self.user)

    @patch('reportes.scheduler.get_scheduler')
    def test_registrar_job_llama_add_job_con_id_namespaced(self, mock_get_scheduler):
        from .scheduler import registrar_job_reporte
        mock_scheduler = MagicMock()
        mock_get_scheduler.return_value = mock_scheduler
        registrar_job_reporte(self.reporte)
        mock_scheduler.add_job.assert_called_once()
        _args, kwargs = mock_scheduler.add_job.call_args
        self.assertEqual(kwargs['id'], f'reporte_{self.reporte.id}')
        self.assertEqual(kwargs['trigger'], 'cron')
        self.assertEqual(kwargs['args'], [self.reporte.id])

    @patch('reportes.scheduler.get_scheduler')
    def test_quitar_job_llama_remove_job(self, mock_get_scheduler):
        from .scheduler import quitar_job_reporte
        mock_scheduler = MagicMock()
        mock_get_scheduler.return_value = mock_scheduler
        quitar_job_reporte(self.reporte.id)
        mock_scheduler.remove_job.assert_called_once_with(f'reporte_{self.reporte.id}')

    @patch('reportes.scheduler.get_scheduler')
    def test_quitar_job_no_lanza_si_no_existe(self, mock_get_scheduler):
        from .scheduler import quitar_job_reporte
        mock_scheduler = MagicMock()
        mock_scheduler.remove_job.side_effect = Exception('job not found')
        mock_get_scheduler.return_value = mock_scheduler
        quitar_job_reporte(999)  # no debe lanzar


class CargarReportesActivosTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='sched_admin3', password='x')

    @patch('reportes.scheduler.registrar_job_reporte')
    def test_registra_solo_los_activos(self, mock_registrar):
        from .scheduler import cargar_reportes_activos
        ReporteProgramado.objects.create(
            nombre='Activo', query_sql='SELECT 1', frecuencia='diario',
            hora_ejecucion=dt_time(8, 0), destinatarios='a@test.local',
            creado_por=self.user, activo=True)
        ReporteProgramado.objects.create(
            nombre='Inactivo', query_sql='SELECT 1', frecuencia='diario',
            hora_ejecucion=dt_time(8, 0), destinatarios='a@test.local',
            creado_por=self.user, activo=False)
        cargar_reportes_activos()
        mock_registrar.assert_called_once()
```

- [ ] **Step 2: Correr los tests para confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test reportes --settings=Programarprecios.test_settings`
Expected: FAIL con `ModuleNotFoundError: No module named 'reportes.scheduler'`.

- [ ] **Step 3: Implementar `reportes/scheduler.py`**

```python
"""Registro de jobs cron para reportes programados, sobre el scheduler
singleton ya arrancado por tasks (manage.py programador)."""
from tasks.scheduler import get_scheduler


def calcular_trigger_kwargs(reporte) -> dict:
    kwargs = {'hour': reporte.hora_ejecucion.hour, 'minute': reporte.hora_ejecucion.minute}
    if reporte.frecuencia == 'semanal':
        kwargs['day_of_week'] = ','.join(str(d) for d in reporte.lista_dias_semana())
    elif reporte.frecuencia == 'mensual':
        kwargs['day'] = reporte.dia_mes
    return kwargs


def registrar_job_reporte(reporte) -> None:
    from .tasks import ejecutar_reporte_programado
    scheduler = get_scheduler()
    scheduler.add_job(
        ejecutar_reporte_programado, trigger='cron', id=f'reporte_{reporte.id}',
        args=[reporte.id], replace_existing=True, jobstore='default',
        max_instances=1, misfire_grace_time=9600, **calcular_trigger_kwargs(reporte))


def quitar_job_reporte(reporte_id) -> None:
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(f'reporte_{reporte_id}')
    except Exception:
        pass


def cargar_reportes_activos() -> None:
    from .models import ReporteProgramado
    for reporte in ReporteProgramado.objects.filter(activo=True):
        registrar_job_reporte(reporte)
```

- [ ] **Step 4: Correr los tests de `reportes/scheduler.py`**

Run: `venv\Scripts\python.exe manage.py test reportes --settings=Programarprecios.test_settings`
Expected: todos los tests de `reportes` PASS (incluye los de tasks anteriores).

- [ ] **Step 5: Escribir el test de integración con `tasks.scheduler.iniciar_scheduler` (fallando primero)**

Reemplazar el contenido de `tasks/tests.py`:

```python
from unittest.mock import MagicMock, patch

from django.test import TestCase


class IniciarSchedulerCargaReportesTest(TestCase):
    @patch('reportes.scheduler.cargar_reportes_activos')
    @patch('tasks.scheduler.programar_correo')
    @patch('tasks.scheduler.cargar_tareas_pendientes')
    @patch('tasks.scheduler.eliminar_ejecuciones_antiguas')
    @patch('tasks.scheduler.get_scheduler')
    def test_iniciar_scheduler_carga_reportes_activos(
            self, mock_get_scheduler, mock_eliminar, mock_cargar_tareas,
            mock_programar_correo, mock_cargar_reportes):
        mock_scheduler = MagicMock()
        mock_scheduler.running = False
        mock_get_scheduler.return_value = mock_scheduler

        from tasks.scheduler import iniciar_scheduler
        iniciar_scheduler()

        mock_cargar_reportes.assert_called_once()
```

- [ ] **Step 6: Correr el test para confirmar que falla**

Run: `venv\Scripts\python.exe manage.py test tasks --settings=Programarprecios.test_settings`
Expected: FAIL — `cargar_reportes_activos` todavía no se llama desde `iniciar_scheduler`.

- [ ] **Step 7: Enganchar `reportes` en `iniciar_scheduler`**

En `tasks/scheduler.py`, dentro de `iniciar_scheduler()`, después de `programar_correo()` y antes del `print("Scheduler iniciado correctamente")`:

```python
            cargar_tareas_pendientes()
            programar_correo()
            from reportes.scheduler import cargar_reportes_activos
            cargar_reportes_activos()

            print("Scheduler iniciado correctamente")
```

(El import local evita cualquier ciclo de import a nivel de módulo entre `tasks` y `reportes`.)

- [ ] **Step 8: Correr el test de integración**

Run: `venv\Scripts\python.exe manage.py test tasks --settings=Programarprecios.test_settings`
Expected: 1 test PASS.

- [ ] **Step 9: Commit**

```bash
git add reportes/scheduler.py reportes/tests.py tasks/scheduler.py tasks/tests.py
git commit -m "feat(reportes): agrega scheduler de reportes y lo engancha en tasks.iniciar_scheduler"
```

---

### Task 7: Job de ejecución programada (correo + manejo de errores)

**Files:**
- Create: `reportes/tasks.py`
- Test: `reportes/tests.py`

**Interfaces:**
- Consume: `ReportesDBISAM().ejecutar_query`, `validar_select`, `ejecutar_transformacion`, `generar_semilla`, `reporte.lista_destinatarios()`.
- Produce: `ejecutar_reporte_programado(reporte_id: int) -> None` (target del job cron registrado en Task 6).

- [ ] **Step 1: Escribir los tests (fallando primero)**

Agregar a `reportes/tests.py`:

```python
from django.core import mail


class EjecutarReporteProgramadoTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='job_admin', password='x', email='admin@test.local')
        from .semilla import generar_semilla
        columnas = [{'nombre': 'SKU', 'tipo': 'string'}, {'nombre': 'PRECIO', 'tipo': 'number'}]
        self.reporte = ReporteProgramado.objects.create(
            nombre='Ventas', query_sql='SELECT SKU, PRECIO FROM SINVENTARIO',
            frecuencia='diario', hora_ejecucion=dt_time(8, 0),
            destinatarios='dest@test.local', creado_por=self.user,
            columnas_detectadas=columnas, definicion=generar_semilla(columnas),
            activo=True)

    @patch('reportes.tasks.ReportesDBISAM')
    def test_envia_correo_con_pdf_adjunto(self, mock_db_cls):
        from .tasks import ejecutar_reporte_programado
        mock_db_cls.return_value.ejecutar_query.return_value = (
            [{'nombre': 'SKU', 'tipo': 'string'}, {'nombre': 'PRECIO', 'tipo': 'number'}],
            [{'SKU': 'A1', 'PRECIO': 10.5}],
        )
        ejecutar_reporte_programado(self.reporte.id)
        self.assertEqual(len(mail.outbox), 1)
        enviado = mail.outbox[0]
        self.assertEqual(enviado.to, ['dest@test.local'])
        self.assertEqual(len(enviado.attachments), 1)
        nombre_archivo, contenido, tipo = enviado.attachments[0]
        self.assertTrue(nombre_archivo.endswith('.pdf'))
        self.assertEqual(tipo, 'application/pdf')
        self.assertTrue(bytes(contenido).startswith(b'%PDF'))

    @patch('reportes.tasks.ReportesDBISAM')
    def test_sin_filas_no_envia_correo(self, mock_db_cls):
        from .tasks import ejecutar_reporte_programado
        mock_db_cls.return_value.ejecutar_query.return_value = ([], [])
        ejecutar_reporte_programado(self.reporte.id)
        self.assertEqual(len(mail.outbox), 0)

    @patch('reportes.tasks.ReportesDBISAM')
    def test_fallo_de_query_notifica_al_dueno(self, mock_db_cls):
        from .tasks import ejecutar_reporte_programado
        mock_db_cls.return_value.ejecutar_query.side_effect = Exception('odbc down')
        ejecutar_reporte_programado(self.reporte.id)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Error al generar', mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ['admin@test.local'])

    def test_query_sql_invalido_notifica_al_dueno(self):
        from .tasks import ejecutar_reporte_programado
        self.reporte.query_sql = 'DROP TABLE SINVENTARIO'
        self.reporte.save(update_fields=['query_sql'])
        ejecutar_reporte_programado(self.reporte.id)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Error al generar', mail.outbox[0].subject)

    @patch('reportes.tasks.ReportesDBISAM')
    def test_transformacion_fallida_notifica_al_dueno(self, mock_db_cls):
        from .tasks import ejecutar_reporte_programado
        mock_db_cls.return_value.ejecutar_query.return_value = (
            [{'nombre': 'SKU', 'tipo': 'string'}], [{'SKU': 'A1'}])
        self.reporte.transformacion_codigo = "def transformar(filas):\n    return 1 / 0\n"
        self.reporte.save(update_fields=['transformacion_codigo'])
        ejecutar_reporte_programado(self.reporte.id)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Error al generar', mail.outbox[0].subject)

    def test_reporte_inactivo_no_hace_nada(self):
        from .tasks import ejecutar_reporte_programado
        self.reporte.activo = False
        self.reporte.save(update_fields=['activo'])
        ejecutar_reporte_programado(self.reporte.id)
        self.assertEqual(len(mail.outbox), 0)

    def test_reporte_inexistente_no_hace_nada(self):
        from .tasks import ejecutar_reporte_programado
        ejecutar_reporte_programado(999999)
        self.assertEqual(len(mail.outbox), 0)
```

- [ ] **Step 2: Correr los tests para confirmar que fallan**

Run: `venv\Scripts\python.exe manage.py test reportes.tests.EjecutarReporteProgramadoTest --settings=Programarprecios.test_settings`
Expected: FAIL con `ModuleNotFoundError: No module named 'reportes.tasks'`.

- [ ] **Step 3: Implementar `ejecutar_reporte_programado`**

Crear `reportes/tasks.py`:

```python
"""Job de ejecución programada: query -> transformación opcional -> PDF -> correo.

Nunca propaga excepciones (es el target de un job APScheduler): cualquier
fallo se loguea y se notifica por correo al dueño del reporte.
"""
import logging
from datetime import date

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

from .dbisam import ReportesDBISAM
from .semilla import generar_semilla
from .transformacion import ejecutar_transformacion
from .validacion_sql import validar_select

logger = logging.getLogger(__name__)


def ejecutar_reporte_programado(reporte_id: int) -> None:
    from .models import ReporteProgramado

    reporte = ReporteProgramado.objects.filter(id=reporte_id).first()
    if reporte is None or not reporte.activo:
        return

    try:
        error_sql = validar_select(reporte.query_sql)
        if error_sql:
            raise ValueError(f'Query inválido: {error_sql}')

        _columnas, filas = ReportesDBISAM().ejecutar_query(reporte.query_sql)

        if reporte.transformacion_codigo:
            filas = ejecutar_transformacion(reporte.transformacion_codigo, filas)

        if not filas:
            logger.info('Reporte %s sin filas, no se envía', reporte.nombre)
            return

        from reportbro import Report
        definicion = reporte.definicion or generar_semilla(reporte.columnas_detectadas or [])
        report = Report(definicion, {'filas': filas})
        if report.errors:
            raise ValueError(f'Errores de plantilla: {report.errors}')
        pdf = bytes(report.generate_pdf())

        _enviar_reporte(reporte, pdf)
    except Exception as exc:  # noqa: BLE001
        logger.exception('Fallo ejecutando reporte programado %s', reporte_id)
        _notificar_error(reporte, exc)


def _enviar_reporte(reporte, pdf: bytes) -> None:
    nombre_archivo = f'{reporte.nombre}_{date.today().isoformat()}.pdf'
    email = EmailMultiAlternatives(
        subject=f'Reporte: {reporte.nombre}',
        body='Adjunto el reporte generado según la programación configurada.',
        from_email=settings.EMAIL_HOST_USER,
        to=reporte.lista_destinatarios(),
    )
    email.attach(nombre_archivo, pdf, 'application/pdf')
    email.send(fail_silently=False)


def _notificar_error(reporte, exc: Exception) -> None:
    destinatario = reporte.actualizado_por or reporte.creado_por
    if destinatario is None or not destinatario.email:
        logger.warning('Reporte %s sin destinatario de error configurado', reporte.nombre)
        return
    email = EmailMultiAlternatives(
        subject=f'Error al generar el reporte: {reporte.nombre}',
        body=f'El reporte "{reporte.nombre}" no pudo generarse el '
             f'{date.today().isoformat()}.\n\nDetalle: {exc}',
        from_email=settings.EMAIL_HOST_USER,
        to=[destinatario.email],
    )
    email.send(fail_silently=True)
```

- [ ] **Step 4: Correr los tests**

Run: `venv\Scripts\python.exe manage.py test reportes.tests.EjecutarReporteProgramadoTest --settings=Programarprecios.test_settings`
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add reportes/tasks.py reportes/tests.py
git commit -m "feat(reportes): agrega ejecutar_reporte_programado (query, transformacion, PDF, correo)"
```

---

### Task 8: Vistas, URLs y templates de gestión

**Files:**
- Create: `reportes/views.py`
- Create: `reportes/urls.py`
- Create: `templates/reportes-lista.html`
- Create: `templates/reportes-nuevo.html`
- Create: `templates/reportes-detalle.html`
- Create: `templates/reportes-disenar.html`
- Create: `templates/reportes-programacion.html`
- Modify: `Programarprecios/urls.py` (agregar `include('reportes.urls')`)
- Test: `reportes/tests.py`

**Interfaces:**
- Consume: `formatos.generacion.validar_plantilla`, `formatos.models.ReportePreview`, `ReportesDBISAM`, `validar_select`, `generar_semilla`, `registrar_job_reporte`, `quitar_job_reporte`.
- Produce: nombres de URL `reportes-lista`, `reportes-nuevo`, `reportes-detalle`, `reportes-probar`, `reportes-disenar`, `reportes-report-run`, `reportes-guardar`, `reportes-programacion`, `reportes-activar`, `reportes-desactivar`, `reportes-eliminar`.

- [ ] **Step 1: Implementar `reportes/views.py`**

```python
import json
import uuid
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import (
    HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.safestring import SafeString
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from reportbro import Report, ReportBroError

from formatos.generacion import validar_plantilla
from formatos.models import ReportePreview

from .dbisam import ReportesDBISAM
from .models import ReporteProgramado
from .scheduler import quitar_job_reporte, registrar_job_reporte
from .semilla import generar_semilla
from .validacion_sql import validar_select

_es_superusuario = user_passes_test(lambda u: u.is_superuser, login_url='dashboard')
LIMITE_PREVIEW = 200


@login_required(login_url='/login/')
@_es_superusuario
def lista(request):
    reportes = ReporteProgramado.objects.order_by('-fecha_actualizacion')
    return render(request, 'reportes-lista.html', {'reportes': reportes})


@login_required(login_url='/login/')
@_es_superusuario
def nuevo(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        query_sql = request.POST.get('query_sql', '').strip()
        if not nombre or not query_sql:
            messages.error(request, 'Nombre y query son obligatorios.')
            return render(request, 'reportes-nuevo.html', {'nombre': nombre, 'query_sql': query_sql})
        error = validar_select(query_sql)
        if error:
            messages.error(request, error)
            return render(request, 'reportes-nuevo.html', {'nombre': nombre, 'query_sql': query_sql})
        reporte = ReporteProgramado.objects.create(
            nombre=nombre, query_sql=query_sql, frecuencia='diario',
            hora_ejecucion='08:00', destinatarios='', creado_por=request.user)
        return redirect('reportes-detalle', reporte.id)
    return render(request, 'reportes-nuevo.html')


@login_required(login_url='/login/')
@_es_superusuario
def detalle(request, reporte_id):
    reporte = get_object_or_404(ReporteProgramado, id=reporte_id)
    return render(request, 'reportes-detalle.html', {'reporte': reporte})


@login_required(login_url='/login/')
@_es_superusuario
@require_POST
def probar(request, reporte_id):
    reporte = get_object_or_404(ReporteProgramado, id=reporte_id)
    query_sql = request.POST.get('query_sql', reporte.query_sql).strip()
    error = validar_select(query_sql)
    if error:
        return JsonResponse({'ok': False, 'error': error}, status=400)
    try:
        columnas, filas = ReportesDBISAM().ejecutar_query(query_sql, limite=LIMITE_PREVIEW)
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    reporte.query_sql = query_sql
    reporte.columnas_detectadas = columnas
    reporte.save(update_fields=['query_sql', 'columnas_detectadas'])
    return JsonResponse({'ok': True, 'columnas': columnas, 'filas': filas[:20]})


@login_required(login_url='/login/')
@_es_superusuario
def disenar(request, reporte_id):
    reporte = get_object_or_404(ReporteProgramado, id=reporte_id)
    if not reporte.columnas_detectadas:
        messages.error(request, 'Primero probá el query para detectar las columnas.')
        return redirect('reportes-detalle', reporte.id)
    if reporte.definicion is None:
        reporte.definicion = generar_semilla(reporte.columnas_detectadas)
        reporte.save(update_fields=['definicion'])
    return render(request, 'reportes-disenar.html', {
        'reporte': reporte,
        'definicion_json': SafeString(json.dumps(reporte.definicion)),
    })


@csrf_exempt
def report_run(request, reporte_id):
    if not request.user.is_authenticated or not request.user.is_superuser:
        return HttpResponseForbidden()
    reporte = get_object_or_404(ReporteProgramado, id=reporte_id)

    if request.method == 'PUT':
        try:
            json_data = json.loads(request.body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return HttpResponseBadRequest('JSON inválido')
        if not isinstance(json_data, dict) or not isinstance(json_data.get('report'), dict):
            return HttpResponseBadRequest('invalid report values')
        if json_data.get('outputFormat') != 'pdf':
            return HttpResponseBadRequest('outputFormat inválido (solo pdf)')
        try:
            _columnas, filas = ReportesDBISAM().ejecutar_query(reporte.query_sql, limite=LIMITE_PREVIEW)
        except Exception as exc:  # noqa: BLE001
            return HttpResponse(json.dumps({'errors': [str(exc)]}))
        try:
            report = Report(json_data['report'], {'filas': filas})
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


@login_required(login_url='/login/')
@_es_superusuario
@require_POST
def guardar(request, reporte_id):
    reporte = get_object_or_404(ReporteProgramado, id=reporte_id)
    try:
        definicion = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponseBadRequest('JSON inválido')
    if not isinstance(definicion, dict) or \
            not isinstance(definicion.get('docElements'), list) or \
            not isinstance(definicion.get('parameters'), list) or \
            not isinstance(definicion.get('styles'), list) or \
            not isinstance(definicion.get('documentProperties'), dict) or \
            not isinstance(definicion.get('version'), int):
        return HttpResponseBadRequest('definición incompleta')
    reporte.actualizar_definicion(definicion, request.user)
    return HttpResponse('ok')


@login_required(login_url='/login/')
@_es_superusuario
def programacion(request, reporte_id):
    reporte = get_object_or_404(ReporteProgramado, id=reporte_id)
    if request.method == 'POST':
        reporte.frecuencia = request.POST.get('frecuencia', 'diario')
        reporte.hora_ejecucion = request.POST.get('hora_ejecucion') or reporte.hora_ejecucion
        reporte.dias_semana = ','.join(request.POST.getlist('dias_semana'))
        dia_mes = request.POST.get('dia_mes')
        if dia_mes:
            valor = int(dia_mes)
            if not 1 <= valor <= 31:
                messages.error(request, 'El día del mes debe estar entre 1 y 31.')
                return redirect('reportes-programacion', reporte.id)
            reporte.dia_mes = valor
        else:
            reporte.dia_mes = None
        reporte.destinatarios = request.POST.get('destinatarios', '').strip()
        reporte.transformacion_codigo = request.POST.get('transformacion_codigo', '').strip() or None
        reporte.actualizado_por = request.user
        reporte.save()
        if reporte.activo:
            registrar_job_reporte(reporte)
        messages.success(request, 'Programación guardada.')
        return redirect('reportes-detalle', reporte.id)
    return render(request, 'reportes-programacion.html', {
        'reporte': reporte,
        'dias_semana_choices': ReporteProgramado.DIAS_SEMANA_CHOICES,
    })


@login_required(login_url='/login/')
@_es_superusuario
@require_POST
def activar(request, reporte_id):
    reporte = get_object_or_404(ReporteProgramado, id=reporte_id)
    if not reporte.destinatarios.strip():
        messages.error(request, 'Configurá al menos un destinatario antes de activar.')
        return redirect('reportes-detalle', reporte.id)
    if not reporte.definicion:
        messages.error(request, 'Diseñá el formato antes de activar.')
        return redirect('reportes-detalle', reporte.id)
    try:
        _columnas, filas = ReportesDBISAM().ejecutar_query(reporte.query_sql)
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f'No se activó: fallo al ejecutar el query. Detalle: {exc}')
        return redirect('reportes-detalle', reporte.id)
    error = validar_plantilla(reporte.definicion, {'filas': filas})
    if error:
        messages.error(request, f'No se activó: la plantilla no genera un PDF válido. Detalle: {error}')
        return redirect('reportes-detalle', reporte.id)
    reporte.activo = True
    reporte.save(update_fields=['activo'])
    registrar_job_reporte(reporte)
    messages.success(request, f'Reporte "{reporte.nombre}" activado y programado.')
    return redirect('reportes-detalle', reporte.id)


@login_required(login_url='/login/')
@_es_superusuario
@require_POST
def desactivar(request, reporte_id):
    reporte = get_object_or_404(ReporteProgramado, id=reporte_id)
    reporte.activo = False
    reporte.save(update_fields=['activo'])
    quitar_job_reporte(reporte.id)
    messages.success(request, f'Reporte "{reporte.nombre}" desactivado.')
    return redirect('reportes-detalle', reporte.id)


@login_required(login_url='/login/')
@_es_superusuario
@require_POST
def eliminar(request, reporte_id):
    reporte = get_object_or_404(ReporteProgramado, id=reporte_id)
    quitar_job_reporte(reporte.id)
    reporte.delete()
    messages.success(request, 'Reporte eliminado.')
    return redirect('reportes-lista')
```

- [ ] **Step 2: Implementar `reportes/urls.py`**

```python
from django.urls import path

from . import views

urlpatterns = [
    path('reportes/', views.lista, name='reportes-lista'),
    path('reportes/nuevo/', views.nuevo, name='reportes-nuevo'),
    path('reportes/<int:reporte_id>/', views.detalle, name='reportes-detalle'),
    path('reportes/<int:reporte_id>/probar/', views.probar, name='reportes-probar'),
    path('reportes/<int:reporte_id>/disenar/', views.disenar, name='reportes-disenar'),
    path('reportes/<int:reporte_id>/report/run', views.report_run, name='reportes-report-run'),
    path('reportes/<int:reporte_id>/guardar/', views.guardar, name='reportes-guardar'),
    path('reportes/<int:reporte_id>/programacion/', views.programacion, name='reportes-programacion'),
    path('reportes/<int:reporte_id>/activar/', views.activar, name='reportes-activar'),
    path('reportes/<int:reporte_id>/desactivar/', views.desactivar, name='reportes-desactivar'),
    path('reportes/<int:reporte_id>/eliminar/', views.eliminar, name='reportes-eliminar'),
]
```

- [ ] **Step 3: Registrar las URLs en el proyecto**

En `Programarprecios/urls.py`, agregar después de `path('', include('formatos.urls')),`:

```python
    path('', include('reportes.urls')),
```

- [ ] **Step 4: Crear los templates**

Crear `templates/reportes-lista.html`:

```html
{% extends "dashboard.html" %}
{% block content %}

<div class="pd-header">
    <div class="pd-header-left">
        <div>
            <span class="pd-header-eyebrow">Configuración</span>
            <div class="pd-header-title-row">
                <h1 class="pd-header-num">Reportes programados</h1>
            </div>
        </div>
    </div>
    <a href="{% url 'reportes-nuevo' %}" class="btn btn-primary">Nuevo reporte</a>
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
                <th>Nombre</th>
                <th>Estado</th>
                <th>Frecuencia</th>
                <th>Última modificación</th>
                <th class="text-end">Acciones</th>
            </tr>
        </thead>
        <tbody>
            {% for reporte in reportes %}
            <tr>
                <td>{{ reporte.nombre }}</td>
                <td>
                    {% if reporte.activo %}
                    <span class="pl-chip pl-chip-recibido">Activo</span>
                    {% else %}
                    <span class="pl-chip pl-chip-pendiente">Inactivo</span>
                    {% endif %}
                </td>
                <td>{{ reporte.get_frecuencia_display }}</td>
                <td>{{ reporte.fecha_actualizacion|date:"d/m/Y H:i" }}</td>
                <td class="text-end">
                    <a href="{% url 'reportes-detalle' reporte.id %}" class="btn btn-sm btn-primary">Ver</a>
                </td>
            </tr>
            {% empty %}
            <tr><td colspan="5">No hay reportes creados todavía.</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

Crear `templates/reportes-nuevo.html`:

```html
{% extends "dashboard.html" %}
{% block content %}

<div class="pd-header">
    <h1 class="pd-header-num">Nuevo reporte programado</h1>
</div>

{% if messages %}
    {% for message in messages %}
    <div class="alert alert-{{ message.tags }}">{{ message }}</div>
    {% endfor %}
{% endif %}

<form method="post" class="pl-table-card p-3">
    {% csrf_token %}
    <div class="mb-3">
        <label class="form-label">Nombre</label>
        <input type="text" name="nombre" class="form-control" value="{{ nombre|default:'' }}" required>
    </div>
    <div class="mb-3">
        <label class="form-label">Query SQL (solo SELECT, DBISAM)</label>
        <textarea name="query_sql" class="form-control" rows="8" required>{{ query_sql|default:'' }}</textarea>
    </div>
    <button type="submit" class="btn btn-primary">Crear</button>
    <a href="{% url 'reportes-lista' %}" class="btn btn-outline-secondary">Cancelar</a>
</form>
{% endblock %}
```

Crear `templates/reportes-detalle.html`:

```html
{% extends "dashboard.html" %}
{% block content %}

<div class="pd-header">
    <h1 class="pd-header-num">{{ reporte.nombre }}</h1>
</div>

{% if messages %}
    {% for message in messages %}
    <div class="alert alert-{{ message.tags }}">{{ message }}</div>
    {% endfor %}
{% endif %}

<div class="pl-table-card p-3 mb-3">
    <h5>Query</h5>
    <textarea id="query_sql" class="form-control" rows="8">{{ reporte.query_sql }}</textarea>
    <button id="btn-probar" class="btn btn-outline-primary mt-2" type="button">Probar query</button>
    <div id="resultado-prueba" class="mt-3"></div>
</div>

<div class="pl-table-card p-3 mb-3">
    <h5>Formato</h5>
    {% if reporte.columnas_detectadas %}
    <a href="{% url 'reportes-disenar' reporte.id %}" class="btn btn-primary">Diseñar formato</a>
    {% else %}
    <p class="text-muted">Probá el query primero para detectar las columnas.</p>
    {% endif %}
</div>

<div class="pl-table-card p-3 mb-3">
    <h5>Programación</h5>
    <a href="{% url 'reportes-programacion' reporte.id %}" class="btn btn-outline-primary">
        Configurar frecuencia y destinatarios
    </a>
</div>

<div class="pl-table-card p-3">
    {% if reporte.activo %}
    <form method="post" action="{% url 'reportes-desactivar' reporte.id %}" class="d-inline">
        {% csrf_token %}
        <button class="btn btn-outline-warning">Desactivar</button>
    </form>
    {% else %}
    <form method="post" action="{% url 'reportes-activar' reporte.id %}" class="d-inline">
        {% csrf_token %}
        <button class="btn btn-outline-success">Activar</button>
    </form>
    {% endif %}
    <form method="post" action="{% url 'reportes-eliminar' reporte.id %}" class="d-inline"
          onsubmit="return confirm('¿Eliminar este reporte?');">
        {% csrf_token %}
        <button class="btn btn-outline-danger">Eliminar</button>
    </form>
</div>

<script>
document.getElementById('btn-probar').addEventListener('click', function () {
    var query_sql = document.getElementById('query_sql').value;
    fetch("{% url 'reportes-probar' reporte.id %}", {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': '{{ csrf_token }}',
        },
        body: 'query_sql=' + encodeURIComponent(query_sql),
    }).then(function (resp) { return resp.json(); }).then(function (data) {
        var div = document.getElementById('resultado-prueba');
        if (!data.ok) {
            div.innerHTML = '<div class="alert alert-danger">' + data.error + '</div>';
            return;
        }
        var html = '<table class="table table-sm"><thead><tr>';
        data.columnas.forEach(function (c) { html += '<th>' + c.nombre + '</th>'; });
        html += '</tr></thead><tbody>';
        data.filas.forEach(function (fila) {
            html += '<tr>';
            data.columnas.forEach(function (c) { html += '<td>' + (fila[c.nombre] ?? '') + '</td>'; });
            html += '</tr>';
        });
        html += '</tbody></table>';
        div.innerHTML = html;
        setTimeout(function () { location.reload(); }, 800);
    }).catch(function () {
        document.getElementById('resultado-prueba').innerHTML =
            '<div class="alert alert-danger">Error de red al probar el query</div>';
    });
});
</script>
{% endblock %}
```

Crear `templates/reportes-disenar.html`:

```html
{% load static %}
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Diseñar reporte — {{ reporte.nombre }}</title>
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
        <a href="{% url 'reportes-detalle' reporte.id %}">&larr; {{ reporte.nombre }}</a>
        <span id="fmt-estado"></span>
    </div>
    <div id="reportbro"></div>

    <script src="{% static 'vendor/reportbro/reportbro.js' %}"></script>
    <script>
        function guardarReporte() {
            fetch("{% url 'reportes-guardar' reporte.id %}", {
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

        var rb = new ReportBro(document.getElementById('reportbro'), {
            reportServerUrl: "{% url 'reportes-report-run' reporte.id %}",
            saveCallback: guardarReporte,
        });
        rb.load({{ definicion_json }});
    </script>
</body>
</html>
```

Crear `templates/reportes-programacion.html`:

```html
{% extends "dashboard.html" %}
{% block content %}

<div class="pd-header">
    <h1 class="pd-header-num">Programación — {{ reporte.nombre }}</h1>
</div>

{% if messages %}
    {% for message in messages %}
    <div class="alert alert-{{ message.tags }}">{{ message }}</div>
    {% endfor %}
{% endif %}

<form method="post" class="pl-table-card p-3">
    {% csrf_token %}
    <div class="mb-3">
        <label class="form-label">Frecuencia</label>
        <select name="frecuencia" class="form-select">
            <option value="diario" {% if reporte.frecuencia == 'diario' %}selected{% endif %}>Diario</option>
            <option value="semanal" {% if reporte.frecuencia == 'semanal' %}selected{% endif %}>Semanal</option>
            <option value="mensual" {% if reporte.frecuencia == 'mensual' %}selected{% endif %}>Mensual</option>
        </select>
    </div>
    <div class="mb-3">
        <label class="form-label">Días de la semana (solo si es semanal)</label><br>
        {% for valor, etiqueta in dias_semana_choices %}
        <label class="me-3">
            <input type="checkbox" name="dias_semana" value="{{ valor }}"
                   {% if valor in reporte.lista_dias_semana %}checked{% endif %}>
            {{ etiqueta }}
        </label>
        {% endfor %}
    </div>
    <div class="mb-3">
        <label class="form-label">Día del mes (solo si es mensual, 1-31)</label>
        <input type="number" name="dia_mes" class="form-control" min="1" max="31"
               value="{{ reporte.dia_mes|default:'' }}">
    </div>
    <div class="mb-3">
        <label class="form-label">Hora de ejecución</label>
        <input type="time" name="hora_ejecucion" class="form-control"
               value="{{ reporte.hora_ejecucion|time:'H:i' }}" required>
    </div>
    <div class="mb-3">
        <label class="form-label">Destinatarios (emails separados por coma)</label>
        <textarea name="destinatarios" class="form-control" rows="2">{{ reporte.destinatarios }}</textarea>
    </div>
    <div class="mb-3">
        <label class="form-label">Transformación Python (opcional — corre con privilegios del servidor)</label>
        <textarea name="transformacion_codigo" class="form-control" rows="6"
                  placeholder="def transformar(filas):&#10;    return filas">{{ reporte.transformacion_codigo|default:'' }}</textarea>
    </div>
    <button type="submit" class="btn btn-primary">Guardar programación</button>
    <a href="{% url 'reportes-detalle' reporte.id %}" class="btn btn-outline-secondary">Volver</a>
</form>
{% endblock %}
```

- [ ] **Step 5: Escribir los tests de vistas**

Agregar a `reportes/tests.py`:

```python
import json as json_mod


class VistasGestionTest(TestCase):
    def setUp(self):
        from django.urls import reverse
        self.reverse = reverse
        self.admin = User.objects.create_superuser(username='rep_su', password='x')
        self.normal = User.objects.create_user(username='rep_normal', password='x')

    def test_no_superusuario_es_redirigido(self):
        self.client.force_login(self.normal)
        resp = self.client.get(self.reverse('reportes-lista'))
        self.assertEqual(resp.status_code, 302)

    def test_lista_vacia(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self.reverse('reportes-lista'))
        self.assertContains(resp, 'No hay reportes')

    def test_nuevo_crea_reporte_con_query_valido(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.reverse('reportes-nuevo'), {
            'nombre': 'Ventas', 'query_sql': 'SELECT FI_CODIGO FROM SINVENTARIO'})
        self.assertEqual(resp.status_code, 302)
        reporte = ReporteProgramado.objects.get(nombre='Ventas')
        self.assertEqual(reporte.creado_por, self.admin)

    def test_nuevo_rechaza_query_invalido(self):
        self.client.force_login(self.admin)
        resp = self.client.post(self.reverse('reportes-nuevo'), {
            'nombre': 'Malo', 'query_sql': 'DROP TABLE SINVENTARIO'})
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ReporteProgramado.objects.filter(nombre='Malo').exists())

    def test_detalle_muestra_query(self):
        self.client.force_login(self.admin)
        reporte = ReporteProgramado.objects.create(
            nombre='R', query_sql='SELECT 1', frecuencia='diario',
            hora_ejecucion='08:00', creado_por=self.admin)
        resp = self.client.get(self.reverse('reportes-detalle', args=[reporte.id]))
        self.assertContains(resp, 'SELECT 1')


class ProbarQueryViewTest(TestCase):
    def setUp(self):
        from django.urls import reverse
        self.reverse = reverse
        self.admin = User.objects.create_superuser(username='rep_probar', password='x')
        self.client.force_login(self.admin)
        self.reporte = ReporteProgramado.objects.create(
            nombre='R', query_sql='SELECT 1', frecuencia='diario',
            hora_ejecucion='08:00', creado_por=self.admin)

    @patch('reportes.views.ReportesDBISAM')
    def test_probar_actualiza_columnas_detectadas(self, mock_db_cls):
        mock_db_cls.return_value.ejecutar_query.return_value = (
            [{'nombre': 'SKU', 'tipo': 'string'}], [{'SKU': 'A1'}])
        resp = self.client.post(
            self.reverse('reportes-probar', args=[self.reporte.id]),
            {'query_sql': 'SELECT SKU FROM SINVENTARIO'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['ok'])
        self.reporte.refresh_from_db()
        self.assertEqual(self.reporte.columnas_detectadas, [{'nombre': 'SKU', 'tipo': 'string'}])

    def test_probar_con_query_invalido_devuelve_400(self):
        resp = self.client.post(
            self.reverse('reportes-probar', args=[self.reporte.id]),
            {'query_sql': 'DROP TABLE X'})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['ok'])

    @patch('reportes.views.ReportesDBISAM')
    def test_probar_con_fallo_dbisam_devuelve_400(self, mock_db_cls):
        mock_db_cls.return_value.ejecutar_query.side_effect = Exception('odbc down')
        resp = self.client.post(
            self.reverse('reportes-probar', args=[self.reporte.id]),
            {'query_sql': 'SELECT 1'})
        self.assertEqual(resp.status_code, 400)


class DisenarYPreviewTest(TestCase):
    def setUp(self):
        from django.urls import reverse
        self.reverse = reverse
        self.admin = User.objects.create_superuser(username='rep_dis', password='x')
        self.client.force_login(self.admin)
        self.reporte = ReporteProgramado.objects.create(
            nombre='R', query_sql='SELECT SKU FROM SINVENTARIO', frecuencia='diario',
            hora_ejecucion='08:00', creado_por=self.admin,
            columnas_detectadas=[{'nombre': 'SKU', 'tipo': 'string'}])

    def test_disenar_sin_columnas_redirige(self):
        reporte2 = ReporteProgramado.objects.create(
            nombre='Sin columnas', query_sql='SELECT 1', frecuencia='diario',
            hora_ejecucion='08:00', creado_por=self.admin)
        resp = self.client.get(self.reverse('reportes-disenar', args=[reporte2.id]))
        self.assertEqual(resp.status_code, 302)

    def test_disenar_genera_semilla_si_no_existe(self):
        resp = self.client.get(self.reverse('reportes-disenar', args=[self.reporte.id]))
        self.assertEqual(resp.status_code, 200)
        self.reporte.refresh_from_db()
        self.assertIsNotNone(self.reporte.definicion)
        self.assertContains(resp, 'ReportBro(')

    @patch('reportes.views.ReportesDBISAM')
    def test_preview_put_devuelve_key_y_get_descarga_pdf(self, mock_db_cls):
        from .semilla import generar_semilla
        mock_db_cls.return_value.ejecutar_query.return_value = (
            [{'nombre': 'SKU', 'tipo': 'string'}], [{'SKU': 'A1'}])
        definicion = generar_semilla(self.reporte.columnas_detectadas)
        url = self.reverse('reportes-report-run', args=[self.reporte.id])
        resp = self.client.put(url, data=json_mod.dumps({
            'report': definicion, 'outputFormat': 'pdf', 'data': {}, 'isTestData': True}),
            content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        cuerpo = resp.content.decode()
        self.assertTrue(cuerpo.startswith('key:'), cuerpo)
        key = cuerpo[4:]
        resp2 = self.client.get(url, {'key': key, 'outputFormat': 'pdf'})
        self.assertEqual(resp2['Content-Type'], 'application/pdf')
        self.assertTrue(resp2.content.startswith(b'%PDF'))

    def test_guardar_rota_definicion(self):
        from .semilla import generar_semilla
        definicion = generar_semilla(self.reporte.columnas_detectadas)
        self.reporte.definicion = definicion
        self.reporte.save()
        nueva = {**definicion, 'styles': [{'id': 99}]}
        resp = self.client.post(
            self.reverse('reportes-guardar', args=[self.reporte.id]),
            data=json_mod.dumps(nueva), content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.reporte.refresh_from_db()
        self.assertEqual(self.reporte.definicion['styles'], [{'id': 99}])
        self.assertEqual(self.reporte.definicion_anterior, definicion)


class ProgramacionActivarDesactivarTest(TestCase):
    def setUp(self):
        from django.urls import reverse
        self.reverse = reverse
        self.admin = User.objects.create_superuser(username='rep_prog', password='x')
        self.client.force_login(self.admin)
        from .semilla import generar_semilla
        columnas = [{'nombre': 'SKU', 'tipo': 'string'}]
        self.reporte = ReporteProgramado.objects.create(
            nombre='R', query_sql='SELECT SKU FROM SINVENTARIO', frecuencia='diario',
            hora_ejecucion='08:00', creado_por=self.admin,
            columnas_detectadas=columnas, definicion=generar_semilla(columnas))

    def test_programacion_guarda_datos(self):
        resp = self.client.post(
            self.reverse('reportes-programacion', args=[self.reporte.id]), {
                'frecuencia': 'semanal', 'dias_semana': ['0', '2'],
                'hora_ejecucion': '09:15', 'destinatarios': 'x@test.local',
            })
        self.assertEqual(resp.status_code, 302)
        self.reporte.refresh_from_db()
        self.assertEqual(self.reporte.frecuencia, 'semanal')
        self.assertEqual(self.reporte.lista_dias_semana(), [0, 2])
        self.assertEqual(self.reporte.destinatarios, 'x@test.local')

    @patch('reportes.views.registrar_job_reporte')
    @patch('reportes.views.ReportesDBISAM')
    def test_activar_exitoso(self, mock_db_cls, mock_registrar):
        mock_db_cls.return_value.ejecutar_query.return_value = (
            self.reporte.columnas_detectadas, [{'SKU': 'A1'}])
        self.reporte.destinatarios = 'x@test.local'
        self.reporte.save()
        resp = self.client.post(self.reverse('reportes-activar', args=[self.reporte.id]))
        self.assertEqual(resp.status_code, 302)
        self.reporte.refresh_from_db()
        self.assertTrue(self.reporte.activo)
        mock_registrar.assert_called_once()

    def test_activar_sin_destinatarios_falla(self):
        resp = self.client.post(self.reverse('reportes-activar', args=[self.reporte.id]))
        self.reporte.refresh_from_db()
        self.assertFalse(self.reporte.activo)

    @patch('reportes.views.quitar_job_reporte')
    def test_desactivar_quita_job(self, mock_quitar):
        self.reporte.activo = True
        self.reporte.save()
        resp = self.client.post(self.reverse('reportes-desactivar', args=[self.reporte.id]))
        self.assertEqual(resp.status_code, 302)
        self.reporte.refresh_from_db()
        self.assertFalse(self.reporte.activo)
        mock_quitar.assert_called_once_with(self.reporte.id)

    @patch('reportes.views.quitar_job_reporte')
    def test_eliminar_borra_reporte(self, mock_quitar):
        reporte_id = self.reporte.id
        resp = self.client.post(self.reverse('reportes-eliminar', args=[reporte_id]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ReporteProgramado.objects.filter(id=reporte_id).exists())
        mock_quitar.assert_called_once_with(reporte_id)
```

- [ ] **Step 6: Correr toda la suite de `reportes`**

Run: `venv\Scripts\python.exe manage.py test reportes --settings=Programarprecios.test_settings`
Expected: todos los tests PASS.

- [ ] **Step 7: Commit**

```bash
git add reportes/views.py reportes/urls.py templates/reportes-*.html \
        Programarprecios/urls.py reportes/tests.py
git commit -m "feat(reportes): agrega vistas, urls y templates de gestion"
```

---

### Task 9: Wiring final — navegación y verificación de la suite completa

**Files:**
- Modify: `templates/dashboard.html:109-111` (agregar enlace "Reportes Programados" junto a "Formatos de Impresión")

- [ ] **Step 1: Agregar el enlace en el menú**

En `templates/dashboard.html`, dentro del bloque `{% if request.user.is_superuser %}` que hoy solo tiene el enlace a Formatos:

```html
                        {% if request.user.is_superuser %}
                        <li><a href="/formatos/">Formatos de Impresión</a></li>
                        <li><a href="/reportes/">Reportes Programados</a></li>
                        {% endif %}
```

- [ ] **Step 2: Correr la suite completa del proyecto para descartar regresiones**

Run: `venv\Scripts\python.exe manage.py test reportes formatos tasks --settings=Programarprecios.test_settings`
Expected: todos los tests PASS (sin regresiones en `formatos` por el cambio de `_tabla`, ni en `tasks` por el hook de `iniciar_scheduler`).

- [ ] **Step 3: Verificación manual con el servidor de desarrollo**

Run: `venv\Scripts\python.exe manage.py runserver --settings=Programarprecios.settings` (usar el settings real, no `test_settings`, para probar contra DBISAM real si está disponible)

Como superusuario, navegar a `/reportes/`, crear un reporte con un `SELECT` simple contra una tabla real de DBISAM (ej. `SELECT FI_CODIGO, FI_DESCRIPCION FROM SINVENTARIO`), probar el query, diseñar el formato arrastrando la lista `filas` al canvas, guardar, configurar una programación diaria a un horario cercano con un destinatario de prueba, y activar. Confirmar que el job aparece en `DjangoJob` (`/admin/django_apscheduler/djangojob/`) con el `id` `reporte_<id>` esperado. Si hay un proceso `manage.py programador` corriendo, esperar a la hora programada y confirmar la llegada del correo con el PDF adjunto.

- [ ] **Step 4: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat(reportes): agrega enlace de navegacion en el dashboard"
```

---

## Self-Review

**Cobertura del spec:**
- Query SQL libre, solo superusuario → Tasks 2, 8 (validación + gate `_es_superusuario`).
- Fuente de datos solo DBISAM → Task 3 (`ReportesDBISAM`, sin opción de otra fuente).
- Detección automática de columnas ejecutando el query → Task 3 + vista `probar` (Task 8).
- Programación recurrente simple (diario/semanal/mensual + hora) → Tasks 1 (modelo), 6 (scheduler), 8 (vista `programacion`).
- Destinatarios por reporte (lista de emails) → modelo `destinatarios` + `lista_destinatarios()` (Task 1), vista `programacion` (Task 8).
- Transformación Python opcional con namespace restringido + timeout → Task 5, consumida en Task 7.
- Reutilización del scheduler de `tasks` → Task 6.
- Reutilización del patrón ReportBro de `formatos` → Task 4 (`generar_semilla` sobre helpers de `formatos.semillas`), Task 8 (`validar_plantilla`, `ReportePreview` de `formatos`).
- 0 filas → omitir envío → Task 7 (`_enviar_reporte` no se llama).
- Fallo de query/transformación/plantilla → correo de error al dueño → Task 7 (`_notificar_error`).

**Escaneo de placeholders:** sin TBD/TODO; todos los pasos de código llevan implementación completa.

**Consistencia de tipos:** `ReportesDBISAM.ejecutar_query`, `generar_semilla`, `validar_select`, `ejecutar_transformacion`, `registrar_job_reporte`/`quitar_job_reporte`/`cargar_reportes_activos`/`calcular_trigger_kwargs`, y `ejecutar_reporte_programado` se usan con la misma firma en todos los tasks que los consumen (Task 7 y Task 8 importan las mismas funciones de Tasks 2-6 sin renombrarlas).

**Desviación registrada respecto del spec:** `dias_semana` se implementa como `CharField` CSV en vez de `ArrayField` (el spec lo mostraba como `ArrayField` en el bloque de código) porque los tests corren contra SQLite, que no soporta ese tipo de campo Postgres-específico — mismo patrón que ya usa `destinatarios` en el propio spec. No cambia el comportamiento observable (`lista_dias_semana()` sigue devolviendo `list[int]`).
