"""
Django settings for setup project.
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Carrega as variáveis ocultas do arquivo .env
load_dotenv(os.path.join(BASE_DIR, '.env'))

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.getenv('SECRET_KEY')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG') == 'True'

# Puxa a lista de hosts do .env e separa por vírgula
hosts = os.getenv('ALLOWED_HOSTS')
ALLOWED_HOSTS = hosts.split(',') if hosts else []

# Application definition
INSTALLED_APPS = [
    'jazzmin', # JAZZMIN SEMPRE NO TOPO!
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core', # Seu app principal
    'webpush', # Para notificações push
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'setup.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [], # Deixamos vazio pois o Django buscará dentro da pasta 'core/templates'
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'setup.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    { 'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator', },
    { 'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator', },
]

# Internationalization
LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles') # Obrigatório para o PythonAnywhere
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]

# --- CONFIGURAÇÕES DO SISTEMA DBV ---

# Usar nosso modelo de usuário personalizado
AUTH_USER_MODEL = 'core.Usuario'

# Redirecionamentos de Login
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

# --- CONFIGURAÇÕES DE NOTIFICAÇÃO PUSH ---
WEBPUSH_SETTINGS = {
    "VAPID_PUBLIC_KEY": os.getenv('VAPID_PUBLIC_KEY'),
    "VAPID_PRIVATE_KEY": os.getenv('VAPID_PRIVATE_KEY'),
    "VAPID_ADMIN_EMAIL": "joaocintraduarte@gmail.com"
}

# --- BLINDAGEM DE SEGURANÇA (Ativa apenas em Produção) ---
if not DEBUG:
    # Garante que todo o tráfego passe por HTTPS
    SECURE_SSL_REDIRECT = True
    
    # Protege os cookies de sessão e CSRF (evita roubo de login em Wi-Fi público)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    
    # Força os navegadores a lembrarem que o site é HTTPS por 1 ano (HSTS)
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True