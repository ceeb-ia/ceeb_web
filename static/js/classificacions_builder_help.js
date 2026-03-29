(function () {
  const HELP = {
    global_overview: {
      title: "Manual del builder de classificacions",
      summary:
        "Aquest builder defineix qui entra a la classificacio, com es calcula el resultat i com es mostra. El flux recomanat es: metadades, particions, puntuacio, desempat, filtres i presentacio.",
      sections: [
        {
          title: "Que decideix cada bloc",
          list: [
            "Metadades: identitat i tipus de classificacio.",
            "Particions: com es divideix la sortida final en blocs.",
            "Puntuacio: com es calcula el valor numeric o de victories.",
            "Desempat: com es resol un empat de resultat final.",
            "Filtres: qui entra al calcul abans de puntuar.",
            "Presentacio: quines files i columnes es mostren.",
          ],
        },
        {
          title: "Idea clau",
          text:
            "Hi ha tres preguntes diferents: qui entra, com es calcula i com es mostra. Els filtres responen la primera, la puntuacio la segona i la presentacio la tercera.",
        },
      ],
    },
    meta_overview: {
      title: "Metadades",
      summary:
        "Aquest bloc identifica la classificacio. No canvia el calcul numeric, excepte el tipus, que si condiciona quina logica esta disponible.",
    },
    field_tipus: {
      title: "Tipus",
      summary:
        "Defineix la unitat principal de la classificacio: una fila per inscripcio, per entitat o per equip.",
      sections: [
        {
          title: "Quan usar cada opcio",
          list: [
            "Individual: una fila per participant o inscripcio.",
            "Per entitat: agrega els resultats per club o entitat.",
            "Equips: calcula i agrupa per equips, amb configuracio addicional.",
          ],
        },
        {
          title: "Important",
          text:
            "El mode victories nomes esta disponible per a classificacions individuals.",
        },
      ],
    },
    particions_overview: {
      title: "Particions",
      summary:
        "Una particio divideix la sortida final en blocs visibles. No filtra participants ni canvia el calcul intern.",
      sections: [
        {
          title: "Exemple",
          text:
            "Si tries categoria i subcategoria, obtindras blocs com 'Alevi / Masculi' i 'Alevi / Femeni', pero tots els participants continuen entrant al calcul si no hi ha filtres.",
        },
        {
          title: "Error habitual",
          text:
            "Confondre particio amb filtre. Si vols excloure participants, fes-ho al bloc de filtres.",
        },
      ],
    },
    equips_overview: {
      title: "Configuracio d'equips",
      summary:
        "Aquest bloc nomes s'aplica quan el tipus es equips. Serveix per decidir com es formen o divideixen els equips a la sortida.",
    },
    eq_include_sense_equip: {
      title: "Incloure participants sense equip",
      summary:
        "Permet que les inscripcions sense equip no quedin fora de la classificacio d'equips.",
      sections: [
        {
          title: "Quan activar-ho",
          text:
            "Activa-ho si vols veure una sortida completa encara que hi hagi participants pendents d'assignacio o categories mixtes.",
        },
      ],
    },
    eq_manual_particions: {
      title: "Particions manuals d'equips",
      summary:
        "Permeten definir blocs d'equips manuals, per exemple Base, Promocio o Escola, independentment de l'edat.",
      sections: [
        {
          title: "Exemple",
          text:
            "Pots crear una particio manual 'Base' i associar-hi tres equips concrets. La classificacio mostrara aquest bloc amb aquests equips.",
        },
      ],
    },
    eq_age_particio: {
      title: "Particio per edat maxima d'equip",
      summary:
        "Divideix els equips segons l'edat maxima dels seus membres i permet definir llindars com 10, 12 o 14.",
      sections: [
        {
          title: "Exemple",
          text:
            "Amb llindars 10, 12 i 14, un equip amb edat maxima 11 entraria al bloc de 12.",
        },
        {
          title: "Que no fa",
          text:
            "No reordena els membres ni canvia el calcul de punts. Nomes segmenta la sortida d'equips.",
        },
      ],
    },
    puntuacio_overview: {
      title: "Puntuacio",
      summary:
        "Aquest bloc descriu el pipeline real del calcul: aparells, camps, valor per exercici, seleccio d'exercicis, agregacio per aparell i resultat final.",
      sections: [
        {
          title: "Pipeline base",
          list: [
            "1. Selecciones quins aparells entren.",
            "2. Tries quins camps de cada aparell compten.",
            "3. Si hi ha diversos camps, es combinen dins de cada exercici.",
            "4. Esculls quins exercicis compten.",
            "5. Els exercicis seleccionats es combinen per obtenir el resultat de l'aparell.",
            "6. Segons el mode, el resultat de l'aparell es tracta com score o com victories.",
            "7. Finalment s'agreguen els aparells.",
          ],
        },
        {
          title: "Important",
          text:
            "Els modes score i victories comparteixen gran part del pipeline. Victories no substitueix la seleccio de camps i exercicis; afegeix una capa de comparacio entre participants.",
        },
      ],
    },
    apps_selected: {
      title: "Aparells inclosos i camps",
      summary:
        "Nomes es calculen els aparells marcats. Dins de cada aparell, els camps seleccionats defineixen d'on surt el valor que compta.",
      sections: [
        {
          title: "Exemple",
          text:
            "Si selecciones TR i DM, qualsevol nota d'un altre aparell queda fora del calcul. A TR pots fer servir total i a DM E_total + D_total.",
        },
      ],
    },
    agregacio_camps: {
      title: "Agregacio de camps dins de cada exercici",
      summary:
        "Combina els camps seleccionats d'un mateix exercici en un valor unic. Aquest valor es la base per seleccionar exercicis i continuar el calcul.",
      sections: [
        {
          title: "Exemple numeric",
          list: [
            "Si un exercici te E = 8.2 i D = 2.0, amb sum el valor es 10.2.",
            "Amb avg, el valor passa a 5.1.",
            "Amb max, el valor es 8.2.",
          ],
        },
        {
          title: "Important",
          text:
            "Afecta tant score com victories, perque el sistema sempre necessita construir el valor base de cada exercici.",
        },
        {
          title: "Si despres tries camps per separat a victories",
          text:
            "No hi ha contradiccio: aquesta agregacio actua abans, per construir o seleccionar el valor base de l'exercici. Si a victories tries camps separats, el duel ja no comparara aquest valor agregat, sino cada camp per separat.",
        },
        {
          title: "Regla practica",
          text:
            "Amb score, aquesta agregacio mana directament. Amb victories, nomes mana al pas previ de construccio o seleccio. El duel el governa la configuracio propia de victories.",
        },
      ],
    },
    seleccio_exercicis: {
      title: "Seleccio d'exercicis",
      summary:
        "Defineix com s'aplica el criteri de seleccio d'exercicis: igual per a tots els aparells, amb overrides per aparell o sobre un sac global.",
      sections: [
        {
          title: "Opcions",
          list: [
            "Per aparell (criteri global): tots els aparells usen la mateixa regla.",
            "Per aparell (override): cada aparell pot tenir una regla diferent.",
            "Sac global: tots els exercicis dels aparells seleccionats entren en un mateix pool abans de triar.",
          ],
        },
        {
          title: "Exemple comparatiu",
          text:
            "Amb millor_1 i dos aparells, en mode per aparell es tria el millor exercici de cada aparell. En mode global_pool es tria un sol exercici entre tots els exercicis dels dos aparells.",
        },
      ],
    },
    mode_exercicis: {
      title: "Mode d'exercicis",
      summary:
        "Decideix quins exercicis compten dins del conjunt disponible per a cada aparell o per al pool global.",
      sections: [
        {
          title: "Modes disponibles",
          list: [
            "tots: compten tots els exercicis disponibles.",
            "millor_1 o millor_n: compten els de valor mes alt.",
            "pitjor_1 o pitjor_n: compten els de valor mes baix.",
            "primer i ultim: compten el primer o l'ultim existent.",
            "index: compta l'exercici amb aquell numero.",
            "llista: compten nomes els indexos indicats.",
          ],
        },
        {
          title: "Exemples",
          list: [
            "millor_2: si tens 10.1, 9.8 i 8.5, es queden 10.1 i 9.8.",
            "index = 2: nomes compta el segon exercici.",
            "llista = 1,3: nomes compten el primer i el tercer.",
          ],
        },
      ],
    },
    exercise_mode_details: {
      title: "Detalls de N, index, llista i maxim per participant",
      summary:
        "Aquests camps nomes tenen efecte en alguns modes d'exercicis i serveixen per afinar exactament quants exercicis es poden triar.",
      sections: [
        {
          title: "Quan s'usa cada camp",
          list: [
            "N: nomes per millor_n i pitjor_n.",
            "Index: nomes per index.",
            "Llista: nomes per llista.",
            "Max N per participant: limita quants exercicis pot aportar una mateixa inscripcio, especialment al sac global.",
          ],
        },
        {
          title: "Exemple",
          text:
            "Amb global_pool i max_per_participant = 1, una mateixa inscripcio no pot omplir el pool amb dos exercicis, encara que tingui dues notes molt altes.",
        },
      ],
    },
    agregacio_exercicis: {
      title: "Agregacio d'exercicis",
      summary:
        "Combina els exercicis seleccionats per obtenir el resultat numeric de l'aparell abans de l'ultim pas del calcul.",
      sections: [
        {
          title: "Exemple numeric",
          list: [
            "Si els exercicis seleccionats valen 10.1 i 9.8, amb sum obtens 19.9.",
            "Amb avg obtens 9.95.",
            "Amb max obtens 10.1.",
          ],
        },
        {
          title: "Important",
          text:
            "En victories continua afectant sempre que els exercicis es tractin de forma agregada abans del duel.",
        },
      ],
    },
    agregacio_aparells: {
      title: "Agregacio entre aparells",
      summary:
        "Combina els resultats finals dels aparells seleccionats per construir la puntuacio total de la classificacio.",
      sections: [
        {
          title: "Exemple numeric",
          text:
            "Si TR val 10 i DM val 8, amb sum el total es 18; amb avg el total es 9.",
        },
        {
          title: "Important",
          text:
            "En victories no agrega notes, agrega els punts de victoria finals de cada aparell.",
        },
      ],
    },
    ordre_principal: {
      title: "Ordre principal",
      summary:
        "Defineix si el valor mes alt guanya o si el valor mes baix guanya.",
      sections: [
        {
          title: "Quan usar asc",
          text:
            "Utilitza asc quan treballes amb temps, penalitzacions o qualsevol magnitud on menys es millor.",
        },
      ],
    },
    resultat_per_aparell: {
      title: "Resultat per aparell",
      summary:
        "Decideix si cada aparell aporta directament una puntuacio numeric o si primer es converteix en un duel entre participants.",
      sections: [
        {
          title: "Score",
          text:
            "Cada aparell aporta el seu valor numeric calculat i despres s'agrega entre aparells.",
        },
        {
          title: "Victories",
          text:
            "Cada aparell compara participants entre si i reparteix punts de victoria segons la posicio relativa dins del duel.",
        },
      ],
    },
    victories_overview: {
      title: "Configuracio de victories",
      summary:
        "Aquest bloc nomes canvia com es comparen els participants. No redefineix quins camps o exercicis entren al pipeline base.",
      sections: [
        {
          title: "Idea clau",
          text:
            "Primer es construeixen valors a partir de camps i exercicis. Despres victories decideix si el duel es fa sobre valors agregats o sobre unitats mes petites.",
        },
        {
          title: "Que preval quan sembla que hi ha dues opcions diferents",
          text:
            "No hi ha una sola opcio que prevalgui sempre. Les opcions del bloc principal de puntuacio actuen abans, al pipeline base. Les opcions de victories actuen durant el duel i en la recombinacio final dels punts de victoria.",
        },
      ],
    },
    victory_mode_camps: {
      title: "Calcul sobre camps",
      summary:
        "Decideix si els camps del mateix exercici competeixen junts o per separat.",
      sections: [
        {
          title: "Exemple",
          text:
            "Amb E i D, en agregat cada exercici te un sol valor. En separat, E i D poden donar punts de victoria diferents dins del mateix exercici.",
        },
        {
          title: "Relacio amb agregacio de camps",
          text:
            "Si aquí tries agregat, el duel fa servir el valor que surt de l'agregacio de camps del bloc principal. Si aquí tries separat, el duel ja no usa aquest valor agregat per comparar camps; compara E, D o cada camp per separat.",
        },
        {
          title: "Exemple de possible confusio",
          text:
            "Si E = 10 i D = 1 per a A, i E = 8 i D = 8 per a B, amb agregacio de camps = sum i camps agregats guanya B per 16 contra 11. Amb camps separats, A guanya E i B guanya D; despres combines aquestes victories amb l'agregacio de victories entre camps.",
        },
      ],
    },
    victory_mode_exercicis: {
      title: "Calcul sobre exercicis",
      summary:
        "Decideix si els exercicis seleccionats es combinen abans del duel o si cada exercici fa el seu duel propi.",
      sections: [
        {
          title: "Exemple",
          text:
            "Amb agregat, els exercicis 1 i 2 es redueixen a un sol valor de l'aparell. Amb separat, l'exercici 1 i el 2 poden donar punts de victoria independents.",
        },
      ],
    },
    victory_field_selection: {
      title: "Seleccio d'exercicis amb camps separats",
      summary:
        "Quan els camps es tracten per separat, decideix si cada camp pot triar exercicis diferents o si tots els camps han de compartir la mateixa seleccio.",
      sections: [
        {
          title: "per_camp",
          text:
            "Cada camp resol millor_n, pitjor_n o la regla activa pel seu compte.",
        },
        {
          title: "global",
          text:
            "La seleccio es calcula una sola vegada amb el valor agregat normal de l'exercici i despres s'aplica igual a tots els camps.",
        },
        {
          title: "Exemple",
          text:
            "Si E te el millor valor a l'exercici 1 i D el te a l'exercici 2, per_camp pot acabar comparant E sobre l'exercici 1 i D sobre el 2. Global obligara a fer servir la mateixa seleccio per a tots dos camps.",
        },
      ],
    },
    victory_agg_camps: {
      title: "Agregacio de victories entre camps",
      summary:
        "Combina els punts de victoria dels camps dins de la unitat actual d'exercici.",
      sections: [
        {
          title: "Exemple",
          text:
            "Si un participant guanya E amb 1 punt i perd D amb 0 punts, amb sum obten 1.0 i amb avg obten 0.5.",
        },
      ],
    },
    victory_agg_exercicis: {
      title: "Agregacio de victories entre exercicis",
      summary:
        "Combina els punts de victoria dels exercicis dins del mateix aparell.",
      sections: [
        {
          title: "Exemple",
          text:
            "Si un participant guanya el primer exercici amb 1 punt i empata el segon amb 0.5, amb sum obten 1.5 i amb avg obten 0.75.",
        },
      ],
    },
    victory_internal_tie: {
      title: "Desempat intern de victories",
      summary:
        "Resol empats dins d'un duel concret. Sempre treballa dins del mateix aparell comparat i, si toca, dins del mateix exercici o camp de la unitat activa.",
      sections: [
        {
          title: "Que no pot fer",
          text:
            "No pot ampliar el criteri a altres aparells ni a altres participants. Tampoc substitueix el desempat general de la classificacio final.",
        },
      ],
    },
    desempat_overview: {
      title: "Desempat general",
      summary:
        "S'aplica despres de calcular els punts finals de la classificacio. Serveix per ordenar empats a la taula final.",
      sections: [
        {
          title: "No confondre",
          text:
            "El desempat general ordena la classificacio final. El desempat intern de victories decideix guanyadors dins d'un duel concret.",
        },
      ],
    },
    desempat_aparells: {
      title: "Desempat: aparells",
      summary:
        "Permet limitar el criteri de desempat a uns aparells concrets o heretar la seleccio principal.",
    },
    desempat_camps: {
      title: "Desempat: camps",
      summary:
        "Indica quin camp o camps es faran servir per comparar participants en aquest criteri de desempat.",
      sections: [
        {
          title: "Exemple",
          text:
            "Pots desempatar amb E_total, amb penalitzacio o amb una combinacio de diversos camps si tenen sentit conjuntament.",
        },
      ],
    },
    desempat_exercicis: {
      title: "Desempat: exercicis",
      summary:
        "Defineix quins exercicis entren al criteri de desempat. El mecanisme es semblant al de la puntuacio principal, pero nomes per aquest criteri.",
    },
    desempat_participants: {
      title: "Desempat: participants",
      summary:
        "Nomes te sentit en classificacions d'equips. Decideix quants membres de l'equip compten dins del criteri de desempat.",
    },
    desempat_ordre: {
      title: "Desempat: ordre",
      summary:
        "Defineix si en aquest criteri concret mes es millor o menys es millor.",
    },
    filtres_overview: {
      title: "Filtres",
      summary:
        "Els filtres actuen abans del calcul, pero la seva unitat depen del tipus: participants a individual i entitat, membres a equips derivats i composicio completa a equips natius.",
      sections: [
        {
          title: "Exemple",
          text:
            "Si filtres per categoria A, els participants d'altres categories ni es calculen ni es mostren.",
        },
        {
          title: "Equips natius",
          text:
            "Quan la classificacio usa notes natives d'equip, l'equip nomes entra si tots els seus membres compleixen els filtres actius.",
        },
      ],
    },
    presentacio_overview: {
      title: "Presentacio",
      summary:
        "Aquest bloc no canvia el calcul. Decideix quantes files es mostren, com es tracten els empats i quines columnes veu l'usuari.",
    },
    top_n: {
      title: "Top N",
      summary:
        "Limita quantes files es mostren per particio. Amb 0 no hi ha limit.",
      sections: [
        {
          title: "Exemple",
          text:
            "Amb Top N = 3 es mostren les tres primeres files de cada particio, subjecte al tractament dels empats.",
        },
      ],
    },
    mostrar_empats: {
      title: "Mostrar empats",
      summary:
        "Decideix si s'han de mantenir visibles les files empatades quan el tall del Top N cau al mig d'un empat.",
      sections: [
        {
          title: "Exemple",
          text:
            "Amb Top N = 3 i empat a la tercera posicio, activar aquesta opcio pot fer que es mostrin 4 o mes files.",
        },
      ],
    },
    columns_builtin: {
      title: "Columnes builtin",
      summary:
        "Afegeixen columnes estandards com posicio, nom, entitat o punts finals sense haver de referenciar un camp concret.",
    },
    columns_raw: {
      title: "Columnes raw",
      summary:
        "Mostren valors d'un camp concret d'un aparell i exercici. En equips, la live pot ensenyar resum i detall per membres o valor natiu d'equip segons el mode.",
    },
    preview_help: {
      title: "Previsualitzacio",
      summary:
        "Executa la classificacio amb la configuracio actual i mostra una taula de comprovacio per validar la sortida abans de desar o publicar.",
    },
    advanced_json: {
      title: "Schema complet (JSON)",
      summary:
        "Mostra el JSON real que genera el builder. Serveix per revisar o depurar, pero no es el flux normal de configuracio.",
      sections: [
        {
          title: "Recomanacio",
          text:
            "Utilitza'l com a referencia tecnica. Si no tens clar el format intern, es millor continuar treballant des de la UI del builder.",
        },
      ],
    },
  };

  const DEFAULT_KEY = "global_overview";

  function ensureTopLayerMount() {
    const drawer = document.getElementById("classifHelpDrawer");
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
    const titleEl = document.getElementById("classifHelpTitle");
    const bodyEl = document.getElementById("classifHelpBody");
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
    document.body.classList.add("classif-help-open");
  }

  function closeHelp() {
    const drawer = document.getElementById("classifHelpDrawer");
    if (!drawer) return;
    drawer.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
    document.body.classList.remove("classif-help-open");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureTopLayerMount);
  } else {
    ensureTopLayerMount();
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-help-key]");
    if (trigger) {
      event.preventDefault();
      event.stopPropagation();
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
    if (event.key === "Escape") closeHelp();
  });
})();
