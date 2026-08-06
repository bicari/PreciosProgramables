from unittest.mock import patch

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


class CuerpoUbicacionServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='tester3')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)

    def test_crear_cuerpo_autogenera_2_ubicaciones_con_numeracion_global(self):
        cuerpo1 = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.assertEqual(cuerpo1.codigo, '01')
        ubics1 = list(cuerpo1.ubicaciones.order_by('codigo'))
        self.assertEqual([u.codigo for u in ubics1], ['01', '02'])

        cuerpo2 = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.assertEqual(cuerpo2.codigo, '02')
        ubics2 = list(cuerpo2.ubicaciones.order_by('codigo'))
        self.assertEqual([u.codigo for u in ubics2], ['03', '04'])

    def test_crear_cuerpo_autogenera_niveles_segun_max_niveles_del_rack(self):
        cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        for ubicacion in cuerpo.ubicaciones.all():
            self.assertEqual(list(ubicacion.niveles.order_by('numero').values_list('numero', flat=True)), [1, 2, 3, 4, 5, 6])

    def test_crear_cuerpo_codigo_completo_del_nivel_reproduce_formato_fisico(self):
        cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        ubicacion = cuerpo.ubicaciones.order_by('codigo').first()
        nivel4 = ubicacion.niveles.get(numero=4)
        self.assertEqual(nivel4.codigo_completo, '1A0101.4')

    def test_crear_cuerpo_registra_un_solo_movimiento(self):
        UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.assertEqual(MovimientoUbicacion.objects.filter(tipo='CREACION_CUERPO').count(), 1)

    def test_desactivar_cuerpo_con_ubicaciones_activas_falla(self):
        cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.desactivar_cuerpo(cuerpo, self.user)

    def test_desactivar_ubicacion_con_niveles_activos_falla(self):
        cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        ubicacion = cuerpo.ubicaciones.first()
        with self.assertRaises(ValidationError):
            UbicacionesService.desactivar_ubicacion(ubicacion, self.user)


class NivelServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='tester4')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.ubicacion = self.cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel = self.ubicacion.niveles.get(numero=1)

    def test_editar_nivel_cambia_tipo_y_descripcion(self):
        UbicacionesService.editar_nivel(self.nivel, Nivel.ALMACENAJE, 'Nota', self.user)
        self.nivel.refresh_from_db()
        self.assertEqual(self.nivel.tipo, Nivel.ALMACENAJE)
        self.assertEqual(self.nivel.descripcion, 'Nota')

    def test_editar_nivel_fusionado_falla(self):
        otro_nivel = self.ubicacion.niveles.get(numero=2)
        self.nivel.fusionado_en = otro_nivel
        self.nivel.save(update_fields=['fusionado_en'])
        with self.assertRaises(ValidationError):
            UbicacionesService.editar_nivel(self.nivel, Nivel.ALMACENAJE, '', self.user)

    def test_desactivar_nivel_con_productos_falla(self):
        ProductoUbicacion.objects.create(codigo_producto='ABC', nivel=self.nivel, cantidad=1)
        with self.assertRaises(ValidationError):
            UbicacionesService.desactivar_nivel(self.nivel, self.user)

    def test_desactivar_nivel_sin_productos_ok(self):
        UbicacionesService.desactivar_nivel(self.nivel, self.user)
        self.nivel.refresh_from_db()
        self.assertFalse(self.nivel.activo)


class AsignacionServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='tester5')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.ubicacion = self.cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel = self.ubicacion.niveles.get(numero=1)
        self.otro_nivel = self.ubicacion.niveles.get(numero=2)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_asignar_producto_dentro_de_existencia_ok(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 100
        pu = UbicacionesService.asignar_producto('ABC', self.nivel, 40, None, self.user)
        self.assertEqual(pu.cantidad, 40)
        mock_db.return_value.consultar_stock.assert_called_once_with('ABC', deposito=1)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_asignar_producto_excede_existencia_falla(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 30
        with self.assertRaises(ValidationError):
            UbicacionesService.asignar_producto('ABC', self.nivel, 40, None, self.user)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_asignar_producto_suma_asignaciones_existentes(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        UbicacionesService.asignar_producto('ABC', self.nivel, 30, None, self.user)
        with self.assertRaises(ValidationError):
            UbicacionesService.asignar_producto('ABC', self.otro_nivel, 25, None, self.user)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_asignar_producto_en_nivel_fusionado_falla(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 100
        self.nivel.fusionado_en = self.otro_nivel
        self.nivel.save(update_fields=['fusionado_en'])
        with self.assertRaises(ValidationError):
            UbicacionesService.asignar_producto('ABC', self.nivel, 10, None, self.user)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_editar_cantidad_excluye_su_propia_fila_de_la_suma(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        pu = UbicacionesService.asignar_producto('ABC', self.nivel, 30, None, self.user)
        UbicacionesService.editar_cantidad(pu, 50, None, self.user)
        pu.refresh_from_db()
        self.assertEqual(pu.cantidad, 50)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_quitar_producto(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        pu = UbicacionesService.asignar_producto('ABC', self.nivel, 30, None, self.user)
        UbicacionesService.quitar_producto(pu.pk, self.user)
        self.assertFalse(ProductoUbicacion.objects.filter(pk=pu.pk).exists())

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_trasladar_producto_mueve_la_asignacion(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        UbicacionesService.asignar_producto('ABC', self.nivel, 30, None, self.user)
        UbicacionesService.trasladar_producto('ABC', self.nivel, self.otro_nivel, self.user)
        self.assertFalse(ProductoUbicacion.objects.filter(nivel=self.nivel, codigo_producto='ABC').exists())
        self.assertTrue(ProductoUbicacion.objects.filter(nivel=self.otro_nivel, codigo_producto='ABC').exists())

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_trasladar_producto_a_nivel_fusionado_falla(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        UbicacionesService.asignar_producto('ABC', self.nivel, 30, None, self.user)
        self.otro_nivel.fusionado_en = self.nivel
        self.otro_nivel.save(update_fields=['fusionado_en'])
        with self.assertRaises(ValidationError):
            UbicacionesService.trasladar_producto('ABC', self.nivel, self.otro_nivel, self.user)


class FusionServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='tester6')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack_a = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.rack_b = UbicacionesService.crear_rack(self.galpon, 'B', '', 2, 1, 1, 1, 6, self.user)
        cuerpo = UbicacionesService.crear_cuerpo(self.rack_a, '', self.user)
        ubicacion = cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel1 = ubicacion.niveles.get(numero=1)
        self.nivel2 = ubicacion.niveles.get(numero=2)
        self.nivel3 = ubicacion.niveles.get(numero=3)
        cuerpo_b = UbicacionesService.crear_cuerpo(self.rack_b, '', self.user)
        self.nivel_otro_rack = cuerpo_b.ubicaciones.order_by('codigo').first().niveles.get(numero=1)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_fusionar_niveles_consolida_cantidades_en_el_maestro(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 100
        UbicacionesService.asignar_producto('ABC', self.nivel1, 10, None, self.user)
        UbicacionesService.asignar_producto('ABC', self.nivel2, 15, None, self.user)

        transferidos = UbicacionesService.fusionar_niveles(
            [self.nivel1, self.nivel2], self.nivel1, self.user,
        )

        self.assertEqual(transferidos, 1)
        self.nivel2.refresh_from_db()
        self.assertEqual(self.nivel2.fusionado_en_id, self.nivel1.pk)
        pu = ProductoUbicacion.objects.get(nivel=self.nivel1, codigo_producto='ABC')
        self.assertEqual(pu.cantidad, 25)
        self.assertFalse(ProductoUbicacion.objects.filter(nivel=self.nivel2).exists())

    def test_fusionar_niveles_de_distinto_rack_falla(self):
        with self.assertRaises(ValidationError):
            UbicacionesService.fusionar_niveles(
                [self.nivel1, self.nivel_otro_rack], self.nivel1, self.user,
            )

    def test_fusionar_nivel_ya_fusionado_falla(self):
        UbicacionesService.fusionar_niveles([self.nivel1, self.nivel2], self.nivel1, self.user)
        self.nivel2.refresh_from_db()
        with self.assertRaises(ValidationError):
            UbicacionesService.fusionar_niveles([self.nivel1, self.nivel2, self.nivel3], self.nivel1, self.user)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_desfusionar_ultimo_miembro_con_stock_en_maestro_ok(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 100
        UbicacionesService.asignar_producto('ABC', self.nivel1, 10, None, self.user)
        UbicacionesService.fusionar_niveles([self.nivel1, self.nivel2], self.nivel1, self.user)
        self.nivel2.refresh_from_db()

        UbicacionesService.desfusionar_nivel(self.nivel2, self.user)

        self.nivel2.refresh_from_db()
        self.assertIsNone(self.nivel2.fusionado_en_id)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_desfusionar_con_stock_y_otros_miembros_fusionados_falla(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 100
        UbicacionesService.asignar_producto('ABC', self.nivel1, 10, None, self.user)
        UbicacionesService.fusionar_niveles([self.nivel1, self.nivel2, self.nivel3], self.nivel1, self.user)
        self.nivel2.refresh_from_db()

        with self.assertRaises(ValidationError):
            UbicacionesService.desfusionar_nivel(self.nivel2, self.user)

    def test_desfusionar_nivel_no_fusionado_falla(self):
        with self.assertRaises(ValidationError):
            UbicacionesService.desfusionar_nivel(self.nivel1, self.user)


class AsignacionTrasladoFusionTemplatesSmokeTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from django.test import Client

        self.user = User.objects.create_user(username='webuser6', password='x')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client = Client()
        self.client.login(username='webuser6', password='x')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.nivel = self.cuerpo.ubicaciones.order_by('codigo').first().niveles.get(numero=1)

    def test_paginas_devuelven_200(self):
        urls = [
            f'/ubicaciones/niveles/{self.nivel.pk}/asignar/',
            '/ubicaciones/trasladar/',
            '/ubicaciones/fusionar/',
            '/ubicaciones/movimientos/',
            '/ubicaciones/buscar-nivel/',
            '/ubicaciones/buscar-producto/',
        ]
        for url in urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"{url} devolvió {resp.status_code}")

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_producto_detalle_devuelve_200(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        UbicacionesService.asignar_producto('ABC', self.nivel, 10, None, self.user)
        with patch('ubicaciones.views.PedidosDBISAM') as mock_views_db:
            mock_views_db.return_value.buscar_producto.return_value = None
            resp = self.client.get('/ubicaciones/productos/ABC/')
        self.assertEqual(resp.status_code, 200)


class ApiUbicacionesTest(TestCase):
    def setUp(self):
        from rest_framework.test import APIClient

        self.user = User.objects.create_superuser(username='api_tester', password='x')
        self.api = APIClient()
        self.api.force_authenticate(user=self.user)
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.ubicacion = self.cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel = self.ubicacion.niveles.get(numero=1)

    def test_listar_galpones(self):
        resp = self.api.get('/api/galpones/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)

    def test_detalle_rack_incluye_cuerpos(self):
        resp = self.api.get(f'/api/racks/{self.rack.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['cuerpos']), 1)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_asignar_producto_via_api(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        resp = self.api.post(
            f'/api/niveles/{self.nivel.pk}/asignar/',
            data={'codigo_producto': 'ABC', 'cantidad': 10}, format='json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(ProductoUbicacion.objects.filter(codigo_producto='ABC', nivel=self.nivel).exists())

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_asignar_producto_excede_existencia_via_api(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 5
        resp = self.api.post(
            f'/api/niveles/{self.nivel.pk}/asignar/',
            data={'codigo_producto': 'ABC', 'cantidad': 10}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_fusionar_via_api(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        nivel2 = self.ubicacion.niveles.get(numero=2)
        resp = self.api.post(
            '/api/niveles/fusionar/',
            data={'niveles': [self.nivel.pk, nivel2.pk], 'maestro': self.nivel.pk}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        nivel2.refresh_from_db()
        self.assertEqual(nivel2.fusionado_en_id, self.nivel.pk)


class GalponRackViewsTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from django.test import Client

        self.user = User.objects.create_user(username='webuser', password='x')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client = Client()
        self.client.login(username='webuser', password='x')

    def test_crear_galpon_via_web_redirige(self):
        resp = self.client.post('/ubicaciones/galpones/crear/', {
            'codigo': '1', 'nombre': 'Galpón 1', 'grid_filas': 10, 'grid_columnas': 10,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Galpon.objects.filter(codigo='1').exists())

    def test_lista_galpones_requiere_grupo(self):
        from django.test import Client
        User.objects.create_user(username='sin_grupo', password='x')
        client = Client()
        client.login(username='sin_grupo', password='x')
        resp = client.get('/ubicaciones/galpones/')
        self.assertEqual(resp.status_code, 302)

    def test_crear_rack_via_web_redirige(self):
        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        resp = self.client.post(f'/ubicaciones/galpones/{galpon.pk}/racks/crear/', {
            'codigo': 'A', 'descripcion': '', 'grid_fila': 1, 'grid_columna': 1,
            'ancho': 1, 'alto': 1, 'max_niveles': 6,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Rack.objects.filter(galpon=galpon, codigo='A').exists())

    def test_desactivar_rack_con_cuerpos_redirige_con_error(self):
        galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        rack = UbicacionesService.crear_rack(galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        UbicacionesService.crear_cuerpo(rack, '', self.user)
        resp = self.client.post(f'/ubicaciones/racks/{rack.pk}/desactivar/')
        self.assertEqual(resp.status_code, 302)
        rack.refresh_from_db()
        self.assertTrue(rack.activo)


class RackFormTest(TestCase):
    def test_max_niveles_disabled_cuando_bloqueado(self):
        from ubicaciones.forms import RackForm
        form = RackForm(bloquear_max_niveles=True)
        self.assertTrue(form.fields['max_niveles'].disabled)

    def test_max_niveles_habilitado_por_defecto(self):
        from ubicaciones.forms import RackForm
        form = RackForm()
        self.assertFalse(form.fields['max_niveles'].disabled)


class CuerpoUbicacionNivelViewsTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from django.test import Client

        self.user = User.objects.create_user(username='webuser2', password='x')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client = Client()
        self.client.login(username='webuser2', password='x')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)

    def test_crear_cuerpo_via_web_redirige(self):
        resp = self.client.post(f'/ubicaciones/racks/{self.rack.pk}/cuerpos/crear/', {'descripcion': ''})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.rack.cuerpos.count(), 1)

    def test_editar_nivel_via_web_redirige(self):
        cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        nivel = cuerpo.ubicaciones.first().niveles.get(numero=1)
        resp = self.client.post(f'/ubicaciones/niveles/{nivel.pk}/editar/', {
            'tipo': Nivel.ALMACENAJE, 'descripcion': 'Nota',
        })
        self.assertEqual(resp.status_code, 302)
        nivel.refresh_from_db()
        self.assertEqual(nivel.tipo, Nivel.ALMACENAJE)

    def test_desactivar_nivel_con_productos_redirige_con_error(self):
        cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        nivel = cuerpo.ubicaciones.first().niveles.get(numero=1)
        ProductoUbicacion.objects.create(codigo_producto='X', nivel=nivel, cantidad=1)
        resp = self.client.post(f'/ubicaciones/niveles/{nivel.pk}/desactivar/')
        self.assertEqual(resp.status_code, 302)
        nivel.refresh_from_db()
        self.assertTrue(nivel.activo)


class AsignacionTrasladoFusionViewsTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from django.test import Client

        self.user = User.objects.create_user(username='webuser3', password='x')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client = Client()
        self.client.login(username='webuser3', password='x')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.ubicacion = self.cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel1 = self.ubicacion.niveles.get(numero=1)
        self.nivel2 = self.ubicacion.niveles.get(numero=2)

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_asignar_producto_via_web_redirige(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        resp = self.client.post(f'/ubicaciones/niveles/{self.nivel1.pk}/asignar/', {
            'asignar': '1', 'codigo_producto': 'ABC', 'cantidad': 10,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ProductoUbicacion.objects.filter(codigo_producto='ABC', nivel=self.nivel1).exists())

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_trasladar_via_web_redirige(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        UbicacionesService.asignar_producto('ABC', self.nivel1, 10, None, self.user)
        resp = self.client.post('/ubicaciones/trasladar/', {
            'codigo_producto': 'ABC', 'nivel_origen': self.nivel1.pk, 'nivel_destino': self.nivel2.pk,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ProductoUbicacion.objects.filter(codigo_producto='ABC', nivel=self.nivel2).exists())

    @patch('ubicaciones.services.PedidosDBISAM')
    def test_fusionar_via_web_redirige(self, mock_db):
        mock_db.return_value.consultar_stock.return_value = 50
        resp = self.client.post('/ubicaciones/fusionar/', {
            'niveles': [self.nivel1.pk, self.nivel2.pk], 'maestro': self.nivel1.pk,
        })
        self.assertEqual(resp.status_code, 302)
        self.nivel2.refresh_from_db()
        self.assertEqual(self.nivel2.fusionado_en_id, self.nivel1.pk)

    def test_desfusionar_via_web_redirige(self):
        UbicacionesService.fusionar_niveles([self.nivel1, self.nivel2], self.nivel1, self.user)
        resp = self.client.post(f'/ubicaciones/niveles/{self.nivel2.pk}/desfusionar/')
        self.assertEqual(resp.status_code, 302)
        self.nivel2.refresh_from_db()
        self.assertIsNone(self.nivel2.fusionado_en_id)


class FusionarFormTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username='formtester')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.ubicacion = self.cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel1 = self.ubicacion.niveles.get(numero=1)

    def test_maestro_debe_estar_entre_niveles_seleccionados(self):
        from ubicaciones.forms import FusionarForm
        otro_nivel = self.ubicacion.niveles.get(numero=2)
        tercer_nivel = self.ubicacion.niveles.get(numero=3)
        form = FusionarForm(data={
            'niveles': [self.nivel1.pk, otro_nivel.pk], 'maestro': tercer_nivel.pk,
        })
        self.assertFalse(form.is_valid())


class GalponRackTemplatesSmokeTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from django.test import Client

        self.user = User.objects.create_user(username='webuser4', password='x')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client = Client()
        self.client.login(username='webuser4', password='x')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)

    def test_paginas_de_galpon_y_rack_devuelven_200(self):
        urls = [
            '/ubicaciones/galpones/',
            '/ubicaciones/galpones/crear/',
            f'/ubicaciones/galpones/{self.galpon.pk}/',
            f'/ubicaciones/galpones/{self.galpon.pk}/editar/',
            f'/ubicaciones/galpones/{self.rack.galpon_id}/racks/crear/',
            f'/ubicaciones/racks/{self.rack.pk}/',
            f'/ubicaciones/racks/{self.rack.pk}/editar/',
        ]
        for url in urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"{url} devolvió {resp.status_code}")


class CuerpoUbicacionNivelTemplatesSmokeTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Group
        from django.test import Client

        self.user = User.objects.create_user(username='webuser5', password='x')
        grupo, _ = Group.objects.get_or_create(name='Pedidos Ubicaciones')
        self.user.groups.add(grupo)
        self.client = Client()
        self.client.login(username='webuser5', password='x')
        self.galpon = UbicacionesService.crear_galpon('1', 'Galpón 1', 10, 10, self.user)
        self.rack = UbicacionesService.crear_rack(self.galpon, 'A', '', 1, 1, 1, 1, 6, self.user)
        self.cuerpo = UbicacionesService.crear_cuerpo(self.rack, '', self.user)
        self.ubicacion = self.cuerpo.ubicaciones.order_by('codigo').first()
        self.nivel = self.ubicacion.niveles.get(numero=1)

    def test_paginas_de_cuerpo_ubicacion_nivel_devuelven_200(self):
        urls = [
            f'/ubicaciones/racks/{self.rack.pk}/cuerpos/crear/',
            f'/ubicaciones/cuerpos/{self.cuerpo.pk}/',
            f'/ubicaciones/cuerpos/{self.cuerpo.pk}/editar/',
            f'/ubicaciones/ubicaciones/{self.ubicacion.pk}/',
            f'/ubicaciones/ubicaciones/{self.ubicacion.pk}/editar/',
            f'/ubicaciones/niveles/{self.nivel.pk}/',
            f'/ubicaciones/niveles/{self.nivel.pk}/editar/',
        ]
        for url in urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200, f"{url} devolvió {resp.status_code}")
