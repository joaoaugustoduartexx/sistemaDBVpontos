"""Envio de web push desacoplado da requisição e da transação do banco.

O envio só começa depois do commit (transaction.on_commit) e roda num pool de
threads, com timeout em cada requisição HTTP ao serviço de push. Assim uma
notificação em massa não segura a thread da requisição nem o lock de escrita
do SQLite.

Servidores uWSGI sem --enable-threads (caso do PythonAnywhere) não executam
threads criadas pela aplicação; nesse caso o envio acontece de forma síncrona,
ainda depois do commit e com o mesmo timeout. A setting PUSH_EM_SEGUNDO_PLANO
(True/False) força um dos modos; sem ela, o modo é detectado automaticamente.
"""
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import requests
from django.conf import settings
from django.db import connections, transaction
from pywebpush import WebPushException, webpush

logger = logging.getLogger(__name__)

TIMEOUT_PUSH = 5  # segundos por requisição ao serviço de push
TTL_PUSH = 1000  # segundos que o serviço de push guarda a mensagem
MAX_THREADS_PUSH = 4
STATUS_INSCRICAO_EXPIRADA = (404, 410)

_executor = None
_executor_pid = None
_executor_lock = threading.Lock()


def agendar_push(usuario_ids, payload):
    """Agenda o push para os usuários depois do commit da transação atual."""
    ids = list(usuario_ids)
    if not ids:
        return

    def disparar():
        if usar_threads():
            executor_do_processo().submit(_enviar_em_thread, ids, payload)
        else:
            enviar_push_para_usuarios(ids, payload)

    transaction.on_commit(disparar)


def usar_threads():
    """Diz se o push pode rodar em threads neste processo."""
    forcado = getattr(settings, 'PUSH_EM_SEGUNDO_PLANO', None)
    if forcado is not None:
        return bool(forcado)
    try:
        import uwsgi  # só existe dentro do uWSGI
    except ImportError:
        return True
    opcoes = {
        (k.decode() if isinstance(k, bytes) else k) for k in uwsgi.opt
    }
    return bool(opcoes & {'enable-threads', 'threads'})


def executor_do_processo():
    """Pool de threads criado sob demanda por processo (seguro após fork)."""
    global _executor, _executor_pid
    with _executor_lock:
        if _executor is None or _executor_pid != os.getpid():
            _executor = ThreadPoolExecutor(
                max_workers=MAX_THREADS_PUSH, thread_name_prefix='webpush'
            )
            _executor_pid = os.getpid()
        return _executor


def _enviar_em_thread(usuario_ids, payload):
    try:
        enviar_push_para_usuarios(usuario_ids, payload)
    finally:
        # cada thread abre a própria conexão com o banco: fecha ao terminar
        connections.close_all()


def enviar_push_para_usuarios(usuario_ids, payload):
    """Envia o push às inscrições dos usuários; nunca levanta exceção."""
    from webpush.models import PushInformation

    try:
        dados = json.dumps(payload)
        infos = PushInformation.objects.filter(
            user_id__in=usuario_ids
        ).select_related('subscription')
        for info in infos:
            _enviar_para_inscricao(info.subscription, dados)
    except Exception:
        logger.exception('Falha ao enviar web push')


def _enviar_para_inscricao(inscricao, dados):
    webpush_settings = getattr(settings, 'WEBPUSH_SETTINGS', {})
    vapid = {}
    if webpush_settings.get('VAPID_PRIVATE_KEY'):
        vapid = {
            'vapid_private_key': webpush_settings['VAPID_PRIVATE_KEY'],
            'vapid_claims': {
                'sub': f"mailto:{webpush_settings.get('VAPID_ADMIN_EMAIL')}"
            },
        }
    try:
        webpush(
            subscription_info={
                'endpoint': inscricao.endpoint,
                'keys': {'p256dh': inscricao.p256dh, 'auth': inscricao.auth},
            },
            data=dados,
            ttl=TTL_PUSH,
            timeout=TIMEOUT_PUSH,
            **vapid,
        )
    except WebPushException as e:
        status = getattr(e.response, 'status_code', None)
        if status in STATUS_INSCRICAO_EXPIRADA:
            inscricao.delete()  # o navegador cancelou a inscrição
        else:
            logger.warning('Web push recusado (status %s): %s', status, e)
    except requests.RequestException as e:
        logger.warning('Web push sem resposta (timeout/rede): %s', e)
