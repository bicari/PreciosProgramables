from django.urls import path
from . import api_views

urlpatterns = [
    path('login/', api_views.api_login, name='api-login'),
    path('logout/', api_views.api_logout, name='api-logout'),
    path('me/', api_views.api_me, name='api-me'),
    path('users/', api_views.api_users_list, name='api-users-list'),
]
