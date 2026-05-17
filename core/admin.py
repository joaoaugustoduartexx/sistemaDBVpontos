from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario, Unidade, Desbravador, PontoExtra, AvaliacaoSemanal, Evento, NotificacaoManual
from webpush import send_user_notification

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

@admin.register(NotificacaoManual)
class NotificacaoManualAdmin(admin.ModelAdmin):
    list_display = ('titulo', 'criado_em')
    filter_horizontal = ('destinatarios',) 

    # TROCAMOS AQUI: Usamos o save_related em vez do save_model
    def save_related(self, request, form, formsets, change):
        # 1. Primeiro, deixamos o Django salvar a mensagem E a lista de usuários no banco
        super().save_related(request, form, formsets, change)
        
        # 2. Agora pegamos o objeto recém-salvo (com os usuários já atrelados a ele!)
        obj = form.instance
        
        payload = {
            "head": obj.titulo,
            "body": obj.mensagem
        }
        
        # 3. Dispara o Push (agora a lista não está mais vazia!)
        for usuario in obj.destinatarios.all():
            try:
                send_user_notification(user=usuario, payload=payload, ttl=1000)
            except Exception as e:
                # Se falhar, vai imprimir o erro no terminal preto onde o servidor está rodando
                print(f"Erro ao enviar webpush para {usuario}: {e}")