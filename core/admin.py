from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, Unidade, Desbravador, PontoExtra, AvaliacaoSemanal, Evento

# Tenta desregistrar para evitar o erro "AlreadyRegistered" caso o Django recarregue
try:
    admin.site.unregister(Usuario)
except admin.sites.NotRegistered:
    pass

class CustomUserAdmin(UserAdmin):
    # Adicionamos os campos personalizados ao formulário do Admin
    fieldsets = UserAdmin.fieldsets + (
        ('Cargos e Permissões do Clube', {'fields': ('is_diretoria', 'unidade_responsavel')}),
    )
    
    # O que aparece na tabela de usuários
    list_display = ('username', 'email', 'first_name', 'is_diretoria', 'unidade_responsavel')
    
    # Filtros laterais (AGORA FUNCIONA pois is_diretoria é um campo real no models.py)
    list_filter = ('is_diretoria', 'unidade_responsavel', 'is_staff')

# Registra tudo
admin.site.register(Usuario, CustomUserAdmin)
admin.site.register(Unidade)
admin.site.register(Desbravador)
admin.site.register(PontoExtra)
admin.site.register(AvaliacaoSemanal)
admin.site.register(Evento)