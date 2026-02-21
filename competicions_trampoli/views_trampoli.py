from collections import defaultdict
from types import SimpleNamespace
from django.shortcuts import get_object_or_404
from django.views.generic import TemplateView, UpdateView
from django.urls import reverse
from competicions_trampoli.forms import CompeticioAparellForm
from competicions_trampoli.models_classificacions import ClassificacioConfig
from .models import Competicio, Inscripcio
from .models_trampoli import TrampoliConfiguracio, TrampoliNota, CompeticioAparell, Aparell
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db import IntegrityError
import json
from django.views.generic import ListView, CreateView, View
from django import forms
from django.shortcuts import redirect
from competicions_trampoli.forms import CompeticioAparellForm, AparellForm
from django.views.generic import ListView, CreateView, UpdateView





class TrampoliNotesHome(TemplateView):
    template_name = "competicio/trampoli_notes_home.html"

    def get(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = self.competicio

        cfg, _ = TrampoliConfiguracio.objects.get_or_create(
            competicio=competicio,
            defaults={
                "nombre_jutges_execucio": 3,
                "nombre_jutges_dificultat": 1,
                "nombre_exercicis": 1,
            },
        )

        ins = (
            Inscripcio.objects
            .filter(competicio=competicio)
            .order_by("grup", "ordre_sortida", "id")
        )

        # --- grups ---
        grouped = defaultdict(list)
        for r in ins:
            grouped[r.grup if r.grup is not None else 0].append(r)

        group_keys = sorted([k for k in grouped.keys() if k != 0])
        if 0 in grouped:
            group_keys = [0] + group_keys
        groups = [(g, grouped[g]) for g in group_keys]

        # --- exercicis (1..4) ---
        n_ex = int(getattr(cfg, "nombre_exercicis", 1) or 1)
        n_ex = max(1, min(4, n_ex))
        exercicis = list(range(1, n_ex + 1))

        # --- aparells configurats a la competició (actius) ---
        aparells_cfg = CompeticioAparell.objects.filter(
            competicio=competicio,
            actiu=True,
        ).select_related("aparell").order_by("ordre", "id")

        # si no n'hi ha, crea'n un per defecte
        if not aparells_cfg.exists():
            a, _ = Aparell.objects.get_or_create(codi="TRAMP", defaults={"nom": "Trampolí"})
            CompeticioAparell.objects.create(
                competicio=competicio,
                aparell=a,
                ordre=1,
                nombre_elements=11,
                te_execucio=True,
                te_dificultat=True,
                te_tof=True,
                te_hd=True,
                te_penalitzacio=True,
                mode_execucio="salts",
                actiu=True,
            )
            aparells_cfg = CompeticioAparell.objects.filter(
                competicio=competicio,
                actiu=True,
            ).select_related("aparell").order_by("ordre", "id")

        # --- Classificacions configurades a la competició (actius) ---
        classificacions_cfg = ClassificacioConfig.objects.filter(
            competicio=competicio,
            activa=True,
        ).select_related("schema")


        # màxim de salts per poder fer ljust al template
        max_salts = max([int(x.nombre_elements or 0) for x in aparells_cfg] + [0])

        # --- notes existents: per tots els exercicis i aparells ---
        notes_qs = TrampoliNota.objects.filter(
            competicio=competicio,
            inscripcio__in=ins,
            exercici__in=exercicis,
            comp_aparell__in=aparells_cfg,
        )

        # (ins_id, ex, comp_aparell_id) -> nota
        notes_by_key = {(n.inscripcio_id, n.exercici, n.comp_aparell_id): n for n in notes_qs}

        # JSON pel front: "insId|ex|appId"
        notes_payload = {}
        for n in notes_qs:
            key = f"{n.inscripcio_id}|{n.exercici}|{n.comp_aparell_id}"
            notes_payload[key] = {
                "notes_execucio": n.notes_execucio,
                "execucio_manuals": n.execucio_manuals,
                "crash_execucio": n.crash_execucio,
                "dificultat": float(n.dificultat),
                "tof": float(n.tof),
                "hd": float(n.hdc),
                "penalitzacio": float(n.penalitzacio),
                "execucio_manual": float(n.execucio_manual) if n.execucio_manual is not None else None,
                "execucio_total": float(n.execucio_total),
                "total": float(n.total),
                "exercici": int(n.exercici),
                "comp_aparell_id": int(n.comp_aparell_id),
            }

        ctx["notes_json"] = json.dumps(notes_payload)

        ctx.update({
            "competicio": competicio,
            "cfg": cfg,
            "groups": groups,
            "aparells_cfg": aparells_cfg,     
            "classificacions_cfg": classificacions_cfg,
            "exercicis": exercicis,
            "n_exercicis": n_ex,
            "n_jutges": cfg.nombre_jutges_execucio,
            "max_salts": max_salts,           # NOU (per fer el for al template)
            "notes_by_key": notes_by_key,     # NOU
            "ins_count": ins.count(),
        })
        return ctx




class ConfiguracioCompeticio(TemplateView):
    template_name = "competicio/configuracio_trampoli.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        competicio = get_object_or_404(Competicio, pk=self.kwargs["pk"])

        # El teu template fa servir "object.competicio.nom" i "object.competicio.aparells_cfg..."
        # així que li passem un objecte "fake" amb l'atribut competicio.
        ctx["object"] = SimpleNamespace(competicio=competicio)

        return ctx


NUM_SALTS = 11



def calc_execucio_jutge(deduccions_11, crash_at: int) -> float:
    """
    deduccions_11: [S1..S11] en dècimes (0..10)
    crash_at: 0 = sense crash; si crash_at=3 => només compta fins S2
    """
    vals = list(deduccions_11 or [])
    vals = (vals + [0] * NUM_SALTS)[:NUM_SALTS]

    # normalitza i limita a 0..10 (dècimes)
    norm = []
    for v in vals:
        try:
            x = float(v)
        except (TypeError, ValueError):
            x = 0.0
        norm.append(max(0.0, min(10.0, x)))

    # quants elements s'han fet (k salts puntuables)
    if crash_at and crash_at > 0:
        k = max(0, min(NUM_SALTS, int(crash_at) - 1))
    else:
        # si no hi ha crash i vols "prefix omplert", canvia aquest criteri.
        k = NUM_SALTS

    # punts base: S1..S10 sumen 1 punt per element fet (S11 NO suma punt)
    base = min(k, 10)

    # deduccions: sumem les dècimes dels salts fets (inclou S11 si k==11)
    ded = sum(norm[:k]) / 10.0

    total = base - ded
    print("calc_execucio_jutge:", vals, crash_at, "->", total)
    return total

def _to_float(v):
    try:
        if v is None or v == "":
            return 0.0
        return float(v)
    except (TypeError, ValueError):
        return 0.0

def _avg(vals):
    vals = list(vals or [])
    return (sum(vals) / len(vals)) if vals else 0.0


def _select_exec_notes(exec_scores, k: int, criteri: str):
    """
    exec_scores: llista de notes (float) per jutge (mes alta = millor).
    k: quantes notes compten (>=1)
    criteri:
      - totes: agafa les millors k (si k<n) i mitjana
      - eliminar_extrems: elimina extrems fins quedar k
          * si n = k+1: elimina el valor mes allunyat de la mediana
            (empat -> elimina el maxim)
      - maximes: agafa les k mes altes
      - minimes: agafa les k mes baixes
    """
    vals = [float(x) for x in (exec_scores or [])]
    n = len(vals)
    if n == 0:
        return []

    k = max(1, min(int(k), n))

    if criteri == "minimes":
        return sorted(vals)[:k]

    if criteri == "maximes":
        return sorted(vals, reverse=True)[:k]

    if criteri == "eliminar_extrems":
        s = sorted(vals)
        if len(s) <= k:
            return s

        # Cas especial: n = k + 1 (nomes sobra 1)
        if len(s) == k + 1:
            # mediana de s (len impar o parell)
            m = len(s)
            if m % 2 == 1:
                med = s[m // 2]
            else:
                med = (s[m // 2 - 1] + s[m // 2]) / 2.0

            # elimina el mes llunya de la mediana; si empat, elimina el maxim
            dists = [abs(x - med) for x in s]
            max_dist = max(dists)
            idxs = [i for i, d in enumerate(dists) if d == max_dist]
            drop_idx = idxs[-1]  # el de mes a la dreta = el maxim en empat

            s.pop(drop_idx)
            return s

        # Cas general: si sobren >= 2, treu parelles min+max
        while len(s) > k and (len(s) - 2) >= k:
            s = s[1:-1]

        # Si encara sobra 1 (molt poc habitual despres d'aixo), aplica mateixa regla de mediana
        if len(s) > k:
            m = len(s)
            if m % 2 == 1:
                med = s[m // 2]
            else:
                med = (s[m // 2 - 1] + s[m // 2]) / 2.0
            dists = [abs(x - med) for x in s]
            max_dist = max(dists)
            idxs = [i for i, d in enumerate(dists) if d == max_dist]
            drop_idx = idxs[-1]
            s.pop(drop_idx)

        return s

    # "totes": si k < n, agafa les millors k
    s = sorted(vals, reverse=True)
    return s[:k]



@require_POST
@transaction.atomic
def trampoli_guardar_nota(request, pk):
    competicio = get_object_or_404(Competicio, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON invàlid"}, status=400)

    ins_id = payload.get("inscripcio_id")
    if not ins_id:
        return JsonResponse({"ok": False, "error": "Falta inscripcio_id"}, status=400)

    ins = get_object_or_404(Inscripcio, pk=ins_id, competicio=competicio)

    cfg, _ = TrampoliConfiguracio.objects.get_or_create(competicio=competicio)
    n_jutges = int(getattr(cfg, "nombre_jutges_execucio", 3) or 3)

    # -------- notes_execucio: normalitza n_jutges x 11 (dècimes) --------
    notes_execucio = payload.get("notes_execucio", [])
    if not isinstance(notes_execucio, list):
        notes_execucio = []

    while len(notes_execucio) < n_jutges:
        notes_execucio.append([0] * NUM_SALTS)
    notes_execucio = notes_execucio[:n_jutges]

    for j in range(n_jutges):
        row = notes_execucio[j]
        if not isinstance(row, list):
            row = []
        row = (row + [0] * NUM_SALTS)[:NUM_SALTS]
        # aquí guardem DÈCIMES (0..10)
        notes_execucio[j] = [max(0.0, min(10.0, _to_float(x))) for x in row]

    # -------- crash_execucio: normalitza longitud n_jutges --------
    crash = payload.get("crash_execucio", [])
    if not isinstance(crash, list):
        crash = []
    while len(crash) < n_jutges:
        crash.append(0)
    crash = crash[:n_jutges]
    crash = [max(0, min(NUM_SALTS, int(x or 0))) for x in crash]  # 0..11


    comp_aparell_id = payload.get("comp_aparell_id")
    if not comp_aparell_id:
        return JsonResponse({"ok": False, "error": "Falta comp_aparell_id"}, status=400)

    comp_aparell = get_object_or_404(
        CompeticioAparell,
        pk=comp_aparell_id,
        competicio=competicio,
        actiu=True,
    )
    # -------- carrega o crea nota --------
    exercici = int(payload.get("exercici") or 1)
    exercici = max(1, min(4, exercici))

    nota, _ = TrampoliNota.objects.get_or_create(
        competicio=competicio,
        inscripcio=ins,
        exercici=exercici,
        comp_aparell=comp_aparell,
    )

    # -------- assigna camps (primer dades, després càlculs) --------
    nota.notes_execucio = notes_execucio
    nota.crash_execucio = crash

    nota.dificultat = _to_float(payload.get("dificultat"))
    nota.tof = _to_float(payload.get("tof"))
    nota.hdc = _to_float(payload.get("hd"))
    nota.penalitzacio = _to_float(payload.get("penalitzacio"))

    execucio_manual = payload.get("execucio_manual", None)

    # -------- calcula execució per jutge i execució global --------
    # --- decideix execució segons configuració ---
    mode = getattr(comp_aparell, "mode_execucio", "salts") or "salts"

    if mode == "manual":
        manuals = payload.get("execucio_manuals", [])
        if not isinstance(manuals, list):
            manuals = []
        # normalitza longitud n_jutges
        while len(manuals) < n_jutges:
            manuals.append(0)
        manuals = manuals[:n_jutges]
        manuals = [_to_float(x) for x in manuals]
        nota.execucio_manuals = manuals  # NOU
        nota.execucio_manual = None      # (opcional) ja no el necessites com a input únic

        k = int(getattr(cfg, "nombre_notes_valides_execucio", n_jutges) or n_jutges)
        k = max(1, min(k, n_jutges))
        criteri = getattr(cfg, "criteri_execucio", "totes") or "totes"

        selected = _select_exec_notes(manuals, k=k, criteri=criteri)
        nota.execucio_total = sum(selected)

        # en manual no uses salts/crash
        nota.notes_execucio = []
        nota.crash_execucio = []
    else:
        # execució per salts (com ara)
        nota.execucio_manual = None

        exec_j = []
        for j in range(n_jutges):
            exec_j.append(calc_execucio_jutge(notes_execucio[j], crash[j]))

        # NOU: k notes vàlides + criteri
        k = int(getattr(cfg, "nombre_notes_valides_execucio", n_jutges) or n_jutges)
        k = max(1, min(k, n_jutges))

        criteri = getattr(cfg, "criteri_execucio", "totes") or "totes"

        selected = _select_exec_notes(exec_j, k=k, criteri=criteri)

        # FIG-like: mitjana de les notes seleccionades
        nota.execucio_total = sum(selected)

    # -------- total global segons el teu criteri --------
    nota.total = (
        float(nota.execucio_total)
        + float(nota.dificultat)
        + float(nota.tof)
        + float(nota.hdc)
        - float(nota.penalitzacio)
    )

    nota.save()

    return JsonResponse({
        "ok": True,
        "inscripcio_id": ins.id,
        "exercici": exercici,
        "execucio_total": float(nota.execucio_total),
        "total": float(nota.total),
    })


class TrampoliAparellList(ListView):
    template_name = "competicio/trampoli_aparells_list.html"
    context_object_name = "aparells_cfg"

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return (
            CompeticioAparell.objects
            .filter(competicio=self.competicio)
            .select_related("aparell")
            .order_by("ordre", "id")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = self.competicio
        
        return ctx


class CompeticioAparellCreate(CreateView):
    template_name = "competicio/trampoli_aparell_form.html"
    form_class = CompeticioAparellForm

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["competicio"] = self.competicio
        return kwargs

    def form_valid(self, form):
        obj = form.save(commit=False)
        obj.competicio = self.competicio
        try:
            obj.save()
        except IntegrityError:
            form.add_error("aparell", "Aquest aparell ja esta afegit a la competicio.")
            return self.form_invalid(form)

        self.object = obj
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("trampoli_aparells_list", kwargs={"pk": self.kwargs["pk"]})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = self.competicio
        return ctx

class CompeticioAparellUpdate(UpdateView):
    template_name = "competicio/trampoli_aparell_form.html"
    form_class = CompeticioAparellForm
    model = CompeticioAparell
    pk_url_kwarg = "app_id"


    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        # IMPORTANT: només permet editar aparells d'aquesta competició
        return CompeticioAparell.objects.filter(competicio=self.competicio)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["competicio"] = self.competicio
        return kwargs

    def get_success_url(self):
        return reverse("trampoli_aparells_list", kwargs={"pk": self.kwargs["pk"]})

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = self.competicio
        return ctx


class AparellList(ListView):
    template_name = "competicio/aparells_list.html"
    context_object_name = "aparells"

    def get_queryset(self):
        return Aparell.objects.all().order_by("nom")


class AparellCreate(CreateView):
    template_name = "competicio/aparell_form.html"
    form_class = AparellForm

    def get_success_url(self):
        # Tornem al catàleg
        return reverse("aparells_list")


class AparellUpdate(UpdateView):
    template_name = "competicio/aparell_form.html"
    form_class = AparellForm
    model = Aparell

    def get_success_url(self):
        next_url = self.request.GET.get("next")
        if next_url:
            return next_url
        return reverse("aparells_list")
    

class CompeticioAparellDeleteView(View):
    def post(self, request, pk, app_id):
        comp_aparell = get_object_or_404(CompeticioAparell, pk=app_id, competicio_id=pk)
        comp_aparell.delete()
        return redirect(reverse('trampoli_config', kwargs={'pk': pk}))
