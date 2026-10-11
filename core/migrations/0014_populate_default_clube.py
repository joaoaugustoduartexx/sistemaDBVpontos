"""Migração de dados: cria o clube padrão e vincula a ele todos os registros.

Roda entre a criação das FKs `clube` (ainda nulas, 0013) e a migração que as
torna obrigatórias (NOT NULL). Nenhum registro pode ficar sem clube, senão a
próxima migração falha.
"""
from django.db import migrations

CLUBE_PADRAO_SLUG = 'jovens-do-rei'
CLUBE_PADRAO_NOME = 'Jovens do Rei'
MODELOS_COM_CLUBE = ('Unidade', 'Usuario', 'Evento', 'NotificacaoManual')


def popular_clube_padrao(apps, schema_editor):
    """Cria (se preciso) o clube padrão e atribui a ele os registros sem clube."""
    db = schema_editor.connection.alias
    Clube = apps.get_model('core', 'Clube')
    clube, _ = Clube.objects.using(db).get_or_create(
        slug=CLUBE_PADRAO_SLUG, defaults={'nome': CLUBE_PADRAO_NOME}
    )
    for nome_modelo in MODELOS_COM_CLUBE:
        Modelo = apps.get_model('core', nome_modelo)
        Modelo.objects.using(db).filter(clube__isnull=True).update(clube=clube)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_clube_evento_clube_notificacaomanual_clube_and_more'),
    ]

    operations = [
        # Reverter não precisa desfazer nada: reverter a 0013 remove as colunas
        migrations.RunPython(popular_clube_padrao, migrations.RunPython.noop),
    ]
