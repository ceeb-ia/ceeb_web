import pandas as pd


def load_modalitat_map(path="map_modalitat_nom.csv"):
    return pd.read_csv(path, delimiter=";")
