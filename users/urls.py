from django.urls import path
from .views import LoginView, DashboardView, LogoutView

urlpatterns= [
    path('login/', LoginView, name='login'),
    path('dashboard/', DashboardView, name='dashboard'),
    path('logout/', LogoutView, name='logout')

]