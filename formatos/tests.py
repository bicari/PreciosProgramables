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
