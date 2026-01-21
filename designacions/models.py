# designacions_app/models.py
from django.db import models

class DesignationRun(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("processing", "Processing"),
        ("done", "Done"),
        ("failed", "Failed"),
    ]
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    result_summary = models.JSONField(null=True, blank=True, default=dict)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    error = models.TextField(null=True, blank=True)

    task_id = models.CharField(max_length=64, unique=True, db_index=True)
    map_path = models.CharField(max_length=500, null=True, blank=True)

    input_partits = models.FileField(upload_to="designacions/inputs/", null=True, blank=True)
    input_disponibilitats = models.FileField(upload_to="designacions/inputs/", null=True, blank=True)

    def __str__(self):
        return f"Run {self.id} ({self.status})"


class Referee(models.Model):
    # codi tutor real (ex: "5016 F5")
    code = models.CharField(max_length=50, unique=True, db_index=True)  # "Codi Tutor de Joc"
    name = models.CharField(max_length=255, db_index=True)              # Nom + Cognoms

    nif = models.CharField(max_length=20, null=True, blank=True)        # "Nif/Nie"
    level = models.CharField(max_length=50, null=True, blank=True)      # "Nivell"
    modality = models.CharField(max_length=120, null=True, blank=True)  # "Modalitat"
    transport = models.CharField(max_length=50, null=True, blank=True)  # "Mitjà de Transport"

    active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.code})"


class Match(models.Model):
    run = models.ForeignKey(DesignationRun, on_delete=models.CASCADE, related_name="matches")

    # Del teu excel de partits:
    code = models.CharField(max_length=80, db_index=True)            # "Codi" (identificador operatiu)
    engine_id = models.CharField(max_length=20, null=True, blank=True, db_index=True)  # hash "ID" del motor (opcional)

    club_local = models.CharField(max_length=255, null=True, blank=True)    # "Club Local"
    equip_local = models.CharField(max_length=255, null=True, blank=True)   # "Equip local"
    equip_visitant = models.CharField(max_length=255, null=True, blank=True)# "Equip visitant"

    lliga = models.CharField(max_length=255, null=True, blank=True)         # "Lliga"
    group = models.CharField(max_length=255, null=True, blank=True)         # "Grup"
    jornada = models.CharField(max_length=50, null=True, blank=True)        # "Jornada"
    modality = models.CharField(max_length=120, null=True, blank=True)      # "Modalitat"
    category = models.CharField(max_length=120, null=True, blank=True)      # "Categoria"
    subcategory = models.CharField(max_length=120, null=True, blank=True)   # "Subcategoria"

    date = models.DateField(null=True, blank=True)                          # "Data"
    hour_raw = models.CharField(max_length=50, null=True, blank=True)       # "Hora" (tal qual)
    domicile = models.CharField(max_length=255, null=True, blank=True)      # "Domicili"
    municipality = models.CharField(max_length=120, null=True, blank=True)  # "Municipi"
    venue = models.CharField(max_length=255, null=True, blank=True)         # "Pista joc"
    sub_venue = models.CharField(max_length=255, null=True, blank=True)     # "SubPista joc"

    def __str__(self):
        return f"{self.code} - {self.club_local}"


class Availability(models.Model):
    run = models.ForeignKey(DesignationRun, on_delete=models.CASCADE, related_name="availabilities")
    referee = models.ForeignKey(Referee, on_delete=models.CASCADE, related_name="availabilities")
    raw = models.JSONField(default=dict)

    def __str__(self):
        return f"Avail {self.referee.code} (run {self.run_id})"


class Assignment(models.Model):
    run = models.ForeignKey(DesignationRun, on_delete=models.CASCADE, related_name="assignments")
    match = models.OneToOneField(Match, on_delete=models.CASCADE, related_name="assignment")

    referee = models.ForeignKey(Referee, on_delete=models.SET_NULL, null=True, blank=True, related_name="assignments")
    locked = models.BooleanField(default=False)
    note = models.CharField(max_length=255, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.match.code} -> {self.referee_id}"



class ModalityMap(models.Model):
    """
    Equivalent a map_modalitat_nom.csv (Id Categoria;Modalitat;Nom;Descripció;Nom Abreviat;Ordre;CodiExtern)
    Mantinc key/name per compatibilitat amb imports previs.
    """
    # Camps “antics” (ja tens dades) -> NO els eliminem
    key = models.CharField(max_length=255, unique=True, db_index=True)   # abans 120 (et petava)
    name = models.CharField(max_length=255)

    # Camps nous (del CSV real) -> nullable per no trencar registres existents
    id_categoria = models.IntegerField(null=True, blank=True, db_index=True)
    modalitat = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    nom = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    descripcio = models.TextField(null=True, blank=True)
    nom_abreviat = models.CharField(max_length=255, null=True, blank=True)
    ordre = models.IntegerField(null=True, blank=True)
    codi_extern = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"{self.modalitat or self.key} / {self.nom or self.name}"


class Address(models.Model):
    """
    Master d’adreces (substitueix domicilis_geocodificats.csv)
    """
    text = models.CharField(max_length=500, unique=True, db_index=True)
    municipality = models.CharField(max_length=120, null=True, blank=True)

    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)

    geocode_status = models.CharField(
        max_length=20,
        default="pending",
        choices=[("pending","pending"), ("ok","ok"), ("not_found","not_found"), ("manual","manual")]
    )
    provider = models.CharField(max_length=50, null=True, blank=True)
    last_error = models.CharField(max_length=255, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.text


class AddressCluster(models.Model):
    """
    Clusterització PER RUN (substitueix domicilis_clusteritzats.csv)
    """
    run = models.ForeignKey("DesignationRun", on_delete=models.CASCADE, related_name="address_clusters")
    address = models.ForeignKey(Address, on_delete=models.CASCADE, related_name="clusters")

    cluster_id = models.IntegerField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("run", "address")
