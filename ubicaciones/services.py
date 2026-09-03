from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from PedidosAlmacen.dbisam import DEPOSITO_ALMACEN, PedidosDBISAM

from .models import Cuerpo, Galpon, MovimientoUbicacion, Nivel, ProductoUbicacion, Rack, Ubicacion


def _registrar(tipo: str, usuario, **kwargs) -> None:
    MovimientoUbicacion.objects.create(tipo=tipo, usuario=usuario, **kwargs)


class UbicacionesService:

    # ------------------------------------------------------------------ Galpón

    @staticmethod
    @transaction.atomic
    def crear_galpon(codigo: str, nombre: str, grid_filas: int, grid_columnas: int, usuario) -> Galpon:
        """Crea un galpón normalizando el código a mayúsculas."""
        codigo = codigo.strip().upper()
        if Galpon.objects.filter(codigo=codigo).exists():
            raise ValidationError(f"Ya existe un galpón con código '{codigo}'.")
        galpon = Galpon.objects.create(
            codigo=codigo, nombre=nombre,
            grid_filas=grid_filas, grid_columnas=grid_columnas,
            creado_por=usuario,
        )
        _registrar('CREACION_GALPON', usuario, galpon=galpon)
        return galpon

    @staticmethod
    @transaction.atomic
    def editar_galpon(galpon: Galpon, nombre: str, grid_filas: int, grid_columnas: int, usuario) -> Galpon:
        galpon.nombre = nombre
        galpon.grid_filas = grid_filas
        galpon.grid_columnas = grid_columnas
        galpon.save(update_fields=['nombre', 'grid_filas', 'grid_columnas', 'fecha_modificacion'])
        _registrar('EDICION_GALPON', usuario, galpon=galpon)
        return galpon

    @staticmethod
    @transaction.atomic
    def desactivar_galpon(galpon: Galpon, usuario) -> None:
        """Soft-delete de galpón. Rechaza si tiene racks activos."""
        if galpon.racks.filter(activo=True).exists():
            raise ValidationError(
                f"El galpón '{galpon.codigo}' tiene racks activos. "
                "Desactívalos antes de desactivar el galpón."
            )
        galpon.activo = False
        galpon.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_GALPON', usuario, galpon=galpon)

    # ------------------------------------------------------------------ Rack

    @staticmethod
    @transaction.atomic
    def crear_rack(
        galpon: Galpon, codigo: str, descripcion: str,
        grid_fila: int, grid_columna: int, ancho: int, alto: int,
        max_niveles: int, usuario,
    ) -> Rack:
        """Crea un rack normalizando el código a mayúsculas."""
        codigo = codigo.strip().upper()
        if not galpon.activo:
            raise ValidationError(f"El galpón '{galpon.codigo}' está desactivado.")
        if Rack.objects.filter(galpon=galpon, codigo=codigo).exists():
            raise ValidationError(
                f"Ya existe un rack con código '{codigo}' en el galpón '{galpon.codigo}'."
            )
        rack = Rack.objects.create(
            galpon=galpon, codigo=codigo, descripcion=descripcion,
            grid_fila=grid_fila, grid_columna=grid_columna, ancho=ancho, alto=alto,
            max_niveles=max_niveles, creado_por=usuario,
        )
        _registrar('CREACION_RACK', usuario, galpon=galpon, rack=rack)
        return rack

    @staticmethod
    @transaction.atomic
    def editar_rack(
        rack: Rack, descripcion: str,
        grid_fila: int, grid_columna: int, ancho: int, alto: int,
        max_niveles: int, usuario,
    ) -> Rack:
        """Edita un rack. `max_niveles` solo se puede cambiar si el rack aún no tiene cuerpos."""
        if max_niveles != rack.max_niveles and rack.cuerpos.exists():
            raise ValidationError(
                f"El rack '{rack.codigo}' ya tiene cuerpos creados; "
                "no se puede cambiar el máximo de niveles."
            )
        rack.descripcion = descripcion
        rack.grid_fila = grid_fila
        rack.grid_columna = grid_columna
        rack.ancho = ancho
        rack.alto = alto
        rack.max_niveles = max_niveles
        rack.save(update_fields=[
            'descripcion', 'grid_fila', 'grid_columna', 'ancho', 'alto',
            'max_niveles', 'fecha_modificacion',
        ])
        _registrar('EDICION_RACK', usuario, galpon=rack.galpon, rack=rack)
        return rack

    @staticmethod
    @transaction.atomic
    def desactivar_rack(rack: Rack, usuario) -> None:
        """Soft-delete de rack. Rechaza si tiene cuerpos activos."""
        if rack.cuerpos.filter(activo=True).exists():
            raise ValidationError(
                f"El rack '{rack.codigo}' tiene cuerpos activos. "
                "Desactívalos antes de desactivar el rack."
            )
        rack.activo = False
        rack.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_RACK', usuario, galpon=rack.galpon, rack=rack)

    # ------------------------------------------------------------------ Cuerpo

    @staticmethod
    @transaction.atomic
    def crear_cuerpo(rack: Rack, descripcion: str, usuario) -> Cuerpo:
        """
        Crea un cuerpo en el rack, autogenerando sus 2 Ubicaciones (numeración
        global no reiniciada por cuerpo, para calzar con las etiquetas físicas
        ya impresas) y, para cada una, sus Niveles según `rack.max_niveles`.
        """
        if not rack.activo:
            raise ValidationError(f"El rack '{rack.codigo}' está desactivado.")
        siguiente_num = rack.cuerpos.count() + 1
        cuerpo = Cuerpo.objects.create(
            rack=rack, codigo=f"{siguiente_num:02d}",
            descripcion=descripcion, creado_por=usuario,
        )
        for offset in (0, 1):
            ubicacion_num = 2 * siguiente_num - 1 + offset
            ubicacion = Ubicacion.objects.create(
                cuerpo=cuerpo, codigo=f"{ubicacion_num:02d}", creado_por=usuario,
            )
            Nivel.objects.bulk_create([
                Nivel(ubicacion=ubicacion, numero=n, creado_por=usuario)
                for n in range(1, rack.max_niveles + 1)
            ])
        _registrar('CREACION_CUERPO', usuario, galpon=rack.galpon, rack=rack, cuerpo=cuerpo)
        return cuerpo

    @staticmethod
    @transaction.atomic
    def desactivar_cuerpo(cuerpo: Cuerpo, usuario) -> None:
        """Soft-delete de cuerpo. Rechaza si tiene ubicaciones activas."""
        if cuerpo.ubicaciones.filter(activo=True).exists():
            raise ValidationError(
                f"El cuerpo '{cuerpo.codigo}' tiene ubicaciones activas. "
                "Desactívalas antes de desactivar el cuerpo."
            )
        cuerpo.activo = False
        cuerpo.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_CUERPO', usuario, galpon=cuerpo.rack.galpon, rack=cuerpo.rack, cuerpo=cuerpo)

    # ------------------------------------------------------------------ Ubicación

    @staticmethod
    @transaction.atomic
    def desactivar_ubicacion(ubicacion: Ubicacion, usuario) -> None:
        """Soft-delete de ubicación. Rechaza si tiene niveles activos."""
        if ubicacion.niveles.filter(activo=True).exists():
            raise ValidationError(
                f"La ubicación '{ubicacion.codigo}' tiene niveles activos. "
                "Desactívalos antes de desactivar la ubicación."
            )
        ubicacion.activo = False
        ubicacion.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar(
            'DESACTIVACION_UBICACION', usuario,
            galpon=ubicacion.rack.galpon, rack=ubicacion.rack, ubicacion=ubicacion,
        )

    # ------------------------------------------------------------------ Nivel

    @staticmethod
    @transaction.atomic
    def editar_nivel(nivel: Nivel, tipo: str, descripcion: str, usuario) -> Nivel:
        if nivel.esta_fusionado:
            raise ValidationError(
                f"El nivel '{nivel.codigo_completo}' está fusionado con "
                f"'{nivel.fusionado_en.codigo_completo}'; edítalo desde el nivel maestro."
            )
        nivel.tipo = tipo
        nivel.descripcion = descripcion
        nivel.save(update_fields=['tipo', 'descripcion', 'fecha_modificacion'])
        _registrar('EDICION_NIVEL', usuario, galpon=nivel.galpon, rack=nivel.rack, nivel=nivel)
        return nivel

    @staticmethod
    @transaction.atomic
    def desactivar_nivel(nivel: Nivel, usuario) -> None:
        """Soft-delete de nivel. Rechaza si tiene productos asignados."""
        if nivel.productos.exists():
            raise ValidationError(
                f"El nivel '{nivel.codigo_completo}' tiene productos asignados. "
                "Quítalos o trasládalos antes de desactivarlo."
            )
        nivel.activo = False
        nivel.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_NIVEL', usuario, galpon=nivel.galpon, rack=nivel.rack, nivel=nivel)

    # ------------------------------------------------------------------ Asignaciones

    @staticmethod
    def _validar_cantidad_contra_a2(codigo: str, cantidad_nueva: int, excluir_pu_id: int | None = None) -> None:
        ya_asignado = ProductoUbicacion.objects.filter(codigo_producto=codigo)
        if excluir_pu_id:
            ya_asignado = ya_asignado.exclude(pk=excluir_pu_id)
        suma_actual = ya_asignado.aggregate(total=Sum('cantidad'))['total'] or 0
        total_pedido = suma_actual + cantidad_nueva
        existencia = PedidosDBISAM().consultar_stock(codigo, deposito=DEPOSITO_ALMACEN)
        if total_pedido > existencia:
            raise ValidationError(
                f"La cantidad total asignada de '{codigo}' ({total_pedido}) "
                f"excede la existencia en depósito ({existencia})."
            )

    @staticmethod
    @transaction.atomic
    def asignar_producto(
        codigo: str, nivel: Nivel, cantidad: int, stock_minimo: int | None, usuario,
    ) -> ProductoUbicacion:
        """Asigna un producto (código DBISAM) a un nivel, validando cantidad contra a2."""
        codigo = codigo.strip().upper()
        if not nivel.activo:
            raise ValidationError(f"El nivel '{nivel.codigo_completo}' está desactivado.")
        if nivel.esta_fusionado:
            raise ValidationError(
                f"El nivel '{nivel.codigo_completo}' está fusionado con "
                f"'{nivel.fusionado_en.codigo_completo}'; asigna el producto al nivel maestro."
            )
        if ProductoUbicacion.objects.filter(codigo_producto=codigo, nivel=nivel).exists():
            raise ValidationError(f"El producto '{codigo}' ya está asignado a '{nivel.codigo_completo}'.")
        UbicacionesService._validar_cantidad_contra_a2(codigo, cantidad)
        pu = ProductoUbicacion.objects.create(
            codigo_producto=codigo, nivel=nivel, cantidad=cantidad,
            stock_minimo=stock_minimo if nivel.tipo == Nivel.PICKING else None,
            asignado_por=usuario,
        )
        _registrar(
            'ASIGNACION', usuario, galpon=nivel.galpon, rack=nivel.rack,
            nivel_destino=nivel, codigo_producto=codigo,
        )
        return pu

    @staticmethod
    @transaction.atomic
    def editar_cantidad(
        producto_ubicacion: ProductoUbicacion, cantidad: int, stock_minimo: int | None, usuario,
    ) -> ProductoUbicacion:
        UbicacionesService._validar_cantidad_contra_a2(
            producto_ubicacion.codigo_producto, cantidad, excluir_pu_id=producto_ubicacion.pk,
        )
        producto_ubicacion.cantidad = cantidad
        if producto_ubicacion.nivel.tipo == Nivel.PICKING:
            producto_ubicacion.stock_minimo = stock_minimo
        producto_ubicacion.save(update_fields=['cantidad', 'stock_minimo'])
        _registrar(
            'EDICION_CANTIDAD', usuario,
            galpon=producto_ubicacion.nivel.galpon, rack=producto_ubicacion.nivel.rack,
            nivel_destino=producto_ubicacion.nivel, codigo_producto=producto_ubicacion.codigo_producto,
        )
        return producto_ubicacion

    @staticmethod
    @transaction.atomic
    def quitar_producto(producto_ubicacion_id: int, usuario) -> None:
        pu = ProductoUbicacion.objects.select_related('nivel').get(pk=producto_ubicacion_id)
        codigo = pu.codigo_producto
        nivel = pu.nivel
        pu.delete()
        _registrar(
            'DESASIGNACION', usuario, galpon=nivel.galpon, rack=nivel.rack,
            nivel_origen=nivel, codigo_producto=codigo,
        )

    # ------------------------------------------------------------------ Traslado

    @staticmethod
    @transaction.atomic
    def trasladar_producto(
        codigo: str, nivel_origen: Nivel, nivel_destino: Nivel, usuario, notas: str = '',
    ) -> None:
        """Mueve la asignación de `codigo` de nivel_origen a nivel_destino."""
        codigo = codigo.strip().upper()
        if nivel_origen.pk == nivel_destino.pk:
            raise ValidationError("El origen y el destino deben ser niveles distintos.")
        if not nivel_destino.activo:
            raise ValidationError(f"El nivel destino '{nivel_destino.codigo_completo}' está desactivado.")
        if nivel_destino.esta_fusionado:
            raise ValidationError(
                f"El nivel destino '{nivel_destino.codigo_completo}' está fusionado; "
                f"traslada al nivel maestro '{nivel_destino.fusionado_en.codigo_completo}'."
            )

        pu_origen = ProductoUbicacion.objects.select_for_update().filter(
            codigo_producto=codigo, nivel=nivel_origen,
        ).first()
        if not pu_origen:
            raise ValidationError(f"El producto '{codigo}' no está asignado a '{nivel_origen.codigo_completo}'.")

        cantidad = pu_origen.cantidad
        pu_origen.delete()

        pu_destino, created = ProductoUbicacion.objects.get_or_create(
            codigo_producto=codigo, nivel=nivel_destino,
            defaults={'cantidad': cantidad, 'asignado_por': usuario},
        )
        if not created:
            pu_destino.cantidad += cantidad
            pu_destino.save(update_fields=['cantidad'])

        _registrar(
            'TRASLADO', usuario, galpon=nivel_origen.galpon, rack=nivel_origen.rack,
            nivel_origen=nivel_origen, nivel_destino=nivel_destino,
            codigo_producto=codigo, notas=notas,
        )

    # ------------------------------------------------------------------ Fusión

    @staticmethod
    @transaction.atomic
    def fusionar_niveles(niveles: list[Nivel], maestro: Nivel, usuario, notas: str = '') -> int:
        """
        Fusiona `niveles` hacia `maestro` (debe estar incluido en la lista):
        consolida las cantidades de ProductoUbicacion de los miembros en el
        maestro y marca `fusionado_en` en cada miembro. Retorna la cantidad
        de asignaciones de producto consolidadas (transferidas o sumadas).
        """
        if maestro.pk not in {n.pk for n in niveles}:
            raise ValidationError("El maestro debe estar incluido en la lista de niveles a fusionar.")
        racks = {n.rack.pk for n in niveles}
        if len(racks) > 1:
            raise ValidationError("Solo se pueden fusionar niveles del mismo Rack.")
        if maestro.esta_fusionado:
            raise ValidationError(f"El maestro '{maestro.codigo_completo}' ya está fusionado.")

        miembros = [n for n in niveles if n.pk != maestro.pk]
        for miembro in miembros:
            if miembro.esta_fusionado:
                raise ValidationError(f"El nivel '{miembro.codigo_completo}' ya está fusionado.")

        transferidos = 0
        for miembro in miembros:
            for pu in ProductoUbicacion.objects.select_for_update().filter(nivel=miembro):
                destino_pu, created = ProductoUbicacion.objects.select_for_update().get_or_create(
                    codigo_producto=pu.codigo_producto, nivel=maestro,
                    defaults={'cantidad': pu.cantidad, 'stock_minimo': pu.stock_minimo, 'asignado_por': usuario},
                )
                if not created:
                    destino_pu.cantidad += pu.cantidad
                    destino_pu.stock_minimo = destino_pu.stock_minimo or pu.stock_minimo
                    destino_pu.save(update_fields=['cantidad', 'stock_minimo'])
                pu.delete()
                transferidos += 1

            miembro_actualizado = Nivel.objects.select_for_update(of=('self',)).get(pk=miembro.pk)
            miembro_actualizado.fusionado_en = maestro
            miembro_actualizado.save(update_fields=['fusionado_en', 'fecha_modificacion'])
            _registrar(
                'FUSION_NIVEL', usuario, galpon=maestro.galpon, rack=maestro.rack,
                nivel_origen=miembro, nivel_destino=maestro, notas=notas,
            )
        return transferidos

    @staticmethod
    @transaction.atomic
    def desfusionar_nivel(nivel_miembro: Nivel, usuario) -> None:
        if not nivel_miembro.esta_fusionado:
            raise ValidationError(f"El nivel '{nivel_miembro.codigo_completo}' no está fusionado.")

        maestro = nivel_miembro.fusionado_en
        hermanos_fusionados = Nivel.objects.filter(fusionado_en=maestro).exclude(pk=nivel_miembro.pk)
        maestro_tiene_stock = ProductoUbicacion.objects.filter(nivel=maestro).exists()
        if maestro_tiene_stock and hermanos_fusionados.exists():
            raise ValidationError(
                f"El maestro '{maestro.codigo_completo}' tiene stock y quedan otros niveles fusionados; "
                "redistribuye manualmente las cantidades antes de desfusionar."
            )

        nivel_miembro.fusionado_en = None
        nivel_miembro.save(update_fields=['fusionado_en', 'fecha_modificacion'])
        _registrar(
            'DESFUSION_NIVEL', usuario, galpon=maestro.galpon, rack=maestro.rack,
            nivel_origen=maestro, nivel_destino=nivel_miembro,
        )

    # ------------------------------------------------------------------ Principal / picking

    @staticmethod
    @transaction.atomic
    def marcar_principal(producto_ubicacion: ProductoUbicacion, usuario) -> ProductoUbicacion:
        """Marca esta ProductoUbicacion como principal para su codigo_producto,
        desmarcando cualquier otra del mismo código."""
        ProductoUbicacion.objects.filter(
            codigo_producto=producto_ubicacion.codigo_producto,
        ).exclude(pk=producto_ubicacion.pk).update(es_principal=False)
        producto_ubicacion.es_principal = True
        producto_ubicacion.save(update_fields=['es_principal'])
        return producto_ubicacion

    @staticmethod
    @transaction.atomic
    def descontar_por_picking(
        pedido_item, cantidad: int, usuario, nivel_id: int | None = None,
    ) -> dict:
        """Descuenta `cantidad` de la ubicación PICKING del producto de `pedido_item`.

        Reentrante: revierte el descuento vigente para este pedido_item (si lo
        hay) antes de aplicar el nuevo, así que puede llamarse cada vez que se
        guarda cantidad_preparada sin duplicar descuentos. Nunca lanza
        ValidationError: cualquier ambigüedad (varias ubicaciones sin indicar
        cuál) o faltante de stock queda registrado como incidencia
        (pendiente_revision=True) en vez de bloquear la operación.
        """
        codigo = pedido_item.codigo
        resultado = {'aplicado': False, 'nivel_id': None, 'incidencia': False, 'mensaje': ''}

        if nivel_id is not None:
            nivel_id = int(nivel_id)

        # Paso 1: revertir el descuento vigente para este ítem, si existe.
        anterior = (
            MovimientoUbicacion.objects
            .select_for_update()
            .filter(tipo='PICKING', pedido_item=pedido_item, activo=True)
            .first()
        )
        if anterior is not None:
            if anterior.nivel_origen_id is not None and anterior.cantidad:
                pu_anterior = (
                    ProductoUbicacion.objects
                    .select_for_update()
                    .filter(codigo_producto=codigo, nivel_id=anterior.nivel_origen_id)
                    .first()
                )
                if pu_anterior is None:
                    ProductoUbicacion.objects.create(
                        codigo_producto=codigo, nivel_id=anterior.nivel_origen_id, cantidad=anterior.cantidad,
                    )
                else:
                    pu_anterior.cantidad += anterior.cantidad
                    pu_anterior.save(update_fields=['cantidad'])
            anterior.activo = False
            anterior.save(update_fields=['activo'])

        if cantidad <= 0:
            return resultado

        # Paso 2: resolver la ubicación de origen.
        candidatos = list(
            ProductoUbicacion.objects
            .select_for_update()
            .filter(
                codigo_producto=codigo, nivel__tipo=Nivel.PICKING, nivel__activo=True,
                nivel__fusionado_en__isnull=True,
            )
            .select_related('nivel__ubicacion__cuerpo__rack__galpon')
        )

        if not candidatos:
            return resultado

        if len(candidatos) == 1:
            origen = candidatos[0]
        else:
            origen = next((pu for pu in candidatos if pu.nivel_id == nivel_id), None)
            if origen is None:
                MovimientoUbicacion.objects.create(
                    tipo='PICKING', pedido_item=pedido_item, codigo_producto=codigo,
                    cantidad=cantidad, pendiente_revision=True, activo=False, usuario=usuario,
                    notas='Ambigüedad: varias ubicaciones PICKING, ninguna indicada.',
                )
                resultado['incidencia'] = True
                resultado['mensaje'] = 'Varias ubicaciones PICKING; se registró incidencia sin descuento.'
                return resultado

        # Paso 3: aplicar el descuento.
        disponible = origen.cantidad
        incidencia = cantidad > disponible
        descuento = min(cantidad, disponible)
        origen.cantidad = disponible - descuento
        origen.save(update_fields=['cantidad'])

        MovimientoUbicacion.objects.create(
            tipo='PICKING', pedido_item=pedido_item, codigo_producto=codigo,
            nivel_origen=origen.nivel, cantidad=cantidad, activo=True,
            pendiente_revision=incidencia, usuario=usuario,
            galpon=origen.nivel.galpon, rack=origen.nivel.rack,
            notas='Faltante de stock en la ubicación.' if incidencia else '',
        )
        resultado.update(aplicado=True, nivel_id=origen.nivel_id, incidencia=incidencia)
        if incidencia:
            resultado['mensaje'] = f'Ubicación quedó en 0; faltaron {cantidad - disponible} unidades.'
        return resultado

    # ------------------------------------------------------------------ Incidencias

    @staticmethod
    @transaction.atomic
    def resolver_incidencia(movimiento: MovimientoUbicacion, usuario, nota: str = '') -> MovimientoUbicacion:
        movimiento.pendiente_revision = False
        movimiento.revisado_por = usuario
        movimiento.fecha_revision = timezone.now()
        if nota:
            movimiento.notas = f"{movimiento.notas}\n{nota}".strip()
        movimiento.save(update_fields=['pendiente_revision', 'revisado_por', 'fecha_revision', 'notas'])
        return movimiento

    # ------------------------------------------------------------------ Reconciliación a2

    @staticmethod
    @transaction.atomic
    def ajustar_por_reconciliacion_a2(codigo_producto: str, existencia_a2: int, usuario=None) -> dict:
        """Compara la existencia real en a2 contra lo asignado por ubicación
        para un producto y, si a2 quedó por debajo (salida externa), ajusta
        la ubicación resuelta sin ambigüedad y registra la incidencia.
        No lanza excepciones."""
        asignaciones = list(
            ProductoUbicacion.objects
            .select_for_update()
            .filter(codigo_producto=codigo_producto)
            .select_related('nivel__ubicacion__cuerpo__rack__galpon')
        )
        resultado = {'faltante': 0, 'ajustado': False, 'nivel_id': None}
        if not asignaciones:
            return resultado

        suma = sum(pu.cantidad for pu in asignaciones)
        if existencia_a2 >= suma:
            return resultado

        faltante = suma - existencia_a2
        resultado['faltante'] = faltante

        if len(asignaciones) == 1:
            origen = asignaciones[0]
        else:
            origen = next((pu for pu in asignaciones if pu.es_principal), None)

        if origen is not None:
            disponible = origen.cantidad
            descuento = min(faltante, disponible)
            origen.cantidad = disponible - descuento
            origen.save(update_fields=['cantidad'])
            resultado['ajustado'] = True
            resultado['nivel_id'] = origen.nivel_id

        MovimientoUbicacion.objects.create(
            tipo='AJUSTE_A2', codigo_producto=codigo_producto, cantidad=faltante,
            pendiente_revision=True, activo=False, usuario=usuario,
            nivel_destino=origen.nivel if origen else None,
            galpon=origen.nivel.galpon if origen else None,
            rack=origen.nivel.rack if origen else None,
            notas=(
                'Salida externa detectada por reconciliación con a2.' if origen else
                'Salida externa detectada; ambigüedad de ubicación, requiere resolución manual.'
            ),
        )
        return resultado
