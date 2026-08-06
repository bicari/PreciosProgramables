from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from ubicaciones.models import Cuerpo, Galpon, MovimientoUbicacion, Nivel, ProductoUbicacion, Rack, Ubicacion
from ubicaciones.services import UbicacionesService

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


class GalponRackServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='tester2')

    def test_crear_galpon(self):
        galpon = UbicacionesService.crear_galpon('2', 'Galpón 2', 8, 8, self.user)
        self.assertEqual(galpon.codigo, '2')
        self.assertEqual(MovimientoUbicacion.objects.filter(tipo='CREACION_GALPON').count(), 1)

    def test_crear_galpon_codigo_duplicado_falla(self):
        UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.crear_galpon('1', 'Otro', 10, 10, self.user)

    def test_crear_rack(self):
        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        rack = UbicacionesService.crear_rack(
            galpon=galpon, codigo='A', descripcion='', grid_fila=1, grid_columna=1,
            ancho=1, alto=1, max_niveles=6, usuario=self.user,
        )
        self.assertEqual(rack.codigo, 'A')
        self.assertEqual(rack.max_niveles, 6)

    def test_crear_rack_codigo_duplicado_en_mismo_galpon_falla(self):
        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        UbicacionesService.crear_rack(galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.crear_rack(galpon, 'A', '', 2, 1, 1, 1, 6, self.user)

    def test_editar_max_niveles_bloqueado_si_ya_tiene_cuerpos(self):
        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        rack = UbicacionesService.crear_rack(galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        Cuerpo.objects.create(rack=rack, codigo='01', creado_por=self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.editar_rack(rack, '', 1, 1, 1, 1, 4, self.user)

    def test_desactivar_rack_con_cuerpos_activos_falla(self):
        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        rack = UbicacionesService.crear_rack(galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        Cuerpo.objects.create(rack=rack, codigo='01', creado_por=self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.desactivar_rack(rack, self.user)

    def test_desactivar_galpon_con_racks_activos_falla(self):
        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        UbicacionesService.crear_rack(galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.desactivar_galpon(galpon, self.user)
