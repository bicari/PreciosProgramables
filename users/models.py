from django.contrib.auth.models import  AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.contrib.auth.hashers import make_password, check_password


class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('El nombre de usuario es obligatorio')
        user = self.model(username=username, **extra_fields)
        user.set_password(password)  # Esto hashea la contraseña
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('El superusuario debe tener is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('El superusuario debe tener is_superuser=True.')

        return self.create_user(username, password, **extra_fields)

# Create your models here.
class User(AbstractBaseUser, PermissionsMixin):
    username = models.CharField(max_length=150, unique=True)
    password = models.CharField(max_length=128)
    status   = models.BooleanField(default=True)
    last_login = models.DateTimeField(blank=True, null=True, verbose_name='last login')
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)
    objects = UserManager()
    USERNAME_FIELD = 'username' 

    def __str__(self):
        return self.username
    
    
    
    

    # class Meta:
    #     verbose_name = 'User'
    #     verbose_name_plural = 'Users'
    #     ordering = ['username']