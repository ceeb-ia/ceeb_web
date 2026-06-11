AVATAR_MESSAGES = {
  "classifications_scoring_general": {
    "id": "classifications_scoring_general",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "A Puntuació configures com IA Score transforma les notes introduïdes pels jutges en el resultat final d’una classificació."
      },
      {
        "text": "És una de les seccions més importants, perquè permet crear classificacions molt diferents a partir de les mateixes notes de competició."
      },
      {
        "text": "La secció es divideix en 3 grans blocs: Base i ordre, Configuració dels aparells i Resum del càlcul."
      },
      {
        "text": "A Base i ordre defineixes el mètode de càlcul dels resultats i si els valors s’ordenen de manera ascendent o descendent."
      },
      {
        "text": "El mètode Score calcula la classificació a partir de la puntuació resultant de combinar les notes introduïdes pels jutges."
      },
      {
        "text": "El mètode Victòries compara els scores entre participants o unitats competitives i suma punts segons aquestes comparacions."
      },
      {
        "text": "Després has d’escollir els aparells que formaran part de la classificació i quina fase es tindrà en compte per a cada aparell."
      },
      {
        "text": "Pots seleccionar tants aparells com vulguis dins de la competició, però només una fase per cada aparell."
      },
      {
        "text": "Finalment, has d’indicar com es tractaran les notes dels aparells: amb tractament individual per aparell o amb tractament conjunt."
      },
      {
        "text": "Amb tractament individual per aparell, IA Score resol primer cada aparell per separat i després agrega els resultats dels aparells per obtenir la nota final."
      },
      {
        "text": "Amb tractament conjunt, IA Score no diferencia de quin aparell ve cada nota a l’hora de calcular el resultat final."
      },
      {
        "text": "Una manera senzilla d’entendre-ho és imaginar cada aparell com una bossa de notes."
      },
      {
        "text": "En una classificació individual, cada aparell aporta una bossa amb les notes individuals de cada inscripció dins de la fase seleccionada."
      },
      {
        "text": "En una classificació d’equips derivada d’individual, cada aparell aporta una bossa amb les notes individuals dels membres de l’equip."
      },
      {
        "text": "En una classificació nativa d’equip, cada aparell d’equip aporta una bossa amb les notes de l’equip com a unitat competitiva."
      },
      {
        "text": "Si el tractament és conjunt, IA Score ajunta les bosses dels aparells seleccionats i tracta totes les notes com un únic conjunt."
      },
      {
        "text": "El Resum del càlcul et permet revisar la configuració final i comprovar com IA Score interpretarà la classificació abans de generar els resultats."
      }
    ],
    "actions": []
  },

  "classifications_scoring_team_member_treatment": {
    "id": "classifications_scoring_team_member_treatment",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "Quan la classificació és per equips derivada d’individual, IA Score mostra també el tractament de membres."
      },
      {
        "text": "Aquest tractament defineix com es converteixen les notes individuals dels membres en una nota candidata per a l’equip."
      },
      {
        "text": "El mode Tractament per membre de l’equip resol primer cada membre per separat."
      },
      {
        "text": "Això vol dir que IA Score calcula una nota per cada membre a partir dels seus propis exercicis, i després posa aquests resultats dins la bossa de l’equip."
      },
      {
        "text": "Després, sobre aquesta bossa de resultats de membres, es fa la selecció i agregació final de l’equip."
      },
      {
        "text": "El mode Bossa d’equip amb totes les notes posa totes les notes individuals dels membres dins d’un mateix sac, sense separar primer per membre ni per exercici."
      },
      {
        "text": "En aquest mode, totes les notes competeixen en igualtat de condicions per formar la nota de l’equip."
      },
      {
        "text": "Aquest mode també pot limitar la contribució màxima de cada participant, per evitar que un sol membre aporti massa exercicis al resultat final."
      },
      {
        "text": "El mode Bossa d’equip per exercicis és útil quan vols donar un tractament específic a cada número d’exercici."
      },
      {
        "text": "En aquest cas, IA Score agrupa tots els primers exercicis dels membres, tots els segons exercicis, i així successivament."
      },
      {
        "text": "Cada bossa d’exercici es resol per separat, i després els resultats resolts passen a una bossa comuna per fer la selecció i agregació final de l’equip."
      }
    ],
    "actions": []
  },

  "classifications_scoring_apparatus_config": {
    "id": "classifications_scoring_apparatus_config",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "A Configuració dels aparells és on defineixes exactament quines notes entren al càlcul i com es converteixen en el resultat final."
      },
      {
        "text": "La idea és resoldre la bossa de notes candidates de cada unitat competitiva i obtenir una puntuació comparable amb la resta."
      },
      {
        "text": "El primer pas és seleccionar els camps de puntuació que vols tenir en compte."
      },
      {
        "text": "Aquests camps són els que has configurat dins de l’aparell, com poden ser diferents notes, penalitzacions o valors puntuables."
      },
      {
        "text": "Pots seleccionar un o diversos camps del llistat disponible."
      },
      {
        "text": "Si selecciones diversos camps, hauràs d’indicar com s’agreguen entre ells mitjançant l’agregació de camps."
      },
      {
        "text": "Per exemple, pots sumar diversos camps, fer-ne una mitjana o aplicar el criteri que correspongui segons la configuració de l’aparell."
      },
      {
        "text": "Un cop seleccionats els camps, IA Score construeix la bossa de notes candidates sobre la qual treballarà la classificació."
      },
      {
        "text": "En classificacions individuals i natives d’equip, la bossa és directa: conté els exercicis de la unitat competitiva que s’està classificant."
      },
      {
        "text": "En aquests casos, només cal decidir quins exercicis compten, com se seleccionen i com s’agreguen per obtenir el resultat."
      },
      {
        "text": "Per exemple, pots tenir en compte tots els exercicis, només els millors, només certs exercicis concrets o qualsevol altre criteri disponible."
      },
      {
        "text": "Després, aquestes notes seleccionades s’agreguen per obtenir la puntuació final de la inscripció o de l’equip."
      },
      {
        "text": "En classificacions d’equips derivades d’individual, la bossa és més complexa perquè està formada per notes de diversos membres de l’equip."
      },
      {
        "text": "En aquest cas, primer cal decidir com es tracten els membres: resolent-los individualment, posant totes les notes en una bossa comuna o separant-les per exercici."
      },
      {
        "text": "A partir d’aquest tractament, IA Score genera la bossa final de l’equip i aplica la selecció i agregació configurades."
      },
      {
        "text": "Així pots construir classificacions d’equip molt diferents: per suma de membres, millors contribucions, millors exercicis o altres combinacions."
      }
    ],
    "actions": []
  },

  "classifications_scoring_multiple_apparatus": {
    "id": "classifications_scoring_multiple_apparatus",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "Quan una classificació utilitza diversos aparells, IA Score aplica la configuració segons el tractament d’aparells que hagis escollit."
      },
      {
        "text": "Amb tractament individual per aparell, cada aparell es resol per separat."
      },
      {
        "text": "Això vol dir que IA Score selecciona i agrega les notes dins de cada aparell, obté un resultat per aparell i després fa una última selecció i agregació entre aparells."
      },
      {
        "text": "Aquest mode és útil quan vols conservar la identitat de cada aparell fins al final del càlcul."
      },
      {
        "text": "Amb tractament conjunt, les notes dels aparells seleccionats es posen en una bossa global."
      },
      {
        "text": "En aquest cas, IA Score no diferencia si una nota ve d’un aparell o d’un altre: totes les notes entren al càlcul en igualtat de condicions."
      },
      {
        "text": "Si la classificació és d’equips derivada d’individual, els modes de tractament de membres continuen existint."
      },
      {
        "text": "La diferència és que els membres es poden resoldre considerant els exercicis de tots els aparells seleccionats."
      },
      {
        "text": "En el mode Bossa d’equip amb totes les notes, la bossa pot incloure notes individuals de tots els membres i de tots els aparells."
      },
      {
        "text": "En el mode Bossa d’equip per exercicis, IA Score resol les bosses d’exercici pròpies de cada aparell abans de portar els resultats al sac comú final."
      },
      {
        "text": "Per això és important revisar el Resum del càlcul: t’ajuda a comprovar si els aparells s’estan tractant per separat o com una única bossa global."
      }
    ],
    "actions": []
  }
}