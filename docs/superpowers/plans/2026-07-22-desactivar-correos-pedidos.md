# Desactivar correos de PedidosAlmacen con flag — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Desactivar todo el envío de correos de la app PedidosAlmacen mediante el setting `PEDIDOS_ENVIAR_CORREOS` (default False), conservando el código para poder reactivarlo por `.env`.

**Architecture:** Un setting nuevo leído con decouple en `Programarprecios/settings.py` y una guardia de retorno temprano al inicio de las 3 funciones de `PedidosAlmacen/notifications.py`. Las llamadas en `views.py` quedan intactas y pasan a ser no-op. La app `tasks` (correos de listas de precios) no se toca.

**Tech Stack:** Django 4.x, python-decouple, tests con `django.test.TestCase` (backend de correo locmem automático en tests).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-22-desactivar-correos-pedidos-design.md`.
- El setting se llama exactamente `PEDIDOS_ENVIAR_CORREOS`, con `default=False, cast=bool`.
- NO tocar: `PedidosAlmacen/views.py`, `templates/pedido-mail.html`, la app `tasks`, ni los settings de email existentes (`EMAIL_HOST`, `EMAIL_USERS`, `EMAIL_RECEPCIONES`, …).
- Tests se corren desde la raíz del worktree con: `.\venv\Scripts\python.exe manage.py test ... --settings=Programarprecios.test_settings` (venv en `C:\Proyectos\Python\Precios-KsaHome\venv`; si el worktree no tiene venv propio, usar la ruta absoluta del venv principal).
- Mensajes de commit en español, estilo convencional del repo (`feat(pedidos): ...`), con la línea `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Flag `PEDIDOS_ENVIAR_CORREOS` + guardia en notifications.py

**Files:**
- Modify: `Programarprecios/settings.py` (tras la línea 268, bloque `#CONFIGURACION DEL CORREO`)
- Modify: `PedidosAlmacen/notifications.py` (inicio de las funciones en líneas 39, 61 y 83)
- Test: `PedidosAlmacen/tests.py` (clase nueva al final del archivo)

**Interfaces:**
- Consumes: `PedidosAlmacen.notifications.notificar_nuevo_pedido / notificar_despacho / notificar_despacho_parcial` (firmas existentes, reciben un `Pedido`); `decouple.config` ya importado en settings.
- Produces: `settings.PEDIDOS_ENVIAR_CORREOS: bool` (default False). Ningún cambio de firma en las funciones de notificación.

- [ ] **Step 1: Escribir los tests que fallan**

Al final de `PedidosAlmacen/tests.py` agregar:

```python
class NotificacionesDesactivadasTest(TestCase):
    """Con PEDIDOS_ENVIAR_CORREOS=False (default) la app no envía correos;
    con el flag activo el envío sigue funcionando (camino de reactivación)."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from users.models import User
        from .models import Pedido
        grupo_tienda, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda = User.objects.create_user(
            username='notif_tienda', password='x', email='tienda@test.local')
        self.tienda.groups.add(grupo_tienda)
        self.almacen = User.objects.create_user(username='notif_almacen', password='x')
        self.pedido = Pedido.objects.create(
            solicitante=self.tienda, despachador=self.almacen, estado='DESPACHADO')

    def test_flag_apagado_por_defecto(self):
        from django.conf import settings
        self.assertFalse(settings.PEDIDOS_ENVIAR_CORREOS)

    def test_nuevo_pedido_no_envia_correo(self):
        from django.core import mail
        from .notifications import notificar_nuevo_pedido
        notificar_nuevo_pedido(self.pedido)
        self.assertEqual(len(mail.outbox), 0)

    def test_despacho_no_envia_correo(self):
        from django.core import mail
        from .notifications import notificar_despacho
        notificar_despacho(self.pedido)
        self.assertEqual(len(mail.outbox), 0)

    def test_despacho_parcial_no_envia_correo(self):
        from django.core import mail
        from .notifications import notificar_despacho_parcial
        notificar_despacho_parcial(self.pedido)
        self.assertEqual(len(mail.outbox), 0)

    def test_con_flag_activo_el_despacho_si_envia(self):
        from django.core import mail
        from django.test import override_settings
        from .notifications import notificar_despacho
        with override_settings(PEDIDOS_ENVIAR_CORREOS=True):
            notificar_despacho(self.pedido)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Despachado', mail.outbox[0].subject)
        self.assertIn('tienda@test.local', mail.outbox[0].to)
```

Notas para el implementador:
- `mail.outbox` existe porque Django fuerza el backend locmem en tests; no hay que configurar nada.
- `override_settings` como context manager (no decorador) para que el `assert` del outbox quede fuera pero en el mismo test.
- El destinatario del último test sale de `_emails_por_grupos('Pedidos Tienda')`: por eso `self.tienda` necesita email y pertenecer al grupo.
- El pedido necesita `despachador` porque `notificar_despacho` usa `pedido.despachador.username`.

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `.\venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.NotificacionesDesactivadasTest --settings=Programarprecios.test_settings`
Expected: FAIL — `test_flag_apagado_por_defecto` con `AttributeError: 'Settings' object has no attribute 'PEDIDOS_ENVIAR_CORREOS'` y los tests de "no envía" fallan con `AssertionError: 1 != 0` (el correo sí sale hoy).

- [ ] **Step 3: Agregar el setting**

En `Programarprecios/settings.py`, después de la línea `EMAIL_RECEPCIONES = config('EMAIL_RECEPCIONES').split(',')` (línea 268):

```python
# Interruptor de los correos de PedidosAlmacen (nuevo pedido y despachos).
PEDIDOS_ENVIAR_CORREOS = config('PEDIDOS_ENVIAR_CORREOS', default=False, cast=bool)
```

- [ ] **Step 4: Agregar la guardia en las 3 funciones**

En `PedidosAlmacen/notifications.py`, insertar al inicio del cuerpo de `notificar_nuevo_pedido` (línea 39), `notificar_despacho` (línea 61) y `notificar_despacho_parcial` (línea 83), antes del `try` de cada una:

```python
    if not settings.PEDIDOS_ENVIAR_CORREOS:
        logger.info(f'Correos de pedidos desactivados; se omite notificación del pedido #{pedido.numero_pedido}')
        return
```

(`settings` y `logger` ya están importados/definidos en el módulo; no hace falta ningún import nuevo.)

- [ ] **Step 5: Correr los tests de la clase y verificar que pasan**

Run: `.\venv\Scripts\python.exe manage.py test PedidosAlmacen.tests.NotificacionesDesactivadasTest --settings=Programarprecios.test_settings`
Expected: PASS — `Ran 5 tests ... OK`.

- [ ] **Step 6: Correr la suite completa de la app (regresión)**

Run: `.\venv\Scripts\python.exe manage.py test PedidosAlmacen --settings=Programarprecios.test_settings`
Expected: PASS (≈140 tests, OK). Ojo: los tests existentes de crear/despachar pedidos ahora no envían correo, lo cual no rompe nada porque ninguno asegura `mail.outbox`.

- [ ] **Step 7: Commit**

```powershell
git add Programarprecios/settings.py PedidosAlmacen/notifications.py PedidosAlmacen/tests.py
git commit -m @'
feat(pedidos): flag PEDIDOS_ENVIAR_CORREOS para desactivar correos de la app

Default False: PedidosAlmacen deja de enviar correos de nuevo pedido y
despachos. Reactivable con PEDIDOS_ENVIAR_CORREOS=True en .env.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```
