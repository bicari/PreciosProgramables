from django.core.exceptions import ValidationError
from django.db import transaction

from .models import (
    MovimientoUbicacion,
    Nivel,
    ProductoUbicacion,
    Rack,
    Ubicacion,
)


def _registrar(tipo: str, usuario, **kwargs) -> None:
    MovimientoUbicacion.objects.create(tipo=tipo, usuario=usuario, **kwargs)


class UbicacionesService:

    # ------------------------------------------------------------------ Rack

    @staticmethod
    @transaction.atomic
    def crear_rack(codigo: str, descripcion: str, max_niveles: int | None, usuario) -> Rack:
        """Crea un rack normalizando el código a mayúsculas."""
        codigo = codigo.strip().upper()
        if Rack.objects.filter(codigo=codigo).exists():
            raise ValidationError(f"Ya existe un rack con código '{codigo}'.")
        rack = Rack.objects.create(
            codigo=codigo,
            descripcion=descripcion,
            max_niveles=max_niveles,
            creado_por=usuario,
        )
        _registrar('CREACION_RACK', usuario, rack=rack)
        return rack

    @staticmethod
    @transaction.atomic
    def editar_rack(rack: Rack, descripcion: str, max_niveles: int | None, usuario) -> Rack:
        """Edita descripción y max_niveles de un rack."""
        if max_niveles is not None and rack.total_niveles > max_niveles:
            raise ValidationError(
                f"El rack ya tiene {rack.total_niveles} niveles; "
                f"el nuevo tope ({max_niveles}) no puede ser menor."
            )
        rack.descripcion = descripcion
        rack.max_niveles = max_niveles
        rack.save(update_fields=['descripcion', 'max_niveles', 'fecha_modificacion'])
        _registrar('EDICION_RACK', usuario, rack=rack)
        return rack

    @staticmethod
    @transaction.atomic
    def desactivar_rack(rack: Rack, usuario) -> None:
        """Soft-delete de rack. Rechaza si tiene niveles activos."""
        if rack.niveles.filter(activo=True).exists():
            raise ValidationError(
                f"El rack '{rack.codigo}' tiene niveles activos. "
                "Desactívalos antes de desactivar el rack."
            )
        rack.activo = False
        rack.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_RACK', usuario, rack=rack)

    # ------------------------------------------------------------------ Nivel

    @staticmethod
    @transaction.atomic
    def crear_nivel(rack: Rack, codigo: str, tipo: str, descripcion: str, usuario) -> Nivel:
        """Crea un nivel en el rack respetando max_niveles (activos + inactivos)."""
        codigo = codigo.strip().upper()
        if not rack.activo:
            raise ValidationError(f"El rack '{rack.codigo}' está desactivado.")
        if rack.max_niveles is not None and rack.total_niveles >= rack.max_niveles:
            raise ValidationError(
                f"El rack '{rack.codigo}' alcanzó su máximo de {rack.max_niveles} niveles."
            )
        if Nivel.objects.filter(rack=rack, codigo=codigo).exists():
            raise ValidationError(
                f"Ya existe el nivel '{codigo}' en el rack '{rack.codigo}'."
            )
        nivel = Nivel.objects.create(
            rack=rack, codigo=codigo, tipo=tipo,
            descripcion=descripcion, creado_por=usuario,
        )
        _registrar('CREACION_NIVEL', usuario, rack=rack, nivel=nivel)
        return nivel

    @staticmethod
    @transaction.atomic
    def editar_nivel(nivel: Nivel, tipo: str, descripcion: str, usuario) -> Nivel:
        nivel.tipo = tipo
        nivel.descripcion = descripcion
        nivel.save(update_fields=['tipo', 'descripcion', 'fecha_modificacion'])
        _registrar('EDICION_NIVEL', usuario, rack=nivel.rack, nivel=nivel)
        return nivel

    @staticmethod
    @transaction.atomic
    def desactivar_nivel(nivel: Nivel, usuario) -> None:
        """Soft-delete de nivel. Rechaza si tiene ubicaciones con productos."""
        ubicaciones_con_productos = Ubicacion.objects.filter(
            nivel=nivel, activo=True, productos__isnull=False
        ).distinct()
        if ubicaciones_con_productos.exists():
            raise ValidationError(
                f"El nivel '{nivel.codigo}' tiene ubicaciones con productos asignados. "
                "Desasigna los productos antes de desactivar el nivel."
            )
        nivel.activo = False
        nivel.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_NIVEL', usuario, rack=nivel.rack, nivel=nivel)

    # ------------------------------------------------------------------ Ubicación

    @staticmethod
    @transaction.atomic
    def crear_ubicacion(nivel: Nivel, codigo: str, descripcion: str, usuario) -> Ubicacion:
        """Crea una ubicación en el nivel dado."""
        codigo = codigo.strip().upper()
        if not nivel.activo:
            raise ValidationError(f"El nivel '{nivel.codigo}' está desactivado.")
        if Ubicacion.objects.filter(nivel=nivel, codigo=codigo).exists():
            raise ValidationError(
                f"Ya existe la ubicación '{codigo}' en el nivel '{nivel.codigo}'."
            )
        ubic = Ubicacion.objects.create(
            nivel=nivel, codigo=codigo,
            descripcion=descripcion, creado_por=usuario,
        )
        _registrar('CREACION_UBICACION', usuario,
                   rack=nivel.rack, nivel=nivel, ubicacion_destino=ubic)
        return ubic

    @staticmethod
    @transaction.atomic
    def editar_ubicacion(ubicacion: Ubicacion, descripcion: str, usuario) -> Ubicacion:
        ubicacion.descripcion = descripcion
        ubicacion.save(update_fields=['descripcion', 'fecha_modificacion'])
        _registrar('EDICION_UBICACION', usuario,
                   rack=ubicacion.rack, nivel=ubicacion.nivel,
                   ubicacion_destino=ubicacion)
        return ubicacion

    @staticmethod
    @transaction.atomic
    def desactivar_ubicacion(ubicacion: Ubicacion, usuario) -> None:
        """Soft-delete de ubicación. Rechaza si tiene productos asignados."""
        if ProductoUbicacion.objects.filter(ubicacion=ubicacion).exists():
            raise ValidationError(
                f"La ubicación '{ubicacion.codigo_completo}' tiene productos asignados. "
                "Quítalos o trasládalos antes de desactivarla."
            )
        ubicacion.activo = False
        ubicacion.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar('DESACTIVACION_UBICACION', usuario,
                   rack=ubicacion.rack, nivel=ubicacion.nivel,
                   ubicacion_origen=ubicacion)

    # ------------------------------------------------------------------ Asignaciones

    @staticmethod
    @transaction.atomic
    def asignar_producto(codigo: str, ubicacion: Ubicacion, usuario) -> ProductoUbicacion:
        """
        Asigna un producto (código DBISAM) a una ubicación.
        Valida la existencia del código en DBISAM antes de asignar.
        """
        from PedidosAlmacen.dbisam import PedidosDBISAM

        codigo = codigo.strip().upper()
        if not ubicacion.activo:
            raise ValidationError(f"La ubicación '{ubicacion.codigo_completo}' está desactivada.")
        if not ubicacion.nivel.activo:
            raise ValidationError(f"El nivel '{ubicacion.nivel.codigo}' está desactivado.")
        if ProductoUbicacion.objects.filter(codigo_producto=codigo, ubicacion=ubicacion).exists():
            raise ValidationError(
                f"El producto '{codigo}' ya está asignado a '{ubicacion.codigo_completo}'."
            )
        if not PedidosDBISAM().buscar_producto(codigo):
            raise ValidationError(
                f"El código '{codigo}' no existe en el inventario DBISAM."
            )
        pu = ProductoUbicacion.objects.create(
            codigo_producto=codigo,
            ubicacion=ubicacion,
            asignado_por=usuario,
        )
        _registrar('ASIGNACION', usuario,
                   rack=ubicacion.rack, nivel=ubicacion.nivel,
                   ubicacion_destino=ubicacion, codigo_producto=codigo)
        return pu

    @staticmethod
    @transaction.atomic
    def quitar_producto(producto_ubicacion_id: int, usuario) -> None:
        """Elimina la asignación de un producto a una ubicación."""
        pu = ProductoUbicacion.objects.get(pk=producto_ubicacion_id)
        codigo = pu.codigo_producto
        ubic = pu.ubicacion
        pu.delete()
        _registrar('DESASIGNACION', usuario,
                   rack=ubic.rack, nivel=ubic.nivel,
                   ubicacion_origen=ubic, codigo_producto=codigo)

    # ------------------------------------------------------------------ Traslado

    @staticmethod
    @transaction.atomic
    def trasladar_producto(
        codigo: str,
        ubic_origen: Ubicacion,
        ubic_destino: Ubicacion,
        usuario,
        notas: str = '',
    ) -> None:
        """
        Mueve la asignación de `codigo` de ubic_origen a ubic_destino.
        Si el producto ya estaba en destino, elimina solo el origen (sin duplicar).
        """
        codigo = codigo.strip().upper()
        if ubic_origen.pk == ubic_destino.pk:
            raise ValidationError("El origen y el destino deben ser ubicaciones distintas.")
        if not ubic_destino.activo:
            raise ValidationError(f"La ubicación destino '{ubic_destino.codigo_completo}' está desactivada.")

        pu_origen = ProductoUbicacion.objects.select_for_update().filter(
            codigo_producto=codigo, ubicacion=ubic_origen,
        ).first()
        if not pu_origen:
            raise ValidationError(
                f"El producto '{codigo}' no está asignado a '{ubic_origen.codigo_completo}'."
            )

        pu_origen.delete()

        ProductoUbicacion.objects.get_or_create(
            codigo_producto=codigo,
            ubicacion=ubic_destino,
            defaults={'asignado_por': usuario},
        )

        _registrar('TRASLADO', usuario,
                   rack=ubic_origen.rack, nivel=ubic_origen.nivel,
                   ubicacion_origen=ubic_origen, ubicacion_destino=ubic_destino,
                   codigo_producto=codigo, notas=notas)

    # ------------------------------------------------------------------ Fusión

    @staticmethod
    @transaction.atomic
    def fusionar_ubicaciones(
        ubic_a: Ubicacion,
        ubic_b: Ubicacion,
        usuario,
        notas: str = '',
    ) -> int:
        """
        Transfiere todas las asignaciones de ubic_a a ubic_b y desactiva ubic_a.
        Retorna el número de productos transferidos.
        """
        if ubic_a.pk == ubic_b.pk:
            raise ValidationError("No se puede fusionar una ubicación consigo misma.")
        if not ubic_a.activo:
            raise ValidationError(f"La ubicación '{ubic_a.codigo_completo}' ya está desactivada.")
        if not ubic_b.activo:
            raise ValidationError(f"La ubicación destino '{ubic_b.codigo_completo}' está desactivada.")

        items = list(ProductoUbicacion.objects.select_for_update().filter(ubicacion=ubic_a))
        for pu in items:
            ProductoUbicacion.objects.get_or_create(
                codigo_producto=pu.codigo_producto,
                ubicacion=ubic_b,
                defaults={'asignado_por': usuario},
            )
            _registrar('FUSION', usuario,
                       rack=ubic_a.rack, nivel=ubic_a.nivel,
                       ubicacion_origen=ubic_a, ubicacion_destino=ubic_b,
                       codigo_producto=pu.codigo_producto, notas=notas)
            pu.delete()

        ubic_a.activo = False
        ubic_a.save(update_fields=['activo', 'fecha_modificacion'])
        _registrar(
            'DESACTIVACION_UBICACION', usuario,
            rack=ubic_a.rack, nivel=ubic_a.nivel,
            ubicacion_origen=ubic_a,
            notas=f"Fusionada en {ubic_b.codigo_completo}. {notas}".strip(),
        )
        return len(items)
