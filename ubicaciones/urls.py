from django.urls import path

from . import views

urlpatterns = [
    # Racks
    path('ubicaciones/racks/', views.lista_racks, name='ubicaciones-racks-lista'),
    path('ubicaciones/racks/crear/', views.crear_rack, name='ubicaciones-racks-crear'),
    path('ubicaciones/racks/<int:pk>/', views.detalle_rack, name='ubicaciones-racks-detalle'),
    path('ubicaciones/racks/<int:pk>/editar/', views.editar_rack, name='ubicaciones-racks-editar'),
    path('ubicaciones/racks/<int:pk>/desactivar/', views.desactivar_rack, name='ubicaciones-racks-desactivar'),

    # Niveles
    path('ubicaciones/niveles/crear/', views.crear_nivel, name='ubicaciones-niveles-crear'),
    path('ubicaciones/niveles/<int:pk>/', views.detalle_nivel, name='ubicaciones-niveles-detalle'),
    path('ubicaciones/niveles/<int:pk>/editar/', views.editar_nivel, name='ubicaciones-niveles-editar'),
    path('ubicaciones/niveles/<int:pk>/desactivar/', views.desactivar_nivel, name='ubicaciones-niveles-desactivar'),

    # Ubicaciones
    path('ubicaciones/ubicaciones/crear/', views.crear_ubicacion, name='ubicaciones-ubicaciones-crear'),
    path('ubicaciones/ubicaciones/<int:pk>/', views.detalle_ubicacion, name='ubicaciones-ubicaciones-detalle'),
    path('ubicaciones/ubicaciones/<int:pk>/editar/', views.editar_ubicacion, name='ubicaciones-ubicaciones-editar'),
    path('ubicaciones/ubicaciones/<int:pk>/desactivar/', views.desactivar_ubicacion, name='ubicaciones-ubicaciones-desactivar'),

    # Asignaciones
    path('ubicaciones/ubicaciones/<int:pk>/asignar/', views.asignar_producto, name='ubicaciones-asignar'),
    path('ubicaciones/ubicaciones/<int:pk>/quitar/<int:pu_id>/', views.quitar_producto, name='ubicaciones-quitar'),

    # Operaciones especiales
    path('ubicaciones/trasladar/', views.trasladar, name='ubicaciones-trasladar'),
    path('ubicaciones/fusionar/', views.fusionar, name='ubicaciones-fusionar'),

    # Histórico
    path('ubicaciones/movimientos/', views.lista_movimientos, name='ubicaciones-movimientos'),

    # Producto → sus ubicaciones
    path('ubicaciones/productos/<str:codigo>/', views.producto_ubicaciones, name='ubicaciones-producto-detalle'),

    # Fragmentos htmx
    path('ubicaciones/buscar-ubicacion/', views.buscar_ubicacion_fragment, name='ubicaciones-buscar-ubicacion'),
    path('ubicaciones/buscar-producto/', views.buscar_producto_dbisam_fragment, name='ubicaciones-buscar-producto'),
]
