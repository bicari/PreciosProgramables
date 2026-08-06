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
]
