### 🛑 CRITICAL - Password reset endpoint enables account takeover with a hardcoded password
* **File/Module:** `core/views.py`
* **The Flaw:** `reset_senha_diretoria` authorizes only on the caller's global `is_diretoria` flag, never checks the target's role (superuser, peer director) or club, and sets a hardcoded password (`dbv@123`) that the UI itself discloses. It also runs on a plain GET.
* **Business/Security Impact:** Any director, or any page that makes a logged-in director's browser issue one GET, can reset a superuser's password to the publicly known value (the repo is public) and log in as superuser; reproduced end-to-end, giving full control of every tenant's data including minors' medical notes.
* **Code Context:**
  ```python
  usuario = get_object_or_404(Usuario, id=user_id)
  usuario.set_password('dbv@123')
  usuario.save()
  ```
* **Architectural Fix Strategy:** Replace with a POST-only, CSRF-protected, tenant-scoped action guarded by a role hierarchy (never superusers or peers); issue single-use tokens via Django's `PasswordResetTokenGenerator` (or a random temporary password plus a `must_change_password` flag enforced by middleware); audit-log every reset and add login throttling.
---

### 🛑 CRITICAL - Cross-club IDOR: objects resolved by raw id and authorized only by a global role
* **File/Module:** `core/views.py`
* **The Flaw:** Every object-level view (`avaliar_membro`, `aprovar_membro`, `recusar_membro`, `toggle_acesso`, `reset_senha_diretoria`, painel mass points) loads targets with `get_object_or_404(Model, id=...)` and checks only the deployment-wide `is_diretoria` flag. No ownership or tenant predicate exists.
* **Business/Security Impact:** Once a second club shares the deployment, any director can read another club's children's medical notes, score them, delete their members with full history, and reset or lock the other club's directors (all reproduced with two simulated clubs), a direct LGPD breach.
* **Code Context:**
  ```python
  membro = get_object_or_404(Desbravador, id=id_dbv)
  membro.aprovado = True
  membro.save()
  ```
* **Architectural Fix Strategy:** Resolve every lookup through a tenant-scoped queryset (`get_object_or_404(request.tenant.<relation>, pk=...)`) supplied by tenant middleware, replace `is_diretoria` with per-tenant `Membership(user, tenant, role)` permissions, and add automated cross-tenant access tests for every route.
---

### 🛑 CRITICAL - No tenant boundary: global querysets expose every club's roster, users and minors' notes
* **File/Module:** `core/views.py`
* **The Flaw:** There is no Club/Tenant model, tenant FK, scoped manager or tenant-resolving middleware; every list, report, export and ranking query spans the whole database. `Evento` (null unit), directors (null unit) and `NotificacaoManual` have no derivable owner at all.
* **Business/Security Impact:** Each director's panel lists all clubs' members, usernames, pending registrations and counselors' confidential notes about minors; the report/CSV export every club's scores; any logged-in user sees every club's ranking — cross-tenant disclosure from the first onboarding.
* **Code Context:**
  ```python
  todos_usuarios = Usuario.objects.all().order_by('username')
  pendentes = (
      Desbravador.objects.filter(ativo=True, aprovado=False)
  ```
* **Architectural Fix Strategy:** Add a `Club` tenant model and a tenant FK on every owned table (including `Usuario`, `Evento`, `NotificacaoManual`) with a back-fill migration first; resolve `request.tenant` from the subdomain in middleware; make a tenant-filtering manager the default on all models (or use schema-per-tenant via django-tenants on PostgreSQL); enforce with cross-tenant tests.
---

### 🛑 CRITICAL - Stored XSS in director panel via member name inside onclick confirm()
* **File/Module:** `core/templates/core/painel_diretoria.html`
* **The Flaw:** A counselor-controlled value (`nome_completo`) is interpolated into a JavaScript string inside an HTML event-handler attribute. Django's HTML escaping (`&#x27;`) is decoded by the browser before the handler executes, so the value breaks out of the JS string.
* **Business/Security Impact:** The lowest-privilege role can register a member named `x'+fetch('/diretoria/reset-senha/1/')+'` and execute code in a director's session when the director clicks "Recusar", chaining to superuser takeover through the GET endpoints.
* **Code Context:**
  ```python
  <a href="{% url 'recusar_membro' dbv.id %}" class="btn btn-sm btn-outline-danger fw-bold" onclick="return confirm('Tem certeza que deseja recusar e excluir o cadastro de {{ dbv.nome_completo }}?');">
      <i class="fas fa-times-circle me-1"></i> Recusar
  </a>
  ```
* **Architectural Fix Strategy:** Never build JS from template variables in `on*` attributes: use POST forms with static confirmation text or `data-*` attributes read via `dataset`/`textContent` (or `|escapejs` where JS context is unavoidable), add a strict nonce-based CSP without `unsafe-inline`, and add a template lint that rejects `{{ }}` inside event handlers.
---

### 🛑 HIGH - Destructive director actions are state-changing GET endpoints (CSRF/prefetch triggerable)
* **File/Module:** `core/views.py`
* **The Flaw:** `toggle_acesso`, `aprovar_membro`, `recusar_membro` and `reset_senha_diretoria` mutate data on GET without `@require_POST`, so Django's CSRF middleware never applies. The UI triggers them with plain `<a href>` links guarded only by `onclick` confirm().
* **Business/Security Impact:** One `<img src>` in an email or web page viewed by a logged-in director locks accounts, approves or deletes members, or resets passwords; Turbo 8 (referenced in base.html) hover-prefetches such links, which would fire them without the confirm dialog.
* **Code Context:**
  ```python
  usuario_alvo.is_active = not usuario_alvo.is_active
  usuario_alvo.save()
  return redirect('painel_diretoria')
  ```
* **Architectural Fix Strategy:** Make every mutation POST-only behind `@require_POST` with `{% csrf_token %}` forms, mark action links `data-turbo-prefetch="false"`, and add a CI test asserting that no GET route changes database state.
---

### 🛑 HIGH - Production SECRET_KEY committed to public git history alongside DEBUG=True
* **File/Module:** `setup/settings.py`
* **The Flaw:** The key used in production from February to May 2026 is permanently readable in the public GitHub history (commits `e701386`..`b30f467`), and nothing shows it was rotated when it moved to the environment.
* **Business/Security Impact:** Anyone can forge data the app signs with `SECRET_KEY` (signed message cookies, password-reset tokens when combined with any leaked hash, any future `django.core.signing` use); if production still uses that value, every signed artifact across all tenants is untrustworthy.
* **Code Context:**
  ```python
  # SECURITY WARNING: keep the secret key used in production secret!
  SECRET_KEY = os.getenv('SECRET_KEY')
  ```
* **Architectural Fix Strategy:** Treat the key as burned: rotate it now using `SECRET_KEY_FALLBACKS` for a grace window, invalidate sessions, keep per-environment secrets in a secret manager, and add secret scanning (gitleaks or GitHub push protection) to CI.
---

### 🛑 HIGH - Ranking, report and CSV totals inflated by multi-join aggregation over all history
* **File/Module:** `core/views.py`
* **The Flaw:** Each aggregate annotates `Sum()` over two reverse relations (`avaliacoes`, `pontos_extras`) in one query with the month only in `FILTER`, not `WHERE`. The JOIN therefore multiplies every evaluation by every extra-points row the member ever received, and scans the entire history.
* **Business/Security Impact:** Core output is wrong and drifts upward weekly without new activity (20+15 pts shown as 90; ×53 after one year), so awards are decided on corrupted numbers; cost grows quadratically with history (300 members × 52 weeks: dashboard 4 s, report 7.4 s), exhausting workers.
* **Code Context:**
  ```python
  total_regular=Coalesce(
      Sum(TOTAL_REGULAR_EXPR, filter=Q(avaliacoes__data__month=mes, avaliacoes__data__year=ano)), 0
  ),
  ```
* **Architectural Fix Strategy:** Compute each relation in its own `Subquery`/grouped query whose `WHERE` carries tenant id plus a half-open date range, add `(tenant, desbravador, data)` indexes, and ideally serve dashboard/report/CSV from a per-tenant monthly score table maintained on write; add regression tests with multi-month history.
---

### 🛑 HIGH - Counselors can inflate unit rankings: duplicates, backdating, ghost and inactive members
* **File/Module:** `core/views.py`
* **The Flaw:** Score writes have no uniqueness per member and meeting, no date bounds or closed periods, and no `ativo`/`aprovado` check, while the dashboard sums points of never-approved and departed members.
* **Business/Security Impact:** A counselor (or a double submit) can repeat evaluations (130 pts each), backdate into an announced month (reproduced: closed month result reversed), or score a never-approved "ghost" member (unit +130 pts with 0 members); no audit trail exists, so rankings are untrustworthy for every club.
* **Code Context:**
  ```python
  avaliacao.desbravador = membro
  avaliacao.autor = request.user
  avaliacao.save()
  ```
* **Architectural Fix Strategy:** Route all score writes through one validated service: `UniqueConstraint(tenant, desbravador, meeting_date)`, update-or-create semantics, dates bounded to the open period with per-tenant period closing, a tenant-scoped "rankable members" manager used by every query, and `created_at`/`created_by` plus an append-only score audit log.
---

### 🛑 HIGH - Unbounded extra points overflow SQLite SUM and take the dashboard down for all users
* **File/Module:** `core/views.py`
* **The Flaw:** The mass-points POST stores `int(raw POST value)` with no form, bounds, `full_clean` or DB `CHECK` (the only rule lives in the never-used `PontoExtraForm`), and the global dashboard SUM raises `integer overflow` before the result is cached.
* **Business/Security Impact:** One extreme value from any director makes `/dashboard/` (the post-login landing page) return 500 for every user of every club until the row is fixed by hand; a typo such as `999999999` silently decides the month.
* **Code Context:**
  ```python
  pontos=int(pontos),
  motivo=motivo,
  data=date.today()
  ```
* **Architectural Fix Strategy:** Validate points through a form/service with per-tenant bounds (negatives for directors only), add a `CheckConstraint` on the range, enforce `motivo` length, and compute rankings from a per-tenant aggregate table so no single row can break a shared page.
---

### 🛑 HIGH - "Select all" posts every member id twice, doubling mass awards and punishments
* **File/Module:** `core/templates/core/painel_diretoria.html`
* **The Flaw:** Each member is rendered twice in the same form (desktop row and hidden mobile card, both `name="selecionados"`), both select-all handlers tick every `.checkbox-item`, and the view loops the raw list without deduplication.
* **Business/Security Impact:** Every mass award or punishment made with "Selecionar Todos" is applied twice (verified in headless Chrome: +10 became +20 per member), and a member the director unticks still receives the points through the hidden copy; the success banner reports the doubled count.
* **Code Context:**
  ```python
  if(selectAll) { selectAll.addEventListener('change', function() { checkboxes.forEach(cb => cb.checked = this.checked); if(selectAllMobile) selectAllMobile.checked = this.checked; updateCounter(); }); }
  if(selectAllMobile) { selectAllMobile.addEventListener('change', function() { checkboxes.forEach(cb => cb.checked = this.checked); if(selectAll) selectAll.checked = this.checked; updateCounter(); }); }
  ```
* **Architectural Fix Strategy:** Render a single responsive checkbox per member (or disable the off-screen copy), and on the server convert `selecionados` to a set of ints validated against the tenant's rankable members, written with `bulk_create` inside `transaction.atomic` plus an idempotency token.
---

### 🛑 HIGH - Calendar view issues one SQL query per day of the month (N+1)
* **File/Module:** `core/views.py`
* **The Flaw:** `calendario()` builds a new filtered queryset for each calendar day and the template evaluates each one, and `data_evento` has no index.
* **Business/Security Impact:** A main navigation page costs 33 queries per load (measured), each scanning the global events table; latency and DB connection usage grow linearly with tenants and users.
* **Code Context:**
  ```python
  else:
      eventos_do_dia = eventos.filter(data_evento__day=dia)
      dias_semana.append({
  ```
* **Architectural Fix Strategy:** Fetch the month's events once with a tenant-scoped half-open date-range query (`select_related`), group them by day in Python, and add a `(tenant, data_evento)` index.
---

### 🛑 HIGH - Web push sent synchronously inside the DB transaction, without timeout, and duplicated
* **File/Module:** `core/models.py`
* **The Flaw:** The `m2m_changed` receiver runs inside `destinatarios.add()/set()`'s transaction and, per recipient, does ~6 queries plus a blocking HTTPS call (`pywebpush` passes `timeout=None`). `NotificacaoManualAdmin.save_related` then sends every push a second time.
* **Business/Security Impact:** A broadcast holds SQLite's single write lock for its whole duration, so other clubs' logins and score writes fail with `database is locked` (500) after 5 s (measured); large broadcasts exceed worker timeouts and leave partial delivery, a hung push endpoint pins workers indefinitely, and admin-created notices reach users twice.
* **Code Context:**
  ```python
  try:
      send_user_notification(user=user, payload=payload, ttl=1000)
  except Exception as e:
  ```
* **Architectural Fix Strategy:** Use a transactional outbox: persist the notification and bulk-create in-app rows, then enqueue delivery via `transaction.on_commit` on a task queue (Celery/RQ on Redis) with pooled sessions, explicit timeouts, retries, per-subscription idempotency and 404/410 pruning; delete the admin push loop.
---

### 🛑 HIGH - SQLite file database as the production store for a multi-tenant deployment
* **File/Module:** `setup/settings.py`
* **The Flaw:** All tenants share one SQLite file with default options (rollback journal, 5 s busy timeout, deferred transactions), which allows a single writer for the entire database and cannot be shared across app hosts.
* **Business/Security Impact:** Writes from every club (logins, evaluations, approvals, notifications) serialize on one lock, any long write transaction turns into cross-tenant 500s, and the platform cannot scale horizontally or isolate tenants at the database level.
* **Code Context:**
  ```python
  'ENGINE': 'django.db.backends.sqlite3',
  'NAME': BASE_DIR / 'db.sqlite3',
  ```
* **Architectural Fix Strategy:** Migrate to managed PostgreSQL configured from environment variables, with connection pooling, tenant-leading composite indexes, and row-level security or schema-per-tenant; keep network I/O and long work out of transactions.
---

### 🛑 HIGH - Ranking cache is process-local, globally keyed and invalidated on only two write paths
* **File/Module:** `core/views.py`
* **The Flaw:** The ranking is cached in the default per-process `LocMemCache` under a key with no tenant component. Only `avaliar_membro` and the painel POST delete it, and only for the current month, in the worker that served the write.
* **Business/Security Impact:** After approvals, rejections, member registrations, admin edits or member moves (5 paths verified stale) the dashboard shows wrong totals for up to 10 minutes in every worker; once the query is tenant-scoped, the shared key would serve one club's ranking to another.
* **Code Context:**
  ```python
  # 1. Cria uma chave de cache única para o mês atual
  chave_cache = f'ranking_unidades_{mes_atual}_{ano_atual}'
  ```
* **Architectural Fix Strategy:** Use a shared Redis cache with tenant- and period-namespaced versioned keys bumped from `post_save`/`post_delete` handlers in `transaction.on_commit`, or drop the cache in favor of a maintained monthly score table.
---

### 🛑 HIGH - Director panel loads every member, user and pending record unpaginated, rendered twice
* **File/Module:** `core/views.py`
* **The Flaw:** `painel_diretoria` fetches all active members, all users and all pending registrations with no limit, and the template emits each list twice (desktop table and mobile cards), plus redundant COUNT queries.
* **Business/Security Impact:** Page weight grows ~2 KB per entity (41 KB → 232 KB from 1 to 20 members); with global querysets a director's landing page would carry tens of megabytes and every club's children's names once many clubs are onboarded.
* **Code Context:**
  ```python
  desbravadores = (
      Desbravador.objects.filter(ativo=True, aprovado=True)
      .select_related('unidade')
  ```
* **Architectural Fix Strategy:** Scope every panel queryset by tenant, paginate server-side with SQL search (or lazy-load each tab via its own paginated endpoint), and render one responsive list instead of duplicated markup.
---

### 🛑 HIGH - Notification fan-out crosses clubs: "todos" targets every user and unidade_id any club
* **File/Module:** `core/views.py`
* **The Flaw:** `enviar_notificacao_massa` builds recipients from `Usuario.objects.filter(is_active=True)` with no tenant bound and trusts a raw `unidade_id` from POST.
* **Business/Security Impact:** A director of one club can push in-app and browser notifications to every user of every other club, or to a rival club's unit by id (reproduced), causing cross-tenant disclosure and spam, amplified by the synchronous send.
* **Code Context:**
  ```python
  usuarios = Usuario.objects.filter(is_active=True)

  if publico_alvo == 'conselheiros':
  ```
* **Architectural Fix Strategy:** Start the recipient query from `request.tenant` memberships, validate `unidade_id` against the tenant's units, attach a tenant FK to `NotificacaoManual`, and make the delivery job fan out only within that tenant.
---

### 🛑 HIGH - Global identity namespace: usernames are globally unique across all clubs
* **File/Module:** `core/models.py`
* **The Flaw:** `Usuario` inherits `AbstractUser.username` with a global UNIQUE constraint and a single login namespace; `Classe`/`Especialidade` are shared catalogs with no owner.
* **Business/Security Impact:** Onboarding a second club fails with `IntegrityError` on natural usernames like `diretor` (reproduced) and leaks the existence of other clubs' accounts; catalog edits by one club affect all clubs.
* **Code Context:**
  ```python
  class Usuario(AbstractUser):
      """Usuário do sistema (liderança do clube), com cargo, unidade responsável e flags de aprovação e diretoria."""
  ```
* **Architectural Fix Strategy:** Scope identity per tenant: replace the global unique with `UniqueConstraint(club, username)` (or per-club email login) via migration, authenticate within the resolved tenant, and give catalogs a tenant FK or make them read-only platform data.
---

### 🛑 HIGH - Score history is mutable and destructible: rankings recompute from current membership
* **File/Module:** `core/views.py`
* **The Flaw:** `recusar_membro` hard-deletes any member by id (including approved ones), cascading all evaluations and points. Score rows store no unit or tenant snapshot, so moving or deactivating a member rewrites every past month's ranking.
* **Business/Security Impact:** One mistaken or forged request permanently erases a member's history; moving a member transferred all past points to the new unit and deactivation removed them from past reports (reproduced), so no published ranking is reproducible or auditable.
* **Code Context:**
  ```python
  membro = get_object_or_404(Desbravador, id=id_dbv)
  membro.delete()
  return redirect('painel_diretoria')
  ```
* **Architectural Fix Strategy:** Restrict rejection to pending records in the tenant, use soft delete/anonymization and `PROTECT` on score FKs, snapshot `unidade_id`/`tenant_id` on each score row, keep a membership-history table, and freeze closed months into an immutable per-tenant `MonthlyUnitScore` table.
---

### 🛑 HIGH - Business month computed in UTC with one global timezone for all tenants
* **File/Module:** `core/views.py`
* **The Flaw:** Dashboard, report, CSV and cache keys derive the month from `timezone.now()` (UTC), while stored score dates are local calendar dates; `TIME_ZONE` is a single global constant.
* **Business/Security Impact:** From 21:00 BRT on the last day of each month the dashboard shows the next (empty) month and points entered that evening never appear; admin forms pre-fill tomorrow's date after 21:00; clubs in other time zones get points in the wrong day or month.
* **Code Context:**
  ```python
  hoje = timezone.now()
  mes_atual = hoje.month
  ano_atual = hoje.year
  ```
* **Architectural Fix Strategy:** Store a timezone per tenant, activate it per request in middleware, derive every business date and period from `timezone.localdate()`, and model scoring periods explicitly as `(tenant, year, month)` shared by queries, cache keys and labels.
---

### 🛑 HIGH - Unpinned third-party module from Skypack executes on every authenticated page
* **File/Module:** `core/templates/core/base.html`
* **The Flaw:** base.html loads `https://cdn.skypack.dev/@hotwired/turbo` with no version pin and no Subresource Integrity on every page, including the director panel; other CDN assets lack SRI too.
* **Business/Security Impact:** A CDN compromise or malicious release gains full script access to directors' sessions across all tenants; today Skypack serves a throwing build-error stub for v8.0.23, so the "native app" Turbo layer is silently broken in production.
* **Code Context:**
  ```python
  <head>
      <script type="module" src="https://cdn.skypack.dev/@hotwired/turbo"></script> <!-- Script para que tudo rode sem travas, como um app nativo do OP -->
  ```
* **Architectural Fix Strategy:** Self-host pinned front-end assets through the static pipeline (or pin exact versions with `integrity`/`crossorigin`), remove Skypack, and enforce a CSP that allows scripts only from your own origin.
---

### 🛑 HIGH - Club identity and contact data hardcoded in settings, templates and PWA files
* **File/Module:** `setup/settings.py`
* **The Flaw:** Tenant-facing identity (product name, author footer, colors, logo, manifest name/icon hotlinked from flaticon) and the push-service contact (a personal Gmail) are compiled into code; icon paths are hardcoded absolute URLs to a file that does not exist.
* **Business/Security Impact:** Every club would see one club's branding and one person's personal email as the push contact; white-labeling or contact changes require code deploys, and PWA/notification icons 404.
* **Code Context:**
  ```python
      "VAPID_PRIVATE_KEY": os.getenv('VAPID_PRIVATE_KEY'),
      "VAPID_ADMIN_EMAIL": "joaocintraduarte@gmail.com"
  }
  ```
* **Architectural Fix Strategy:** Move branding and contact data into a per-tenant settings model (name, colors, logo in tenant-namespaced media storage), render manifest and service worker per tenant via `{% static %}`/storage URLs, and read deployment-level values from environment variables.
---
