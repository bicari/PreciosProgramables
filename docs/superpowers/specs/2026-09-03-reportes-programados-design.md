# Reportes programados con query DBISAM y ReportBro

**Fecha:** 2026-09-03
**Estado:** Aprobado para implementación (pendiente de revisión final del usuario)

## Contexto y motivación

Hoy la generación de PDFs con ReportBro (app `formatos`) está limitada a un
conjunto fijo de tipos de documento del sistema (`despacho`, `pedido`), cada
uno con una plantilla única y un contrato de datos hardcodeado
(`datos_ejemplo(tipo)`). El scheduler de la app `tasks` (APScheduler +
`django_apscheduler`) ya corre en background y programa tareas puntuales y un
cron fijo de correo diario.

Surge la necesidad de que un superusuario pueda definir sus **propios**
reportes: una consulta SQL personalizada contra DBISAM (a2Softway), un
formato de salida diseñado con ReportBro, y un envío automático por correo
según una programación recurrente propia (no un tipo fijo del sistema).

## Objetivo

Permitir crear, diseñar y programar reportes ad-hoc que:
1. Extraen datos de DBISAM mediante un SELECT escrito por el usuario.
2. Se presentan con un formato diseñado visualmente en ReportBro.
3. Se envían automáticamente por correo, como PDF adjunto, según una
   frecuencia (diaria/semanal/mensual) y hora configuradas por reporte.

## Alcance

**Incluido:**
- App nueva `reportes`, con su propio modelo, vistas y scheduler jobs.
- Autoría de SQL libre (solo `SELECT`), restringida a superusuarios.
- Fuente de datos: solo DBISAM (no la base Postgres interna).
- Detección automática de columnas ejecutando el query de prueba, para
  alimentar el diseñador ReportBro.
- Programación recurrente simple: diario / semanal (días de la semana) /
  mensual (día del mes) + hora del día. No cron flexible.
- Destinatarios configurables por reporte (lista de emails).
- Transformación Python opcional por reporte, para casos donde el SQL92 de
  DBISAM no alcance (sin CTEs, sin funciones de ventana). Ejecutada en un
  namespace restringido con timeout — mitigación de negligencia, no sandbox
  de aislamiento total.
- Reutilización del scheduler singleton de `tasks` (`get_scheduler()`) y del
  patrón de integración con el ReportBro Designer ya usado en `formatos`.

**Fuera de alcance (explícitamente descartado en esta iteración):**
- Constructor de queries guiado sin SQL crudo.
- Reportes contra la base Postgres interna.
- Cron flexible (expresiones tipo `* * * * *`).
- Destinatarios como usuarios del sistema (se usa lista de emails).
- Aislamiento de la transformación Python en subproceso con límites de
  recursos (se documenta como posible evolución futura si el riesgo lo
  amerita).
- Reportes accesibles a usuarios no-superusuario.

## Arquitectura

Nueva app Django `reportes`, agregada a `INSTALLED_APPS`. No se extiende
`formatos` porque su modelo asume un conjunto cerrado de tipos con una sola
plantilla activa por tipo; un reporte programado es una entidad con muchas
instancias, cada una con su propio query y columnas dinámicas.

Se reutiliza de código existente:
- **`tasks.scheduler.get_scheduler()`**: mismo `BackgroundScheduler`
  singleton con `DjangoJobStore` sobre Postgres. `reportes` registra sus
  propios jobs con id namespaced (`reporte_<id>`), sin tocar
  `tasks/scheduler.py`.
- **Patrón de integración ReportBro de `formatos`**: JS del Designer,
  protocolo PUT/GET de preview (`report_run`), modelo `ReportePreview`,
  función `validar_plantilla`. La generación dinámica de la definición
  inicial (`generar_semilla`) reemplaza a `formatos/semillas.py`, que es
  estática por tipo.

## Modelo de datos

```python
class ReporteProgramado(models.Model):
    FRECUENCIA_CHOICES = [('diario', 'Diario'), ('semanal', 'Semanal'), ('mensual', 'Mensual')]

    nombre = models.CharField(max_length=150)
    query_sql = models.TextField(help_text="SELECT sobre DBISAM. Solo lectura.")
    columnas_detectadas = models.JSONField(null=True, blank=True)
    transformacion_codigo = models.TextField(
        blank=True, null=True,
        help_text="Función Python opcional transformar(filas) -> filas. "
                   "Corre con privilegios del servidor: solo para casos donde "
                   "el SQL de DBISAM no alcance."
    )
    definicion = models.JSONField(null=True, blank=True)
    definicion_anterior = models.JSONField(null=True, blank=True)

    frecuencia = models.CharField(max_length=10, choices=FRECUENCIA_CHOICES)
    dias_semana = ArrayField(models.PositiveSmallIntegerField(), blank=True, default=list)  # solo 'semanal', 0=lunes
    dia_mes = models.PositiveSmallIntegerField(null=True, blank=True)  # solo 'mensual', 1-31
    hora_ejecucion = models.TimeField()

    destinatarios = models.TextField(help_text="Emails separados por coma")
    activo = models.BooleanField(default=False)

    creado_por = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='reportes_creados')
    actualizado_por = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='reportes_actualizados')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)
```

`ReportePreview` se reutiliza (mismo mecanismo de key efímera para el
preview del diseñador).

`activo=True` solo se permite si `validar_plantilla(definicion, datos_reales)`
pasa sin error (mismo criterio que `formatos.activar`).

## Flujo de creación/edición

Todas las vistas bajo `@login_required` + `@_es_superusuario` (mismo patrón
que `formatos`).

1. **`reportes-nuevo`**: nombre + `query_sql`. Se guarda como borrador
   (`activo=False`, sin `definicion`).
2. **`reportes-probar/<id>`** (POST): ejecuta `query_sql` contra DBISAM con
   límite de filas (`fetchmany`, como el resto del código existente). Del
   `cursor.description` se derivan nombre y tipo por columna →
   `columnas_detectadas`. Se muestra una grilla de muestra. Si el query
   falla, se muestra el error de DBISAM tal cual y no se guarda nada.
3. Con `columnas_detectadas` presente se habilita
   **`reportes-disenar/<id>`**: mismo JS del ReportBro Designer que
   `formatos-disenar.html`. La definición inicial, si no existe, se genera
   con `generar_semilla(columnas_detectadas)` — un parámetro tipo `array`
   llamado `filas` con un `child` por columna detectada. Guardado/preview
   reutilizan el protocolo PUT/GET existente; los datos de preview salen de
   correr `query_sql` real (con el mismo límite) en vez de un
   `datos_ejemplo` fijo.
4. **`reportes-programacion/<id>`**: formulario de frecuencia/día(s)/hora/
   destinatarios/`transformacion_codigo` (opcional).
5. **`reportes-activar/<id>`**: corre `validar_plantilla` con datos reales
   de DBISAM (sin límite artificial). Si pasa, `activo=True` y se registra
   el job en el scheduler. Si falla, se informa el error (igual que
   `formatos`) y no se activa.
6. **`reportes-desactivar/<id>`**: `activo=False` y se remueve el job del
   scheduler.

Si se edita `query_sql` y cambian las columnas, hay que volver a "probar" y
potencialmente rediseñar. Si se intenta activar sin volver a validar,
`validar_plantilla` lo frena (columnas ausentes → error de ReportBro).

## Ejecución programada

**Registro de jobs** (`reportes/scheduler.py`):

```python
def registrar_job_reporte(reporte: ReporteProgramado):
    scheduler = get_scheduler()  # de tasks.scheduler
    job_id = f'reporte_{reporte.id}'
    trigger_kwargs = {'hour': reporte.hora_ejecucion.hour, 'minute': reporte.hora_ejecucion.minute}
    if reporte.frecuencia == 'semanal':
        trigger_kwargs['day_of_week'] = ','.join(str(d) for d in reporte.dias_semana)
    elif reporte.frecuencia == 'mensual':
        trigger_kwargs['day'] = reporte.dia_mes
    scheduler.add_job(ejecutar_reporte_programado, trigger='cron', id=job_id,
                       args=[reporte.id], replace_existing=True, jobstore='default',
                       max_instances=1, misfire_grace_time=9600, **trigger_kwargs)
```

Se llama desde `reportes-activar` y desde `reportes-programacion` si se edita
un reporte ya activo. Al desactivar/eliminar: `scheduler.remove_job(job_id)`.

Igual que `cargar_tareas_pendientes()` en `tasks`, `ReportesConfig.ready()`
recorre `ReporteProgramado.objects.filter(activo=True)` al iniciar la app y
re-registra los jobs que falten (cubre reinicios del proceso).

**`ejecutar_reporte_programado(reporte_id)`** (`reportes/tasks.py`):

1. Conectar a DBISAM, correr `reporte.query_sql` completo (sin límite de
   filas, a diferencia del preview). Re-validar contra la lista negra antes
   de ejecutar (defensa en profundidad, ver Seguridad).
2. Si 0 filas → log info, no enviar correo.
3. Si `transformacion_codigo` está definido → ejecutar `transformar(filas)`
   en namespace restringido con timeout; su resultado reemplaza `filas`.
4. `datos = {'filas': filas}` (mismo nombre de parámetro que generó
   `generar_semilla`); generar PDF con
   `Report(reporte.definicion, datos).generate_pdf()`.
5. Enviar correo con `EmailMultiAlternatives` (no `send_mail`, porque este
   sí necesita adjuntar el PDF) a `reporte.destinatarios`, con el PDF
   adjunto.
6. Cualquier excepción en 1–4 (fallo de conexión DBISAM, error de SQL, error
   o timeout de transformación, error de generación de PDF) → capturada,
   logueada, y se envía un correo de error a
   `reporte.actualizado_por or reporte.creado_por` con el detalle. No se
   propaga la excepción (coherente con el resto del código del proyecto,
   que nunca deja que un fallo de una tarea programada tumbe el proceso).

## Seguridad

**SQL** (defensa en profundidad, no un parser completo):
- Al guardar `query_sql`: debe empezar con `SELECT` (ignorando espacios y
  comentarios líderes), no debe contener `;` salvo al final (bloquea
  múltiples sentencias), y se rechaza si contiene, como palabra completa,
  alguna de: `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`,
  `TRUNCATE`, `EXEC`.
- La misma validación se re-aplica en `ejecutar_reporte_programado` antes de
  correr la query programada, no solo al guardar.
- Nivel de confianza: igual al que ya tienen los superusuarios sobre el
  diseñador de plantillas de `formatos` y sobre el propio código del
  repositorio. La lista negra mitiga descuidos, no ataques deliberados de
  alguien con esas credenciales.

**Transformación Python opcional:**
- `exec()` en un namespace restringido: sin `__builtins__` completo, solo
  una lista blanca chica (`len, range, str, int, float, sum, min, max,
  sorted, round, dict, list, ...`); sin `import`, `open`, `eval`, `exec`,
  `__import__`, `os`, `sys`.
- Timeout vía `threading.Timer` (Windows no tiene `signal.alarm`) — si se
  excede, se trata como fallo del reporte (mismo camino que fallo de query:
  correo de error al dueño).
- Cualquier excepción durante la transformación se captura igual que un
  fallo de query.
- La UI advierte explícitamente: "este código corre con privilegios del
  servidor — solo para superusuarios que entiendan el riesgo."
- Es una mitigación básica de negligencia (bugs, loops infinitos, imports
  peligrosos), no un sandbox real contra código malicioso deliberado. Un
  aislamiento más fuerte (subproceso con límites de memoria/CPU) queda como
  posible evolución futura si el riesgo lo amerita.

## Envío de correo

`EmailMultiAlternatives` con el PDF adjunto (`application/pdf`,
`f'{reporte.nombre}_{fecha}.pdf'`), reutilizando `settings.EMAIL_HOST_USER`
como remitente. Cuerpo simple indicando que el reporte fue generado según lo
programado. Correo de error de fallo usa el mismo backend, sin adjunto, con
el detalle de la excepción.

## Testing

Siguiendo el patrón de `formatos/tests.py` y `ubicaciones/tests.py`
(`test_settings.py`/SQLite para lo que no toque DBISAM real):

- Validación de `query_sql` (casos que deben rechazarse: `INSERT`, múltiples
  sentencias, palabras de la lista negra, etc.).
- `generar_semilla(columnas)` produce una definición ReportBro válida.
- Namespace restringido de `transformar()`: bloquea `import os`, `open()`,
  etc.; respeta el timeout.
- Cálculo de `trigger_kwargs` para diario/semanal/mensual.
- `ejecutar_reporte_programado`: rutas de éxito, 0 filas (sin envío), fallo
  de query (correo de error), fallo de transformación (correo de error) —
  mockeando la conexión DBISAM y el envío de correo.
