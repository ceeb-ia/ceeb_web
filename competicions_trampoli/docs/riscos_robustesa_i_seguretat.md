# Riscos de Robustesa i Seguretat

Aquest document recull els principals riscos detectats a `competicions_trampoli` abans de començar la seva correccio puntual.

L'objectiu es tenir una llista de treball clara per resoldre'ls un a un, sense barrejar encara la fase d'analisi amb la d'implementacio.

## Abast

- Modul de competicions de trampoli
- Fluxos d'administracio de competicions
- Fluxos de scoring i jutges
- Classificacions live
- Upload i publicacio de videos
- Configuracio base amb impacte directe sobre seguretat i operacio

## Riscos prioritaris

### 1. Secrets insegurs i configuracio insegura per defecte

La configuracio actual permet arrencar l'aplicacio amb valors per defecte per `SECRET_KEY`, `DEBUG` i `EMAIL_HOST_PASSWORD` si falten variables d'entorn.

Risc:

- L'aplicacio no falla de manera segura quan falta configuracio critica.
- Es possible exposar traces, configuracio interna o comportaments de debug en entorns no previstos.
- Una clau coneguda o previsible redueix fortament la seguretat global del sistema.

Impacte:

- Alt

### 2. Control d'acces inconsistent a l'administracio de competicions

Diverses pantalles i operacions de gestio de competicions, inscripcions, scoring i configuracio no tenen un patró d'autenticacio i autoritzacio consistent.

Risc:

- Es poden consultar o modificar dades de competicio sense una barrera clara d'accés.
- Es poden crear, editar o eliminar recursos sensibles sense un model de permisos explicit.
- El risc es especialment alt si la instancia es accessible fora d'una xarxa interna controlada.

Impacte:

- Critic

### 3. Gestio de tokens QR d'administracio sense proteccio suficient

La creacio i revocacio de tokens de jutges i de public live forma part de l'administracio funcional del sistema, pero actualment no queda clarament protegida per autenticacio forta.

Risc:

- Es poden generar tokens d'accés a fluxos sensibles per tercers no autoritzats.
- Es poden revocar o regenerar accessos sense control operatiu fiable.
- La seguretat del flux de jutges queda condicionada per una capa d'entrada massa oberta.

Impacte:

- Critic

### 4. El mode public live no queda realment protegit pel token public

Existeix un token per compartir classificacions live, pero el flux public es basa en una redireccio i la vista live es pot consultar directament per identificador de competicio.

Risc:

- El token public no actua com a veritable mecanisme de proteccio.
- Coneixent o endevinant l'identificador d'una competicio es pot accedir a classificacions live.
- Es desdibuixa la diferencia entre recurs public compartit i recurs intern de la competicio.

Impacte:

- Alt

### 5. Exposicio publica de videos sota `/media/`

Els videos pujats pels jutges queden servits com a fitxers sota `MEDIA_URL` i es poden convertir en URL directes descarregables si se'n coneix la ruta.

Risc:

- Els fitxers multimedia poden quedar accessibles fora del flux de token.
- Es perd control real sobre qui pot visualitzar o descarregar els videos.
- Hi ha risc de privacitat, especialment tractant-se de menors o d'entorns esportius escolars.

Impacte:

- Alt

### 6. Risc de perdua de dades per concurrencia a l'escriptura de puntuacions

Els fluxos de guardat parcial i de guardat de jutges fan operacions de lectura, merge i escriptura sobre la mateixa entrada de puntuacio.

Risc:

- Dues peticions simultanies poden llegir el mateix estat antic i trepitjar-se.
- Es poden perdre valors parcials introduits per diferents jutges o per autosave concurrent.
- El sistema pot semblar correcte en proves manuals i fallar el dia de competicio sota us real.

Impacte:

- Alt

### 7. Validacio de video massa dependent del client

La validacio del tipus MIME i de la durada del video depen en bona part de metadades enviades o suggerides pel client.

Risc:

- Es poden acceptar fitxers incorrectes, corruptes o falsejats.
- La validacio funcional de l'MVP no garanteix robustesa davant entrades malicioses o defectuoses.
- Els errors poden aparèixer tard, un cop el fitxer ja ha estat guardat o publicat.

Impacte:

- Mitja

### 8. Exposicio de dades live sense una capa d'autoritzacio formal

Les dades de classificacions live i altres recursos de consulta es basen principalment en el coneixement de la URL o del `pk` de competicio.

Risc:

- Es poden consultar dades operatives sense cap comprovacio de rol o context.
- L'aillament entre competicions depen massa de la discrecio de les rutes.
- Es complica justificar el sistema des del punt de vista de privacitat i minim privilegi.

Impacte:

- Alt

### 9. Cobertura de tests insuficient per riscos de seguretat i concurrencia

Hi ha tests útils de domini i de flux funcional, pero no es veu cobertura especifica per concurrencia, control d'accés administratiu, aillament de dades o proteccio real dels endpoints public/live.

Risc:

- Errors greus poden passar a produccio sense ser detectats.
- Les regressions de seguretat poden quedar invisibles mentre els fluxos funcionals continuin passant.
- Es dificulta refactoritzar amb confiança les parts mes sensibles.

Impacte:

- Mitja

## Observacions generals

- El model de domini esta ben encaminat en integritat de dades i restriccions funcionals.
- La part mes feble no es tant el calcul de puntuacions com la capa d'exposicio, accessos i operacio.
- El sistema sembla mes robust per entorn intern controlat que no pas per un entorn obert o semiobert.
- La prioritat inicial hauria de centrar-se en accessos, secrets, visibilitat de dades i concurrencia.

## Ordre recomanat de tractament

Sense entrar encara en solucions concretes, l'ordre de revisio recomanat es:

1. Configuracio insegura per defecte
2. Control d'acces d'administracio
3. Proteccio real de tokens i public live
4. Exposicio de videos i recursos sota `media`
5. Concurrencia en escriptures de scoring
6. Validacio dura de fitxers de video
7. Ampliacio de cobertura de tests

## Estat

- Document inicial redactat
- Sense canvis funcionals aplicats encara
