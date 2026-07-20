from django.shortcuts import render, redirect
from django.http import request
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .models import User as User_Model


# Create your views here.
def LoginView(request: request):
    if request.method == 'GET':
        return render(request, 'login.html')
    user = request.POST.get('username', '').strip()
    password = request.POST.get('password', '')
    if not user or not password:
        messages.error(request, 'Usuario o contraseña incorrectos')
        return redirect('login')
    user_auth = authenticate(request, username=user, password=password)
    if user_auth is not None:
        login(request, user_auth)
        return redirect('dashboard')
    messages.error(request, 'Usuario o contraseña incorrectos')
    return redirect('login')

def LogoutView(request: request):
    logout(request)
    return redirect('login')

@login_required(login_url='/login/')
def DashboardView(request: request):
    print(request.user)
    
    return render(request, 'dashboard.html', context={'user': request.user})
    