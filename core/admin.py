from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Clube, Usuario, Unidade, Desbravador, PontoExtra, AvaliacaoSemanal, Evento, NotificacaoManual

# Tenta desregistrar para evitar o erro "AlreadyRegistered" caso o Django recarregue
try:
    admin.site.unregister(Usuario)
except admin.sites.NotRegistered:
    pass


class CustomUserAdmin(UserAdmin):
    # Adicionamos os campos personalizados ao formulário do Admin
    fieldsets = UserAdmin.fieldsets + (
        ('Cargos e Permissões do Clube', {'fields': ('clube', 'is_diretoria', 'unidade_responsavel')}),
    )

    # Todo usuário pertence a um clube (campo obrigatório): pedimos já na criação
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Clube', {'fields': ('clube',)}),
    )

    # O que aparece na tabela de usuários
    list_display = ('username', 'email', 'first_name', 'clube', 'is_diretoria', 'unidade_responsavel')

    # Filtros laterais (AGORA FUNCIONA pois is_diretoria é um campo real no models.py)
    list_filter = ('clube', 'is_diretoria', 'unidade_responsavel', 'is_staff')


@admin.register(Clube)
class ClubeAdmin(admin.ModelAdmin):
    list_display = ('nome', 'slug', 'ativo', 'data_criacao')
    prepopulated_fields = {'slug': ('nome',)}


@admin.register(Unidade)
class UnidadeAdmin(admin.ModelAdmin):
    list_display = ('nome', 'clube')
    list_filter = ('clube',)

    def get_readonly_fields(self, request, obj=None):
        # A unidade não muda de clube: conselheiros e eventos dela ficariam no clube antigo
        return ('clube',) if obj else ()


# Registra tudo
admin.site.register(Usuario, CustomUserAdmin)
admin.site.register(Desbravador)
admin.site.register(PontoExtra)
admin.site.register(AvaliacaoSemanal)
admin.site.register(Evento)


@admin.register(NotificacaoManual)
class NotificacaoManualAdmin(admin.ModelAdmin):
    # O push sai só pelo sinal m2m_changed (core/models.py), depois do commit:
    # sem envio aqui, cada destinatário recebe a notificação uma única vez
    list_display = ('titulo', 'clube', 'criado_em')
    filter_horizontal = ('destinatarios',)
