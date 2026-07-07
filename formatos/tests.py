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


CLAVES_DESPACHO = {
    'numero_despacho', 'numero_pedido', 'estado', 'condicion', 'deposito',
    'solicitante', 'despachador', 'picker', 'receptor', 'fecha_despacho',
    'fecha_recepcion', 'observaciones', 'items', 'total_items', 'total_despachado',
}
CLAVES_PEDIDO = {
    'numero_pedido', 'estado', 'condicion', 'deposito', 'categoria',
    'solicitante', 'despachador', 'picker', 'fecha_creacion', 'fecha_despacho',
    'fecha_recepcion', 'observaciones', 'items', 'total_items', 'total_solicitado',
    'mostrar_cantidades',
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
        self.assertTrue(datos['mostrar_cantidades'])
        self.assertEqual(datos['items'][0]['cantidad_despachada'], 8)

    def test_datos_pedido_sin_privilegio_anula_cantidades(self):
        from .contratos import datos_pedido
        datos = datos_pedido(self.pedido, self.pedido.items.all(),
                             mostrar_cantidades=False)
        self.assertFalse(datos['mostrar_cantidades'])
        fila = datos['items'][0]
        self.assertIsNone(fila['cantidad_despachada'])
        self.assertIsNone(fila['cantidad_back_order'])
        self.assertIsNone(fila['cantidad_recibida'])
        # lo no sensible se conserva
        self.assertEqual(fila['cantidad_solicitada'], 10)
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


class SemillasTest(TestCase):
    def test_semillas_definen_ambos_tipos(self):
        from .semillas import SEMILLAS
        self.assertEqual(set(SEMILLAS.keys()), {'despacho', 'pedido'})
        claves = {'docElements', 'parameters', 'styles', 'version', 'documentProperties'}
        for definicion in SEMILLAS.values():
            self.assertEqual(claves, set(definicion.keys()) & claves)

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

    def test_semilla_pedido_genera_pdf_sin_cantidades(self):
        """Con mostrar_cantidades=False (cantidades en None) la semilla sigue generando."""
        from reportbro import Report
        from .contratos import datos_pedido
        from .semillas import SEMILLAS
        from PedidosAlmacen.models import Pedido, PedidoItem
        user = User.objects.create_superuser(username='fmt_sem_nc', password='x')
        pedido = Pedido.objects.create(solicitante=user)
        PedidoItem.objects.create(
            pedido=pedido, codigo='A1', descripcion='Taza',
            cantidad_solicitada=5, cantidad_despachada=3)
        datos = datos_pedido(pedido, pedido.items.all(), mostrar_cantidades=False)
        report = Report(SEMILLAS['pedido'], datos)
        self.assertFalse(report.errors)
        pdf = report.generate_pdf()
        self.assertTrue(bytes(pdf).startswith(b'%PDF'))

    def test_obtener_plantilla_siembra_inactiva(self):
        from .models import obtener_plantilla
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
        PlantillaImpresion.objects.create(
            tipo='despacho', definicion=self.definicion_ok, activa=True)
        pdf = generar_pdf('despacho', datos_ejemplo('despacho'))
        self.assertTrue(bytes(pdf).startswith(b'%PDF'))

    def test_plantilla_rota_devuelve_none_sin_lanzar(self):
        from .contratos import datos_ejemplo
        from .generacion import generar_pdf
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
        from .semillas import SEMILLAS
        PlantillaImpresion.objects.create(
            tipo='despacho', definicion=SEMILLAS['despacho'], activa=True)
        with patch('PedidosAlmacen.views.generar_despacho_pdf') as mock_rl:
            resp = self.client.get(self.url)
        mock_rl.assert_not_called()
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF'))

    def test_pedido_pdf_de_tienda_pasa_mostrar_cantidades_false(self):
        """Un usuario de tienda genera el PDF de su pedido con cantidades anuladas."""
        from unittest.mock import patch
        from django.contrib.auth.models import Group
        from django.urls import reverse
        from .contratos import datos_pedido as datos_pedido_real
        from .semillas import SEMILLAS
        grupo, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        tienda = User.objects.create_user(username='fmt_tienda', password='x')
        tienda.groups.add(grupo)
        self.pedido.solicitante = tienda
        self.pedido.save(update_fields=['solicitante'])
        PlantillaImpresion.objects.create(
            tipo='pedido', definicion=SEMILLAS['pedido'], activa=True)
        self.client.force_login(tienda)

        with patch('formatos.contratos.datos_pedido',
                   side_effect=datos_pedido_real) as mock_datos:
            resp = self.client.get(reverse('pedidos-pdf', args=[self.pedido.numero_pedido]))
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertFalse(mock_datos.call_args.kwargs['mostrar_cantidades'])

    def test_pedido_pdf_supervisor_pasa_mostrar_cantidades_true(self):
        from unittest.mock import patch
        from django.urls import reverse
        from .contratos import datos_pedido as datos_pedido_real
        from .semillas import SEMILLAS
        PlantillaImpresion.objects.create(
            tipo='pedido', definicion=SEMILLAS['pedido'], activa=True)

        with patch('formatos.contratos.datos_pedido',
                   side_effect=datos_pedido_real) as mock_datos:
            resp = self.client.get(reverse('pedidos-pdf', args=[self.pedido.numero_pedido]))
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(mock_datos.call_args.kwargs['mostrar_cantidades'])


import json as json_mod  # noqa: E402


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
