# Resum de la conversa

## **Context inicial**
L'usuari treballa en un projecte Django amb Celery per gestionar tasques en segon pla. Té una `view` síncrona que desa fitxers i envia una tasca a Celery (`process_certificats_task`). Aquesta tasca és asíncrona (`async def`) i fa una petició HTTP a un servei extern (`CERTIFICATS_API`) utilitzant `httpx`.

---

## **Temes tractats**

### **1. Diferència entre `sync` i `async`**
- Les operacions síncrones (`sync`) bloquegen el fil fins que es completen.
- Les operacions asíncrones (`async`) permeten que el fil cedeixi el control durant punts d'espera (`await`), millorant la concurrència.

### **2. Com funciona Celery amb tasques asíncrones**
- Celery pot gestionar tasques asíncrones si el treballador està configurat amb el pool `solo`.
- Quan una tasca asíncrona s'executa, Celery utilitza un **event loop** per gestionar-la.
- L'event loop és únic per al treballador i pot alternar entre múltiples tasques asíncrones.

### **3. Flux d'execució en el projecte**
1. La `view` síncrona crida `process_certificats_task.delay()`, que envia la tasca a la cua de Celery.
2. El treballador Celery rep la tasca i la comença a executar.
3. Si la tasca és asíncrona, l'event loop del treballador gestiona l'execució i cedeix el control en punts d'espera (`await`).

### **4. Beneficis de l'`async` en Celery**
- **Concurrència millorada:** El treballador pot gestionar múltiples tasques simultàniament.
- **No bloqueig:** Les operacions d'E/S no bloquegen el treballador.
- **Escalabilitat:** Es poden gestionar més tasques amb menys recursos.

### **5. Punts d'enganxament de l'event loop**
- L'event loop es pot enganxar en qualsevol operació asíncrona (`await`), com:
  - Peticions HTTP amb `httpx`.
  - Operacions de fitxers amb `aiofiles`.

### **6. Optimització de la tasca `process_certificats_task`**
- Es va suggerir substituir operacions síncrones amb fitxers (`open`, `write`, `os.remove`) per equivalents asíncrones amb `aiofiles`.
- Això permet establir més punts d'enganxament per a l'event loop, millorant la concurrència.

---

## **Exemple de codi optimitzat**
Es va proporcionar una versió millorada de la tasca `process_certificats_task` amb `aiofiles` per fer les operacions de fitxers asíncrones:

```python
import aiofiles

@shared_task(bind=True, queue='async_queue')
async def process_certificats_task(self, file_paths):
    try:
        self.update_state(state='STARTED', meta={'logs': ['Iniciant el procés...']})
        multipart = [
            ('files', (os.path.basename(path), await aiofiles.open(path, 'rb')))
            for path in file_paths
        ]

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(CERTIFICATS_API, files=multipart)

        if resp.status_code != 200:
            raise Exception(f"Error del servei de certificats ({resp.status_code}).")

        buffer = io.BytesIO(resp.content)
        zip_filename = f"certificats_{uuid.uuid4()}.zip"
        zip_path = os.path.join(settings.MEDIA_ROOT, 'certificats', zip_filename)
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)

        async with aiofiles.open(zip_path, 'wb') as zip_file:
            await zip_file.write(buffer.getvalue())

        for path in file_paths:
            try:
                await aiofiles.os.remove(path)
            except FileNotFoundError:
                pass

        return f"{settings.MEDIA_URL}certificats/{zip_filename}"
    except Exception as e:
        self.update_state(state='FAILURE', meta={'logs': [str(e)]})
        raise