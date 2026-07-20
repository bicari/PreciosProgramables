# Botón "volver" con memoria de origen y filtro — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** El botón "volver" del detalle de pedido regresa a la última lista visitada (pedidos o despachos) conservando su filtro de estado.

**Architecture:** Las vistas de lista guardan su URL completa (con querystring) en `request.session['pedidos_volver_url']` justo antes de renderizar. La vista de detalle lee esa clave con fallback a `reverse('pedidos-lista')` y la pasa al template, cuyo botón usa `{{ volver_url }}`. Las acciones POST del detalle no se tocan: nunca escriben la clave, por lo que sobreviven N ciclos POST→redirect.

**Tech Stack:** Django 5.2 (sesiones estándar), templates Django, tests con `django.test.TestCase` + test client.

**Spec:** `docs/superpowers/specs/2026-07-06-boton-volver-con-filtro-design.md`

## Global Constraints

- No modificar ningún formulario ni acción POST existente (restricción del spec).
- Clave de sesión exacta: `pedidos_volver_url`.
- El valor de sesión proviene solo de `request.get_full_path()` en vistas propias (nunca de input del cliente).
- Tests: si `manage.py test` falla con "se ha denegado el permiso para crear la base de datos" (el usuario PostgreSQL no tiene CREATEDB), crear un módulo de settings temporal con SQLite (código en Task 1, Step 2) y añadir `--settings=test_settings_sqlite` con `PYTHONPATH` apuntando a su carpeta.

---

### Task 1: Las listas guardan su URL de origen en sesión

**Files:**
- Modify: `PedidosAlmacen/views.py` (función `lista_pedidos`, línea ~173; función `lista_despachos`, línea ~760)
- Test: `PedidosAlmacen/tests.py` (añadir clase al final)

**Interfaces:**
- Consumes: vistas existentes `lista_pedidos` (URL name `pedidos-lista`, path `/pedidos/`) y `lista_despachos` (URL name `despachos-lista`, path `/despachos/`, requiere supervisor).
- Produces: clave de sesión `pedidos_volver_url` (str, ruta + querystring, ej. `/pedidos/?estado=PENDIENTE`) que Task 2 consume.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `PedidosAlmacen/tests.py`:

```python
class VolverUrlSesionListasTest(TestCase):
    """Las vistas de lista guardan su URL completa (con filtro) en sesión."""

    def setUp(self):
        from users.models import User
        self.user = User.objects.create_superuser(username='volver_u', password='x')
        self.client.force_login(self.user)

    def test_lista_pedidos_guarda_url_con_filtro_en_sesion(self):
        from django.urls import reverse
        url = reverse('pedidos-lista') + '?estado=PENDIENTE'
        self.client.get(url)
        self.assertEqual(self.client.session['pedidos_volver_url'], url)

    def test_lista_pedidos_sin_filtro_guarda_url_limpia(self):
        from django.urls import reverse
        url = reverse('pedidos-lista')
        self.client.get(url)
        self.assertEqual(self.client.session['pedidos_volver_url'], url)

    def test_lista_despachos_guarda_url_con_filtro_en_sesion(self):
        from django.urls import reverse
        url = reverse('despachos-lista') + '?estado=ENVIADO'
        self.client.get(url)
        self.assertEqual(self.client.session['pedidos_volver_url'], url)
```

- [ ] **Step 2: Ejecutar los tests y verificar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.VolverUrlSesionListasTest -v 2`

Expected: FAIL con `KeyError: 'pedidos_volver_url'` en los 3 tests.

Si el runner falla antes con "se ha denegado el permiso para crear la base de datos": crear el archivo `%TEMP%\test_settings_sqlite.py` con el contenido de abajo y reintentar con `$env:PYTHONPATH=$env:TEMP` y `--settings=test_settings_sqlite`:

```python
from Programarprecios.settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}
```

- [ ] **Step 3: Implementación mínima**

En `PedidosAlmacen/views.py`, función `lista_pedidos` (~línea 173), añadir la línea marcada justo antes del `return render`:

```python
    request.session['pedidos_volver_url'] = request.get_full_path()
    return render(request, 'pedidos-lista.html', {
        'pedidos': pedidos,
        'estado_filter': estado_filter,
        # (el resto del diccionario existente queda igual: estados, es_tienda,
        #  es_picker, es_supervisor, pickers_disponibles, puede_recibir)
```

En la función `lista_despachos` (~línea 760), igual:

```python
    request.session['pedidos_volver_url'] = request.get_full_path()
    return render(request, 'despachos-lista.html', {
        'despachos': despachos,
        'estado_filter': estado_filter,
        'estados': Despacho.ESTADO_CHOICES,
    })
```

- [ ] **Step 4: Ejecutar los tests y verificar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.VolverUrlSesionListasTest -v 2`

Expected: `OK`, 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/tests.py
git commit -m "feat(pedidos): listas guardan url de origen con filtro en sesion"
```

---

### Task 2: El detalle usa la URL de origen con fallback

**Files:**
- Modify: `PedidosAlmacen/views.py` (imports línea 1; función `detalle_pedido`, contexto del render en líneas ~336-349)
- Modify: `templates/pedidos-detalle.html` (botón `pd-back`, línea ~39)
- Test: `PedidosAlmacen/tests.py` (añadir clase al final)

**Interfaces:**
- Consumes: clave de sesión `pedidos_volver_url` (str) escrita por Task 1.
- Produces: variable de contexto `volver_url` (str) usada por el template `pedidos-detalle.html`.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir al final de `PedidosAlmacen/tests.py`:

```python
class VolverUrlDetallePedidoTest(TestCase):
    """El detalle del pedido usa la URL de origen guardada en sesión, con fallback."""

    def setUp(self):
        from users.models import User
        from django.urls import reverse
        from .models import Pedido
        self.reverse = reverse
        self.user = User.objects.create_superuser(username='volver_det_u', password='x')
        self.client.force_login(self.user)
        self.pedido = Pedido.objects.create(solicitante=self.user)
        self.url = reverse('pedidos-detalle', args=[self.pedido.numero_pedido])

    def test_boton_volver_usa_url_de_sesion(self):
        origen = self.reverse('despachos-lista') + '?estado=ENVIADO'
        session = self.client.session
        session['pedidos_volver_url'] = origen
        session.save()

        resp = self.client.get(self.url)
        self.assertContains(resp, f'href="{origen}"')

    def test_sin_sesion_cae_a_lista_de_pedidos(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'href="{}"'.format(self.reverse('pedidos-lista')))
```

- [ ] **Step 2: Ejecutar los tests y verificar que fallan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.VolverUrlDetallePedidoTest -v 2`

Expected: `test_boton_volver_usa_url_de_sesion` FAIL (el href sigue siendo el de `pedidos-lista`). `test_sin_sesion_cae_a_lista_de_pedidos` puede pasar ya (el template actual apunta fijo a esa URL) — es la red de seguridad de la regresión.

- [ ] **Step 3: Implementación mínima**

En `PedidosAlmacen/views.py`, línea 1, añadir `reverse` a los imports:

```python
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
```

En `detalle_pedido`, añadir al diccionario del `return render` (líneas ~336-349):

```python
    return render(request, 'pedidos-detalle.html', {
        'pedido': pedido,
        'items': items,
        'despachos': despachos,
        # (claves existentes sin cambios: ver_despachado, es_supervisor,
        #  es_despachador, puede_recibir, ver_cantidad_despacho,
        #  puede_imprimir_despacho, es_superuser, es_picker_asignado)
        'vistas_pdf': vistas_pdf,
        'volver_url': request.session.get('pedidos_volver_url') or reverse('pedidos-lista'),
    })
```

En `templates/pedidos-detalle.html`, línea ~39, cambiar:

```html
<a href="{% url 'pedidos-lista' %}" class="pd-back" title="Volver a pedidos">
```

por:

```html
<a href="{{ volver_url }}" class="pd-back" title="Volver a pedidos">
```

- [ ] **Step 4: Ejecutar los tests y verificar que pasan**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.VolverUrlDetallePedidoTest -v 2`

Expected: `OK`, 2 tests PASS.

- [ ] **Step 5: Ejecutar la suite completa de la app**

Run: `venv\Scripts\python.exe manage.py test PedidosAlmacen`

Expected: `OK`, sin regresiones (86 tests: 81 previos + 5 nuevos).

- [ ] **Step 6: Verificación manual del flujo**

1. Iniciar el servidor y abrir `/pedidos/?estado=PENDIENTE`.
2. Entrar a un pedido; ejecutar una acción POST cualquiera (p. ej. confirmar un despacho pendiente si existe).
3. Pulsar el botón volver (flecha del header) → debe regresar a `/pedidos/?estado=PENDIENTE`.
4. Abrir `/despachos/?estado=ENVIADO`, entrar a un pedido desde ahí, volver → debe regresar a `/despachos/?estado=ENVIADO`.

- [ ] **Step 7: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/tests.py templates/pedidos-detalle.html
git commit -m "feat(pedidos): boton volver regresa al origen conservando el filtro"
```
