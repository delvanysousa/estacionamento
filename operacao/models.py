from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q
from django.utils import timezone

ATIVOS = ["ESTACIONADO", "PAGO", "EM_RETIRADA"]


class Andar(models.Model):
    numero = models.PositiveIntegerField("Subsolo", unique=True)
    capacidade = models.PositiveIntegerField("Capacidade (carros)", default=0)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ["numero"]

    def __str__(self):
        return f"{self.numero}º subsolo"

    def ocupados(self):
        return self.carros.filter(status__in=ATIVOS).count()

    def livres(self):
        return max(self.capacidade - self.ocupados(), 0)

    def cheio(self):
        return self.livres() == 0

    def percentual(self):
        if not self.capacidade:
            return 100
        return min(100, round(self.ocupados() * 100 / self.capacidade))

    def cor(self):
        if self.cheio():
            return "vermelho"
        return "amarelo" if self.percentual() >= 80 else "verde"


class Carro(models.Model):
    STATUS = [
        ("ESTACIONADO", "Estacionado"),
        ("PAGO", "Pago - pode subir"),
        ("EM_RETIRADA", "Em retirada"),
        ("ENTREGUE", "Entregue"),
    ]
    ticket = models.CharField(max_length=30)
    placa = models.CharField(max_length=7, blank=True, default="")
    andar = models.ForeignKey(Andar, on_delete=models.PROTECT, related_name="carros")
    status = models.CharField(max_length=12, choices=STATUS, default="ESTACIONADO")
    recebido_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name="carros_recebidos")
    desceu_por = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="carros_descidos")
    recebido_em = models.DateTimeField(default=timezone.now)
    pago_por = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="carros_pagos")
    pago_em = models.DateTimeField(null=True, blank=True)
    retirado_por = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name="carros_retirados")
    retirada_em = models.DateTimeField(null=True, blank=True)
    entregue_em = models.DateTimeField(null=True, blank=True)
    historico = models.TextField(blank=True)

    class Meta:
        ordering = ["-recebido_em"]
        permissions = [
            ("registrar_entrada", "Pode receber carro (registrar entrada)"),
            ("usar_saida", "Pode consultar carros e usar a tela Saída"),
            ("marcar_pago", "Pode marcar carro como pago"),
            ("marcar_entregue", "Pode marcar carro como entregue"),
            ("ver_relatorios", "Pode ver relatórios"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["ticket"],
                condition=~Q(status="ENTREGUE"),
                name="ticket_unico_entre_ativos",
            )
        ]

    def __str__(self):
        return f"{self.placa} (ticket {self.ticket})"

    @property
    def quem_desceu(self):
        return self.desceu_por or self.recebido_por
