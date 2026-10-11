from django.db import models
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.conf import settings
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .push import agendar_push


# 0. CLUBES (TENANT)
class Clube(models.Model):
    """Clube de desbravadores (tenant): unidades, usuários, eventos e notificações pertencem a um clube."""

    nome = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    logo = models.ImageField(upload_to='clubes/logos/', null=True, blank=True)
    cor_principal = models.CharField(max_length=7, default='#0d47a1', verbose_name="Cor principal (hex)")
    ativo = models.BooleanField(default=True)
    data_criacao = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Clube"
        verbose_name_plural = "Clubes"

    def __str__(self):
        return self.nome


# 1. UNIDADES
class Unidade(models.Model):
    """Unidade do clube, que agrupa desbravadores; o campo cor guarda a classe CSS usada na interface."""

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

    clube = models.ForeignKey(Clube, on_delete=models.CASCADE, related_name='unidades')
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
class UsuarioManager(UserManager):
    """Aceita o clube como instância ou como id (o createsuperuser passa o id digitado)."""

    def _create_user_object(self, username, email, password, **extra_fields):
        clube = extra_fields.get('clube')
        # models.Model (e não Clube): em migrations o clube é uma instância do modelo histórico
        if clube is not None and not isinstance(clube, models.Model):
            extra_fields['clube_id'] = extra_fields.pop('clube')
        return super()._create_user_object(username, email, password, **extra_fields)


class Usuario(AbstractUser):
    """Usuário do sistema (liderança do clube), com cargo, unidade responsável e flags de aprovação e diretoria."""

    class Cargos(models.TextChoices):
        DIRETOR = 'DIR', 'Diretor (Acesso Total)'
        VICE = 'VICE', 'Vice-Diretor (Acesso Total)'
        CAPELAO = 'CAP', 'Capelão (Acesso Supremo)'
        CONSELHEIRO = 'CONS', 'Conselheiro'
        INSTRUTOR = 'INST', 'Instrutor'
        SECRETARIO = 'SEC', 'Secretário'

    clube = models.ForeignKey(Clube, on_delete=models.CASCADE, related_name='usuarios')
    cargo = models.CharField(max_length=4, choices=Cargos.choices, default=Cargos.CONSELHEIRO)
    status_aprovado = models.BooleanField(default=False, verbose_name="Acesso Aprovado?")
    unidade_responsavel = models.ForeignKey(
        Unidade, on_delete=models.SET_NULL, null=True, blank=True, related_name='conselheiros'
    )
    is_diretoria = models.BooleanField(default=False, verbose_name="É Diretoria?")

    objects = UsuarioManager()

    # Todo usuário pertence a um clube: o createsuperuser também pede o clube (id)
    REQUIRED_FIELDS = AbstractUser.REQUIRED_FIELDS + ['clube']

    def clean(self):
        super().clean()
        # A unidade pela qual o usuário responde precisa ser do clube dele
        if (self.unidade_responsavel_id and self.clube_id
                and self.unidade_responsavel.clube_id != self.clube_id):
            raise ValidationError({'unidade_responsavel': 'Escolha uma unidade do clube do usuário.'})

    def __str__(self):
        return f"{self.username} - {self.get_cargo_display()}"


# 3. DESBRAVADORES
class Desbravador(models.Model):
    """Desbravador (membro do clube) vinculado a uma unidade, com situação de ativo e aprovação pela diretoria."""

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
    """Avaliação semanal de um desbravador, com a pontuação (0, 5 ou 10) de cada critério."""

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

    clube_visivel = models.IntegerField(
        choices=OPCOES_PONTOS_BOOL, default=0, verbose_name="Clube Visível (Uniforme na Igreja)"
    )
    estudo_biblico = models.IntegerField(choices=OPCOES_PONTOS_BOOL, default=0, verbose_name="Estudo Bíblico")
    escola_sabatina = models.IntegerField(choices=OPCOES_PONTOS_BOOL, default=0, verbose_name="Escola Sabatina")

    pequeno_grupo = models.IntegerField(choices=OPCOES_PONTOS_BOOL, default=0, verbose_name="Pequeno Grupo")
    fanfarra = models.IntegerField(choices=OPCOES_PONTOS, default=0, verbose_name="Ensaio da Fanfarra")
    ordem_unida = models.IntegerField(choices=OPCOES_PONTOS, default=0, verbose_name="Ensaio de Ordem Unida")

    observacao = models.TextField(blank=True, null=True, verbose_name="Observação")

    @property
    def total_semanal(self):
        """Soma os pontos de todos os critérios desta avaliação."""
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
    """Pontos extras dados a um desbravador, com o motivo; valores negativos descontam pontos."""

    desbravador = models.ForeignKey(Desbravador, on_delete=models.CASCADE, related_name='pontos_extras')
    autor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True)
    data = models.DateField(default=timezone.now)
    motivo = models.CharField(max_length=100)
    pontos = models.IntegerField(help_text="Use negativo para tirar pontos (Ex: -10)")

    def __str__(self):
        return f"{self.pontos} pts - {self.motivo}"


# 6. ANOTAÇÕES
class AnotacaoDisciplinar(models.Model):
    """Anotação disciplinar registrada por um usuário sobre um desbravador."""

    desbravador = models.ForeignKey(Desbravador, on_delete=models.CASCADE)
    autor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True)
    texto = models.TextField()
    data_criacao = models.DateTimeField(auto_now_add=True)
    visivel = models.BooleanField(default=True)

    def __str__(self):
        return f"Anotação - {self.desbravador.nome_completo}"


# 7. EVENTOS
class Evento(models.Model):
    """Evento do calendário, de uma unidade específica ou do clube todo (quando a unidade é nula)."""

    clube = models.ForeignKey(Clube, on_delete=models.CASCADE, related_name='eventos')
    titulo = models.CharField(max_length=100, verbose_name="Título")
    descricao = models.TextField(blank=True, null=True, verbose_name="Descrição")
    data_evento = models.DateField(verbose_name="Data do Evento")
    unidade = models.ForeignKey(Unidade, on_delete=models.CASCADE, related_name='eventos', null=True, blank=True)
    autor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True)

    def clean(self):
        super().clean()
        # Evento de unidade: a unidade precisa ser do mesmo clube do evento
        if self.unidade_id and self.clube_id and self.unidade.clube_id != self.clube_id:
            raise ValidationError({'unidade': 'Escolha uma unidade do clube do evento.'})

    def __str__(self):
        destino = self.unidade.nome if self.unidade else "CLUBE TODO"
        return f"[{destino}] {self.titulo} - {self.data_evento}"


# 8. CLASSES E ESPECIALIDADES
class Classe(models.Model):
    """Classe regular de desbravadores (Amigo, Companheiro, Pesquisador, Pioneiro, Excursionista ou Guia)."""

    NOME_CLASSES = [
        ('AM', 'Amigo'), ('AP', 'Companheiro'), ('PE', 'Pesquisador'),
        ('PI', 'Pioneiro'), ('EX', 'Excursionista'), ('GU', 'Guia'),
    ]
    nome = models.CharField(max_length=2, choices=NOME_CLASSES, unique=True)
    cor_referencia = models.CharField(max_length=20, default="blue")

    def __str__(self):
        return self.get_nome_display()


class Especialidade(models.Model):
    """Especialidade de desbravadores, classificada por categoria."""

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
    """Conquista de um desbravador: conclusão de uma classe ou de uma especialidade."""

    desbravador = models.ForeignKey(Desbravador, on_delete=models.CASCADE, related_name='conquistas')
    classe = models.ForeignKey(Classe, on_delete=models.CASCADE, null=True, blank=True)
    especialidade = models.ForeignKey(Especialidade, on_delete=models.CASCADE, null=True, blank=True)
    data_conclusao = models.DateField(default=timezone.now)
    instrutor = models.ForeignKey(Usuario, on_delete=models.SET_NULL, null=True)

    def __str__(self):
        item = self.classe.nome if self.classe else self.especialidade.nome
        return f"{self.desbravador.nome_completo} - {item}"


class NotificacaoManual(models.Model):
    """Notificação manual para vários usuários; adicionar destinatários aciona processar_disparo_notificacao."""

    clube = models.ForeignKey(Clube, on_delete=models.CASCADE, related_name='notificacoes')
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
    """Aviso exibido na central de notificações do app para um usuário, marcado como lido ou não."""

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
    """Dispara uma NotificacaoManual para os destinatários recém-adicionados (action post_add).

    Cria os avisos in-app (NotificacaoInApp) de uma vez e agenda o web push para depois do commit:
    o envio roda fora da requisição e da transação, com timeout (ver core/push.py).
    """
    if action != "post_add" or not pk_set:
        return
    if kwargs.get('reverse'):
        # usuario.notificacaomanual_set.add(...): instance é o usuário e pk_set são notificações
        envios = [(n, [instance.pk]) for n in NotificacaoManual.objects.filter(pk__in=pk_set)]
    else:
        envios = [(instance, pk_set)]

    for notificacao, usuario_ids in envios:
        NotificacaoInApp.objects.bulk_create([
            NotificacaoInApp(usuario_id=uid, titulo=notificacao.titulo, mensagem=notificacao.mensagem)
            for uid in usuario_ids
        ])
        # Aponta direto para a rota de notificações cheia
        agendar_push(usuario_ids, {
            "head": notificacao.titulo,
            "body": notificacao.mensagem,
            "url": "/notificacoes/",
        })
