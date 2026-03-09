(function () {
  const HELP = {
    global_overview: {
      title: "Manual del Builder",
      summary:
        "Configura l'esquema de puntuació de l'aparell (Avançat: JSON com a suport de revisió). El flux correcte és definir dades d'entrada, definir càlculs i validar el resultat.",
      sections: [
        {
          title: "Flux recomanat",
          list: [
            "Defineix els camps d'entrada a la pestanya Camps.",
            "Afegeix fórmules que facin càlculs amb els camps d'entrada definits o altres funcions (ex: E_ex -> TOTAL).",
            "Revisa camps, comprova noms i desa.",
          ],
        },
        {
          title: "Regles clau",
          list: [
            "Cada `Code` ha de ser únic.",
            "Les fórmules poden escriure's amb `Code` o `Var`.",
            "Si hi ha alguna incoherència en la declaració de noms, Codes o Variables, el schema fallarà en validar/calcular.",
          ],
        },
        {
          title: "Code vs Var (resum)",
          list: [
            "Code: identificador canònic i estable del camp/fórmula.",
            "Var: actua com la variable, l' àlies curt opcional per escriure fórmules més llegibles.",
            "Si dubtes, usa Code a les dependències crítiques.",
          ],
        },
      ],
    },
    fields_overview: {
      title: "Camps d'entrada",
      summary:
        "Aquests camps són les dades que entren de l'usuari/jurat. Després, les fórmules les transformen en resultats calculats.",
      sections: [
        {
          title: "Objectiu",
          list: [
            "Definir quantes notes es recullen.",
            "Definir límits i precisió de les notes.",
            "Preparar els codis que després es fan servir a Fórmules.",
          ],
        },
        {
          title: "Nota de model",
          text:
            "En aquest constructor de puntuació, els camps es guarden com a matriu jutge x item. Pot imaginar-se com una taula de tantes files com jutges i tantes columnes com ítems. Si poses 3 jutges i 2 items, obtindràs una taula de 3 files i 2 columnes.",
        },
      ],
    },
    field_label: {
      title: "Camp: Etiqueta",
      summary: "Nom visible del camp per als usuaris.",
    },
    field_code: {
      title: "Camp: Code",
      summary:
        "Identificador únic i canònic del camp. És la clau real que es guarda i que el motor fa servir per calcular.",
      sections: [
        { title: "Exemple", text: "`E`, `DD`, `TOF`, `TOTAL`" },
        {
          title: "Recomanació",
          text:
            "No canviïs Codes un cop tens dades, per evitar trencar fórmules, exports o configuracions dependents.",
        },
      ],
    },
    field_var: {
      title: "Camp: Var",
      summary:
        "És l'àlies curt (opcional), que actua com a variable del Code. Serveix per escriure fórmules més netes. És per comoditat, no substitueix el Code com a identificador principal.",
      sections: [
        { title: "Exemple", text: "Si Code és `DD`, Var pot ser `d`; en comptes d'escriure TOTAL = E + DD + TOF + HD escric TOTAL = e + d + t + h)."},
        {
          title: "Bona pràctica",
          text:
            "Fes servir 'Vars' simples i consistents (`e`, `d`, `t`, `h`, `p`) i evita reutilitzar el mateix var en diferents files.",
        },
      ],
    },
    field_judges_count: {
      title: "Camp: Jutges",
      summary: "Nombre de jutges que aporten nota a aquest camp.",
    },
    field_items_count: {
      title: "Camp: Items",
      summary: "Nombre de valors que entra cada jutge dins aquest camp, és a dir, nombre de valors que conformen la nota. Per exemple, 'La nota d'Execució és forma a partir de la nota individual de cada un dels 10 elements'.",
    },
    field_min: {
      title: "Camp: Min",
      summary: "Valor mínim admissible. El sistema no deixarà valors per sota, si un jutge escriu un valor menor, se substituirà per el Min definit.",
    },
    field_max: {
      title: "Camp: Max",
      summary: "Valor màxim admissible. El sistema no deixarà valors per sobre, si un jutge escriu un valor major, se substituirà per el Max definit.",
    },
    field_decimals: {
      title: "Camp: Decimals",
      summary: "Precisió decimal que es guardarà i mostrarà. Valors introduits amb més decimals s'arrodoneixen.",
    },
    field_crash: {
      title: "Camp: Crash",
      summary: "Activa gestió de tall/aturada del recorregut per aquest camp.",
      sections: [
        {
          title: "Quan usar-ho",
          text: "Només als camps on aquesta regla tingui sentit reglamentari.",
        },
        {
          title: "Efecte",
          text:
            "Quan està actiu, el motor considera valors de crash per limitar quins items compten en càlculs per jutge/item.",
        },
      ],
    },
    formules_overview: {
      title: "Fórmules",
      summary:
        "Les fórmules creen càlculs a partir de camps d'entrada i de resultats d'altres fórmules. Són la capa de lògica del sistema de puntuació.",
      sections: [
        {
          title: "Dependència i ordre",
          text:
            "No cal ordenar manualment les files perquè el motor resol l'ordre per dependències (ordre topològic). El que sí cal és que els noms referenciats existeixin i que no hi hagi cicles (és a dir, funcions que depenen de sí mateixes, per exemple: TOTAL = TOTAL * 2).",
        },
        {
          title: "Bones pràctiques",
          list: [
            "Defineix sempre `TOTAL` si vols tenir un resultat final principal.",
            "Per dependències entre fórmules, prefereix 'Code' (més explícit).",
            "Usa 'Var' quan millori la llegibilitat de la fórmula.",
          ],
        },
      ],
    },
    formula_preset: {
      title: "Funció de fórmula",
      summary: "Tria el tipus de càlcul: manual o guiat (per jutge/per item).",
      sections: [
        {
          title: "Opcions habituals",
          list: [
            "Fórmula manual: expressió directa.",
            "Per items i despres per jutges (total final): primer es fa el càlcul per files (jutges), combinant els valors dels diferents ítems (columnes), i després combina jutges (files). Per exemple, calculo la nota total de cada jutge sumant els seus ítems, i després faig la nota mitjana entre tots els jutges",
            "Per items i resultat per jutge (sense total final): es fa el càlcul per files (jutges), combinant els valors dels diferents ítems (columnes), i s'obté un llistat de notes per jutge. És com 'Per items i despres per jutges', però sense la part final de càlcul entre jutges. Per exemple, vull obtenir la nota per jutge i res més, tindré [Nota J1, Nota J2,...].",
            "Per jutges i despres per items (total final): primer es fa el càlcul per columnes (ítems), combinant els valors dels diferents jutges, i després combina columnes (ítems). Per exemple, agafo el valor mitjà de cada element (cada columna, ítem) i després sumo el resultat per cada element.",
          ],
        },
      ],
    },
    formula_config: {
      title: "Configuració de fórmula",
      summary:
        "Defineix camp font, transformació a aplicar per cada valor (per exemple, sumar 1 i restar el valor del jutge), mètodes de selecció i agregació. Aquesta combinació determina exactament quins valors compten.",
      sections: [
        {
          title: "Idea simple",
          list: [
            "Esculls d'on surten les dades.",
            "Indiques com es transformen.",
            "Decideixes quins valors compten i com es combinen.",
          ],
        },
        {
          title: "Atenció a seleccions amb N",
          list: [
            "`Extrems alternant fins N`, `Millors N` i `Pitjors N` necessiten N, el nombre de valors que es vol.",
            "Si no poses N en aquests modes, el càlcul donarà error.",
          ],
        },
        {
          title: "Sobre què seleccionar/agregar",
          text:
            "Pots decidir si la selecció/agregació es fa sobre valor original (`raw`) o sobre valor transformat (`item_expr`).",
        },
      ],
    },
    advanced_json: {
      title: "Avançat (JSON)",
      summary:
        "Vista del JSON que genera el builder automàticament. Serveix per entendre exactament què es desa.",
      sections: [
        {
          title: "Per a què serveix",
          list: [
            "Revisar que l'esquema final sigui el que esperes.",
            "Diagnosticar errors de configuració.",
            "Copiar una referència tècnica per depurar incidències.",
          ],
        },
        {
          title: "Recomanació",
          text:
            "Edició manual només si tens clar el format intern. En general és millor mantenir la configuració des de la UI del builder.",
        },
      ],
    },
  };

  const DEFAULT_KEY = "global_overview";

  function ensureTopLayerMount() {
    const drawer = document.getElementById("schemaHelpDrawer");
    if (!drawer) return null;
    if (drawer.parentElement !== document.body) {
      document.body.appendChild(drawer);
    }
    return drawer;
  }

  function createNode(tag, text, className) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text) el.textContent = text;
    return el;
  }

  function renderHelp(key) {
    const entry = HELP[key] || HELP[DEFAULT_KEY];
    const titleEl = document.getElementById("schemaHelpTitle");
    const bodyEl = document.getElementById("schemaHelpBody");
    if (!titleEl || !bodyEl) return;

    titleEl.textContent = entry.title || "Ajuda";
    bodyEl.innerHTML = "";

    if (entry.summary) {
      bodyEl.appendChild(createNode("p", entry.summary));
    }

    (entry.sections || []).forEach((section) => {
      if (section.title) {
        bodyEl.appendChild(createNode("h6", section.title));
      }
      if (section.text) {
        bodyEl.appendChild(createNode("p", section.text));
      }
      if (Array.isArray(section.list) && section.list.length) {
        const ul = createNode("ul");
        section.list.forEach((item) => {
          ul.appendChild(createNode("li", item));
        });
        bodyEl.appendChild(ul);
      }
    });
  }

  function openHelp(key) {
    const drawer = ensureTopLayerMount();
    if (!drawer) return;
    renderHelp(key || DEFAULT_KEY);
    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
    document.body.classList.add("schema-help-open");
  }

  function closeHelp() {
    const drawer = document.getElementById("schemaHelpDrawer");
    if (!drawer) return;
    drawer.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
    document.body.classList.remove("schema-help-open");
  }

  // Ensure the drawer is mounted at body level as soon as the page is ready.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureTopLayerMount);
  } else {
    ensureTopLayerMount();
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-help-key]");
    if (trigger) {
      event.preventDefault();
      openHelp(trigger.getAttribute("data-help-key"));
      return;
    }

    const closeTrigger = event.target.closest("[data-help-close]");
    if (closeTrigger) {
      event.preventDefault();
      closeHelp();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeHelp();
    }
  });
})();
