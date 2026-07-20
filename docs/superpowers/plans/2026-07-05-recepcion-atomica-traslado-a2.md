# Recepción Atómica de Despachos con Traslado a2 — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar los traslados huérfanos en la recepción de despachos: si el traslado tránsito→destino falla en a2 (o el pedido no tiene depósito destino configurado), no debe persistir ningún cambio en Postgres, y el usuario debe ver un único mensaje de error claro (nunca un mensaje de éxito contradictorio).

**Architecture:** Envolver las escrituras de Postgres de `recibir_despacho` (actualización de ítems, guardado de `Despacho`/`Pedido`) y la llamada a `PedidosDBISAM.insertar_traslado_recepcion` dentro de un único `transaction.atomic()`, con la llamada a a2 como última operación del bloque. Cualquier excepción dentro del bloque (fallo de a2, o depósito destino no configurado) revierte todas las escrituras de Postgres de ese intento.

**Tech Stack:** Django (views, `django.db.transaction`), `unittest.mock.patch` para simular `PedidosDBISAM` en tests, `django.test.TestCase`.

## Global Constraints

- Spec de referencia: `docs/superpowers/specs/2026-07-05-recepcion-atomica-traslado-a2-design.md`.
- No se agrega ningún campo nuevo al modelo ni migración.
- No se modifica el flujo de despacho (`confirmar_despacho` / `reintentar_traslado_despacho`).
- Seguir el patrón `transaction.atomic()` ya usado en `PedidosAlmacen/views.py` (función `anular_despacho`, línea 778) — no se requieren imports nuevos (`transaction` ya está importado en `PedidosAlmacen/views.py:6`).
- No se corrigen traslados huérfanos históricos ni el problema de fotos de incidencia huérfanas en disco tras un rollback (fuera de alcance, ver spec).

---

### Task 1: Recepción atómica en `recibir_despacho` con bloqueo ante fallo de a2

**Files:**
- Modify: `PedidosAlmacen/views.py:935-1059` (función `recibir_despacho`)
- Test: `PedidosAlmacen/tests.py` (nueva clase al final del archivo, después de la línea 988)

**Interfaces:**
- Consumes: `PedidosDBISAM.insertar_traslado_recepcion(numero_pedido, deposito_destino, items, responsable, proposito)` (ya existe en `PedidosAlmacen/dbisam.py:410`, sin cambios de firma).
- Produces: ningún símbolo nuevo consumido por otras tareas — este plan tiene una sola tarea.

- [ ] **Step 1: Escribir los tests que describen el comportamiento nuevo (deben fallar contra el código actual)**

Agregar al final de `PedidosAlmacen/tests.py` (después de la línea 988):

```python
class RecibirDespachoTransaccionAtomicaTest(TestCase):
    """recibir_despacho debe ser todo-o-nada: si el traslado en a2 falla o el
    pedido no tiene depósito destino configurado, no debe persistir ningún
    cambio en Postgres, y debe mostrarse un único mensaje de error (nunca
    también un mensaje de éxito)."""

    def setUp(self):
        from users.models import User
        from django.urls import reverse
        from .models import Pedido, PedidoItem, Despacho, DespachoItem
        self.reverse = reverse
        self.user = User.objects.create_superuser(username='recep_atom_u', password='x')
        self.client.force_login(self.user)
        self.pedido = Pedido.objects.create(
            solicitante=self.user, estado='DESPACHADO', deposito_codigo=2,
            condicion='URGENTE',
        )
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='Producto Uno',
            cantidad_solicitada=5, cantidad_despachada=5, estado='DESPACHADO',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='ENVIADO')
        self.di = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item, cantidad_despachada=5,
        )
        self.url = reverse(
            'pedidos-recibir-despacho',
            args=[self.pedido.numero_pedido, self.despacho.numero_despacho],
        )

    def _post(self):
        return self.client.post(self.url, {
            f'recibido_{self.di.id}': '5',
            f'observacion_{self.di.id}': '',
            f'tipo_incidencia_{self.di.id}': '',
            'productos_extra': '[]',
        })

    def _mensajes(self, resp):
        from django.contrib.messages import get_messages
        return [str(m) for m in get_messages(resp.wsgi_request)]

    def test_recepcion_exitosa_actualiza_todo_y_solo_muestra_exito(self):
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.insertar_traslado_recepcion.return_value = None
            resp = self._post()

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, self.reverse('pedidos-detalle', args=[self.pedido.numero_pedido]))

        self.despacho.refresh_from_db()
        self.pedido.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'RECIBIDO')
        self.assertEqual(self.pedido.estado, 'RECIBIDO')
        self.assertEqual(self.item.estado, 'RECIBIDO')

        mock_db.return_value.insertar_traslado_recepcion.assert_called_once_with(
            self.pedido.numero_pedido, 2, [{'codigo': 'SKU1', 'cantidad': 5}],
            responsable=self.user.username, proposito='URGENTE',
        )

        mensajes = self._mensajes(resp)
        self.assertEqual(len(mensajes), 1)
        self.assertIn('registrada correctamente', mensajes[0])

    def test_fallo_a2_no_persiste_nada_y_muestra_un_unico_error(self):
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.insertar_traslado_recepcion.side_effect = Exception('odbc down')
            resp = self._post()

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp.url,
            self.reverse('pedidos-recibir-despacho', args=[self.pedido.numero_pedido, self.despacho.numero_despacho]),
        )

        self.despacho.refresh_from_db()
        self.pedido.refresh_from_db()
        self.item.refresh_from_db()
        self.di.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'ENVIADO')
        self.assertEqual(self.pedido.estado, 'DESPACHADO')
        self.assertEqual(self.item.estado, 'DESPACHADO')
        self.assertEqual(self.di.cantidad_recibida, 0)

        mensajes = self._mensajes(resp)
        self.assertEqual(len(mensajes), 1)
        self.assertIn('No se pudo registrar la recepción', mensajes[0])
        self.assertFalse(any('registrada correctamente' in m for m in mensajes))

    def test_sin_deposito_codigo_bloquea_y_no_llama_a_a2(self):
        self.pedido.deposito_codigo = None
        self.pedido.save()

        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            resp = self._post()
            mock_db.assert_not_called()

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp.url,
            self.reverse('pedidos-recibir-despacho', args=[self.pedido.numero_pedido, self.despacho.numero_despacho]),
        )

        self.despacho.refresh_from_db()
        self.pedido.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'ENVIADO')
        self.assertEqual(self.pedido.estado, 'DESPACHADO')
        self.assertEqual(self.item.estado, 'DESPACHADO')

        mensajes = self._mensajes(resp)
        self.assertEqual(len(mensajes), 1)
        self.assertIn('no tiene depósito destino configurado', mensajes[0])
```

- [ ] **Step 2: Ejecutar los tests nuevos y confirmar que fallan**

Run: `python manage.py test PedidosAlmacen.tests.RecibirDespachoTransaccionAtomicaTest -v 2`

Expected: **FAIL** en `test_fallo_a2_no_persiste_nada_y_muestra_un_unico_error` (hoy `despacho.estado` queda en `'RECIBIDO'` porque Postgres se guarda antes de intentar el traslado, y aparecen 2 mensajes en vez de 1) y en `test_sin_deposito_codigo_bloquea_y_no_llama_a_a2` (hoy el traslado se omite en silencio sin ningún mensaje de error). `test_recepcion_exitosa_actualiza_todo_y_solo_muestra_exito` puede pasar ya (comportamiento sin cambios en el camino feliz) — si pasa, es esperado, no es un error del test.

- [ ] **Step 3: Reemplazar el cuerpo de `recibir_despacho` (líneas 935-1059) con la versión atómica**

Reemplazar exactamente el bloque de `PedidosAlmacen/views.py` que va desde el comentario `# ── Procesar items normales y con producto erróneo ───` (línea 935) hasta `return redirect('pedidos-detalle', pk=pk)` (línea 1059) por:

```python
        # ── Procesar items normales y con producto erróneo ───────────────────
        try:
            with transaction.atomic():
                for di in despacho_items:
                    try:
                        cantidad_recibida = int(request.POST.get(f'recibido_{di.id}', '0'))
                    except ValueError:
                        cantidad_recibida = 0
                    observacion = request.POST.get(f'observacion_{di.id}', '')
                    tipo_inc = request.POST.get(f'tipo_incidencia_{di.id}', '')

                    di.cantidad_recibida = cantidad_recibida
                    di.observacion = observacion

                    if tipo_inc == 'PRODUCTO_ERRONEO':
                        di.tipo_incidencia = 'PRODUCTO_ERRONEO'
                        di.codigo_real = request.POST.get(f'codigo_real_{di.id}', '').strip()
                        di.descripcion_real = request.POST.get(f'descripcion_real_{di.id}', '').strip()
                        di.autorizado_por = auth_user
                        di.foto_incidencia = request.FILES.get(f'foto_{di.id}')
                        hay_incidencia = True
                    elif cantidad_recibida < di.cantidad_despachada:
                        di.tipo_incidencia = 'CANTIDAD_MENOR'
                        hay_incidencia = True
                    elif cantidad_recibida > di.cantidad_despachada:
                        di.tipo_incidencia = 'CANTIDAD_MAYOR'
                        hay_incidencia = True
                    di.save()

                    item = di.pedido_item
                    item.cantidad_recibida = (item.cantidad_recibida or 0) + cantidad_recibida
                    item.observacion = observacion

                    if tipo_inc == 'PRODUCTO_ERRONEO':
                        item.estado = 'INCIDENCIA'
                    elif item.cantidad_recibida >= item.cantidad_solicitada:
                        item.estado = 'RECIBIDO'
                    elif item.cantidad_back_order > 0:
                        item.estado = 'BACK_ORDER'
                    else:
                        tiene_otros_enviados = DespachoItem.objects.filter(
                            pedido_item=item, despacho__estado='ENVIADO',
                        ).exclude(despacho=despacho).exists()
                        if tiene_otros_enviados:
                            item.estado = 'DESPACHADO'
                        elif item.cantidad_recibida < item.cantidad_despachada:
                            item.estado = 'INCIDENCIA'
                        else:
                            item.estado = 'RECIBIDO'
                    item.save()

                    if cantidad_recibida > 0:
                        codigo_traslado = di.codigo_real if tipo_inc == 'PRODUCTO_ERRONEO' and di.codigo_real else item.codigo
                        items_traslado.append({'codigo': codigo_traslado, 'cantidad': cantidad_recibida})

                # ── Procesar SKUs no contemplados ────────────────────────────────────
                if tiene_sku_extra:
                    extras = productos_extra_parsed

                    for extra in extras:
                        codigo = str(extra.get('codigo', '')).strip()
                        descripcion = str(extra.get('descripcion', '')).strip()
                        try:
                            cantidad = int(extra.get('cantidad', 0))
                        except (ValueError, TypeError):
                            cantidad = 0

                        if not codigo or cantidad <= 0:
                            continue

                        # Crear PedidoItem ficticio para trazabilidad
                        nuevo_item = PedidoItem.objects.create(
                            pedido=pedido,
                            codigo=codigo,
                            descripcion=descripcion,
                            cantidad_solicitada=0,
                            cantidad_despachada=cantidad,
                            cantidad_recibida=cantidad,
                            estado='INCIDENCIA',
                            observacion='SKU no contemplado en el pedido original',
                        )
                        di_extra = DespachoItem(
                            despacho=despacho,
                            pedido_item=nuevo_item,
                            cantidad_despachada=cantidad,
                            cantidad_recibida=cantidad,
                            tipo_incidencia='SKU_NO_CONTEMPLADO',
                            autorizado_por=auth_user,
                        )
                        if foto_extras:
                            di_extra.foto_incidencia = foto_extras
                        di_extra.save()
                        items_traslado.append({'codigo': codigo, 'cantidad': cantidad})
                        hay_incidencia = True

                despacho.receptor = request.user
                despacho.fecha_recepcion = datetime.now()
                despacho.estado = 'PARCIAL' if hay_incidencia else 'RECIBIDO'
                despacho.save()

                estados_items = list(pedido.items.values_list('estado', flat=True))
                if all(e == 'RECIBIDO' for e in estados_items):
                    pedido.estado = 'RECIBIDO'
                    pedido.fecha_recepcion = datetime.now()
                elif any(e in ('PENDIENTE', 'BACK_ORDER', 'PARCIAL', 'DESPACHADO') for e in estados_items):
                    pedido.estado = 'PARCIAL'
                pedido.save()

                if items_traslado:
                    if not pedido.deposito_codigo:
                        raise ValueError(
                            f'El pedido #{pedido.numero_pedido} no tiene depósito destino configurado '
                            f'en a2 — no se puede registrar el traslado de recepción. '
                            f'Contacta a un supervisor para configurarlo.'
                        )
                    dbisam = PedidosDBISAM()
                    dbisam.insertar_traslado_recepcion(
                        pedido.numero_pedido,
                        pedido.deposito_codigo,
                        items_traslado,
                        responsable=request.user.username,
                        proposito=pedido.condicion,
                    )
        except ValueError as e:
            logger.error(f'Recepción del despacho #{despacho_id} bloqueada: {e}')
            messages.error(request, str(e))
            return redirect('pedidos-recibir-despacho', pk=pk, despacho_id=despacho_id)
        except Exception as e:
            logger.error(f'Error al insertar traslado DBISAM para despacho #{despacho_id}: {e}')
            messages.error(
                request,
                'No se pudo registrar la recepción: ocurrió un error al conectar con a2. '
                'No se guardó ningún cambio — intenta nuevamente en unos minutos.'
            )
            return redirect('pedidos-recibir-despacho', pk=pk, despacho_id=despacho_id)

        messages.success(request, f'Recepción del Despacho #{despacho_id} registrada correctamente')
        return redirect('pedidos-detalle', pk=pk)
```

No se requieren imports nuevos: `transaction` ya está importado en `PedidosAlmacen/views.py:6`, y `PedidosDBISAM`, `Pedido`, `PedidoItem`, `Despacho`, `DespachoItem` ya están importados (líneas 11, 13).

- [ ] **Step 4: Ejecutar los tests nuevos y confirmar que pasan**

Run: `python manage.py test PedidosAlmacen.tests.RecibirDespachoTransaccionAtomicaTest -v 2`

Expected: **PASS** — los 3 tests (`test_recepcion_exitosa_actualiza_todo_y_solo_muestra_exito`, `test_fallo_a2_no_persiste_nada_y_muestra_un_unico_error`, `test_sin_deposito_codigo_bloquea_y_no_llama_a_a2`) pasan.

- [ ] **Step 5: Ejecutar la suite completa de `PedidosAlmacen` para descartar regresiones**

Run: `python manage.py test PedidosAlmacen -v 2`

Expected: **PASS** — todos los tests existentes (incluyendo los de `recibir_despacho` indirectos, permisos, `ValidarTrasladosRecepcionCommandTest`, etc.) siguen pasando sin cambios.

- [ ] **Step 6: Commit**

```bash
git add PedidosAlmacen/views.py PedidosAlmacen/tests.py
git commit -m "$(cat <<'EOF'
fix(pedidos): recepcion de despachos atomica con traslado a2

Si el traslado tránsito→destino falla en a2, o el pedido no tiene depósito
destino configurado, ya no se persiste ningún cambio en Postgres (antes
quedaba RECIBIDO/PARCIAL sin su traslado, generando huérfanos). Se elimina
también el mensaje de éxito que se mostraba junto al de error.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

## Fuera de alcance (recordatorio del spec)

- Flujo de despacho (`confirmar_despacho` / `reintentar_traslado_despacho`): sin cambios.
- Traslados huérfanos históricos ya detectados por `validar_traslados_recepcion`: se resuelven manualmente en a2, no en este plan.
- Fotos de incidencia huérfanas en disco tras un rollback: limitación conocida de Django, no se corrige aquí.
