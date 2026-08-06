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
]
