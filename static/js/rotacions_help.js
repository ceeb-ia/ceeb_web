(function () {
  const HELP = {
    global_overview: {
      title: "Manual ràpid de Rotacions",
      body: "Aquesta vista et permet construir la graella de rotacions (franges x estacions), assignar-hi grups i exportar el resultat a Excel.",
    },
    grups: {
      title: "Grups",
      body: "Aquí tens els grups disponibles. Arrossega un grup a una cel·la de la graella per assignar-lo. Arrossega '(Buit)' per deixar una cel·la sense assignació.",
    },
    competicio_format: {
      title: "Afegir franja (manual)",
      body: "Crea una franja nova indicant hora d'inici, hora de fi i títol. La franja apareixerà com una fila nova a la graella.",
    },
    control_temps: {
      title: "Generar franges automàticament",
      body: "Crea franges en sèrie entre una hora d'inici i una hora de fi, amb l'interval en minuts indicat. Pots esborrar les franges existents abans de generar-les.",
    },
    incidencies: {
      title: "Afegir descans",
      body: "Afegeix una estació de descans al programa perquè es pugui usar dins la rotació com una columna més de la graella.",
    },
    ordre_sortida: {
      title: "Programa (graella de rotacions)",
      body: "La graella mostra franges (files) i estacions (columnes). Assigna grups a cada cel·la amb drag and drop i revisa que no quedin buits no desitjats.",
    },
    canvis_manuals: {
      title: "Netejar programa",
      body: "Aquest botó elimina totes les assignacions de la graella. És una acció global per reiniciar el programa.",
    },
    aparell_rotacio: {
      title: "Franges i estacions",
      body: "La primera columna identifica la franja horària; la resta de columnes són estacions. Pots reorganitzar estacions arrossegant les capçaleres.",
    },
    publicar: {
      title: "Exportació Excel",
      body: "Des d'aquí pots exportar el programa en Excel en dos formats: participants o grups.",
    },
    validacio: {
      title: "Dades d'export",
      body: "Defineix les dades que sortiran a l'Excel (títol, seu, data i logo) i desa-les per reutilitzar-les en les exportacions.",
    },
    capcalera_grup: {
      title: "Camps de participants (Excel)",
      body: "Selecciona quins camps es mostren en l'exportació de participants i en quin ordre. Pots marcar o desmarcar i arrossegar per ordenar.",
    },
    franja_order_mode: {
      title: "Mode d'ordre de franja",
      body: "Aquest selector defineix com s'ordena el contingut d'aquesta franja. El canvi es desa al moment per a la franja seleccionada.",
    },
    franja_actions: {
      title: "Accions de franja",
      body: "Aquest bloc agrupa les accions ràpides de la fila: editar la franja, inserir-ne una després, netejar la fila, extrapolar i eliminar.",
    },
  };

  const DEFAULT_KEY = "global_overview";

  function ensureTopLayerMount() {
    const drawer = document.getElementById("rotHelpDrawer");
    if (!drawer) return null;
    if (drawer.parentElement !== document.body) {
      document.body.appendChild(drawer);
    }
    return drawer;
  }

  function openHelp(key) {
    const drawer = ensureTopLayerMount();
    const title = document.getElementById("rotHelpTitle");
    const body = document.getElementById("rotHelpBody");
    if (!drawer || !title || !body) return;

    const entry = HELP[key] || HELP[DEFAULT_KEY];
    title.textContent = entry.title || "Ajuda";
    body.innerHTML = "";

    const p = document.createElement("p");
    p.textContent = entry.body || "";
    body.appendChild(p);

    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
    document.body.classList.add("rot-help-open");
  }

  function closeHelp() {
    const drawer = document.getElementById("rotHelpDrawer");
    if (!drawer) return;
    drawer.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
    document.body.classList.remove("rot-help-open");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureTopLayerMount);
  } else {
    ensureTopLayerMount();
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-rot-help-key]");
    if (trigger) {
      event.preventDefault();
      openHelp(trigger.getAttribute("data-rot-help-key"));
      return;
    }

    const closeTrigger = event.target.closest("[data-rot-help-close]");
    if (closeTrigger) {
      event.preventDefault();
      closeHelp();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeHelp();
  });
})();
