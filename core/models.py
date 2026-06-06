from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.conf import settings
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from webpush import send_user_notification
import logging

# 1. UNIDADES
class Unidade(models.Model):
    CORES_CHOICES = [
        ('bg-primary', 'Azul (Padrão)'),
        ('bg-danger', 'Vermelho'),
        ('bg-success', 'Verde'),
        ('bg-warning text-dark', 'Amarelo'),
        ('bg-info text-dark', 'Ciano/Azul Claro'),
        ('bg-dark', 'Preto/Cinza Escuro'),
        ('bg-rosa', 'Rosa (Safira)'),       
        ('bg-roxo', 'Roxo'),               
        ('bg-laranja', 'Laranja'),         
    ]

    nome = models.CharField(max_length=50)
    cor = models.CharField(
        max_length=30, 
        choices=CORES_CHOICES, 
        default='bg-primary',
        verbose_name="Cor da Unidade"
    )
    
    def __str__(self):
        return self.nome

# 2. USUÁRIOS
class Usuario(AbstractUser):
    class Cargos(models.TextChoices):
        DIRETOR = 'DIR', 'Diretor (Acesso Total)'
        VICE = 'VICE', 'Vice-Diretor (Acesso Total)'
        CAPELAO = 'CAP', 'Capelão (Acesso Supremo)'
        CONSELHEIRO = 'CONS', 'Conselheiro'
        INSTRUTOR = 'INST', 'Instrutor'
        SECRETARIO = 'SEC', 'Secretário'

    cargo = models.CharField(max_length=4, choices=Cargos.choices, default=Cargos.CONSELHEIRO)
    status_aprovado = models.BooleanField(default=False, verbose_name="Acesso Aprovado?")
    unidade_responsavel = models.ForeignKey(Unidade, on_delete=models.SET_NULL, null=True, blank=True, related_name='conselheiros')
    is_diretoria = models.BooleanField(default=False, verbose_name="É Diretoria?")

    def __str__(self):
        return f"{self.username} - {self.get_cargo_display()}"

# 3. DESBRAVADORES
class Desbravador(models.Model):
    nome_completo = models.CharField(max_length=150)
    data_nascimento = models.DateField()
    unidade = models.ForeignKey(Unidade, on_delete=models.PROTECT, related_name='membros')
    ativo = models.BooleanField(default=True)
    aprovado = models.BooleanField(default=False, verbose_name="Aprovado pela Diretoria")
    anotacoes_gerais = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nome_completo

# 4. PONTUAÇÃO SEMANAL
class AvaliacaoSemanal(models.Model):
    OPCOES_PONTOS = [
        (0, '0 Pontos - Não fez/Não foi'),
        (5, '5 Pontos - Incompleto'),
        (10, '10 Pontos - Completo'),
    ]

    OPCOES_PONTOS_BOOL = [
        (0, '0 Pontos - Não fez/Não foi'),
        (10, '10 Pontos - Completo'),
    ]

    desbravador = models.ForeignKey(Desbravador, on_delete=models.CASCADE, related_name='avaliacoes')
    autor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True)
    data = models.DateField(default=timezone.now)
    
    biblia = models.IntegerField(choices=OPCOES_PONTOS_BOOL, default=0, verbose_name="Bíblia")
    uniforme = models.IntegerField(choices=OPCOES_PONTOS, default=0, verbose_name="Uniforme Completo")
    lenco = models.IntegerField(choices=OPCOES_PONTOS_BOOL, default=0, verbose_name="Lenço") 
    fazer_ideal = models.IntegerField(choices=OPCOES_PONTOS_BOOL, default=0, verbose_name="Fazer o Ideal (Voto/Lei)")
    orar = models.IntegerField(choices=OPCOES_PONTOS_BOOL, default=0, verbose_name="Orar")
    participacao = models.IntegerField(choices=OPCOES_PONTOS, default=0, verbose_name="Participação Ativa")
    itens_cartao = models.IntegerField(choices=OPCOES_PONTOS, default=0, verbose_name="Itens do Cartão/Classe")

    clube_visivel = models.IntegerField(choices=OPCOES_PONTOS_BOOL, default=0, verbose_name="Clube Visível (Uniforme na Igreja)")
    estudo_biblico = models.IntegerField(choices=OPCOES_PONTOS_BOOL, default=0, verbose_name="Estudo Bíblico")
    escola_sabatina = models.IntegerField(choices=OPCOES_PONTOS_BOOL, default=0, verbose_name="Escola Sabatina")

    pequeno_grupo = models.IntegerField(choices=OPCOES_PONTOS_BOOL, default=0, verbose_name="Pequeno Grupo")
    fanfarra = models.IntegerField(choices=OPCOES_PONTOS, default=0, verbose_name="Ensaio da Fanfarra")
    ordem_unida = models.IntegerField(choices=OPCOES_PONTOS, default=0, verbose_name="Ensaio de Ordem Unida")
    
    observacao = models.TextField(blank=True, null=True, verbose_name="Observação")

    @property
    def total_semanal(self):
        campos = [
            self.biblia, self.uniforme, self.lenco, self.fazer_ideal, 
            self.orar, self.participacao, self.itens_cartao,
            self.clube_visivel, self.estudo_biblico, self.escola_sabatina,
            self.pequeno_grupo, self.fanfarra, self.ordem_unida
        ]
        return sum(campos)

    class Meta:
        verbose_name = "Avaliação Semanal"
        verbose_name_plural = "Avaliações Semanais"

# 5. PONTOS EXTRAS
class PontoExtra(models.Model):
    desbravador = models.ForeignKey(Desbravador, on_delete=models.CASCADE, related_name='pontos_extras')
    autor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True)
    data = models.DateField(default=timezone.now)
    motivo = models.CharField(max_length=100)
    pontos = models.IntegerField(help_text="Use negativo para tirar pontos (Ex: -10)")

    def __str__(self):
        return f"{self.pontos} pts - {self.motivo}"

# 6. ANOTAÇÕES
class AnotacaoDisciplinar(models.Model):
    desbravador = models.ForeignKey(Desbravador, on_delete=models.CASCADE)
    autor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True)
    texto = models.TextField()
    data_criacao = models.DateTimeField(auto_now_add=True)
    visivel = models.BooleanField(default=True)

    def __str__(self):
        return f"Anotação - {self.desbravador.nome_completo}"

# 7. EVENTOS
class Evento(models.Model):
    titulo = models.CharField(max_length=100, verbose_name="Título")
    descricao = models.TextField(blank=True, null=True, verbose_name="Descrição")
    data_evento = models.DateField(verbose_name="Data do Evento")
    unidade = models.ForeignKey(Unidade, on_delete=models.CASCADE, related_name='eventos', null=True, blank=True)
    autor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        destino = self.unidade.nome if self.unidade else "CLUBE TODO"
        return f"[{destino}] {self.titulo} - {self.data_evento}"

# 8. CLASSES E ESPECIALIDADES
class Classe(models.Model):
    NOME_CLASSES = [
        ('AM', 'Amigo'), ('AP', 'Companheiro'), ('PE', 'Pesquisador'),
        ('PI', 'Pioneiro'), ('EX', 'Excursionista'), ('GU', 'Guia'),
    ]
    nome = models.CharField(max_length=2, choices=NOME_CLASSES, unique=True)
    cor_referencia = models.CharField(max_length=20, default="blue")

    def __str__(self):
        return self.get_nome_display()

class Especialidade(models.Model):
    CATEGORIAS = [
        ('AD', 'ADRA'), ('AA', 'Artes'), ('AV', 'Agro'), 
        ('AM', 'Missionárias'), ('AR', 'Recreativas'), ('CS', 'Saúde'),
        ('EN', 'Ecologia'), ('HM', 'Domésticas'), ('OT', 'Outros'),
    ]
    nome = models.CharField(max_length=100)
    categoria = models.CharField(max_length=2, choices=CATEGORIAS)
    
    def __str__(self):
        return self.nome

class ConquistaMembro(models.Model):
    desbravador = models.ForeignKey(Desbravador, on_delete=models.CASCADE, related_name='conquistas')
    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, null=True, blank=True)
    especialidade = models.ForeignKey(Especialidade, on_delete=models.CASCADE, null=True, blank=True)
    data_conclusao = models.DateField(default=timezone.now)
    instrutor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        item = self.classe.nome if self.classe else self.especialidade.nome
        return f"{self.desbravador.nome_completo} - {item}"
    
class NotificacaoManual(models.Model):
    titulo = models.CharField(max_length=100, verbose_name="Título do Alerta")
    mensagem = models.TextField(verbose_name="Conteúdo da Mensagem")
    destinatarios = models.ManyToManyField(settings.AUTH_USER_MODEL, verbose_name="Enviar para os Usuários")
    criado_em = models.DateTimeField(auto_now_add=True, verbose_name="Disparado em")

    class Meta:
        verbose_name = "Notificação Manual"
        verbose_name_plural = "Notificações Manuais"
    def __str__(self):
        return self.titulo

# 9. CENTRAL DE AVISOS NO APP
class NotificacaoInApp(models.Model):
    usuario = models.ForeignKey(Usuario, on_delete=models.CASCADE, related_name='notificacoes_inapp')
    titulo = models.CharField(max_length=100)
    mensagem = models.TextField()
    lida = models.BooleanField(default=False)
    data_criacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Aviso do Sistema"
        verbose_name_plural = "Avisos do Sistema"
        ordering = ['-data_criacao']

    def __str__(self):
        return f"[{'LIDA' if self.lida else 'NOVA'}] {self.usuario.username} - {self.titulo}"

# --- SINAL AUTOMATIZADOR ROBUSTO ---
@receiver(m2m_changed, sender=NotificacaoManual.destinatarios.through)
def processar_disparo_notificacao(sender, instance, action, pk_set, **kwargs):
    if action == "post_add":
        for user_id in pk_set:
            user = Usuario.objects.get(id=user_id)
            
            NotificacaoInApp.objects.get_or_create(
                usuario=user,
                titulo=instance.titulo,
                mensagem=instance.mensagem,
                data_criacao=instance.criado_em
            )
            
            # MUDANÇA SÊNIOR: Aponta direto para a rota de notificações cheia
            payload = {
                "head": instance.titulo,
                "body": instance.mensagem,
                "url": "/notificacoes/"
            }
            try:
                send_user_notification(user=user, payload=payload, ttl=1000)
            except Exception as e:
                logger.error(f"Falha ao enviar push notification para {user.username}: {e}")