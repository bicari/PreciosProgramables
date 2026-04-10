from django.urls import path
from . import views

urlpatterns = [
    path('pedidos/', views.lista_pedidos, name='pedidos-lista'),
    path('pedidos/crear/', views.crear_pedido, name='pedidos-crear'),
    path('pedidos/<int:pk>/', views.detalle_pedido, name='pedidos-detalle'),
    path('pedidos/<int:pk>/despachar/', views.despachar_pedido, name='pedidos-despachar'),
    path('pedidos/<int:pk>/recibir/', views.recibir_pedido, name='pedidos-recibir'),
    path('pedidos/buscar-producto/', views.buscar_producto, name='pedidos-buscar-producto'),
    path('pedidos/pendientes-count/', views.contar_pendientes, name='pedidos-pendientes-count'),
    path('pedidos/reporte/', views.reporte_pedidos, name='pedidos-reporte'),
    path('pedidos/reporte/pdf/', views.exportar_reporte_pdf, name='pedidos-reporte-pdf'),
]
