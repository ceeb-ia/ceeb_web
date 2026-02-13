import random
from django.shortcuts import render
import math
from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.views.generic import CreateView, FormView, ListView, TemplateView, DeleteView
from django.shortcuts import redirect
from django.db.models import Q
from .forms import ImportInscripcionsExcelForm
from .models import Competicio, Inscripcio
from .forms import CompeticioForm
from .services.import_excel import importar_inscripcions_excel
import json
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_protect
from django.db import transaction
from django.views.generic import UpdateView
from django.urls import reverse
from .forms import InscripcioForm
from io import BytesIO
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter
from django.db.models import Q, Max, Min, Case, When, IntegerField
from collections import defaultdict
from collections import OrderedDict


ALLOWED_SORT_FIELDS = {
    "nom": "nom_i_cognoms",
    "edat": "data_naixement",        # per edat, ordenarem per data naixement
    "document": "document",
    "sexe": "sexe",
    "entitat": "entitat",
    "categoria": "categoria",
    "subcategoria": "subcategoria",
    "grup": "grup",
}

ALLOWED_GROUP_FIELDS = {
    "categoria": "categoria",
    "subcategoria": "subcategoria",
    "entitat": "entitat",
    "sexe": "sexe",
    # si més endavant vols: "prova": "prova"
}

def _s(v):
    return "(Sense valor)" if v in (None, "") else str(v)

def arrow_positions(n: int) -> list[int]:
    """
    Retorna la seqüència de posicions "fletxa" per un grup de mida n.

    Exemple n=8 -> [3,4,2,5,1,6,0,7]
    (index del registre ordenat) -> (posició dins del grup)
    """
    if n <= 0:
        return []

    seq = []
    if n % 2 == 0:
        left = n // 2 - 1
        right = n // 2
        while left >= 0 or right < n:
            if left >= 0:
                seq.append(left)
                left -= 1
            if right < n:
                seq.append(right)
                right += 1
    else:
        center = n // 2
        seq.append(center)
        step = 1
        while center - step >= 0 or center + step < n:
            if center - step >= 0:
                seq.append(center - step)
            if center + step < n:
                seq.append(center + step)
            step += 1

    return seq

def init_ordre_sortida(competicio_id):
    qs = Inscripcio.objects.filter(competicio_id=competicio_id).order_by("id")
    with transaction.atomic():
        for i, obj in enumerate(qs, start=1):
            Inscripcio.objects.filter(id=obj.id).update(ordre_sortida=i)

def shuffle_ordre_sortida(qs):
    ids = list(qs.values_list("id", flat=True))
    random.shuffle(ids)

    with transaction.atomic():
        for idx, ins_id in enumerate(ids, start=1):
            Inscripcio.objects.filter(id=ins_id).update(ordre_sortida=idx)



UNDO_SESSION_KEY = "inscripcions_undo_state"

def save_undo_state(request, qs):
    """
    Desa a sessió l'estat actual (grup + ordre_sortida)
    del queryset passat.
    """
    request.session[UNDO_SESSION_KEY] = list(
        qs.values("id", "grup", "ordre_sortida")
    )
    request.session.modified = True


def restore_undo_state(request):
    """
    Restaura l'últim estat guardat.
    Retorna nombre de registres restaurats.
    """
    data = request.session.get(UNDO_SESSION_KEY)
    if not data:
        return 0

    with transaction.atomic():
        for row in data:
            Inscripcio.objects.filter(id=row["id"]).update(
                grup=row["grup"],
                ordre_sortida=row["ordre_sortida"],
            )

    del request.session[UNDO_SESSION_KEY]
    request.session.modified = True
    return len(data)

def assign_groups_balanced(objs, size, start_group_num):
    """
    Reparteix objs en k grups, on k = ceil(n/size),
    i distribueix mides perquè difereixin com a màxim 1.
    Retorna el nou start_group_num (últim grup assignat).
    """
    n = len(objs)
    if n == 0:
        return start_group_num

    k = math.ceil(n / size)           # nombre de grups
    base = n // k                     # mida base de cada grup
    rem = n % k                       # els primers 'rem' grups tindran +1

    idx = 0
    group_num = start_group_num
    for g in range(k):
        group_num += 1
        this_size = base + (1 if g < rem else 0)
        for _ in range(this_size):
            objs[idx].grup = group_num
            idx += 1

    return group_num

def renumber_groups_for_competicio(competicio):
    """
    Re-numera grups consecutivament 1..N dins la competició, evitant forats.
    L'ordre de renumeració segueix la seva aparició a la llista (min ordre_sortida).
    """
    base = Inscripcio.objects.filter(competicio=competicio, grup__isnull=False)

    groups = list(
        base.values("grup")
            .annotate(min_ord=Min("ordre_sortida"))
            .order_by("min_ord", "grup")
    )
    if not groups:
        return

    mapping = {g["grup"]: i + 1 for i, g in enumerate(groups)}

    whens = [When(grup=old, then=new) for old, new in mapping.items()]
    base.update(
        grup=Case(
            *whens,
            default=None,
            output_field=IntegerField(),
        )
    )

def assign_groups_k(objs, k, start_group_num):
    """
    Reparteix objs en k grups (k fix), equilibrant mides (difereixen com a màxim 1).
    """
    n = len(objs)
    if n == 0 or k <= 0:
        return start_group_num

    k = min(k, n)  # no té sentit més grups que persones

    base = n // k
    rem = n % k

    idx = 0
    group_num = start_group_num
    for g in range(k):
        group_num += 1
        this_size = base + (1 if g < rem else 0)
        for _ in range(this_size):
            objs[idx].grup = group_num
            idx += 1

    return group_num

# ------------------------------------------------------------------------------------------------
#
#
#           CREACIÓ COMPETICIONS
#
#
# ------------------------------------------------------------------------------------------------




class CompeticioHomeView(TemplateView):
    template_name = "competicio/home.html"


class CompeticioCreateView(CreateView):
    model = Competicio
    form_class = CompeticioForm
    template_name = "competicio/competicio_form.html"
    success_url = reverse_lazy("created")


class CompeticioDeleteView(DeleteView):
    model = Competicio
    template_name = "competicio/competicio_confirm_delete.html"
    success_url = reverse_lazy("created")

class CompeticioListView(ListView):
    model = Competicio
    template_name = "competicio/competicio_created_list.html"
    context_object_name = "competicions"
    paginate_by = 20



def notes_home_router(request, pk):
    c = get_object_or_404(Competicio, pk=pk)

    if c.tipus == Competicio.Tipus.TRAMPOLI:
        return redirect("trampoli_notes_home", pk=pk)

    # futurs:
    # if c.tipus == Competicio.Tipus.NATACIO: return redirect(...)
    # ...

    return redirect("created")
# ------------------------------------------------------------------------------------------------
#
#
#           TRACTAMENT INSCRIPCIONS
#
#
# ------------------------------------------------------------------------------------------------




class InscripcionsImportExcelView(FormView):
    template_name = "competicio/inscripcions_import.html"
    form_class = ImportInscripcionsExcelForm

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = self.competicio
        return ctx

    def form_valid(self, form):
        fitxer = form.cleaned_data["fitxer"]
        sheet = form.cleaned_data.get("sheet") or ""

        result = importar_inscripcions_excel(fitxer, self.competicio, sheet)
        messages.success(
            self.request,
            f"Importació OK. Full: {result['full']} | Creats: {result['creats']} | "
            f"Actualitzats: {result['actualitzats']} | Ignorats: {result['ignorats']}"
        )
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("inscripcions_list", kwargs={"pk": self.competicio.pk})


def recalcular_ordre_sortida(qs, group_fields):
    # Primari: camps de grup (perquè quedin agrupats)
    # Secundari: ordre_sortida (manté l'ordre previ, que pot ser aleatori)
    order = [f for f in group_fields if f] + ["ordre_sortida", "id"]
    ids = list(qs.order_by(*order).values_list("id", flat=True))

    with transaction.atomic():
        for idx, ins_id in enumerate(ids, start=1):
            Inscripcio.objects.filter(id=ins_id).update(ordre_sortida=idx)

class InscripcionsListView(ListView):
    template_name = "competicio/inscripcions_list.html"
    context_object_name = "records"
    paginate_by = 25

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return self.get_queryset_base_filtrada().order_by("ordre_sortida", "id")

    def get_queryset_base_filtrada(self):
        qs = Inscripcio.objects.filter(competicio=self.competicio)

        q = self.request.GET.get("q")
        categoria = self.request.GET.get("categoria")
        prova = self.request.GET.get("prova")
        subcategoria = self.request.GET.get("subcategoria")
        entitat = self.request.GET.get("entitat")

        if subcategoria:
            qs = qs.filter(subcategoria__iexact=subcategoria)
        if entitat:
            qs = qs.filter(entitat__icontains=entitat)
        if q:
            # Cerca per nom, DNI, o entitat
            qs = qs.filter(
                Q(nom_i_cognoms__icontains=q) |
                Q(document__icontains=q) |
                Q(entitat__icontains=q)
            )
        if categoria:
            qs = qs.filter(categoria__iexact=categoria)
        if prova:
            qs = qs.filter(prova__iexact=prova)

        return qs

    def get(self, request, *args, **kwargs):
        # 0z) Desfer última acció
        if request.GET.get("undo") == "1":
            restored = restore_undo_state(request)

            if restored:
                messages.success(request, f"S'ha desfet l'última acció ({restored} inscripcions).")
            else:
                messages.info(request, "No hi ha cap acció per desfer.")

            query = request.GET.copy()
            query.pop("undo", None)
            return redirect(f"{request.path}?{query.urlencode()}")


        # 0x) Exportar Excel (títol = pestanya (amb merges) + Grup N; columnes seleccionables)
        if request.GET.get("export_excel") == "1":

            # --- Columnes possibles (clau -> (títol, func(obj)->valor)) ---
            def fmt_date(d):
                return d.strftime("%d/%m/%Y") if d else "-"

            ALL_COLUMNS = OrderedDict([
                ("nom", ("Nom i cognoms", lambda o: o.nom_i_cognoms or "-")),
                ("dni", ("DNI", lambda o: o.document or "-")),
                ("sexe", ("Sexe", lambda o: o.sexe or "-")),
                ("naixement", ("Data naixement", lambda o: fmt_date(o.data_naixement))),
                ("entitat", ("Entitat", lambda o: o.entitat or "-")),
                ("categoria", ("Categoria", lambda o: o.categoria or "-")),
                ("subcategoria", ("Subcategoria", lambda o: o.subcategoria or "-")),
                ("grup", ("Grup", lambda o: o.grup if o.grup is not None else "-")),
                ("ordre", ("Ordre", lambda o: o.ordre_sortida if o.ordre_sortida is not None else "-")),
            ])

            selected_cols = request.GET.getlist("excel_cols")
            if not selected_cols:
                selected_cols = list(ALL_COLUMNS.keys())
            selected_cols = [c for c in selected_cols if c in ALL_COLUMNS]

            columns = [(ALL_COLUMNS[c][0], ALL_COLUMNS[c][1]) for c in selected_cols]
            if not columns:
                # fallback per seguretat
                columns = [(ALL_COLUMNS["nom"][0], ALL_COLUMNS["nom"][1])]

            # --- Determina agrupació activa (per construir pestanyes) ---
            selected = [g for g in request.GET.getlist("group_by") if g in ALLOWED_GROUP_FIELDS]
            if not selected:
                selected = self.competicio.group_by_default or []
            selected = [g for g in selected if g in ALLOWED_GROUP_FIELDS]
            group_fields = [ALLOWED_GROUP_FIELDS[g] for g in selected]

            grouping_sig = "|".join(selected)

            # --- QS base (respecta filtres) ---
            qs_base = self.get_queryset_base_filtrada()

            # --- Helpers per construir clau estable de pestanya ---
            def norm_val(v):
                return "__NULL__" if v in (None, "") else str(v)

            def pretty_val(v):
                return "(Sense valor)" if v in (None, "") else str(v)

            # Si no hi ha group_fields, tot és una sola pestanya
            # Si n'hi ha, construïm pestanyes i apliquem merges (tab_merges)
            tabs = []  # [(tab_label, tab_qs)]

            if not group_fields:
                tabs = [("Sense agrupació", qs_base)]
            else:
                # 1) Agrupa per clau simple (vals de group_fields)
                grouped_ids = OrderedDict()   # key(json vals) -> [ids]
                label_map = {}                # key -> label llegible

                for r in qs_base.only("id", *group_fields):
                    vals = [norm_val(getattr(r, f, None)) for f in group_fields]
                    key = json.dumps(vals, ensure_ascii=False)
                    grouped_ids.setdefault(key, []).append(r.id)

                    if key not in label_map:
                        parts = [pretty_val(getattr(r, f, None)) for f in group_fields]
                        label_map[key] = " · ".join(parts)

                # 2) Aplica merges configurats a competicio.tab_merges per aquest grouping_sig
                merges = (self.competicio.tab_merges or {}).get(grouping_sig, [])
                merge_map = {}
                for group_keys in merges:
                    t = tuple(group_keys)
                    for x in group_keys:
                        merge_map[x] = t

                merged_ids = OrderedDict()     # merged_key(json llista subkeys o key simple) -> [ids]
                merged_label = {}              # merged_key -> label

                for k, ids in grouped_ids.items():
                    merge_id = merge_map.get(k)
                    if merge_id:
                        merged_key = json.dumps(list(merge_id), ensure_ascii=False)
                        merged_ids.setdefault(merged_key, []).extend(ids)
                        if merged_key not in merged_label:
                            merged_label[merged_key] = " + ".join(label_map.get(x, x) for x in merge_id)
                    else:
                        merged_ids.setdefault(k, []).extend(ids)
                        merged_label[k] = label_map.get(k, k)

                # 3) Construeix tabs (label + queryset filtrat pels ids)
                for k, ids in merged_ids.items():
                    tab_label = merged_label.get(k, k)
                    tabs.append((tab_label, qs_base.filter(id__in=ids)))

            # --- Excel workbook/estils (mantenim “format maco”) ---
            wb = Workbook()
            ws = wb.active
            ws.title = "Inscripcions"

            title_font = Font(bold=True, size=12)
            header_font = Font(bold=True)
            header_fill = PatternFill("solid", fgColor="E9EEF7")
            group_fill = PatternFill("solid", fgColor="DDE7FF")

            def write_table_header(r):
                for col_i, (label, _) in enumerate(columns, start=1):
                    c = ws.cell(row=r, column=col_i, value=label)
                    c.font = header_font
                    c.fill = header_fill
                    c.alignment = Alignment(vertical="center")

            def write_row(r, obj):
                for col_i, (_, getter) in enumerate(columns, start=1):
                    ws.cell(row=r, column=col_i, value=getter(obj))

            row = 1

            # --- Escriu cada pestanya (i dins, cada grup) ---
            # IMPORTANT: ordenem per grup i després per ordre_sortida (que és el que has estat modificant)
            

            # --- Escriu TAULES en ordre GLOBAL de grup (1..N), però el títol inclou la pestanya ---
            selected = [g for g in request.GET.getlist("group_by") if g in ALLOWED_GROUP_FIELDS]
            if not selected:
                selected = self.competicio.group_by_default or []
            selected = [g for g in selected if g in ALLOWED_GROUP_FIELDS]
            group_fields = [ALLOWED_GROUP_FIELDS[g] for g in selected]
            grouping_sig = "|".join(selected) if selected else ""

            merges = (self.competicio.tab_merges or {}).get(grouping_sig, [])
            merge_map = {}
            for group_keys in merges:
                t = tuple(group_keys)
                for x in group_keys:
                    merge_map[x] = t

            def norm_val(v):
                return "__NULL__" if v in (None, "") else str(v)

            def pretty_val(v):
                return "(Sense valor)" if v in (None, "") else str(v)

            # label per “simple key”
            def label_for_simple_key(simple_key: str) -> str:
                try:
                    vals = json.loads(simple_key)
                    if isinstance(vals, list):
                        return " · ".join(pretty_val(x) for x in vals)
                except Exception:
                    pass
                return simple_key

            # label final de pestanya (simple o merged)
            merged_label_map = {}
            for group_keys in merges:
                merged_key = json.dumps(list(tuple(group_keys)), ensure_ascii=False)
                merged_label_map[merged_key] = " + ".join(label_for_simple_key(x) for x in group_keys)

            def tab_label_for_obj(obj) -> str:
                if not group_fields:
                    return "Sense agrupació"

                vals = [norm_val(getattr(obj, f, None)) for f in group_fields]
                simple_key = json.dumps(vals, ensure_ascii=False)
                mid = merge_map.get(simple_key)
                if mid:
                    merged_key = json.dumps(list(mid), ensure_ascii=False)
                    return merged_label_map.get(merged_key, merged_key)
                return label_for_simple_key(simple_key)

            # QS global ordenat per grup (numèric) i dins per ordre_sortida
            qs_all = qs_base.annotate(
                grup_null=Case(
                    When(grup__isnull=True, then=1),
                    default=0,
                    output_field=IntegerField(),
                )
            ).order_by(
                "grup_null",
                "grup",
                "ordre_sortida",
                "id",
            )

            SENTINEL = object()
            current_grp = SENTINEL
            buffer = []

            def flush_group(objs, grp_num):
                nonlocal row
                if not objs:
                    return

                # pestanya: la deduïm del primer (normalment tot el grup és de la mateixa pestanya)
                tab_label = tab_label_for_obj(objs[0])

                # IMPORTANT: mantenim "Grup X" com sempre
                if grp_num is None:
                    group_title = f"{tab_label} · Sense grup"
                else:
                    group_title = f"{tab_label} · Grup {grp_num}"

                ws.cell(row=row, column=1, value=group_title).font = title_font
                ws.cell(row=row, column=1).fill = group_fill
                ws.cell(row=row, column=1).alignment = Alignment(vertical="center")
                ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(columns))
                row += 1

                write_table_header(row)
                row += 1

                for o in objs:
                    write_row(row, o)
                    row += 1

                row += 1  # espai

            for obj in qs_all:
                g = obj.grup
                if current_grp is SENTINEL:
                    current_grp = g

                if g != current_grp:
                    flush_group(buffer, current_grp)
                    buffer = []
                    current_grp = g

                buffer.append(obj)

            flush_group(buffer, current_grp)

            # Ajust d'amplades (simple, però decent)
            for i, (label, _) in enumerate(columns, start=1):
                ws.column_dimensions[get_column_letter(i)].width = max(12, min(35, len(label) + 4))

            out = BytesIO()
            wb.save(out)
            out.seek(0)

            filename = f"inscripcions_competicio_{self.competicio.pk}.xlsx"
            resp = HttpResponse(
                out.getvalue(),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            resp["Content-Disposition"] = f'attachment; filename="{filename}"'
            return resp



        # 0) Esborrar grups assignats (sempre ha de funcionar)
        if request.GET.get("clear_groups") == "1":
            qs = self.get_queryset_base_filtrada()  # o tots si vols
            save_undo_state(request, qs)

            with transaction.atomic():
                qs.update(grup=None)
                renumber_groups_for_competicio(self.competicio)

            query = request.GET.copy()
            query.pop("clear_groups", None)
            return redirect(f"{request.path}?{query.urlencode()}")

        # 0c) Fer grup independent per un subgrup (header)
        if request.GET.get("make_independent_group") == "1":
            lvl = request.GET.get("lvl")  # "g1", "g2", "g3"

            # camps seleccionats (per saber què és g1/g2/g3)
            selected = self.request.GET.getlist("group_by")
            if not selected:
                selected = self.competicio.group_by_default or []
            group_fields = [ALLOWED_GROUP_FIELDS[g] for g in selected if g in ALLOWED_GROUP_FIELDS]

            # Validació mínima
            if not group_fields:
                messages.error(request, "No hi ha agrupació activa per poder crear un grup independent.")
                query = request.GET.copy()
                query.pop("make_independent_group", None)
                query.pop("lvl", None)
                query.pop("v1", None)
                query.pop("v2", None)
                query.pop("v3", None)
                return redirect(f"{request.path}?{query.urlencode()}")

            # Valors del header (passem v1/v2/v3)
            v1 = request.GET.get("v1")
            v2 = request.GET.get("v2")
            v3 = request.GET.get("v3")

            # --- CAS ESPECIAL: s'ha clicat el botó "Fer grup independent de la pestanya" ---
            # v1 aquí és la group_key (JSON). Pot ser:
            #  - clau simple: ["CAT","SUB",...]
            #  - clau merged: ['["CAT1","SUB1"]','["CAT2","SUB2"]', ...]
            def _is_merged_key_list(lst):
                return (
                    isinstance(lst, list) and lst
                    and all(isinstance(x, str) for x in lst)
                    and all(x.strip().startswith("[") for x in lst)
                )

            def _build_kwargs_from_vals(vals):
                kwargs = {}
                for f, v in zip(group_fields, vals):
                    if v == "__NULL__":
                        kwargs[f"{f}__isnull"] = True
                    else:
                        kwargs[f] = v
                return kwargs

            # Si lvl=g1 i v1 sembla JSON, intentem interpretar-ho com a clau de pestanya
            if lvl == "g1" and v1 and v1.strip().startswith("["):
                try:
                    parsed = json.loads(v1)
                except Exception:
                    parsed = None

                if isinstance(parsed, list):
                    base_qs = self.get_queryset_base_filtrada()

                    # merged: llista de subkeys JSON
                    if _is_merged_key_list(parsed):
                        q_or = Q()
                        for subk in parsed:
                            try:
                                sub_vals = json.loads(subk)
                            except Exception:
                                continue
                            if isinstance(sub_vals, list):
                                q_or |= Q(**_build_kwargs_from_vals(sub_vals))
                        sub_qs = base_qs.filter(q_or)

                    # simple: llista de valors (per cada group_field)
                    else:
                        sub_qs = base_qs.filter(**_build_kwargs_from_vals(parsed))

                    save_undo_state(request, base_qs)

                    # i continuem amb la lògica existent a partir d'aquí (existing_groups, etc.)
                    # IMPORTANT: SALTEM la construcció antiga de filtres
                    existing_groups = list(
                        sub_qs.exclude(grup__isnull=True).values_list("grup", flat=True).distinct()
                    )

                    if existing_groups:
                        new_group_num = min(existing_groups)
                        with transaction.atomic():
                            Inscripcio.objects.filter(competicio=self.competicio, grup=new_group_num).update(grup=None)
                            updated = sub_qs.update(grup=new_group_num)
                            renumber_groups_for_competicio(self.competicio)
                    else:
                        max_grup = (
                            Inscripcio.objects
                            .filter(competicio=self.competicio)
                            .aggregate(m=Max("grup"))["m"]
                            or 0
                        )
                        new_group_num = max_grup + 1
                        with transaction.atomic():
                            updated = sub_qs.update(grup=new_group_num)
                            renumber_groups_for_competicio(self.competicio)

                    messages.success(request, f"Creat el grup {new_group_num} amb {updated} inscripcions del subgrup.")
                    is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
                    if is_ajax:
                        return JsonResponse({"ok": True, "new_group_num": new_group_num, "updated": updated})

                    query = request.GET.copy()
                    query.pop("make_independent_group", None)
                    query.pop("lvl", None)
                    query.pop("v1", None)
                    query.pop("v2", None)
                    query.pop("v3", None)
                    return redirect(f"{request.path}?{query.urlencode()}")

            
        # 0e) Ordenar inscripcions per agrupació (SENSE crear grups)
        if request.GET.get("sort_by_grouping") == "1":
            print("START SORT BY GROUPING", flush=True)

            sort_key = request.GET.get("sort_key") or "nom"
            sort_dir = request.GET.get("sort_dir") or "asc"
            if sort_dir not in ("asc", "desc", "arrow_asc", "arrow_desc"):
                sort_dir = "asc"
 
            if sort_key not in ALLOWED_SORT_FIELDS:
                messages.error(request, "Camp d'ordenació no vàlid.")
                query = request.GET.copy()
                query.pop("sort_by_grouping", None)
                return redirect(f"{request.path}?{query.urlencode()}")

            order_field = ALLOWED_SORT_FIELDS[sort_key]

            # agrupació activa (la que has triat a la UI)
            # IMPORTANT: si el botó/link no porta group_by, usem el guardat (com fa el context)
            selected = [g for g in request.GET.getlist("group_by") if g in ALLOWED_GROUP_FIELDS]
            if not selected:
                selected = self.competicio.group_by_default or []

            group_by_keys = selected
            group_fields = [ALLOWED_GROUP_FIELDS[g] for g in selected if g in ALLOWED_GROUP_FIELDS]

            qs = self.get_queryset_base_filtrada()
            save_undo_state(request, qs)

            updates = []
            idx = 1
            print("SORT group_by_keys:", group_by_keys, flush=True)
            print("SORT grouping_sig:", "|".join(group_by_keys), flush=True)
            print("SORT merges:", (self.competicio.tab_merges or {}).get("|".join(group_by_keys), []), flush=True)
            print("SORT merges:", (self.competicio.tab_merges or {}).get("|".join(group_by_keys), []), flush=True)

            # Cas simple: sense agrupació -> un sol “bloc”
            if not group_fields:
                if sort_dir in ("arrow_asc", "arrow_desc"):
                    base_prefix = "-" if sort_dir == "arrow_desc" else ""
                    base_list = list(qs.order_by(f"{base_prefix}{order_field}", "id").only("id"))
                    n = len(base_list)
                    pos = arrow_positions(n)
                    placed = [None] * n
                    for i, obj in enumerate(base_list):
                        placed[pos[i]] = obj
                    for obj in placed:
                        obj.ordre_sortida = idx
                        updates.append(obj)
                        idx += 1
                else:
                    prefix = "-" if sort_dir == "desc" else ""
                    base_list = list(qs.order_by(f"{prefix}{order_field}", "id").only("id"))
                    for obj in base_list:
                        obj.ordre_sortida = idx
                        updates.append(obj)
                        idx += 1

            # Cas agrupat: EXISTEIXEN pestanyes (i possibles fusions)
            else:
                # Bloc = pestanya final (fusionada o no)
                base_prefix = "-" if sort_dir in ("desc", "arrow_desc") else ""

                grouping_sig = "|".join(group_by_keys) if group_by_keys else ""
                merges = (self.competicio.tab_merges or {}).get(grouping_sig, [])

                # simple_key -> merged_tuple
                merge_map = {}
                for group_keys in merges:
                    t = tuple(group_keys)  # group_keys = llista de simple keys
                    for x in group_keys:
                        merge_map[x] = t

                def norm_val(v):
                    return "__NULL__" if v in (None, "") else str(v)

                # 1) Assignem cada inscripcio a una pestanya FINAL (merged o simple)
                # i conservem l'ordre de pestanyes tal com "apareixen" a ordre_sortida actual.
                tab_to_ids = OrderedDict()
                records = list(qs.order_by("ordre_sortida", "id").only("id", *group_fields))

                for r in records:
                    vals = [norm_val(getattr(r, f, None)) for f in group_fields]
                    simple_key = json.dumps(vals, ensure_ascii=False)

                    merge_id = merge_map.get(simple_key)
                    if merge_id:
                        tab_key = json.dumps(list(merge_id), ensure_ascii=False)  # merged key
                    else:
                        tab_key = simple_key  # tab simple

                    tab_to_ids.setdefault(tab_key, []).append(r.id)

                # 2) Ordenem DINS de cada pestanya FINAL:
                # IMPORTANT: aquí NO respectem sub-blocs; és una sola ordenació global del conjunt.
                for tab_key, tab_ids in tab_to_ids.items():
                    tab_qs = qs.filter(id__in=tab_ids).order_by(f"{base_prefix}{order_field}", "id").only("id")
                    base_list = list(tab_qs)

                    if sort_dir in ("arrow_asc", "arrow_desc"):
                        n = len(base_list)
                        pos = arrow_positions(n)
                        placed = [None] * n
                        for i, obj in enumerate(base_list):
                            placed[pos[i]] = obj
                        for obj in placed:
                            obj.ordre_sortida = idx
                            updates.append(obj)
                            idx += 1
                    else:
                        for obj in base_list:
                            obj.ordre_sortida = idx
                            updates.append(obj)
                            idx += 1

            with transaction.atomic():
                Inscripcio.objects.bulk_update(updates, ["ordre_sortida"], batch_size=500)

            messages.success(
                request,
                f"Inscripcions ordenades per agrupació ({', '.join(group_by_keys) or 'cap'}) i camp '{sort_key}' ({sort_dir})."
            )

            query = request.GET.copy()
            query.pop("sort_by_grouping", None)
            query.pop("sort_key", None)
            query.pop("sort_dir", None)
            return redirect(f"{request.path}?{query.urlencode()}")





        # 0d) Reendreçar dins de cada grup segons un camp
        if request.GET.get("sort_within_groups") == "1":
            sort_key = request.GET.get("sort_key") or "nom"
            sort_dir = request.GET.get("sort_dir") or "asc"  # asc / desc
            if sort_dir not in ("asc", "desc", "arrow_asc", "arrow_desc"):
                sort_dir = "asc"
            if sort_key not in ALLOWED_SORT_FIELDS:
                messages.error(request, "Camp d'ordenació no vàlid.")
                query = request.GET.copy()
                query.pop("sort_within_groups", None)
                query.pop("sort_key", None)
                query.pop("sort_dir", None)
                return redirect(f"{request.path}?{query.urlencode()}")

            order_field = ALLOWED_SORT_FIELDS[sort_key]

            qs = self.get_queryset_base_filtrada()
            save_undo_state(request, qs)


            if not qs.exclude(grup__isnull=True).exists():
                messages.info(request, "No hi ha grups assignats per poder reendreçar dins de grup.")
                query = request.GET.copy()
                query.pop("sort_within_groups", None)
                query.pop("sort_key", None)
                query.pop("sort_dir", None)
                return redirect(f"{request.path}?{query.urlencode()}")

            updates = []
            idx = 1

            # Grups presents (dins el que estàs veient)
            group_nums = list(
                qs.exclude(grup__isnull=True)
                .order_by("grup")
                .values_list("grup", flat=True)
                .distinct()
            )

            with transaction.atomic():
                for g in group_nums:
                    group_qs = qs.filter(grup=g)

                    if sort_dir in ("arrow_asc", "arrow_desc"):
                        base_prefix = "-" if sort_dir == "arrow_desc" else ""
                        # 1) Base order (asc) pel camp triat
                        base_list = list(group_qs.order_by(f"{base_prefix}{order_field}", "id").only("id"))

                        n = len(base_list)
                        pos = arrow_positions(n)  # index del registre ordenat -> posició al grup

                        placed = [None] * n
                        for i, obj in enumerate(base_list):
                            placed[pos[i]] = obj

                        # 2) Assignem ordre_sortida seguint la posició final (0..n-1)
                        for obj in placed:
                            obj.ordre_sortida = idx
                            updates.append(obj)
                            idx += 1

                    else:
                        # asc / desc normal
                        prefix = "-" if sort_dir == "desc" else ""
                        base_list = list(group_qs.order_by(f"{prefix}{order_field}", "id").only("id"))
                        for obj in base_list:
                            obj.ordre_sortida = idx
                            updates.append(obj)
                            idx += 1

                Inscripcio.objects.bulk_update(updates, ["ordre_sortida"], batch_size=500)



            messages.success(request, f"Reendreçat dins dels grups per '{sort_key}' ({sort_dir}).")

            query = request.GET.copy()
            query.pop("sort_within_groups", None)
            query.pop("sort_key", None)
            query.pop("sort_dir", None)
            return redirect(f"{request.path}?{query.urlencode()}")

        # 0b) Crear X grups (PER PESTANYA de l’agrupació; si la pestanya és fusionada => ES TRACTA COM 1 SOLA)
        if request.GET.get("make_groups_count") == "1":

            # --- validar k ---
            try:
                k = int(request.GET.get("group_count") or 0)
            except ValueError:
                k = 0
            if k < 1:
                messages.error(request, "El nombre de grups ha de ser com a mínim 1.")
                query = request.GET.copy()
                query.pop("make_groups_count", None)
                return redirect(f"{request.path}?{query.urlencode()}")

            qs_base = self.get_queryset_base_filtrada()
            save_undo_state(request, qs_base)

            # --- agrupació activa (fields) ---
            selected = self.request.GET.getlist("group_by") or (self.competicio.group_by_default or [])
            selected = [g for g in selected if g in ALLOWED_GROUP_FIELDS]
            group_fields = [ALLOWED_GROUP_FIELDS[g] for g in selected]

            tab_keys = request.GET.getlist("tab_keys")  # checkboxes de pestanyes

            def norm_val(v):
                return "__NULL__" if v in (None, "") else str(v)

            def parse_tab_key(tk: str):
                """
                Retorna:
                - ("simple", [v1,v2,...]) si tk és JSON list de longitud = len(group_fields)
                - ("merged", [[v...],[v...],...]) si tk és JSON list d'strings JSON (simple keys)
                """
                vals = json.loads(tk)

                # simple: ["ALEVI","CN X",...]
                if isinstance(vals, list) and len(vals) == len(group_fields):
                    return ("simple", vals)

                # merged: ["[...]", "[...]", ...]  (cada sub és una simple key en format JSON string)
                if isinstance(vals, list) and vals and all(isinstance(x, str) for x in vals):
                    out = []
                    for sub in vals:
                        try:
                            sub_vals = json.loads(sub)
                        except Exception:
                            continue
                        if isinstance(sub_vals, list) and len(sub_vals) == len(group_fields):
                            out.append(sub_vals)
                    return ("merged", out)

                return ("invalid", None)

            def build_q_from_vals(vlist):
                q = Q()
                for f, v in zip(group_fields, vlist):
                    if v == "__NULL__":
                        q &= Q(**{f"{f}__isnull": True})
                    else:
                        q &= Q(**{f: v})
                return q

            # --- Cas 1: NO hi ha agrupació -> aplica a tot el queryset (una sola “pestanya”) ---
            if not group_fields:
                objs = list(qs_base.order_by("ordre_sortida", "id").only("id", "grup"))
                if not objs:
                    messages.warning(request, "No hi ha inscripcions per crear grups.")
                    query = request.GET.copy()
                    query.pop("make_groups_count", None)
                    query.pop("group_count", None)
                    query.setlist("tab_keys", [])
                    return redirect(f"{request.path}?{query.urlencode()}")

                for o in objs:
                    o.grup = None

                max_grup = (
                    Inscripcio.objects.filter(competicio=self.competicio)
                    .aggregate(m=Max("grup"))["m"] or 0
                )
                start = max_grup

                with transaction.atomic():
                    start = assign_groups_k(objs, k, start)
                    Inscripcio.objects.bulk_update(objs, ["grup"], batch_size=500)
                    renumber_groups_for_competicio(self.competicio)

                messages.success(request, f"Creats grups (k={k}) per totes les inscripcions filtrades.")
                query = request.GET.copy()
                query.pop("make_groups_count", None)
                query.pop("group_count", None)
                query.setlist("tab_keys", [])
                return redirect(f"{request.path}?{query.urlencode()}")

            
            # --- Cas 2: hi ha agrupació -> aplica a pestanyes seleccionades (però fent k grups TOTALS) ---

            # Si no marques cap pestanya, apliquem a TOTES les pestanyes “simples”
            if not tab_keys:
                existing_simple = set()
                for r in qs_base.order_by("ordre_sortida", "id").only("id", *group_fields):
                    vals = [norm_val(getattr(r, f, None)) for f in group_fields]
                    existing_simple.add(json.dumps(vals, ensure_ascii=False))
                tab_keys = list(existing_simple)

            # Construim un únic Q = OR de totes les pestanyes seleccionades (simple i merged)
            combined_q = Q()
            valid_tabs = 0

            for tk in tab_keys:
                try:
                    kind, payload = parse_tab_key(tk)
                except Exception:
                    kind, payload = ("invalid", None)

                if kind == "invalid":
                    continue

                valid_tabs += 1

                if kind == "simple":
                    combined_q |= build_q_from_vals(payload)
                else:  # merged
                    for sub_vals in payload:
                        combined_q |= build_q_from_vals(sub_vals)

            # Apliquem a TOTES les inscripcions d’aquest conjunt
            sub_qs = qs_base.filter(combined_q)
            objs = list(sub_qs.order_by("ordre_sortida", "id").only("id", "grup"))

            if not objs:
                messages.warning(request, "No s'han creat grups: les pestanyes seleccionades no tenen inscripcions.")
                query = request.GET.copy()
                query.pop("make_groups_count", None)
                query.pop("group_count", None)
                query.setlist("tab_keys", [])
                return redirect(f"{request.path}?{query.urlencode()}")

            for o in objs:
                o.grup = None

            max_grup = (
                Inscripcio.objects.filter(competicio=self.competicio)
                .aggregate(m=Max("grup"))["m"] or 0
            )
            start = max_grup

            with transaction.atomic():
                start = assign_groups_k(objs, k, start)
                Inscripcio.objects.bulk_update(objs, ["grup"], batch_size=500)
                renumber_groups_for_competicio(self.competicio)

            messages.success(request, f"Creats {min(k, len(objs))} grups (k={k}) amb {len(objs)} inscripcions (pestanyes seleccionades: {valid_tabs}).")

            query = request.GET.copy()
            query.pop("make_groups_count", None)
            query.pop("group_count", None)
            query.setlist("tab_keys", [])
            return redirect(f"{request.path}?{query.urlencode()}")





        # 0b) Crear grups de mida N (respectant group_by però amb numeració global única)
        if request.GET.get("make_groups") == "1":
            try:
                size = int(request.GET.get("group_size") or 0)
            except ValueError:
                size = 0

            if size < 2:
                messages.error(request, "La mida del grup ha de ser com a mínim 2.")
                query = request.GET.copy()
                query.pop("make_groups", None)
                return redirect(f"{request.path}?{query.urlencode()}")

            group_mode = request.GET.get("group_mode") or "fixed"  # "fixed" (actual) o "balanced"

            # group_by seleccionat (ex: ["categoria","subcategoria"])
            group_by_keys = [g for g in request.GET.getlist("group_by") if g in ALLOWED_GROUP_FIELDS]
            group_fields = [ALLOWED_GROUP_FIELDS[g] for g in group_by_keys]  # camps reals

            # Ordenem per subgrup + ordre_sortida per mantenir el teu ordre previ dins cada subgrup
            qs = self.get_queryset_base_filtrada().order_by(*group_fields, "ordre_sortida", "id")
            save_undo_state(request, qs)

            objs = list(qs.only("id", "grup", *group_fields))

            global_group_num = 0

            if not group_fields:
                if group_mode == "balanced":
                    global_group_num = assign_groups_balanced(objs, size, global_group_num)
                else:
                    # mode actual (fixed)
                    for idx, obj in enumerate(objs, start=1):
                        obj.grup = (idx - 1) // size + 1

            else:
                if group_mode == "balanced":
                    current_key = None
                    buffer = []

                    def flush_buffer():
                        nonlocal global_group_num, buffer
                        if buffer:
                            global_group_num = assign_groups_balanced(buffer, size, global_group_num)
                            buffer = []

                    for obj in objs:
                        key = tuple(getattr(obj, f) for f in group_fields)

                        if key != current_key:
                            flush_buffer()
                            current_key = key

                        buffer.append(obj)

                    flush_buffer()

                else:
                    # mode actual (fixed)
                    current_key = None
                    count_in_chunk = 0

                    for obj in objs:
                        key = tuple(getattr(obj, f) for f in group_fields)

                        if key != current_key:
                            current_key = key
                            count_in_chunk = 0

                        if count_in_chunk == 0:
                            global_group_num += 1

                        obj.grup = global_group_num
                        count_in_chunk += 1

                        if count_in_chunk >= size:
                            count_in_chunk = 0


            with transaction.atomic():
                Inscripcio.objects.bulk_update(objs, ["grup"])
                renumber_groups_for_competicio(self.competicio)

            query = request.GET.copy()
            query.pop("make_groups", None)
            return redirect(f"{request.path}?{query.urlencode()}")


        # 1) Treure agrupació explícitament
        if request.GET.get("clear_group") == "1":
            # Treure agrupació (mai None)
            self.competicio.group_by_default = []

            # ✅ Desfer fusions de pestanyes
            self.competicio.tab_merges = {}

            self.competicio.save(update_fields=["group_by_default", "tab_merges"])

            query = request.GET.copy()
            query.pop("clear_group", None)
            query.setlist("group_by", [])
            return redirect(f"{request.path}?{query.urlencode()}")

        # 2) Recalcular ordre segons agrupació actual
        if request.GET.get("recalc_order") == "1":
            group_fields = [
                ALLOWED_GROUP_FIELDS[g]
                for g in request.GET.getlist("group_by")
                if g in ALLOWED_GROUP_FIELDS
            ]
            qs = self.get_queryset_base_filtrada()
            save_undo_state(request, qs)

            recalcular_ordre_sortida(qs, group_fields)
            renumber_groups_for_competicio(self.competicio)

            query = request.GET.copy()
            query.pop("recalc_order", None)
            return redirect(f"{request.path}?{query.urlencode()}")

        # 3) Shuffle (barreja aleatòria)
        if request.GET.get("shuffle_order") == "1":
            qs = self.get_queryset_base_filtrada()
            save_undo_state(request, qs)

            shuffle_ordre_sortida(qs)

            query = request.GET.copy()
            query.pop("shuffle_order", None)
            return redirect(f"{request.path}?{query.urlencode()}")

        # 4) Persistència de group_by
        if "group_by" in request.GET:
            selected = [g for g in request.GET.getlist("group_by") if g in ALLOWED_GROUP_FIELDS]
            if selected != (self.competicio.group_by_default or []):
                self.competicio.group_by_default = selected
                self.competicio.save(update_fields=["group_by_default"])
        else:
            # 5) Aplicar el guardat quan no ve group_by
            saved = self.competicio.group_by_default or []
            if saved:
                query = request.GET.copy()
                for g in saved:
                    query.appendlist("group_by", g)
                return redirect(f"{request.path}?{query.urlencode()}")

        return super().get(request, *args, **kwargs)


    def get_paginate_by(self, queryset):
        if self.request.GET.getlist("group_by"):
            return None  # amb pestanyes, sense paginació

        per_page = self.request.GET.get("per_page")
        if not per_page or per_page == "all":
            return None  # sense agrupació: mostra tots

        try:
            return int(per_page)
        except ValueError:
            return None


    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = self.competicio
        ctx["allowed_group_fields"] = list(ALLOWED_GROUP_FIELDS.keys())
        ctx["current_query"] = self.request.GET.urlencode()
        ctx["title_fields_selected"] = self.request.GET.getlist("title_fields")

        selected = self.request.GET.getlist("group_by")
        if not selected:
            selected = self.competicio.group_by_default or []
        ctx["selected_group_fields"] = selected

        # Agrupació per pestanyes: agrupem pel primer camp seleccionat
        records = self.get_queryset_base_filtrada().order_by("ordre_sortida", "id")

        records_grouped = None
        grouping_sig = "|".join(selected) if selected else ""
        ctx["grouping_sig"] = grouping_sig  # per JS / merge

        def norm_val(v):
            return "__NULL__" if v in (None, "") else str(v)

        def pretty_val(v):
            return "(Sense valor)" if v in (None, "") else str(v)

        if selected:
            group_fields = [ALLOWED_GROUP_FIELDS[g] for g in selected if g in ALLOWED_GROUP_FIELDS]

            grouped = OrderedDict()
            label_map = {}

            for r in records:
                vals = [norm_val(getattr(r, f, None)) for f in group_fields]
                key = json.dumps(vals, ensure_ascii=False)  # clau estable per merge/checkbox
                grouped.setdefault(key, []).append(r)

                # etiqueta visible (Categoria: X · Entitat: Y ...)
                if key not in label_map:
                    parts = []
                    for gkey, f in zip(selected, group_fields):
                        parts.append(f"{pretty_val(getattr(r, f, None))}")
                    label_map[key] = " · ".join(parts)

            # --- merge tabs (ara per agrupació completa) ---
            merges = (self.competicio.tab_merges or {}).get(grouping_sig, [])

            merge_map = {}
            for group_keys in merges:
                t = tuple(group_keys)
                for x in group_keys:
                    merge_map[x] = t

            merged_grouped = OrderedDict()
            merged_label_map = {}

            for k, items in grouped.items():
                merge_id = merge_map.get(k)
                if merge_id:
                    merged_key = json.dumps(list(merge_id), ensure_ascii=False)
                    merged_grouped.setdefault(merged_key, []).extend(items)

                    if merged_key not in merged_label_map:
                        merged_label_map[merged_key] = " + ".join(label_map.get(x, x) for x in merge_id)
                else:
                    merged_grouped.setdefault(k, []).extend(items)
                    merged_label_map[k] = label_map.get(k, k)
            # IMPORTANT: si una pestanya és fusionada, hem concatenat llistes de subpestanyes.
            # Reordena el conjunt final per ordre_sortida perquè es vegi com un únic bloc real.
            for _k, _items in merged_grouped.items():
                _items.sort(key=lambda r: ((r.ordre_sortida or 10**12), r.id))

            # format final: (label, items, key)
            records_grouped = [(merged_label_map[k], items, k) for k, items in merged_grouped.items()]

        ctx["records_grouped"] = records_grouped

        # Columnes possibles a exportar (mateixes que la taula)
        ALL_EXCEL_COLUMNS = [
            ("nom", "Nom i cognoms"),
            ("dni", "DNI"),
            ("sexe", "Sexe"),
            ("naixement", "Data naixement"),
            ("entitat", "Entitat"),
            ("categoria", "Categoria"),
            ("subcategoria", "Subcategoria"),
            ("grup", "Grup"),
            ("ordre", "Ordre"),
        ]

        ctx["allowed_excel_columns"] = ALL_EXCEL_COLUMNS

        sel_cols = self.request.GET.getlist("excel_cols")
        if not sel_cols:
            sel_cols = [k for k, _ in ALL_EXCEL_COLUMNS]
        ctx["excel_cols_selected"] = sel_cols

        # Categories disponibles dins el conjunt filtrat (respecta q/categoria/subcategoria/entitat/prova)
        base = self.get_queryset_base_filtrada()
        ctx["categories_distinct"] = list(
            base.order_by()
                .values_list("categoria", flat=True)
                .distinct()
        )
        ctx["cats_selected"] = self.request.GET.getlist("cats")

        return ctx


class InscripcioUpdateView(UpdateView):
    model = Inscripcio
    pk_url_kwarg = "ins_id"
    form_class = InscripcioForm
    template_name = "competicio/inscripcio_form.html"

    def get_queryset(self):
        # Seguretat: només permet editar inscripcions de la competició del pk
        return Inscripcio.objects.filter(competicio_id=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = get_object_or_404(Competicio, pk=self.kwargs["pk"])
        ctx["next"] = self.request.GET.get("next", "")
        return ctx

    def get_success_url(self):
        nxt = self.request.GET.get("next")
        if nxt:
            return nxt
        return reverse("inscripcions_list", kwargs={"pk": self.kwargs["pk"]})


class InscripcioCreateView(CreateView):
    model = Inscripcio
    form_class = InscripcioForm
    template_name = "competicio/inscripcio_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.competicio = get_object_or_404(Competicio, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["competicio"] = self.competicio
        ctx["next"] = self.request.GET.get("next", "")
        return ctx

    def form_valid(self, form):
        # Assign the competition before saving
        form.instance.competicio = self.competicio
        # If ordre_sortida not provided, append to the end
        if not form.instance.ordre_sortida:
            max_ord = Inscripcio.objects.filter(competicio=self.competicio).aggregate(m=Max("ordre_sortida"))["m"] or 0
            form.instance.ordre_sortida = max_ord + 1
        return super().form_valid(form)

    def get_success_url(self):
        nxt = self.request.GET.get("next")
        if nxt:
            return nxt
        return reverse("inscripcions_list", kwargs={"pk": self.kwargs["pk"]})


class InscripcioDeleteView(DeleteView):
    model = Inscripcio
    pk_url_kwarg = "ins_id"
    template_name = "competicio/inscripcio_confirm_delete.html"

    def get_queryset(self):
        return Inscripcio.objects.filter(competicio_id=self.kwargs["pk"])

    def get_success_url(self):
        nxt = self.request.GET.get("next")
        if nxt:
            return nxt
        return reverse("inscripcions_list", kwargs={"pk": self.kwargs["pk"]})


@require_POST
@csrf_protect
def inscripcions_reorder(request, pk):
    """
    Rep:
      {
        "ids": [<id1>, <id2>, ...],   # ordre final després del drag
        "moved_id": <id>,            # el registre arrossegat
        "new_index": <int>           # posició nova (0-based) dins ids
      }

    Guarda ordre_sortida = 1..N
    I (NOU) només pel registre mogut: adopta el grup del registre immediatament superior.
    """
    try:
        payload = json.loads(request.body.decode("utf-8"))
        ids = payload.get("ids", [])
        moved_id = payload.get("moved_id", None)
        new_index = payload.get("new_index", None)

        if not isinstance(ids, list) or not ids:
            return HttpResponseBadRequest("Payload invàlid")
    except Exception:
        return HttpResponseBadRequest("JSON invàlid")

    wanted = [int(x) for x in ids if str(x).isdigit()]
    if not wanted:
        return HttpResponseBadRequest("IDs buits")

    # Validació moved_id / new_index (opcional però recomanada)
    if moved_id is not None:
        try:
            moved_id = int(moved_id)
        except Exception:
            return HttpResponseBadRequest("moved_id invàlid")

    if new_index is not None:
        try:
            new_index = int(new_index)
        except Exception:
            return HttpResponseBadRequest("new_index invàlid")

    # Ens assegurem que només reordenem inscripcions d'aquesta competició
    qs = Inscripcio.objects.filter(competicio_id=pk, id__in=wanted)
    found = set(qs.values_list("id", flat=True))
    if set(wanted) != found:
        return HttpResponseBadRequest("IDs no vàlids per aquesta competició")

    # Diccionari id->grup (estat actual abans de canviar)
    id_to_group = dict(qs.values_list("id", "grup"))

    with transaction.atomic():
        # 1) actualitza ordre_sortida
        for idx, ins_id in enumerate(wanted, start=1):
            Inscripcio.objects.filter(id=ins_id).update(ordre_sortida=idx)

        # 2) (NOU) només el registre mogut adopta el grup del superior immediat
        if moved_id is not None and new_index is not None and moved_id in wanted:
            if new_index > 0:
                prev_id = wanted[new_index - 1]
                prev_group = id_to_group.get(prev_id)

                # Mateixa nota: si NO vols que None esborri el grup, fes:
                # if prev_group is not None:
                Inscripcio.objects.filter(id=moved_id).update(grup=prev_group)

    return JsonResponse({"ok": True})


@require_POST
@csrf_protect
def inscripcions_merge_tabs(request, pk):
    c = get_object_or_404(Competicio, pk=pk)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        group_field = payload.get("group_field")   # IMPORTANT: ha de ser la "signature" (grouping_sig)
        source_key = payload.get("source_key")
        target_key = payload.get("target_key")
    except Exception:
        return HttpResponseBadRequest("JSON invàlid")

    if not group_field:
        return HttpResponseBadRequest("group_field buit")
    if not source_key or not target_key or source_key == target_key:
        return HttpResponseBadRequest("claus invàlides")

    merges = c.tab_merges or {}
    lst = merges.get(group_field, [])

    def normalize_key_to_simple_list(k: str) -> list[str]:
        """
        Retorna SEMPRE una llista de 'simple keys' (strings JSON del tipus ["A","B"...]).
        - Si k és simple: retorna [k]
        - Si k és merged: retorna [sub1, sub2, ...] on cada subX és un string JSON d'una clau simple
        """
        try:
            v = json.loads(k)
        except Exception:
            return [k]

        # merged: ['["..."]','["..."]', ...]  (cada element és un JSON de llista)
        if (
            isinstance(v, list) and v
            and all(isinstance(x, str) for x in v)
            and all(x.strip().startswith("[") for x in v)
        ):
            return v

        # simple: ["ALEVI","FEMENI", ...]
        if isinstance(v, list):
            return [k]

        return [k]


    s_list = normalize_key_to_simple_list(source_key)
    t_list = normalize_key_to_simple_list(target_key)

    # Unim t + s preservant ordre i dedup
    desired = []
    for x in (t_list + s_list):
        if x not in desired:
            desired.append(x)

    # Si ja hi ha merges que contenen alguna d'aquestes keys, els absorbim
    consumed_idx = []
    merged_all = []
    for i, g in enumerate(lst):
        # g és una llista de simple keys
        if any(x in g for x in desired):
            merged_all.extend(g)
            consumed_idx.append(i)

    for i in sorted(consumed_idx, reverse=True):
        lst.pop(i)

    merged_all.extend(desired)

    final = []
    for x in merged_all:
        if x not in final:
            final.append(x)

    lst.append(final)
    merges[group_field] = lst
    c.tab_merges = merges
    c.save(update_fields=["tab_merges"])

    return JsonResponse({"ok": True, "merged": final})
