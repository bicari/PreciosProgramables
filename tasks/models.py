from django.db import models
from users.models import User
from django.core.validators import  RegexValidator

class Tasks(models.Model):
    def user_directory_path(instance, filename ):
        return 'uploads/%s/%s' %(instance.user_id.username, filename)

    task_number = models.AutoField(primary_key=True, unique=True, editable=False)
    user_id = models.ForeignKey(User, on_delete=models.CASCADE, max_length=100)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # rif_proveedor = models.CharField(
    #     max_length=10,
    #     validators=[
    #         RegexValidator(
    #             regex=r'^[JGVE][0-9]{9}$',
    #             message='El RIF debe comenzar con J, G, V, E seguido de 9 dígitos.',
    #             code='invalid_rif'
    #         )
    #     ]
    # )
    is_oferta = models.BooleanField(default=False)
    header_file = models.IntegerField(blank=True, null=True)
    file = models.FileField(upload_to=user_directory_path, blank=False, null=True
                            )
    dbisam_table = models.CharField(max_length=100, blank=True, null=True)
    date_to_execute = models.DateField(blank=False)
    status = models.BooleanField(default=True)
    check_process = models.BooleanField(default=False)
    
    

    def __str__(self):
        return str(self.task_number)
    

class ProductsTasks(models.Model):
    task = models.ForeignKey(Tasks, on_delete=models.CASCADE, related_name='products_tasks')
    sku = models.CharField(max_length=100)
    #precio = models.DecimalField(max_digits=10, decimal_places=2)
    #descripcion = models.TextField(blank=True, null=True)
    fecha_ejecucion = models.DateTimeField(default=None, blank=True, null=True)
    
    #precioantes = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    #codbarra = models.CharField(max_length=100, blank=True, null=True)
    #departamento = models.CharField(max_length=100, blank=True, null=True)
    is_oferta = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.sku} - {self.task.task_number}"    
# Create your models here.
