# Desactivar el envío de correos de PedidosAlmacen mediante flag

**Fecha**: 2026-07-22
**Estado**: Aprobado por el usuario

## Contexto

La app `PedidosAlmacen` envía correos en tres momentos, todos desde `PedidosAlmacen/notifications.py`:

- `notificar_nuevo_pedido` — a los grupos Pedidos Almacen y Pedidos Supervisor cuando una tienda crea un pedido (llamada en `views.py:347`).
- `notificar_despacho` — al grupo Pedidos Tienda cuando se despacha completo (llamada en `views.py:756`).
- `notificar_despacho_parcial` — al grupo Pedidos Tienda cuando se despacha parcial (llamada en `views.py:758`).

El usuario ya no usará el correo para notificar pedidos. Decisiones acordadas:

1. **Alcance**: se desactivan TODOS los correos de la app (nuevo pedido, despacho y despacho parcial).
2. **Enfoque**: desactivación con flag de configuración, no eliminación de código. El usuario quiere conservar la posibilidad de reactivarlos sin tocar código.
3. La app `tasks` tiene su propio sistema de correos (listas de precios) que sigue funcionando sin cambios.

## Cambios

### 1. `Programarprecios/settings.py` — setting nuevo

Junto a la configuración de email existente:

```python
PEDIDOS_ENVIAR_CORREOS = config('PEDIDOS_ENVIAR_CORREOS', default=False, cast=bool)
```

Con `default=False` los correos quedan apagados sin tocar el `.env`. Para reactivarlos: agregar `PEDIDOS_ENVIAR_CORREOS=True` al `.env` y reiniciar la app.

### 2. `PedidosAlmacen/notifications.py` — guardia en cada función

Al inicio de `notificar_nuevo_pedido`, `notificar_despacho` y `notificar_despacho_parcial` (antes del `try`):

```python
if not settings.PEDIDOS_ENVIAR_CORREOS:
    logger.info(f'Correos de pedidos desactivados; se omite notificación del pedido #{pedido.numero_pedido}')
    return
```

### 3. Sin cambios (explícito)

- `PedidosAlmacen/views.py`: las 3 llamadas quedan como están y pasan a ser no-op.
- `templates/pedido-mail.html`: se conserva (lo usa el camino de reactivación).
- App `tasks` (`send_mail.py`, `scheduler.py`, comando `send_emails`): independiente, intacta.
- `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_USERS` y demás settings de correo: los sigue usando `tasks`.
- Manejo de errores de `notifications.py`: el `try/except` con log se mantiene para cuando el flag esté activo.

## Tests

Clase nueva `NotificacionesDesactivadasTest` en `PedidosAlmacen/tests.py` (Django usa backend de correo en memoria durante tests):

1. Con el flag en su default (False), crear un pedido no envía correo (`len(mail.outbox) == 0`).
2. Con el flag en False, despachar un pedido no envía correo.
3. Con `@override_settings(PEDIDOS_ENVIAR_CORREOS=True)`, despachar sí genera correo — protege el camino de reactivación.

## Verificación

```powershell
.\venv\Scripts\python.exe manage.py test PedidosAlmacen --settings=Programarprecios.test_settings
.\venv\Scripts\python.exe manage.py test --settings=Programarprecios.test_settings
```

Manual: crear y despachar un pedido en dev y comprobar que no llega correo y que el log registra la omisión.
