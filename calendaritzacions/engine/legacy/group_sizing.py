"""Group sizing for the legacy assignment engine."""

from __future__ import annotations

def crear_grups_equilibrats(num_equips, max_grup=8, min_grup=6):
    '''
        Calcula el número de grups i el nombre d'equips per grup.
    '''

    # Si hi ha menys equips que el mínim, tot en un sol grup
    if num_equips < min_grup:
        return [num_equips]
    # Calcula quants equips per grup (mides equilibrades entre min i max)
    num_grups = max(1, (num_equips + max_grup - 1) // max_grup)
    while True:
        base = num_equips // num_grups
        sobra = num_equips % num_grups
        grups = [base + 1 if i < sobra else base for i in range(num_grups)]
        # Acceptem si complim el màxim; el mínim és desitjable però no forçat
        if max(grups) <= max_grup:
            return grups
        num_grups += 1


