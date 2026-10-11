"""Testes de regressão de segurança do painel da diretoria.

Cobrem as correções das Fases 1 e 1.5: ações destrutivas somente via POST
com CSRF, autorização (inclusive a proteção de superusuários), senha
aleatória no reset, recusa apenas de cadastros pendentes, pontos em massa
sem duplicidade e renderização segura do painel (sem XSS e sem links GET
para ações destrutivas).

E a Fase 2 (multi-tenant): o modelo Clube, a migração que leva os dados
existentes para o clube padrão e o isolamento entre clubes (nenhuma view
ou formulário enxerga ou altera dados de outro clube).
"""
import html
import inspect
import re
import secrets
import string
from datetime import date
from html.parser import HTMLParser
from io import StringIO
from unittest import mock

from django.conf import settings
from django.contrib.messages import constants as msg_constants
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, models, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import (
    Client, TestCase, TransactionTestCase, override_settings,
)
from django.urls import reverse
from django.utils import timezone

from . import views as core_views
from .forms import AvaliacaoForm, DesbravadorForm, EventoForm, PontoExtraForm
from .models import (
    AvaliacaoSemanal, Clube, Desbravador, Evento, NotificacaoInApp,
    NotificacaoManual, PontoExtra, Unidade, Usuario,
)

ALFANUMERICOS = set(string.ascii_letters + string.digits)
MSG_SENHA = 'Senha redefinida com sucesso. Nova senha: '
MSG_APROVADO = 'Membros já aprovados não podem ser excluídos.'
MSG_ADMIN = 'Sem permissão para alterar um administrador do sistema.'
NOME_XSS = 'Teste\'); window.__xss=1; //<b>x</b>"'
ACAO_DESTRUTIVA_RE = re.compile(
    r'/diretoria/(acesso|reset-senha|aprovar|recusar)/(\d+)/'
)
HASHER_RAPIDO = ['django.contrib.auth.hashers.MD5PasswordHasher']
TAGS_SEM_FECHAMENTO = {
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
    'meta', 'param', 'source', 'track', 'wbr',
}


def mensagens(response):
    """Mensagens (nível, texto) adicionadas durante a requisição."""
    storage = get_messages(response.wsgi_request)
    return [(m.level, m.message) for m in storage]


class PainelParser(HTMLParser):
    """Coleta forms (com inputs/botões), links, botões, ids e scripts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self.form_stack = []
        self.nested_forms = []
        self.anchors = []
        self.buttons = []
        self.ids = []
        self.event_attrs = []  # (tag, atributo, valor, linha)
        self.scripts = []
        self._in_script = False
        self.stack = []  # (tag, attrs)

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else '') for k, v in attrs}
        line = self.getpos()[0]
        parent = self.stack[-1] if self.stack else (None, {})
        if 'id' in a:
            self.ids.append(a['id'])
        for k, v in a.items():
            if k.lower().startswith('on'):
                self.event_attrs.append((tag, k, v, line))
        if tag == 'form':
            if self.form_stack:
                externo = self.forms[self.form_stack[-1]]['attrs']
                self.nested_forms.append((line, a, externo))
            self.forms.append(
                {'attrs': a, 'inputs': [], 'buttons': [], 'line': line}
            )
            self.form_stack.append(len(self.forms) - 1)
        elif tag == 'input':
            if self.form_stack:
                self.forms[self.form_stack[-1]]['inputs'].append(a)
        elif tag == 'button':
            enclosing = self.form_stack[-1] if self.form_stack else None
            b = {
                'attrs': a, 'enclosing': enclosing, 'line': line,
                'parent_tag': parent[0],
                'parent_class': parent[1].get('class', ''),
            }
            self.buttons.append(b)
            if enclosing is not None:
                self.forms[enclosing]['buttons'].append(b)
        elif tag == 'a':
            self.anchors.append((a, line))
        elif tag == 'script':
            self._in_script = True
            self.scripts.append('')
        if tag not in TAGS_SEM_FECHAMENTO:
            self.stack.append((tag, a))

    def handle_endtag(self, tag):
        if tag == 'form' and self.form_stack:
            self.form_stack.pop()
        if tag == 'script':
            self._in_script = False
        # desempilha até a tag correspondente
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if self._in_script and self.scripts:
            self.scripts[-1] += data


@override_settings(SECURE_SSL_REDIRECT=False, PASSWORD_HASHERS=HASHER_RAPIDO)
class PainelDiretoriaTestCase(TestCase):
    """Base com os dados compartilhados (não tem testes próprios).

    SECURE_SSL_REDIRECT=False deixa os testes independentes da variável
    DEBUG: com DEBUG desligado as settings ativam o redirect para HTTPS.
    """

    @classmethod
    def setUpTestData(cls):
        # Fase 2: todo dado pertence a um clube (tenant)
        cls.clube = Clube.objects.create(
            nome='Clube Teste', slug='clube-teste'
        )
        cls.unidade = Unidade.objects.create(
            nome='Águia', cor='bg-primary', clube=cls.clube
        )
        cls.diretor = Usuario.objects.create_user(
            'diretor', password='Pw-diretor-123', is_diretoria=True,
            clube=cls.clube,
        )
        cls.comum = Usuario.objects.create_user(
            'conselheiro', password='Pw-comum-123',
            unidade_responsavel=cls.unidade, clube=cls.clube,
        )
        cls.alvo = Usuario.objects.create_user(
            'alvo', password='Pw-alvo-123', clube=cls.clube
        )
        cls.admin = Usuario.objects.create_superuser(
            'master', password='Pw-master-123', clube=cls.clube
        )
        cls.pendente = cls.criar_membro(NOME_XSS, aprovado=False)
        cls.pendente2 = cls.criar_membro('Pendente Dois', aprovado=False)
        cls.aprovado = cls.criar_membro('Membro Aprovado', aprovado=True)
        cls.aprovado2 = cls.criar_membro(
            'Membro Aprovado Dois', aprovado=True
        )
        cls.avaliacao = AvaliacaoSemanal.objects.create(
            desbravador=cls.aprovado, autor=cls.comum, biblia=10,
            observacao='obs de teste',
        )
        cls.ponto = PontoExtra.objects.create(
            desbravador=cls.aprovado, autor=cls.diretor, motivo='Campori',
            pontos=5,
        )

    @classmethod
    def criar_membro(cls, nome, aprovado):
        return Desbravador.objects.create(
            nome_completo=nome, data_nascimento=date(2012, 1, 1),
            unidade=cls.unidade, ativo=True, aprovado=aprovado,
        )

    def estado(self):
        """Estado que as 4 ações destrutivas podem alterar."""
        alvo = Usuario.objects.get(pk=self.alvo.pk)
        membros = Desbravador.objects
        return {
            'alvo_ativo': alvo.is_active,
            'alvo_senha': alvo.password,
            'pendente_existe': membros.filter(pk=self.pendente.pk).exists(),
            'pendente_aprovado': membros.filter(
                pk=self.pendente.pk, aprovado=True
            ).exists(),
            'pendente2_existe': membros.filter(
                pk=self.pendente2.pk
            ).exists(),
            'aprovado_existe': membros.filter(pk=self.aprovado.pk).exists(),
            'n_desbravadores': membros.count(),
            'n_avaliacoes': AvaliacaoSemanal.objects.count(),
            'n_pontos': PontoExtra.objects.count(),
        }

    def urls_destrutivas(self):
        return {
            'toggle_acesso': reverse('toggle_acesso', args=[self.alvo.pk]),
            'reset_senha_diretoria': reverse(
                'reset_senha_diretoria', args=[self.alvo.pk]
            ),
            'aprovar_membro': reverse(
                'aprovar_membro', args=[self.pendente.pk]
            ),
            'recusar_membro': reverse(
                'recusar_membro', args=[self.pendente.pk]
            ),
        }

    def assertRedireciona(self, resp, url):
        self.assertRedirects(resp, url, fetch_redirect_response=False)


class MetodoHttpTests(PainelDiretoriaTestCase):
    """As ações destrutivas não aceitam GET/HEAD (CSRF e prefetch)."""

    def test_get_retorna_405_sem_alterar_estado(self):
        self.client.force_login(self.diretor)
        for nome, url in self.urls_destrutivas().items():
            with self.subTest(view=nome):
                antes = self.estado()
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 405)
                self.assertEqual(resp.headers.get('Allow'), 'POST')
                self.assertEqual(self.estado(), antes)

    def test_head_retorna_405_sem_alterar_estado(self):
        self.client.force_login(self.diretor)
        for nome, url in self.urls_destrutivas().items():
            with self.subTest(view=nome):
                antes = self.estado()
                self.assertEqual(self.client.head(url).status_code, 405)
                self.assertEqual(self.estado(), antes)


class CsrfTests(PainelDiretoriaTestCase):
    def _token_do_painel(self, client):
        resp = client.get(reverse('painel_diretoria'))
        self.assertEqual(resp.status_code, 200)
        m = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"',
            resp.content.decode(),
        )
        self.assertIsNotNone(m, 'csrfmiddlewaretoken ausente no painel')
        return m.group(1)

    def test_post_sem_token_retorna_403(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.diretor)
        # garante o cookie csrftoken: só falta o token do formulário
        self._token_do_painel(c)
        for nome, url in self.urls_destrutivas().items():
            with self.subTest(view=nome):
                antes = self.estado()
                self.assertEqual(c.post(url).status_code, 403)
                self.assertEqual(self.estado(), antes)

    def test_post_com_token_invalido_retorna_403(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.diretor)
        self._token_do_painel(c)
        for nome, url in self.urls_destrutivas().items():
            with self.subTest(view=nome):
                antes = self.estado()
                resp = c.post(url, {'csrfmiddlewaretoken': 'x' * 64})
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(self.estado(), antes)

    def test_post_com_token_valido_funciona(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.diretor)
        painel = reverse('painel_diretoria')
        urls = self.urls_destrutivas()

        tok = self._token_do_painel(c)
        resp = c.post(urls['toggle_acesso'], {'csrfmiddlewaretoken': tok})
        self.assertRedireciona(resp, painel)
        self.assertFalse(Usuario.objects.get(pk=self.alvo.pk).is_active)

        senha_antiga = Usuario.objects.get(pk=self.alvo.pk).password
        tok = self._token_do_painel(c)
        resp = c.post(
            urls['reset_senha_diretoria'], {'csrfmiddlewaretoken': tok}
        )
        self.assertRedireciona(resp, painel)
        self.assertNotEqual(
            Usuario.objects.get(pk=self.alvo.pk).password, senha_antiga
        )

        tok = self._token_do_painel(c)
        resp = c.post(urls['aprovar_membro'], {'csrfmiddlewaretoken': tok})
        self.assertRedireciona(resp, painel)
        self.assertTrue(Desbravador.objects.get(pk=self.pendente.pk).aprovado)

        # recusa um pendente enviando o token pelo header X-CSRFToken
        self._token_do_painel(c)
        resp = c.post(
            reverse('recusar_membro', args=[self.pendente2.pk]),
            HTTP_X_CSRFTOKEN=c.cookies['csrftoken'].value,
        )
        self.assertRedireciona(resp, painel)
        self.assertFalse(
            Desbravador.objects.filter(pk=self.pendente2.pk).exists()
        )


class AutorizacaoTests(PainelDiretoriaTestCase):
    def test_quem_nao_e_diretoria_vai_para_o_dashboard(self):
        self.client.force_login(self.comum)
        for nome, url in self.urls_destrutivas().items():
            with self.subTest(view=nome):
                antes = self.estado()
                resp = self.client.post(url)
                self.assertRedireciona(resp, reverse('dashboard'))
                self.assertEqual(self.estado(), antes)

    def test_post_anonimo_vai_para_o_login(self):
        for nome, url in self.urls_destrutivas().items():
            with self.subTest(view=nome):
                antes = self.estado()
                resp = self.client.post(url)
                self.assertRedireciona(
                    resp, f'{settings.LOGIN_URL}?next={url}'
                )
                self.assertEqual(self.estado(), antes)

    def test_get_anonimo_vai_para_o_login(self):
        for nome, url in self.urls_destrutivas().items():
            with self.subTest(view=nome):
                resp = self.client.get(url)
                self.assertRedireciona(
                    resp, f'{settings.LOGIN_URL}?next={url}'
                )

    def test_ids_inexistentes_retornam_404(self):
        self.client.force_login(self.diretor)
        for nome in ('toggle_acesso', 'reset_senha_diretoria',
                     'aprovar_membro', 'recusar_membro'):
            with self.subTest(view=nome):
                resp = self.client.post(reverse(nome, args=[999999]))
                self.assertEqual(resp.status_code, 404)

    def test_painel_restrito_a_diretoria(self):
        """Quem não é diretoria não vê o painel nem lança pontos em massa."""
        self.client.force_login(self.comum)
        url = reverse('painel_diretoria')
        self.assertRedireciona(self.client.get(url), reverse('dashboard'))
        n = PontoExtra.objects.count()
        resp = self.client.post(url, {
            'selecionados': [str(self.aprovado.pk)],
            'pontos': '-50',
            'motivo': 'Sem permissão',
        })
        self.assertRedireciona(resp, reverse('dashboard'))
        self.assertEqual(PontoExtra.objects.count(), n)


class ToggleAcessoTests(PainelDiretoriaTestCase):
    def test_alterna_is_active_nos_dois_sentidos(self):
        self.client.force_login(self.diretor)
        url = reverse('toggle_acesso', args=[self.alvo.pk])
        self.assertTrue(Usuario.objects.get(pk=self.alvo.pk).is_active)
        resp = self.client.post(url)
        self.assertRedireciona(resp, reverse('painel_diretoria'))
        self.assertFalse(Usuario.objects.get(pk=self.alvo.pk).is_active)
        self.client.post(url)
        self.assertTrue(Usuario.objects.get(pk=self.alvo.pk).is_active)

    def test_alternar_o_proprio_acesso_nao_faz_nada(self):
        self.client.force_login(self.diretor)
        resp = self.client.post(
            reverse('toggle_acesso', args=[self.diretor.pk])
        )
        self.assertRedireciona(resp, reverse('painel_diretoria'))
        self.assertTrue(Usuario.objects.get(pk=self.diretor.pk).is_active)
        resp = self.client.get(reverse('painel_diretoria'))
        self.assertEqual(resp.status_code, 200)


class ResetSenhaTests(PainelDiretoriaTestCase):
    def _resetar(self, usuario):
        resp = self.client.post(
            reverse('reset_senha_diretoria', args=[usuario.pk])
        )
        self.assertRedireciona(resp, reverse('painel_diretoria'))
        # só as mensagens DESTA requisição (as anteriores ainda estão no
        # cookie de mensagens, pois não foram exibidas)
        storage = get_messages(resp.wsgi_request)
        msgs = [(m.level, m.message) for m in storage._queued_messages]
        self.assertEqual(len(msgs), 1, msgs)
        nivel, texto = msgs[0]
        self.assertEqual(nivel, msg_constants.SUCCESS)
        self.assertTrue(texto.startswith(MSG_SENHA), repr(texto))
        senha = texto[len(MSG_SENHA):]
        self.assertEqual(
            texto, f'Senha redefinida com sucesso. Nova senha: {senha}'
        )
        # consome as mensagens pendentes para o cookie não crescer
        self.client.get(reverse('painel_diretoria'))
        return senha

    def test_senha_aleatoria_e_mensagem_exata(self):
        self.client.force_login(self.diretor)
        senha = self._resetar(self.alvo)
        self.assertEqual(len(senha), 8, repr(senha))
        self.assertTrue(set(senha) <= ALFANUMERICOS, repr(senha))
        self.assertNotEqual(senha, 'dbv@123')
        alvo = Usuario.objects.get(pk=self.alvo.pk)
        self.assertTrue(alvo.check_password(senha))
        self.assertFalse(alvo.check_password('dbv@123'))
        self.assertFalse(alvo.check_password('Pw-alvo-123'))
        # o usuário consegue entrar e o diretor continua logado
        self.assertTrue(Client().login(username='alvo', password=senha))
        resp = self.client.get(reverse('painel_diretoria'))
        self.assertEqual(resp.status_code, 200)

    def test_mensagem_exibida_apos_o_redirect(self):
        self.client.force_login(self.diretor)
        resp = self.client.post(
            reverse('reset_senha_diretoria', args=[self.alvo.pk]),
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        achadas = re.findall(
            r'Senha redefinida com sucesso\. Nova senha: ([A-Za-z0-9]{8})\s*<',
            body,
        )
        self.assertEqual(len(achadas), 1, 'mensagem não exibida uma vez')
        alvo = Usuario.objects.get(pk=self.alvo.pk)
        self.assertTrue(alvo.check_password(achadas[0]))
        self.assertIn('alert-success', body)

    def test_senha_exibida_uma_unica_vez(self):
        self.client.force_login(self.diretor)
        resp = self.client.post(
            reverse('reset_senha_diretoria', args=[self.alvo.pk]),
            follow=True,
        )
        self.assertContains(resp, MSG_SENHA, count=1)
        resp = self.client.get(reverse('painel_diretoria'))
        self.assertNotContains(resp, 'Nova senha:')

    def test_dois_resets_seguidos_geram_senhas_diferentes(self):
        self.client.force_login(self.diretor)
        p1 = self._resetar(self.alvo)
        p2 = self._resetar(self.alvo)
        self.assertNotEqual(p1, p2)
        alvo = Usuario.objects.get(pk=self.alvo.pk)
        self.assertTrue(alvo.check_password(p2))
        self.assertFalse(alvo.check_password(p1))

    def test_view_usa_secrets_choice(self):
        self.client.force_login(self.diretor)
        # envolve só o nome `secrets` dentro de core.views: o Django também
        # usa secrets.choice (tokens de sessão/CSRF), que não deve contar
        with mock.patch.object(core_views, 'secrets', wraps=secrets) as spy:
            resp = self.client.post(
                reverse('reset_senha_diretoria', args=[self.alvo.pk])
            )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(spy.choice.call_count, 8)
        for chamada in spy.choice.call_args_list:
            self.assertEqual(set(chamada.args[0]), ALFANUMERICOS)

    def test_codigo_usa_secrets_e_nao_random(self):
        fonte = inspect.getsource(core_views)
        fonte_reset = inspect.getsource(core_views.reset_senha_diretoria)
        self.assertIn('secrets.choice', fonte_reset)
        self.assertNotIn('dbv@123', fonte)
        self.assertIsNone(
            re.search(r'^\s*(import random|from random import)', fonte, re.M)
        )
        self.assertIsNone(re.search(r'\brandom\.', fonte))
        self.assertRegex(fonte, r'(?m)^import secrets$')
        self.assertEqual(
            core_views.CARACTERES_SENHA,
            string.ascii_letters + string.digits,
        )
        self.assertEqual(core_views.TAMANHO_SENHA_RESETADA, 8)

    def test_muitos_resets_alfabeto_e_unicidade(self):
        self.client.force_login(self.diretor)
        senhas = [self._resetar(self.alvo) for _ in range(40)]
        self.assertEqual(len(set(senhas)), 40)
        caracteres = set(''.join(senhas))
        self.assertTrue(caracteres <= ALFANUMERICOS)
        self.assertTrue(caracteres & set(string.ascii_lowercase))
        self.assertTrue(caracteres & set(string.ascii_uppercase))
        self.assertTrue(caracteres & set(string.digits))
        self.assertTrue(all(len(s) == 8 for s in senhas))


class ProtecaoSuperusuarioTests(PainelDiretoriaTestCase):
    """Diretoria comum não altera superusuários nem reseta a própria senha.

    Antes da Fase 1.5 os botões só eram escondidos no template: um POST
    direto redefinia a senha do superusuário (e a exibia) ou o desativava.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.diretor_admin = Usuario.objects.create_superuser(
            'diretor-admin', password='Pw-diradmin-123', is_diretoria=True,
            clube=cls.clube,
        )
        # diretoria com acesso ao /admin/ (is_staff), sem ser superusuário
        cls.diretor_staff = Usuario.objects.create_user(
            'diretor-staff', password='Pw-dirstaff-123',
            is_diretoria=True, is_staff=True, clube=cls.clube,
        )
        # superusuário com is_staff desmarcado no admin
        cls.admin_sem_staff = Usuario.objects.create_user(
            'admin-sem-staff', password='Pw-semstaff-123',
            is_superuser=True, clube=cls.clube,
        )
        cls.staff_comum = Usuario.objects.create_user(
            'staff-comum', password='Pw-staffcomum-123', is_staff=True,
            clube=cls.clube,
        )

    def test_diretoria_nao_redefine_senha_de_superusuario(self):
        self.client.force_login(self.diretor)
        resp = self.client.post(
            reverse('reset_senha_diretoria', args=[self.admin.pk])
        )
        self.assertRedireciona(resp, reverse('painel_diretoria'))
        admin = Usuario.objects.get(pk=self.admin.pk)
        self.assertTrue(admin.check_password('Pw-master-123'))
        msgs = mensagens(resp)
        self.assertIn((msg_constants.ERROR, MSG_ADMIN), msgs)
        # nenhuma senha nova é exibida
        self.assertFalse([texto for _, texto in msgs if MSG_SENHA in texto])

    def test_diretoria_nao_desativa_superusuario(self):
        self.client.force_login(self.diretor)
        resp = self.client.post(
            reverse('toggle_acesso', args=[self.admin.pk])
        )
        self.assertRedireciona(resp, reverse('painel_diretoria'))
        self.assertTrue(Usuario.objects.get(pk=self.admin.pk).is_active)
        self.assertIn((msg_constants.ERROR, MSG_ADMIN), mensagens(resp))

    def test_diretoria_nao_redefine_a_propria_senha(self):
        self.client.force_login(self.diretor)
        resp = self.client.post(
            reverse('reset_senha_diretoria', args=[self.diretor.pk])
        )
        self.assertRedireciona(resp, reverse('painel_diretoria'))
        diretor = Usuario.objects.get(pk=self.diretor.pk)
        self.assertTrue(diretor.check_password('Pw-diretor-123'))
        msgs = mensagens(resp)
        self.assertTrue(
            any(nivel == msg_constants.ERROR for nivel, _ in msgs), msgs
        )
        self.assertFalse([texto for _, texto in msgs if MSG_SENHA in texto])
        # continua logado (antes o reset da própria senha derrubava a sessão)
        resp = self.client.get(reverse('painel_diretoria'))
        self.assertEqual(resp.status_code, 200)

    def test_superusuario_pode_redefinir_senha_de_superusuario(self):
        self.client.force_login(self.diretor_admin)
        resp = self.client.post(
            reverse('reset_senha_diretoria', args=[self.admin.pk])
        )
        self.assertRedireciona(resp, reverse('painel_diretoria'))
        textos = [t for _, t in mensagens(resp) if t.startswith(MSG_SENHA)]
        self.assertEqual(len(textos), 1)
        admin = Usuario.objects.get(pk=self.admin.pk)
        self.assertTrue(admin.check_password(textos[0][len(MSG_SENHA):]))

    def test_superusuario_pode_desativar_superusuario(self):
        self.client.force_login(self.diretor_admin)
        self.client.post(reverse('toggle_acesso', args=[self.admin.pk]))
        self.assertFalse(Usuario.objects.get(pk=self.admin.pk).is_active)

    def test_diretoria_staff_nao_redefine_senha_de_superusuario(self):
        """O guard olha is_superuser do solicitante, e não is_staff."""
        self.client.force_login(self.diretor_staff)
        resp = self.client.post(
            reverse('reset_senha_diretoria', args=[self.admin.pk])
        )
        self.assertRedireciona(resp, reverse('painel_diretoria'))
        admin = Usuario.objects.get(pk=self.admin.pk)
        self.assertTrue(admin.check_password('Pw-master-123'))
        self.assertIn((msg_constants.ERROR, MSG_ADMIN), mensagens(resp))

    def test_diretoria_staff_nao_desativa_superusuario(self):
        self.client.force_login(self.diretor_staff)
        resp = self.client.post(
            reverse('toggle_acesso', args=[self.admin.pk])
        )
        self.assertRedireciona(resp, reverse('painel_diretoria'))
        self.assertTrue(Usuario.objects.get(pk=self.admin.pk).is_active)
        self.assertIn((msg_constants.ERROR, MSG_ADMIN), mensagens(resp))

    def test_superusuario_sem_is_staff_continua_protegido(self):
        """O guard olha is_superuser do alvo, e não is_staff."""
        self.client.force_login(self.diretor)
        pk = self.admin_sem_staff.pk
        self.client.post(reverse('toggle_acesso', args=[pk]))
        self.client.post(reverse('reset_senha_diretoria', args=[pk]))
        alvo = Usuario.objects.get(pk=pk)
        self.assertTrue(alvo.is_active)
        self.assertTrue(alvo.check_password('Pw-semstaff-123'))

    def test_diretoria_altera_staff_que_nao_e_superusuario(self):
        self.client.force_login(self.diretor)
        pk = self.staff_comum.pk
        resp = self.client.post(reverse('reset_senha_diretoria', args=[pk]))
        textos = [t for _, t in mensagens(resp) if t.startswith(MSG_SENHA)]
        self.assertEqual(len(textos), 1)
        self.client.post(reverse('toggle_acesso', args=[pk]))
        alvo = Usuario.objects.get(pk=pk)
        self.assertFalse(alvo.is_active)
        self.assertTrue(alvo.check_password(textos[0][len(MSG_SENHA):]))


class AprovarRecusarTests(PainelDiretoriaTestCase):
    def test_aprovar_marca_como_aprovado(self):
        self.client.force_login(self.diretor)
        resp = self.client.post(
            reverse('aprovar_membro', args=[self.pendente.pk])
        )
        self.assertRedireciona(resp, reverse('painel_diretoria'))
        membro = Desbravador.objects.get(pk=self.pendente.pk)
        self.assertTrue(membro.aprovado)
        self.assertTrue(membro.ativo)

    def test_recusar_pendente_exclui(self):
        self.client.force_login(self.diretor)
        n = Desbravador.objects.count()
        resp = self.client.post(
            reverse('recusar_membro', args=[self.pendente.pk])
        )
        self.assertRedireciona(resp, reverse('painel_diretoria'))
        self.assertFalse(
            Desbravador.objects.filter(pk=self.pendente.pk).exists()
        )
        self.assertEqual(Desbravador.objects.count(), n - 1)
        self.assertFalse(
            any(nivel == msg_constants.ERROR for nivel, _ in mensagens(resp))
        )

    def test_recusar_aprovado_e_bloqueado_e_mantem_historico(self):
        self.client.force_login(self.diretor)
        avaliacoes = AvaliacaoSemanal.objects.filter(desbravador=self.aprovado)
        pontos = PontoExtra.objects.filter(desbravador=self.aprovado)
        self.assertEqual((avaliacoes.count(), pontos.count()), (1, 1))
        resp = self.client.post(
            reverse('recusar_membro', args=[self.aprovado.pk])
        )
        self.assertRedireciona(resp, reverse('painel_diretoria'))
        membro = Desbravador.objects.filter(pk=self.aprovado.pk).first()
        self.assertIsNotNone(membro)
        self.assertTrue(membro.aprovado)
        self.assertEqual((avaliacoes.count(), pontos.count()), (1, 1))
        self.assertTrue(
            AvaliacaoSemanal.objects.filter(pk=self.avaliacao.pk).exists()
        )
        self.assertTrue(PontoExtra.objects.filter(pk=self.ponto.pk).exists())
        self.assertIn((msg_constants.ERROR, MSG_APROVADO), mensagens(resp))

    def test_erro_de_recusa_de_aprovado_e_exibido(self):
        self.client.force_login(self.diretor)
        resp = self.client.post(
            reverse('recusar_membro', args=[self.aprovado.pk]), follow=True
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('alert-danger', body)
        self.assertIn(html.escape(MSG_APROVADO), body)

    def test_recusar_aprovado_inativo_tambem_e_bloqueado(self):
        Desbravador.objects.filter(pk=self.aprovado2.pk).update(ativo=False)
        self.client.force_login(self.diretor)
        self.client.post(reverse('recusar_membro', args=[self.aprovado2.pk]))
        self.assertTrue(
            Desbravador.objects.filter(pk=self.aprovado2.pk).exists()
        )


class PontosEmMassaTests(PainelDiretoriaTestCase):
    def test_ids_duplicados_geram_um_ponto_por_membro(self):
        self.client.force_login(self.diretor)
        a, b = str(self.aprovado.pk), str(self.aprovado2.pk)
        antes_a = PontoExtra.objects.filter(desbravador=self.aprovado).count()
        antes_b = PontoExtra.objects.filter(
            desbravador=self.aprovado2
        ).count()
        resp = self.client.post(reverse('painel_diretoria'), {
            'selecionados': [a, a, b, b],
            'pontos': '10',
            'motivo': 'Campori 2026',
        })
        self.assertRedireciona(resp, reverse('painel_diretoria'))
        novos_a = PontoExtra.objects.filter(
            desbravador=self.aprovado, motivo='Campori 2026'
        )
        novos_b = PontoExtra.objects.filter(
            desbravador=self.aprovado2, motivo='Campori 2026'
        )
        self.assertEqual(novos_a.count(), 1)
        self.assertEqual(novos_b.count(), 1)
        self.assertEqual(
            PontoExtra.objects.filter(desbravador=self.aprovado).count(),
            antes_a + 1,
        )
        self.assertEqual(
            PontoExtra.objects.filter(desbravador=self.aprovado2).count(),
            antes_b + 1,
        )
        self.assertEqual(novos_a.get().pontos, 10)
        self.assertIn(
            (msg_constants.SUCCESS, '2 desbravadores receberam 10 pontos!'),
            mensagens(resp),
        )

    def test_template_gera_dois_checkboxes_por_membro(self):
        """Causa da duplicidade: desktop e mobile têm um checkbox cada."""
        self.client.force_login(self.diretor)
        body = self.client.get(reverse('painel_diretoria')).content.decode()
        for pk in (self.aprovado.pk, self.aprovado2.pk):
            n = len(re.findall(rf'name="selecionados" value="{pk}"', body))
            self.assertEqual(n, 2, f'membro {pk}: {n} checkboxes')

    def test_um_id_continua_funcionando(self):
        self.client.force_login(self.diretor)
        resp = self.client.post(reverse('painel_diretoria'), {
            'selecionados': [str(self.aprovado.pk)],
            'pontos': '-5',
            'motivo': 'Atraso',
        })
        self.assertEqual(PontoExtra.objects.filter(motivo='Atraso').count(), 1)
        self.assertIn(
            (msg_constants.SUCCESS, '1 desbravadores receberam -5 pontos!'),
            mensagens(resp),
        )

    def test_campos_faltando_avisam_e_nao_criam_nada(self):
        self.client.force_login(self.diretor)
        n = PontoExtra.objects.count()
        resp = self.client.post(reverse('painel_diretoria'), {
            'selecionados': [], 'pontos': '10', 'motivo': 'x',
        })
        self.assertEqual(PontoExtra.objects.count(), n)
        self.assertEqual(mensagens(resp)[0][0], msg_constants.WARNING)


class PainelRenderizadoTests(PainelDiretoriaTestCase):
    """HTML do painel: forms POST com CSRF, sem links GET e sem XSS."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.inativo = Usuario.objects.create_user(
            'inativo', password='Pw-inativo-123', is_active=False,
            clube=cls.clube,
        )

    def setUp(self):
        self.client.force_login(self.diretor)
        resp = self.client.get(reverse('painel_diretoria'))
        self.assertEqual(resp.status_code, 200)
        self.body = resp.content.decode()
        self.p = PainelParser()
        self.p.feed(self.body)
        self.p.close()

    def forms_destrutivos(self, tipo=None, obj_id=None):
        encontrados = []
        for f in self.p.forms:
            m = ACAO_DESTRUTIVA_RE.search(f['attrs'].get('action', ''))
            if not m:
                continue
            if tipo and m.group(1) != tipo:
                continue
            if obj_id is not None and int(m.group(2)) != obj_id:
                continue
            encontrados.append(f)
        return encontrados

    def test_sem_dbv123_no_html(self):
        self.assertNotIn('dbv@123', self.body.lower())

    def test_sem_links_para_acoes_destrutivas(self):
        links = [
            (a, linha) for a, linha in self.p.anchors
            if ACAO_DESTRUTIVA_RE.search(a.get('href', ''))
        ]
        self.assertEqual(links, [])
        # nem href= para elas em nenhum lugar (ex.: dentro de strings JS)
        self.assertIsNone(re.search(
            r'href=["\'][^"\']*/diretoria/'
            r'(acesso|reset-senha|aprovar|recusar)/',
            self.body,
        ))

    def test_forms_destrutivos_sao_post_com_csrf(self):
        forms = self.forms_destrutivos()
        # diretor, comum, alvo, inativo -> 4 x (toggle + reset) x 2 = 16
        # pendente, pendente2 -> 2 x (aprovar + recusar) x 2 = 8
        self.assertEqual(
            len(forms), 24, [f['attrs'].get('action') for f in forms]
        )
        for f in forms:
            with self.subTest(action=f['attrs']['action'], line=f['line']):
                self.assertEqual(f['attrs'].get('method', '').upper(), 'POST')
                tokens = [
                    i for i in f['inputs']
                    if i.get('name') == 'csrfmiddlewaretoken'
                ]
                self.assertEqual(len(tokens), 1)
                self.assertEqual(tokens[0].get('type'), 'hidden')
                self.assertGreaterEqual(len(tokens[0].get('value', '')), 32)
                botoes = list(f['buttons'])
                if 'id' in f['attrs']:
                    botoes += [
                        b for b in self.p.buttons
                        if b['attrs'].get('form') == f['attrs']['id']
                    ]
                self.assertGreaterEqual(len(botoes), 1, 'form sem botão')
                for b in botoes:
                    self.assertEqual(b['attrs'].get('type'), 'submit')

    def test_atributo_form_aponta_para_form_existente(self):
        form_ids = [
            f['attrs']['id'] for f in self.p.forms if 'id' in f['attrs']
        ]
        refs = [b for b in self.p.buttons if 'form' in b['attrs']]
        self.assertEqual(len(refs), 8)  # 4 usuários x (toggle + reset)
        for b in refs:
            form_id = b['attrs']['form']
            with self.subTest(form=form_id):
                self.assertIn(form_id, form_ids)
                self.assertEqual(self.p.ids.count(form_id), 1)
                alvo = next(
                    f for f in self.p.forms
                    if f['attrs'].get('id') == form_id
                )
                self.assertTrue(
                    ACAO_DESTRUTIVA_RE.search(alvo['attrs']['action'])
                )
                # botões continuam filhos diretos do .btn-group (visual)
                # e fora de qualquer form
                self.assertEqual(b['parent_tag'], 'div')
                self.assertIn('btn-group', b['parent_class'].split())
                self.assertIsNone(b['enclosing'])
                self.assertIn('d-none', alvo['attrs'].get('class', '').split())
        forms = {
            f['attrs']['id']: f['attrs'].get('action')
            for f in self.p.forms if 'id' in f['attrs']
        }
        for usu in (self.diretor, self.comum, self.alvo, self.inativo):
            self.assertEqual(
                forms[f'form-toggle-acesso-{usu.pk}'],
                reverse('toggle_acesso', args=[usu.pk]),
            )
            self.assertEqual(
                forms[f'form-reset-senha-{usu.pk}'],
                reverse('reset_senha_diretoria', args=[usu.pk]),
            )

    def test_ids_unicos(self):
        duplicados = sorted({i for i in self.p.ids if self.p.ids.count(i) > 1})
        self.assertEqual(duplicados, [])

    def test_sem_forms_aninhados(self):
        self.assertEqual(self.p.nested_forms, [])

    def test_nome_xss_apenas_escapado(self):
        escapado = html.escape(NOME_XSS)  # mesmo mapeamento do Django
        self.assertEqual(
            escapado,
            'Teste&#x27;); window.__xss=1; //&lt;b&gt;x&lt;/b&gt;&quot;',
        )
        self.assertNotIn("'); window.__xss", self.body)
        self.assertNotIn('<b>x</b>', self.body)
        self.assertNotIn('x</b>"', self.body)
        # toda ocorrência do marcador está dentro do nome escapado
        self.assertEqual(self.body.count('__xss'), self.body.count(escapado))
        # td (desktop) + span (mobile) + 2 atributos data-nome
        self.assertEqual(self.body.count(escapado), 4)
        for tag, attr, valor, linha in self.p.event_attrs:
            with self.subTest(tag=tag, attr=attr, linha=linha):
                self.assertNotIn('__xss', valor)
                self.assertNotIn('Teste', valor)
                self.assertNotIn('nome', valor.lower())
        for script in self.p.scripts:
            self.assertNotIn('__xss', script)

    def test_sem_onclick_em_recusar_ou_reset(self):
        def handlers(attrs):
            return [k for k in attrs if k.startswith('on')]

        for f in self.forms_destrutivos():
            self.assertFalse(handlers(f['attrs']), f['attrs'])
            for b in f['buttons']:
                self.assertFalse(handlers(b['attrs']), b['attrs'])
        for b in self.p.buttons:
            if 'form' in b['attrs']:
                self.assertFalse(handlers(b['attrs']), b['attrs'])

    def test_forms_recusar_tem_data_nome(self):
        recusar = self.forms_destrutivos('recusar', self.pendente.pk)
        self.assertEqual(len(recusar), 2)
        for f in recusar:
            # o parser desfaz o escape: o valor volta exatamente ao nome
            self.assertEqual(f['attrs'].get('data-nome'), NOME_XSS)
            classes = f['attrs'].get('class', '').split()
            self.assertIn('form-recusar-membro', classes)
        recusar2 = self.forms_destrutivos('recusar', self.pendente2.pk)
        self.assertEqual(
            [f['attrs'].get('data-nome') for f in recusar2],
            ['Pendente Dois'] * 2,
        )
        self.assertIn(
            'data-nome="Teste&#x27;); window.__xss=1; '
            '//&lt;b&gt;x&lt;/b&gt;&quot;"',
            self.body,
        )

    def test_listener_de_confirmacao_presente(self):
        js = '\n'.join(self.p.scripts)
        self.assertIn("querySelectorAll('form.form-recusar-membro')", js)
        self.assertIn('form.dataset.nome', js)
        self.assertIn("addEventListener('submit'", js)
        self.assertIn('event.preventDefault()', js)
        self.assertIn("querySelectorAll('form[data-confirm]')", js)
        self.assertNotIn('innerHTML', js)
        for f in self.forms_destrutivos('reset-senha'):
            self.assertTrue(f['attrs'].get('data-confirm'))
            self.assertNotIn('dbv@123', f['attrs']['data-confirm'])

    def test_linha_do_superusuario_sem_forms(self):
        self.assertEqual(self.forms_destrutivos('acesso', self.admin.pk), [])
        self.assertEqual(
            self.forms_destrutivos('reset-senha', self.admin.pk), []
        )
        self.assertNotIn(f'form-toggle-acesso-{self.admin.pk}"', self.body)
        self.assertNotIn(f'form-reset-senha-{self.admin.pk}"', self.body)
        self.assertIn('Intocável (Admin)', self.body)
        for usu in (self.comum, self.alvo, self.inativo):
            self.assertEqual(len(self.forms_destrutivos('acesso', usu.pk)), 2)
            self.assertEqual(
                len(self.forms_destrutivos('reset-senha', usu.pk)), 2
            )

    def test_membro_aprovado_sem_forms_aprovar_recusar(self):
        for tipo in ('aprovar', 'recusar'):
            with self.subTest(tipo=tipo):
                self.assertEqual(
                    self.forms_destrutivos(tipo, self.aprovado.pk), []
                )
                self.assertEqual(
                    self.forms_destrutivos(tipo, self.aprovado2.pk), []
                )
                self.assertEqual(
                    len(self.forms_destrutivos(tipo, self.pendente.pk)), 2
                )

    def test_icone_de_acesso_preservado(self):
        # ativo: cadeado aberto; inativo: cadeado fechado (desktop)
        i = self.body.index(f'form="form-toggle-acesso-{self.inativo.pk}"')
        self.assertIn('fa-lock text-danger', self.body[i:i + 400])
        i = self.body.index(f'form="form-toggle-acesso-{self.alvo.pk}"')
        self.assertIn('fa-lock-open text-success', self.body[i:i + 400])

    def test_checkboxes_desktop_e_mobile_sincronizados(self):
        """Fase 1.5: desmarcar um membro também desmarca a cópia oculta.

        Verificação estática (o test client não executa JS), no mesmo
        estilo de test_listener_de_confirmacao_presente.
        """
        js = '\n'.join(self.p.scripts)
        self.assertRegex(js, r'outro\.value\s*===\s*this\.value')
        self.assertRegex(js, r'outro\.checked\s*=\s*this\.checked')
        # o contador conta membros únicos (cada um tem 2 checkboxes)
        self.assertRegex(
            js, r'new Set\(Array\.from\(marcados, cb => cb\.value\)\)'
        )
        # script em IIFE: pode ser reexecutado (Turbo) sem redeclarar const
        self.assertRegex(js, r'\(\(\) => \{\s*// Seus scripts')

    def test_rodape_atualizado(self):
        self.assertIn('uma nova senha aleatória é gerada', self.body)


class ConfiguracaoTests(TestCase):
    def test_default_auto_field_e_bigautofield(self):
        self.assertEqual(
            settings.DEFAULT_AUTO_FIELD, 'django.db.models.BigAutoField'
        )
        for model in (Unidade, Usuario, Desbravador, PontoExtra):
            with self.subTest(model=model.__name__):
                self.assertIsInstance(model._meta.pk, models.BigAutoField)

    def test_app_core_sem_migrations_pendentes(self):
        """Evita migrations "fantasmas" (ex.: AlterField do id)."""
        try:
            call_command(
                'makemigrations', 'core', '--check', '--dry-run',
                verbosity=0,
            )
        except SystemExit:
            self.fail('makemigrations core --check encontrou mudanças')


class IsolamentoEntreClubesTests(PainelDiretoriaTestCase):
    """Fase 2: um clube nunca vê nem altera dados de outro (IDOR)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.outro_clube = Clube.objects.create(
            nome='Outro Clube', slug='outro-clube'
        )
        cls.outra_unidade = Unidade.objects.create(
            nome='Falcão Alheio', clube=cls.outro_clube
        )
        cls.outro_diretor = Usuario.objects.create_user(
            'outro-diretor', password='Pw-outrodir-123', is_diretoria=True,
            clube=cls.outro_clube,
        )
        cls.outro_usuario = Usuario.objects.create_user(
            'outro-usuario', password='Pw-outro-123', clube=cls.outro_clube,
            unidade_responsavel=cls.outra_unidade,
        )
        cls.outro_pendente = Desbravador.objects.create(
            nome_completo='Pendente Alheio', data_nascimento=date(2012, 1, 1),
            unidade=cls.outra_unidade, aprovado=False,
        )
        cls.outro_aprovado = Desbravador.objects.create(
            nome_completo='Aprovado Alheio', data_nascimento=date(2012, 1, 1),
            unidade=cls.outra_unidade, aprovado=True,
        )
        AvaliacaoSemanal.objects.create(
            desbravador=cls.outro_aprovado, autor=cls.outro_usuario,
            observacao='obs alheia',
        )
        hoje = date.today()
        Evento.objects.create(
            titulo='Evento Nosso', data_evento=hoje, clube=cls.clube
        )
        Evento.objects.create(
            titulo='Evento Alheio', data_evento=hoje, clube=cls.outro_clube
        )

    def setUp(self):
        cache.clear()  # o ranking fica em cache (locmem) entre os testes

    def _chaves_do_mes(self):
        hoje = timezone.now()
        return tuple(
            core_views.chave_cache_ranking(c.pk, hoje.month, hoje.year)
            for c in (self.clube, self.outro_clube)
        )

    def test_usuario_de_outro_clube_retorna_404(self):
        self.client.force_login(self.diretor)
        senha = Usuario.objects.get(pk=self.outro_usuario.pk).password
        for nome in ('toggle_acesso', 'reset_senha_diretoria'):
            with self.subTest(view=nome):
                url = reverse(nome, args=[self.outro_usuario.pk])
                self.assertEqual(self.client.post(url).status_code, 404)
        alvo = Usuario.objects.get(pk=self.outro_usuario.pk)
        self.assertTrue(alvo.is_active)
        self.assertEqual(alvo.password, senha)

    def test_membro_de_outro_clube_retorna_404(self):
        self.client.force_login(self.diretor)
        for nome in ('aprovar_membro', 'recusar_membro'):
            with self.subTest(view=nome):
                url = reverse(nome, args=[self.outro_pendente.pk])
                self.assertEqual(self.client.post(url).status_code, 404)
        membro = Desbravador.objects.get(pk=self.outro_pendente.pk)
        self.assertFalse(membro.aprovado)

    def test_avaliar_membro_de_outro_clube_retorna_404(self):
        self.client.force_login(self.diretor)
        url = reverse('avaliar_membro', args=[self.outro_aprovado.pk])
        n = AvaliacaoSemanal.objects.count()
        self.assertEqual(self.client.get(url).status_code, 404)
        resp = self.client.post(url, {'biblia': 10})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(AvaliacaoSemanal.objects.count(), n)

    def test_pontos_em_massa_ignoram_membros_de_outro_clube(self):
        self.client.force_login(self.diretor)
        resp = self.client.post(reverse('painel_diretoria'), {
            'selecionados': [
                str(self.aprovado.pk), str(self.outro_aprovado.pk)
            ],
            'pontos': '10',
            'motivo': 'Teste IDOR',
        })
        self.assertFalse(
            PontoExtra.objects.filter(desbravador=self.outro_aprovado).exists()
        )
        self.assertEqual(
            PontoExtra.objects.filter(
                desbravador=self.aprovado, motivo='Teste IDOR'
            ).count(),
            1,
        )
        self.assertIn(
            (msg_constants.SUCCESS, '1 desbravadores receberam 10 pontos!'),
            mensagens(resp),
        )

    def test_painel_lista_apenas_o_proprio_clube(self):
        self.client.force_login(self.diretor)
        body = self.client.get(reverse('painel_diretoria')).content.decode()
        for alheio in ('Pendente Alheio', 'Aprovado Alheio', 'outro-usuario',
                       'outro-diretor', 'Falcão Alheio', 'obs alheia'):
            with self.subTest(alheio=alheio):
                self.assertNotIn(alheio, body)
        for nosso in ('Membro Aprovado', 'Pendente Dois', 'alvo', 'Águia',
                      'obs de teste'):
            with self.subTest(nosso=nosso):
                self.assertIn(nosso, body)

    def test_relatorio_e_csv_apenas_do_proprio_clube(self):
        self.client.force_login(self.diretor)
        relatorio = self.client.get(reverse('relatorio_mensal'))
        self.assertContains(relatorio, 'Membro Aprovado')
        self.assertNotContains(relatorio, 'Aprovado Alheio')
        csv = self.client.get(reverse('exportar_relatorio_csv'))
        conteudo = csv.content.decode('utf-8-sig')
        self.assertIn('Membro Aprovado', conteudo)
        self.assertNotIn('Aprovado Alheio', conteudo)

    def test_ranking_e_cache_do_dashboard_separados_por_clube(self):
        self.client.force_login(self.diretor)
        resp = self.client.get(reverse('dashboard'))
        self.assertContains(resp, 'Águia')
        self.assertNotContains(resp, 'Falcão Alheio')
        # logo em seguida, o outro clube não pode receber o ranking em cache
        outro = Client()
        outro.force_login(self.outro_diretor)
        resp = outro.get(reverse('dashboard'))
        self.assertContains(resp, 'Falcão Alheio')
        self.assertNotContains(resp, 'Águia')
        chave_nossa, chave_alheia = self._chaves_do_mes()
        hoje = timezone.now()
        self.assertEqual(
            chave_nossa,
            f'ranking_unidades_{self.clube.pk}_{hoje.month}_{hoje.year}',
        )
        self.assertIsNotNone(cache.get(chave_nossa))
        self.assertIsNotNone(cache.get(chave_alheia))

    def test_pontos_em_massa_invalidam_so_o_cache_do_proprio_clube(self):
        chave_nossa, chave_alheia = self._chaves_do_mes()
        cache.set(chave_nossa, 'nosso', 600)
        cache.set(chave_alheia, 'alheio', 600)
        self.client.force_login(self.diretor)
        self.client.post(reverse('painel_diretoria'), {
            'selecionados': [str(self.aprovado.pk)],
            'pontos': '5',
            'motivo': 'Cache',
        })
        self.assertIsNone(cache.get(chave_nossa))
        self.assertEqual(cache.get(chave_alheia), 'alheio')

    def test_avaliacao_invalida_so_o_cache_do_proprio_clube(self):
        chave_nossa, chave_alheia = self._chaves_do_mes()
        cache.set(chave_nossa, 'nosso', 600)
        cache.set(chave_alheia, 'alheio', 600)
        self.client.force_login(self.diretor)
        dados = {
            nome: campo.initial
            for nome, campo in AvaliacaoForm().fields.items()
        }
        dados.update(data=date.today().isoformat(), observacao='')
        resp = self.client.post(
            reverse('avaliar_membro', args=[self.aprovado.pk]), dados
        )
        self.assertRedireciona(resp, reverse('painel_diretoria'))
        self.assertIsNone(cache.get(chave_nossa))
        self.assertEqual(cache.get(chave_alheia), 'alheio')

    def test_calendario_mostra_apenas_eventos_do_proprio_clube(self):
        for usuario in (self.diretor, self.comum):
            with self.subTest(usuario=usuario.username):
                self.client.force_login(usuario)
                resp = self.client.get(reverse('calendario'))
                self.assertContains(resp, 'Evento Nosso')
                self.assertNotContains(resp, 'Evento Alheio')

    def test_evento_criado_pertence_ao_clube_do_autor(self):
        self.client.force_login(self.diretor)
        resp = self.client.post(reverse('cadastrar_evento'), {
            'titulo': 'Acampamento', 'data_evento': '2026-11-20',
            'descricao': '', 'unidade': '',
        })
        self.assertRedireciona(resp, reverse('calendario'))
        self.assertEqual(Evento.objects.get(titulo='Acampamento').clube,
                         self.clube)

    def test_evento_nao_aceita_unidade_de_outro_clube(self):
        self.client.force_login(self.diretor)
        self.client.post(reverse('cadastrar_evento'), {
            'titulo': 'Invasor', 'data_evento': '2026-11-20',
            'descricao': '', 'unidade': self.outra_unidade.pk,
        })
        self.assertFalse(Evento.objects.filter(titulo='Invasor').exists())

    def test_cadastro_de_membro_so_aceita_unidade_do_proprio_clube(self):
        self.client.force_login(self.diretor)
        url = reverse('cadastrar_desbravador')
        dados = {'data_nascimento': '2012-05-05', 'ativo': 'on'}
        self.client.post(url, {
            **dados, 'nome_completo': 'Infiltrado',
            'unidade': self.outra_unidade.pk,
        })
        self.assertFalse(
            Desbravador.objects.filter(nome_completo='Infiltrado').exists()
        )
        self.client.post(url, {
            **dados, 'nome_completo': 'Novato', 'unidade': self.unidade.pk,
        })
        self.assertTrue(Desbravador.objects.filter(
            nome_completo='Novato', unidade=self.unidade
        ).exists())

    def test_notificacao_em_massa_so_para_o_proprio_clube(self):
        self.client.force_login(self.diretor)
        self.client.post(reverse('enviar_notificacao_massa'), {
            'titulo': 'Reunião', 'mensagem': 'Sábado', 'publico_alvo': 'todos',
        })
        notificacao = NotificacaoManual.objects.get(titulo='Reunião')
        self.assertEqual(notificacao.clube, self.clube)
        clubes = set(
            notificacao.destinatarios.values_list('clube_id', flat=True)
        )
        self.assertEqual(clubes, {self.clube.pk})
        self.assertFalse(NotificacaoInApp.objects.filter(
            usuario__clube=self.outro_clube
        ).exists())

    def test_notificacao_para_unidade_de_outro_clube_e_recusada(self):
        self.client.force_login(self.diretor)
        resp = self.client.post(reverse('enviar_notificacao_massa'), {
            'titulo': 'Invasão', 'mensagem': 'x', 'publico_alvo': 'unidade',
            'unidade_id': str(self.outra_unidade.pk),
        })
        self.assertFalse(
            NotificacaoManual.objects.filter(titulo='Invasão').exists()
        )
        self.assertIn(
            (msg_constants.ERROR, 'Selecione uma unidade válida.'),
            mensagens(resp),
        )

    def test_formularios_oferecem_apenas_o_proprio_clube(self):
        unidades = [self.unidade]
        form = DesbravadorForm(user=self.diretor)
        self.assertEqual(list(form.fields['unidade'].queryset), unidades)
        form = EventoForm(user=self.diretor)
        self.assertEqual(list(form.fields['unidade'].queryset), unidades)
        for usuario in (self.diretor, self.comum):
            with self.subTest(usuario=usuario.username):
                form = PontoExtraForm(user=usuario)
                membros = form.fields['desbravador'].queryset
                self.assertIn(self.aprovado, membros)
                self.assertNotIn(self.outro_aprovado, membros)
        # sem usuário não há clube: nenhuma opção (falha fechada)
        self.assertFalse(DesbravadorForm().fields['unidade'].queryset)
        self.assertFalse(EventoForm().fields['unidade'].queryset)
        self.assertFalse(PontoExtraForm().fields['desbravador'].queryset)


class ClubeModelTests(TestCase):
    """Fase 2: o modelo Clube e o vínculo obrigatório dos dados com ele."""

    def test_campos_e_valores_padrao(self):
        clube = Clube.objects.create(nome='Novo Clube', slug='novo-clube')
        self.assertEqual(clube.cor_principal, '#0d47a1')
        self.assertTrue(clube.ativo)
        self.assertIsNotNone(clube.data_criacao)
        self.assertFalse(clube.logo)
        self.assertEqual(str(clube), 'Novo Clube')
        self.assertIsInstance(
            Clube._meta.get_field('logo'), models.ImageField
        )
        self.assertIsInstance(
            Clube._meta.get_field('slug'), models.SlugField
        )

    def test_slug_unico(self):
        Clube.objects.create(nome='A', slug='mesmo-slug')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Clube.objects.create(nome='B', slug='mesmo-slug')

    def test_clube_obrigatorio_nos_modelos(self):
        criar_sem_clube = {
            'Unidade': lambda: Unidade.objects.create(nome='Sem clube'),
            'Usuario': lambda: Usuario.objects.create_user(
                'sem-clube', password='x'
            ),
            'Evento': lambda: Evento.objects.create(
                titulo='x', data_evento=date(2026, 1, 1)
            ),
            'NotificacaoManual': lambda: NotificacaoManual.objects.create(
                titulo='x', mensagem='y'
            ),
        }
        for nome, criar in criar_sem_clube.items():
            with self.subTest(modelo=nome):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    criar()
        nomes = {
            Unidade: 'unidades', Usuario: 'usuarios', Evento: 'eventos',
            NotificacaoManual: 'notificacoes',
        }
        for modelo, related_name in nomes.items():
            with self.subTest(modelo=modelo.__name__):
                campo = modelo._meta.get_field('clube')
                self.assertFalse(campo.null)
                self.assertIs(campo.related_model, Clube)
                self.assertIs(campo.remote_field.on_delete, models.CASCADE)
                self.assertEqual(campo.remote_field.related_name, related_name)

    def test_createsuperuser_exige_e_aceita_o_clube(self):
        clube = Clube.objects.create(nome='Clube Admin', slug='clube-admin')
        with self.assertRaises(CommandError):
            call_command(
                'createsuperuser', interactive=False, username='sem-clube',
                email='a@a.com', stdout=StringIO(), stderr=StringIO(),
            )
        call_command(
            'createsuperuser', interactive=False, username='root2',
            email='r@r.com', clube=str(clube.pk), stdout=StringIO(),
        )
        usuario = Usuario.objects.get(username='root2')
        self.assertTrue(usuario.is_superuser)
        self.assertEqual(usuario.clube, clube)

    def test_unidade_precisa_ser_do_mesmo_clube(self):
        clube_a = Clube.objects.create(nome='A', slug='clube-a')
        clube_b = Clube.objects.create(nome='B', slug='clube-b')
        unidade_b = Unidade.objects.create(nome='Unidade B', clube=clube_b)
        usuario = Usuario(
            username='u', clube=clube_a, unidade_responsavel=unidade_b
        )
        with self.assertRaises(ValidationError) as ctx:
            usuario.full_clean(exclude=['password'])
        self.assertIn('unidade_responsavel', ctx.exception.message_dict)
        evento = Evento(
            titulo='x', data_evento=date(2026, 1, 1), clube=clube_a,
            unidade=unidade_b,
        )
        with self.assertRaises(ValidationError) as ctx:
            evento.full_clean()
        self.assertIn('unidade', ctx.exception.message_dict)


@override_settings(SECURE_SSL_REDIRECT=False, PASSWORD_HASHERS=HASHER_RAPIDO)
class AdminClubeTests(TestCase):
    """O admin continua criando usuários agora que o clube é obrigatório."""

    @classmethod
    def setUpTestData(cls):
        cls.clube = Clube.objects.create(nome='Clube', slug='clube')
        cls.root = Usuario.objects.create_superuser(
            'root', password='Pw-root-123', clube=cls.clube
        )

    def test_admin_cria_usuario_com_clube(self):
        self.client.force_login(self.root)
        url = reverse('admin:core_usuario_add')
        self.assertContains(self.client.get(url), 'name="clube"')
        resp = self.client.post(url, {
            'username': 'novo', 'usable_password': 'true',
            'password1': 'Senha-forte-123', 'password2': 'Senha-forte-123',
            'clube': self.clube.pk,
        })
        self.assertEqual(resp.status_code, 302)
        novo = Usuario.objects.get(username='novo')
        self.assertEqual(novo.clube, self.clube)

    def test_listagens_do_admin_carregam(self):
        self.client.force_login(self.root)
        for nome in ('admin:core_clube_changelist', 'admin:core_clube_add',
                     'admin:core_usuario_changelist'):
            with self.subTest(url=nome):
                resp = self.client.get(reverse(nome))
                self.assertEqual(resp.status_code, 200)


class MigracaoClubePadraoTests(TransactionTestCase):
    """Dados existentes (sem clube) vão para o clube padrão na migração.

    Reproduz o caminho de produção: banco na 0012, com dados, migrado até a
    0015 (FKs obrigatórias). Nenhum registro pode ficar sem clube.
    """

    antes = [('core', '0012_notificacaoinapp')]
    depois = [(
        'core', '0015_alter_usuario_managers_alter_evento_clube_and_more'
    )]

    def tearDown(self):
        # devolve o banco de teste à última migração
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes('core'))
        super().tearDown()

    def test_registros_existentes_vao_para_o_clube_padrao(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.antes)
        apps = executor.loader.project_state(self.antes).apps
        unidade = apps.get_model('core', 'Unidade').objects.create(nome='U')
        apps.get_model('core', 'Usuario').objects.create(
            username='antigo', password='x', unidade_responsavel=unidade
        )
        apps.get_model('core', 'Evento').objects.create(
            titulo='Antigo', data_evento=date(2026, 1, 1)
        )
        apps.get_model('core', 'NotificacaoManual').objects.create(
            titulo='Antiga', mensagem='m'
        )

        executor = MigrationExecutor(connection)
        executor.migrate(self.depois)
        apps = executor.loader.project_state(self.depois).apps
        padrao = apps.get_model('core', 'Clube').objects.get(
            slug='jovens-do-rei'
        )
        self.assertEqual(padrao.nome, 'Jovens do Rei')
        for nome in ('Unidade', 'Usuario', 'Evento', 'NotificacaoManual'):
            with self.subTest(modelo=nome):
                modelo = apps.get_model('core', nome)
                self.assertGreater(modelo.objects.count(), 0)
                self.assertEqual(
                    modelo.objects.filter(clube=padrao).count(),
                    modelo.objects.count(),
                )
                self.assertFalse(modelo._meta.get_field('clube').null)
