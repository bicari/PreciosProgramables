from django.urls import path

from . import views

urlpatterns = [
    # Galpones
    path('ubicaciones/galpones/', views.lista_galpones, name='ubicaciones-galpones-lista'),
    path('ubicaciones/galpones/crear/', views.crear_galpon, name='ubicaciones-galpones-crear'),
    path('ubicaciones/galpones/<int:pk>/', views.detalle_galpon, name='ubicaciones-galpones-detalle'),
    path('ubicaciones/galpones/<int:pk>/editar/', views.editar_galpon, name='ubicaciones-galpones-editar'),
    path('ubicaciones/galpones/<int:pk>/desactivar/', views.desactivar_galpon, name='ubicaciones-galpones-desactivar'),

    # Racks
    path('ubicaciones/galpones/<int:galpon_pk>/racks/crear/', views.crear_rack, name='ubicaciones-racks-crear'),
    path('ubicaciones/racks/<int:pk>/', views.detalle_rack, name='ubicaciones-racks-detalle'),
    path('ubicaciones/racks/<int:pk>/editar/', views.editar_rack, name='ubicaciones-racks-editar'),
    path('ubicaciones/racks/<int:pk>/desactivar/', views.desactivar_rack, name='ubicaciones-racks-desactivar'),

    # Cuerpos
    path('ubicaciones/racks/<int:rack_pk>/cuerpos/crear/', views.crear_cuerpo, name='ubicaciones-cuerpos-crear'),
    path('ubicaciones/cuerpos/<int:pk>/', views.detalle_cuerpo, name='ubicaciones-cuerpos-detalle'),
    path('ubicaciones/cuerpos/<int:pk>/editar/', views.editar_cuerpo, name='ubicaciones-cuerpos-editar'),
    path('ubicaciones/cuerpos/<int:pk>/desactivar/', views.desactivar_cuerpo, name='ubicaciones-cuerpos-desactivar'),

    # Ubicaciones
    path('ubicaciones/ubicaciones/<int:pk>/', views.detalle_ubicacion, name='ubicaciones-ubicaciones-detalle'),
    path('ubicaciones/ubicaciones/<int:pk>/editar/', views.editar_ubicacion, name='ubicaciones-ubicaciones-editar'),
    path('ubicaciones/ubicaciones/<int:pk>/desactivar/', views.desactivar_ubicacion, name='ubicaciones-ubicaciones-desactivar'),

    # Niveles
    path('ubicaciones/niveles/<int:pk>/', views.detalle_nivel, name='ubicaciones-niveles-detalle'),
    path('ubicaciones/niveles/<int:pk>/editar/', views.editar_nivel, name='ubicaciones-niveles-editar'),
    path('ubicaciones/niveles/<int:pk>/desactivar/', views.desactivar_nivel, name='ubicaciones-niveles-desactivar'),

    # Asignaciones
    path('ubicaciones/niveles/<int:pk>/asignar/', views.asignar_producto, name='ubicaciones-asignar'),
    path('ubicaciones/producto-ubicaciones/<int:pu_id>/editar-cantidad/', views.editar_cantidad, name='ubicaciones-editar-cantidad'),
    path('ubicaciones/producto-ubicaciones/<int:pu_id>/quitar/', views.quitar_producto, name='ubicaciones-quitar'),

    # Traslado / Fusión
    path('ubicaciones/trasladar/', views.trasladar, name='ubicaciones-trasladar'),
    path('ubicaciones/fusionar/', views.fusionar, name='ubicaciones-fusionar'),
    path('ubicaciones/niveles/<int:pk>/desfusionar/', views.desfusionar, name='ubicaciones-desfusionar'),

    # Histórico
    path('ubicaciones/movimientos/', views.lista_movimientos, name='ubicaciones-movimientos'),

    # Producto → sus ubicaciones
    path('ubicaciones/productos/<str:codigo>/', views.producto_ubicaciones, name='ubicaciones-producto-detalle'),

    # Fragmentos htmx
    path('ubicaciones/buscar-nivel/', views.buscar_nivel_fragment, name='ubicaciones-buscar-nivel'),
    path('ubicaciones/buscar-producto/', views.buscar_producto_dbisam_fragment, name='ubicaciones-buscar-producto'),

    # Alertas
    path('ubicaciones/alertas/', views.alertas_stock, name='ubicaciones-alertas'),

    # Mapa
    path('ubicaciones/galpones/<int:pk>/mapa/', views.mapa_galpon, name='ubicaciones-mapa-galpon'),
    path('ubicaciones/racks/<int:pk>/mapa/', views.mapa_rack, name='ubicaciones-mapa-rack'),
]
