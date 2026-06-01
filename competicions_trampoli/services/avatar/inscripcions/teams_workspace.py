AVATAR_MESSAGES = {
  "teams_workspace": {
    "id": "teams_workspace",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
      {
        "text": "Aquest és l’espai de treball d’Equips. Aquí pots crear i gestionar equips a partir de les inscripcions de la competició."
      },
      {
        "text": "El workspace es divideix en 4 parts: l’univers de candidats, les accions sobre la selecció, els equips actuals i el detall amb previsualització."
      },
      {
        "text": "A l’Univers de candidats veuràs totes les inscripcions disponibles. Pots cercar-les amb la barra de cerca i aplicar filtres per treballar només amb les que t’interessin."
      },
      {
        "text": "Amb el botó Afegir les inscripcions filtrades, passaràs aquests candidats a la selecció. Amb Netejar, buidaràs completament la selecció."
      },
      {
        "text": "La selecció és el conjunt d’inscripcions sobre el qual s’aplicaran les accions de creació d’equips."
      },
      {
        "text": "En aquest mateix apartat també pots escollir el context de treball. Els equips que creïs viuran dins d’aquest context."
      },
      {
        "text": "Des de Gestionar context pots indicar en quins aparells d’equip de la competició aquest equip actuarà com a unitat competitiva."
      },
      {
        "text": "A Accions sobre la selecció pots crear nous equips dins del context actual."
      },
      {
        "text": "Les estratègies de creació et permeten generar equips ràpidament: pots crear un nombre concret d’equips, equips d’una mida determinada o equips equilibrats dins d’una forquilla."
      },
      {
        "text": "Abans de confirmar la creació, pots previsualitzar el resultat per revisar com quedarien els equips."
      },
      {
        "text": "També tens la creació massiva per buckets, que permet dividir la selecció segons valors de columnes importades de l’Excel."
      },
      {
        "text": "Quan fas servir buckets, IA Score separa les inscripcions en grups segons els valors diferents de les columnnes seleccionades."
      },
      {
        "text": "A Equips actuals trobaràs el llistat d’equips ja creats dins del context. Pots cercar-los i filtrar-los per localitzar ràpidament els que necessitis."
      },
      {
        "text": "Finalment, a Detall i previsualització podràs veure els membres de l’equip seleccionat, aplicar accions d’edició i revisar previsualitzacions abans de confirmar canvis."
      }
    ],
    "actions": []
  }
}


#CONTEXT
AVATAR_MESSAGES = {
  "teams_workspace_context": {
    "id": "teams_workspace_context",
    "avatar": "avatar/explaining/explaining_2.png",
    "variant": "info",
    "steps": [
    {
    "text": "Un context és l’espai on IA Score interpreta quins equips existeixen i per a què serveixen dins de la competició."
    },
    {
    "text": "Dins d’un mateix context, una inscripció només pot formar part d’un equip. Això evita contradiccions quan IA Score ha de calcular resultats o organitzar la participació."
    },
    {
    "text": "Si una mateixa inscripció ha de formar part d’equips diferents, cal crear contextos diferents. Precisament per això existeixen els contextos."
    },
    {
    "text": "Per exemple, una inscripció podria formar part d’un equip per a una classificació conjunta, i d’un altre equip diferent per competir en un aparell d’equip."
    },
    {
    "text": "Els contextos poden servir per crear classificacions d’equip derivades de notes individuals, agrupant resultats de diverses inscripcions."
    },
    {
    "text": "També poden servir per definir un conjunt d’inscripcions que actuarà com una sola unitat competitiva en un aparell d’equip, com parelles, trios o conjunts."
    },
    {
    "text": "Quan gestiones el context, pots indicar en quins aparells d’equip aquest conjunt competirà com a equip i no com a inscripcions individuals separades."
    }
    ],
    "actions": []
    }
}