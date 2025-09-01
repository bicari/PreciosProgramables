from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from .models import User

@admin.register(User)
class UserAdmin(UserAdmin):
    add_form = UserCreationForm
    form = UserChangeForm
    model = User
    list_display = ('username', 'status', 'is_staff', 'is_superuser')
    list_filter = ('status', 'is_staff', 'is_superuser')
    list_editable = ('status',)
    search_fields = ('username',)
    ordering = ('username',)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Permisos", {"fields": ("is_staff", "is_superuser", "status", "groups", "user_permissions")}),
    )

    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "password1", "password2", "is_staff", "is_superuser", "groups", "user_permissions")}
        ),
    )



    #def save_model(self, request, obj, form, change):
    #    if 'password' in form.changed_data:
    #        obj.set_password(form.cleaned_data['password'])
    #    super().save_model(request, obj, form, change)
# Register your models here.
