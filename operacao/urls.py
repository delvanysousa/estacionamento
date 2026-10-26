from django.urls import path

from . import views

urlpatterns = [
    path("", views.painel, name="painel"),
    path("receber/", views.receber, name="receber"),
    path("andar/<int:numero>/", views.andar_detalhe, name="andar"),
    path("pagos/", views.pagos, name="pagos"),
    path("telao/", views.telao, name="telao"),
    path("telao/dados/", views.telao_dados, name="telao_dados"),
    path("busca/", views.busca, name="busca"),
    path("relatorios/", views.relatorios, name="relatorios"),
    path("relatorios/exportar/<str:formato>/", views.exportar, name="exportar"),
    path("usuarios/", views.usuarios, name="usuarios"),
    path("usuarios/novo/", views.usuario_form, name="usuario_novo"),
    path("usuarios/<int:pk>/", views.usuario_form, name="usuario_editar"),
    path("carro/<int:pk>/<str:acao>/", views.acao, name="acao"),
]
