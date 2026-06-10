AVATAR_MESSAGES = {
  "classifications_scoring_overview": {
    "id": "classifications_scoring_overview",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "A Puntuació configures com IA Score transforma les notes introduïdes pels jutges en el resultat final d’una classificació."
      },
      {
        "text": "Aquesta és una de les seccions més importants, perquè permet crear classificacions molt diferents a partir de les mateixes notes de competició."
      },
      {
        "text": "La secció es divideix en 3 grans blocs: Base i ordre, Configuració dels aparells i Resum del càlcul."
      },
      {
        "text": "A Base i ordre defineixes quin mètode de càlcul farà servir la classificació i si els resultats s’ordenaran de manera ascendent o descendent."
      },
      {
        "text": "A Configuració dels aparells decideixes quins aparells i fases entren en el càlcul, quines notes es tenen en compte i com es combinen."
      },
      {
        "text": "Al Resum del càlcul pots revisar la configuració resultant per entendre com IA Score arribarà al resultat final."
      },
      {
        "text": "La idea general és aquesta: IA Score recull una bossa de notes candidates, selecciona les que interessen i les agrega per obtenir la puntuació final de cada unitat competitiva."
      },
      {
        "text": "Segons el tipus de classificació, aquesta unitat competitiva pot ser una inscripció individual o un equip. \nRecorda, el nostre objectiu es arribar a una nota final de cada inscripció o equip que després es pugui ordenar per generar la classificació."
      }
    ],
    "actions": []
  },

  "classifications_scoring_base_order": {
    "id": "classifications_scoring_base_order",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "A Base i ordre defineixes la base del càlcul de la classificació."
      },
      {
        "text": "Primer has d’escollir el mètode de càlcul dels resultats."
      },
      {
        "text": "El mètode Score utilitza la puntuació final obtinguda a partir de les notes introduïdes pels jutges i les combina segons la configuració definida."
      },
      {
        "text": "El mètode Victòries compara els scores entre participants o unitats competitives i assigna punts segons aquestes comparacions."
      },
      {
        "text": "Aquest segon mètode és útil en esports o formats on la classificació es basa en enfrontaments, victòries o comparacions entre resultats."
      },
      {
        "text": "També has d’indicar l’ordre dels valors: ascendent o descendent."
      },
      {
        "text": "En ordre descendent, els valors més alts queden millor classificats. En ordre ascendent, els valors més baixos tenen prioritat."
      },
    ],
    "actions": []
  },

  "classifications_scoring_apparatus_selection": {
    "id": "classifications_scoring_apparatus_selection",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "Després de definir la base del càlcul, has d’indicar quins aparells formaran part de la classificació."
      },
      {
        "text": "Pots seleccionar tants aparells com vulguis dins de la competició per a cada classificació."
      },
      {
        "text": "Per cada aparell seleccionat, també has d’escollir quina fase es tindrà en compte."
      },
      {
        "text": "Només es pot seleccionar una fase per aparell dins d’una mateixa classificació."
      },
      {
        "text": "Això permet, per exemple, crear una classificació basada en la fase preliminar d’un aparell, o una altra basada en una final."
      },
      {
        "text": "A partir d’aquesta selecció, IA Score sap d’on ha d’agafar les notes candidates per construir el resultat."
      }
    ],
    "actions": []
  },

  "classifications_scoring_apparatus_treatment": {
    "id": "classifications_scoring_apparatus_treatment",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "Un cop seleccionats els aparells i fases, has de decidir com es tractaran les notes dels diferents aparells."
      },
      {
        "text": "El tractament pot ser individual per aparell o conjunt."
      },
      {
        "text": "Amb tractament individual per aparell, IA Score calcula primer un resultat per cada aparell i després agrega aquests resultats per obtenir la nota final."
      },
      {
        "text": "Això és útil quan vols que cada aparell mantingui el seu propi pes o resultat abans de combinar-los."
      },
      {
        "text": "Amb tractament conjunt, IA Score no separa les notes segons l’aparell d’origen a l’hora de calcular la nota final."
      },
      {
        "text": "En aquest cas, les notes seleccionades dels diferents aparells es tracten com si formessin part d’un mateix conjunt."
      },
      {
        "text": "Una manera senzilla d’entendre-ho és imaginar cada aparell com una bossa de notes."
      },
      {
        "text": "Si el tractament és individual, IA Score mira cada bossa per separat i després combina els resultats de cada aparell."
      },
      {
        "text": "Si el tractament és conjunt, IA Score ajunta les bosses dels aparells seleccionats i calcula el resultat final a partir del conjunt de notes."
      }
    ],
    "actions": []
  },

  "classifications_scoring_bags_concept": {
    "id": "classifications_scoring_bags_concept",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "Per entendre la configuració de puntuació, pot ajudar pensar en bosses de notes."
      },
      {
        "text": "En una classificació individual, cada aparell aporta una bossa amb les notes individuals de cada exercici de la inscripció dins de la fase seleccionada."
      },
      {
        "text": "En una classificació d’equips derivada d’individual, cada aparell aporta una bossa amb totes les notes individuals de cada exercici dels membres de l’equip."
      },
      {
        "text": "En una classificació nativa d’equip, cada aparell d’equip aporta una bossa amb les notes de cada exercici de l’equip com a unitat competitiva."
      },
      {
        "text": "Això vol dir que tinc tantes bosses com aparells amb tantes notes com exercicis dins de cada bossa. En equips derivats d'individual, la mateixa bossa recull tots els exercicis de tots els membres de l'equip."

      },
      {
        "text": "A partir d’aquestes bosses, IA Score selecciona quines notes interessen i com s’han d’agregar per obtenir el resultat final."
      },
      {
        "text": "Per exemple, pots tenir una bossa amb la nota A de l’exercici 1, la nota B de l’exercici 2 i la nota C de l’exercici 3."
      },
      {
        "text": "Després pots decidir si vols agafar totes aquestes notes, només les millors, una quantitat concreta, o aplicar-hi una agregació com suma o mitjana."
      }
    ],
    "actions": []
  },

  "classifications_scoring_apparatus_fields": {
    "id": "classifications_scoring_apparatus_fields",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "Dins de Configuració dels aparells, el primer pas és definir els camps de puntuació que es tindran en compte."
      },
      {
        "text": "Els camps són les notes o valors que has configurat prèviament dins de cada aparell."
      },
      {
        "text": "Pots seleccionar un o diversos camps del llistat disponible."
      },
      {
        "text": "Si selecciones diversos camps, hauràs d’indicar com s’agreguen entre ells amb l’agregació de camps."
      },
      {
        "text": "Per exemple, pots sumar camps, fer-ne una mitjana o aplicar el criteri que correspongui segons la configuració disponible."
      },
      {
        "text": "Aquesta selecció de camps pot ser comuna per a tots els exercicis de l’aparell."
      },
      {
        "text": "També pot configurar-se per exercici, si vols considerar uns camps en l’exercici 1, uns altres en l’exercici 2, i així successivament."
      },
      {
        "text": "Això dona flexibilitat quan no tots els exercicis d’un aparell s’han de valorar exactament de la mateixa manera."
      }
    ],
    "actions": []
  },

  "classifications_scoring_participant_pretreatment": {
    "id": "classifications_scoring_participant_pretreatment",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "El pretractament per participant permet calcular una nota prèvia per cada membre abans de construir el resultat final."
      },
      {
        "text": "Aquest pas només apareix quan té sentit, especialment en classificacions d’equips derivades d’individual."
      },
      {
        "text": "En aquest tipus de classificació, l’equip obté el resultat a partir de les notes individuals dels seus membres."
      },
      {
        "text": "Per això pot interessar calcular primer una nota total per cada membre abans de decidir quines contribucions compten per a l’equip."
      },
      {
        "text": "Aquí pots indicar quins exercicis es tindran en compte per cada participant."
      },
      {
        "text": "També pots definir com s’agreguen les notes d’aquests exercicis per obtenir la nota prèvia del membre."
      },
      {
        "text": "Per exemple, pots voler sumar diversos exercicis d’un mateix membre abans de seleccionar les millors contribucions de l’equip."
      },
      {
        "text": "Aquest pas ajuda IA Score a passar de notes individuals disperses a una nota candidata per membre."
      }
    ],
    "actions": []
  },

  "classifications_scoring_note_selection": {
    "id": "classifications_scoring_note_selection",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "Un cop IA Score ja sap quins camps i exercicis formen la bossa de notes, arriba el moment de seleccionar quines notes comptaran."
      },
      {
        "text": "Aquesta selecció permet decidir si es tenen en compte totes les notes candidates o només una part."
      },
      {
        "text": "Per exemple, pots voler agafar totes les notes, només les millors, només una quantitat concreta o aplicar un criteri específic de selecció."
      },
      {
        "text": "Això és especialment útil quan una unitat competitiva té diverses notes possibles però només algunes han de contribuir al resultat final."
      },
      {
        "text": "Tornant a la idea de la bossa: primer omples la bossa amb les notes que has configurat, i després decideixes quines en treus per calcular el resultat."
      },
      {
        "text": "Aquesta selecció és el pas que converteix una llista de notes candidates en el conjunt real de notes que comptaran per a la classificació."
      }
    ],
    "actions": []
  },

  "classifications_scoring_final_aggregation": {
    "id": "classifications_scoring_final_aggregation",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "Després de seleccionar les notes candidates, IA Score ha d’agregar-les per obtenir la puntuació final."
      },
      {
        "text": "L’agregació defineix com es combinen les notes seleccionades."
      },
      {
        "text": "Segons la configuració, aquestes notes es poden sumar, mitjanar o combinar amb el criteri que correspongui."
      },
      {
        "text": "En cas d'haver seleccionat varis aparells amb tractament individual, hauràs de definir com es combinen les notes de cada aparell per obtenir la puntuació final."
      },
      {
        "text": "Aquest resultat agregat és el valor que finalment es farà servir per ordenar la classificació."
      },
      {
        "text": "En una classificació individual, aquest valor correspon a cada inscripció."
      },
      {
        "text": "En una classificació d’equips derivada d’individual, correspon al resultat de l’equip calculat a partir de les contribucions dels seus membres."
      },
      {
        "text": "En una classificació nativa d’equip, correspon al resultat de l’equip com a unitat competitiva en un aparell d’equip."
      }
    ],
    "actions": []
  },

  "classifications_scoring_calculation_summary": {
    "id": "classifications_scoring_calculation_summary",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "El Resum del càlcul serveix per revisar com quedarà interpretada la configuració de puntuació."
      },
      {
        "text": "És una manera de comprovar si IA Score està agafant els aparells, fases, camps, seleccions i agregacions que realment vols."
      },
      {
        "text": "Abans de donar per bona una classificació complexa, és recomanable revisar aquest resum amb calma."
      },
      {
        "text": "Si el resum no reflecteix el càlcul que esperaves, pots tornar als blocs anteriors i ajustar la configuració."
      },
      {
        "text": "Pensa en aquest resum com una lectura final de la recepta de puntuació abans que IA Score generi els resultats."
      }
    ],
    "actions": []
  }
}