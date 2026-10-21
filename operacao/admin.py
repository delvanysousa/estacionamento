from django.contrib import admin

from .models import Andar, Carro


@admin.register(Andar)
class AndarAdmin(admin.ModelAdmin):
    list_display = ["numero", "capacidade", "ativo"]
    list_editable = ["capacidade", "ativo"]


@admin.register(Carro)
class CarroAdmin(admin.ModelAdmin):
    list_display = ["placa", "ticket", "andar", "status", "recebido_por", "recebido_em"]
    list_filter = ["status", "andar"]
    search_fields = ["placa", "ticket"]
