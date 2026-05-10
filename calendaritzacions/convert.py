import sys
import pandas as pd
import os

def xlsx_to_csv(xlsx_path):
    if not os.path.isfile(xlsx_path):
        print(f"El archivo {xlsx_path} no existe.")
        return

    csv_path = os.path.splitext(xlsx_path)[0] + ".csv"
    try:
        df = pd.read_excel(xlsx_path)
        df.to_csv(csv_path, index=False)
        print(f"Archivo convertido: {csv_path}")
    except Exception as e:
        print(f"Error al convertir el archivo: {e}")
    return csv_path

if __name__ == "__main__":
    path = "./csv/LlistatGlobal.xlsx"
    xlsx_to_csv(path)