# Estructura Canonica Del Paquet

`competicions_trampoli` fa servir aquests punts d'entrada canònics:

- `competicions_trampoli.models`
- `competicions_trampoli.models.<domini>`
- `competicions_trampoli.urls`
- `competicions_trampoli.views.judge.admin`
- `competicions_trampoli.views.judge.messages`

Els antics fitxers top-level de models, urls i façanes de views s'han retirat del repo. Qualsevol codi nou ha d'importar des dels paquets canònics anteriors.
