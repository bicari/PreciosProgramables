from django.shortcuts import render, redirect
from django.http import request
from django.contrib.auth.decorators import login_required
#from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from .models import User as User_Model
#from django.contrib.auth.hashers import make_password, check_password


# Create your views here.
def LoginView(request: request):
    #USER_PERMISSIONS = ['carlos', 'admin2', 'pedro', 'juan']
    if request.method == 'GET':
        return render(request, 'login.html')
    else:
        user, password = request.POST['username'].lower(), request.POST['password']
        user_auth = authenticate(request, username=user, password=password)
        print(user_auth)
        # For debugging purposes, print the received username and password
        if user_auth is not None:
            #user_created = User_Model.objects.create_user(username=user, password=password)# Crear un nuevo usuario
            #print(user_created)
            login(request, user_auth)  # Log the user in
            return redirect('dashboard')
        else:
            return render(request, 'login.html', context={'error': 'Usuario o contraseña incorrectos'})

def LogoutView(request: request):
    logout(request)
    return redirect('login')

@login_required(login_url='/login/')
def DashboardView(request: request):
    print(request.user)
    
    return render(request, 'dashboard.html', context={'user': request.user})
    