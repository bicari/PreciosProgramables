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
