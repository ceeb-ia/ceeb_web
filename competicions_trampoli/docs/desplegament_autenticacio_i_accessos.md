# Desplegament d'Autenticacio i Control d'Accessos

Aquest document resumeix el desenvolupament fet sobre autenticacio, autoritzacio i separacio de rutes a `competicions_trampoli`.

L'objectiu ha estat reduir els riscos inicials detectats a la capa d'acces, sense substituir el flux de jutges per token i sense abordar encara altres blocs de seguretat no relacionats amb login.

## Objectiu funcional

S'ha implantat una base d'accés intern amb:

- login Django estandard per backoffice
- rols globals de plataforma
- permisos per competicio
- separacio entre rutes internes i rutes publiques/token
- manteniment del flux de jutges per QR/token

## Criteris de disseny adoptats

### 1. No convertir els jutges en usuaris Django

S'ha mantingut el model existent de `JudgeDeviceToken` per a jutges i dispositius de pista.

Motiu:

- hi ha molts jutges i moltes competicions
- crear i gestionar un usuari complet per cada jutge seria massa costós
- el flux de QR/token encaixa millor amb una operativa de competicio

### 2. Fer servir autenticacio Django nativa per al backoffice

Per a usuaris interns s'ha triat:

- `django.contrib.auth`
- sessions
- login/logout
- password reset/change
- admin de Django

Motiu:

- es una base robusta i provada
- simplifica manteniment
- permet escalar rols i permisos sense reinventar autenticacio

### 3. Separar rols globals de rols per competicio

S'ha distingit entre:

- accessos globals de plataforma
- accessos locals dins d'una competicio concreta

Motiu:

- un usuari pot tenir accés general al modul de competicions
- un altre usuari pot tenir accés nomes a una competicio concreta
- els permisos per competicio no encaixen be si nomes es fan amb `Group`

## Fases executades

## Fase 1. Base d'autenticacio

S'han configurat els ajustos basics d'autenticacio a `ceeb_web/settings.py`:

- `LOGIN_URL`
- `LOGIN_REDIRECT_URL`
- `LOGOUT_REDIRECT_URL`

També s'han afegit rutes d'autenticacio via `django.contrib.auth.urls` a `ceeb_web/urls.py`.

## Fase 2. Plantilles d'accés

S'han creat plantilles a `templates/registration/` per:

- login
- password reset form
- password reset done
- password reset confirm
- password reset complete
- password reset email
- password reset subject
- password change form
- password change done

A `templates/base.html` s'han afegit:

- enllac a login per usuaris anonims
- enllac a admin per usuaris autenticats
- boto de logout

## Fase 3. Tancament inicial de `competicions_trampoli`

En una primera passada, les rutes internes de `competicions_trampoli` es van protegir amb login.

Es van mantenir obertes:

- rutes `judge/<token>/...`
- rutes `public/live/<token>/...`

Motiu:

- no trencar el flux de jutges i pantalles publiques mentre s'implantava el model complet d'accessos

## Fase 4. Grups globals

S'ha creat `ceeb_web/auth_groups.py` amb els grups globals base:

- `platform_admin`
- `competicions_manager`
- `designacions_manager`
- `informes_manager`
- `calendar_manager`
- `readonly_backoffice`

També s'ha creat el comandament:

- `python manage.py bootstrap_auth_groups`

Aquest comandament:

- crea els grups si no existeixen
- no crea usuaris
- es idempotent

## Fase 5. Model de permisos per competicio

S'ha afegit el model `CompeticioMembership` a `competicions_trampoli/models.py`.

Rols disponibles:

- `owner`
- `editor`
- `judge_admin`
- `scoring`
- `rotacions`
- `classificacions`
- `readonly`

S'ha creat la migracio:

- `competicions_trampoli/migrations/0035_competiciomembership.py`

Aquest model permet:

- assignar un usuari a una competicio
- definir el seu rol dins d'aquella competicio
- activar o desactivar l'accés
- saber qui l'ha concedit

## Fase 6. Capa reutilitzable d'autoritzacio

S'ha creat `competicions_trampoli/access.py`.

Aquest modul defineix:

- mapatge de capacitats per rol
- comprovacio de grups globals
- comprovacio de permisos per competicio
- decoradors reutilitzables
- mixins reutilitzables

Capacitats utilitzades:

- `competition.view`
- `competition.edit`
- `competition.delete`
- `inscripcions.view`
- `inscripcions.edit`
- `scoring.view`
- `scoring.edit`
- `rotacions.view`
- `rotacions.edit`
- `classificacions.view`
- `classificacions.edit`
- `judge_tokens.manage`
- `public_live.manage`

## Fase 7. Reconnexio de rutes internes a permisos reals

S'ha reestructurat `competicions_trampoli/urls.py` per aplicar permisos segons el tipus de ruta.

Ara hi ha dos nivells:

- rutes globals del modul de competicions:
  - reservades a `platform_admin` o `competicions_manager`
- rutes d'una competicio concreta:
  - protegides per capacitat i membresia en aquella competicio

Exemples:

- notes i scoring: capacitats de `scoring`
- rotacions: capacitats de `rotacions`
- builder de classificacions: capacitats de `classificacions`
- gestio de QR de jutges: `judge_tokens.manage`
- gestio de public live: `public_live.manage`

## Fase 8. Admin d'usuaris i membresies

S'ha ampliat `competicions_trampoli/admin.py`.

Canvis:

- admin de `Competicio` amb inline de membresies
- admin de `CompeticioMembership`
- admin de `CompeticioAparell`
- extensio de l'admin d'usuaris per veure membresies per competicio
- resum dels rols globals a la llista d'usuaris
- filtre per grups globals

Resultat:

- la gestio de rols i accessos es pot fer des de `/admin/`
- no cal una UI propia addicional per a aquesta primera fase

## Fase 9. Separacio entre live intern i live public

Inicialment el `public live` depenia d'una redireccio cap a una URL interna de competicio amb parametres.

S'ha canviat el model per separar:

- live intern
- live loop intern
- live public per token
- live loop public per token
- endpoint de dades public per token

S'han tocat:

- `competicions_trampoli/views_classificacions.py`
- `competicions_trampoli/urls.py`
- templates de live i loop live

Resultat:

- el live intern queda sota login i permisos
- el live public te rutes propies per token
- el frontend ja pot consumir una `data_url` explicita

## Fase 10. Ajustos de la UI publica i de l'admin de tokens

S'ha afegit al panell de tokens publics:

- acces directe a la vista publica live
- acces directe al mode loop public
- acces al QR

S'ha ajustat el frontend de classificacions per treballar amb una URL de dades injectada des del backend.

## Fitxers principals afectats

### Configuracio i autenticacio

- `ceeb_web/settings.py`
- `ceeb_web/urls.py`
- `ceeb_web/auth_groups.py`
- `ceeb_web/management/commands/bootstrap_auth_groups.py`

### Competicions

- `competicions_trampoli/models.py`
- `competicions_trampoli/access.py`
- `competicions_trampoli/urls.py`
- `competicions_trampoli/views_classificacions.py`
- `competicions_trampoli/admin.py`
- `competicions_trampoli/tests.py`
- `competicions_trampoli/migrations/0035_competiciomembership.py`

### Templates

- `templates/base.html`
- `templates/registration/*`
- `competicions_trampoli/templates/competicio/classificacions_live.html`
- `competicions_trampoli/templates/competicio/classificacions_loop_live.html`
- `competicions_trampoli/templates/judge/admin_public_live_tokens.html`

## Canvis de comportament resultants

### Backoffice

Ara requereix autenticacio per a l'operativa interna de competicions.

### Rols globals

Existeix base per distingir:

- administracio global
- gestio global de competicions
- lectura
- altres moduls interns

### Rols per competicio

Ara es pot decidir per cada competicio:

- qui veu
- qui edita
- qui porta scoring
- qui gestiona rotacions
- qui administra QR
- qui publica el live public

### Jutges

No passen a login clàssic.

Continuen amb:

- tokens
- QR
- permisos acotats per aparell i camp

### Public live

Ja no hauria de dependre del `pk` intern de competicio com a mecanisme principal d'accés public.

## Tasques pendents per deixar-ho operatiu a la base de dades

Cal executar:

```powershell
python manage.py migrate
python manage.py bootstrap_auth_groups
```

Despres cal:

- crear o reutilitzar usuaris interns
- assignar-los grups globals
- crear membresies per competicio des de l'admin

## Validacions fetes durant el desenvolupament

S'ha validat:

- sintaxi Python amb `python -m py_compile` en els fitxers tocats

No s'ha pogut completar:

- `manage.py check` en aquest entorn concret, per dependencies no disponibles

## Limitacions actuals

- Encara no s'ha aplicat aquest mateix patró a totes les altres apps internes del projecte.
- Encara no s'ha construït una UI funcional pròpia per gestionar membresies fora de l'admin.
- Encara no s'ha abordat la resta de riscos del document de robustesa, com concurrencia de scoring, secrets per defecte o exposicio de videos.

## Estat final d'aquesta tasca

Queda implantada la base de:

- autenticacio interna
- rols globals
- rols per competicio
- restriccio de gestio QR
- separacio de live intern i live public
- administracio dels accessos des de `/admin/`

Aquest bloc es considera completat a nivell d'arquitectura i codi pendent d'execucio de migracions i assignacio de rols reals.
