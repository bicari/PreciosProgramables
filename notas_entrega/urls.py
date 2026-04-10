from django.urls import path
from .views import * # render_notas_entrega, search_product_by_code, delete_product, search_product_by_description, modal_search, search_order, search_proveedor, procesar_recepcion, obtener_confirmacion, search_proveedor_by_description, modal_search_proveedor
urlpatterns = [
    path('notas-entrega/', render_notas_entrega, name='notas-entrega'),
    path('search-product/', search_product_by_code, name='search-product'),
    path('search-product-description/', search_product_by_description, name='search-product-description'),
    path("search-proveedor-by-description/", search_proveedor_by_description, name="search-proveedor-by-description"),
    path("modal_search", modal_search, name="modal-search"),
    path("modal_search_proveedor", modal_search_proveedor, name="modal-search-proveedor"),
    path('search-order/', search_order, name='search-order'),
    path('product-delete/', delete_product, name='product-delete'),
    path('search-proveedor/', search_proveedor, name='search-proveedor'),
    path('procesar-recepcion/', procesar_recepcion, name='procesar-recepcion'),
    path('confirmar-nota-entrega/', obtener_confirmacion, name='confirmar-nota-entrega'),
    path('consultar-notas/', consultar_notas, name='consultar-notas'),
]
