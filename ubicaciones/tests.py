from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from ubicaciones.models import Cuerpo, Galpon, Nivel, ProductoUbicacion, Rack, Ubicacion

User = get_user_model()


class JerarquiaModeloTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='tester')
        self.galpon = Galpon.objects.create(codigo='1', nombre='Galpón 1', creado_por=self.user)
        self.rack = Rack.objects.create(galpon=self.galpon, codigo='A', max_niveles=6, creado_por=self.user)
        self.cuerpo = Cuerpo.objects.create(rack=self.rack, codigo='01', creado_por=self.user)
        self.ubicacion = Ubicacion.objects.create(cuerpo=self.cuerpo, codigo='01', creado_por=self.user)
        self.nivel = Nivel.objects.create(ubicacion=self.ubicacion, numero=4, creado_por=self.user)

    def test_codigo_completo_reproduce_formato_fisico(self):
        self.assertEqual(self.nivel.codigo_completo, '1A0101.4')

    def test_unicidad_rack_por_galpon(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Rack.objects.create(galpon=self.galpon, codigo='A')

    def test_unicidad_cuerpo_por_rack(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Cuerpo.objects.create(rack=self.rack, codigo='01')

    def test_unicidad_ubicacion_por_cuerpo(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Ubicacion.objects.create(cuerpo=self.cuerpo, codigo='01')

    def test_unicidad_nivel_por_ubicacion(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Nivel.objects.create(ubicacion=self.ubicacion, numero=4)

    def test_producto_ubicacion_requiere_nivel_y_codigo_unicos(self):
        ProductoUbicacion.objects.create(codigo_producto='ABC123', nivel=self.nivel, cantidad=5)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProductoUbicacion.objects.create(codigo_producto='ABC123', nivel=self.nivel, cantidad=1)

    def test_nivel_no_fusionado_por_defecto(self):
        self.assertFalse(self.nivel.esta_fusionado)

    def test_rack_total_cuerpos(self):
        Cuerpo.objects.create(rack=self.rack, codigo='02', creado_por=self.user)
        self.assertEqual(self.rack.total_cuerpos, 2)
