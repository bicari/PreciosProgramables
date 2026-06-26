from types import SimpleNamespace
from types import SimpleNamespace as NS
from unittest.mock import patch

from django.test import TestCase
from django.db import IntegrityError

from .models import DepositoPermitido
from .admin import sincronizar_depositos_permitidos
from . import views


class DepositoPermitidoModelTest(TestCase):
    def test_creacion_y_str(self):
        dep = DepositoPermitido.objects.create(codigo=5, nombre='Tienda Centro')
        self.assertFalse(dep.activo)  # default
        self.assertEqual(str(dep), '5 - Tienda Centro')

    def test_codigo_unico(self):
        DepositoPermitido.objects.create(codigo=5, nombre='Uno')
        with self.assertRaises(IntegrityError):
            DepositoPermitido.objects.create(codigo=5, nombre='Dos')


class SincronizarDepositosTest(TestCase):
    def _row(self, codigo, nombre):
        return SimpleNamespace(FDP_CODIGO=codigo, FDP_DESCRIPCION=nombre)

    def test_upsert_preserva_activo_y_actualiza_nombre(self):
        DepositoPermitido.objects.create(codigo=5, nombre='Viejo', activo=True)

        creados, actualizados = sincronizar_depositos_permitidos([
            self._row(5, 'Nuevo Nombre'),
            self._row(7, 'Tienda Norte'),
        ])

        self.assertEqual((creados, actualizados), (1, 1))

        dep5 = DepositoPermitido.objects.get(codigo=5)
        self.assertTrue(dep5.activo)            # se preserva
        self.assertEqual(dep5.nombre, 'Nuevo Nombre')  # se actualiza

        dep7 = DepositoPermitido.objects.get(codigo=7)
        self.assertFalse(dep7.activo)           # nuevo nace inactivo


class DepositosParaSelectorTest(TestCase):
    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_usa_activos_y_no_consulta_dbisam(self, mock_db):
        DepositoPermitido.objects.create(codigo=3, nombre='Beta', activo=True)
        DepositoPermitido.objects.create(codigo=2, nombre='Alfa', activo=True)
        DepositoPermitido.objects.create(codigo=9, nombre='Inactivo', activo=False)

        resultado = views._depositos_para_selector()

        self.assertEqual(resultado, [(2, 'Alfa'), (3, 'Beta')])  # ordenado por nombre
        mock_db.assert_not_called()

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_fallback_sin_activos(self, mock_db):
        mock_db.return_value.obtener_depositos.return_value = [
            NS(FDP_CODIGO=4, FDP_DESCRIPCION='Tienda Sur'),
        ]
        resultado = views._depositos_para_selector()
        self.assertEqual(resultado, [(4, 'Tienda Sur')])

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_fallback_con_error_dbisam_devuelve_vacio(self, mock_db):
        mock_db.return_value.obtener_depositos.side_effect = Exception('odbc down')
        self.assertEqual(views._depositos_para_selector(), [])
