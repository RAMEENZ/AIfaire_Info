DEPT_CODE_TO_NAME: dict[str, str] = {
    "01": "Ain", "02": "Aisne", "03": "Allier", "04": "Alpes-de-Haute-Provence",
    "05": "Hautes-Alpes", "06": "Alpes-Maritimes", "07": "Ardèche", "08": "Ardennes",
    "09": "Ariège", "10": "Aube", "11": "Aude", "12": "Aveyron",
    "13": "Bouches-du-Rhône", "14": "Calvados", "15": "Cantal", "16": "Charente",
    "17": "Charente-Maritime", "18": "Cher", "19": "Corrèze", "2A": "Corse-du-Sud",
    "2B": "Haute-Corse", "21": "Côte-d'Or", "22": "Côtes-d'Armor", "23": "Creuse",
    "24": "Dordogne", "25": "Doubs", "26": "Drôme", "27": "Eure",
    "28": "Eure-et-Loir", "29": "Finistère", "30": "Gard", "31": "Haute-Garonne",
    "32": "Gers", "33": "Gironde", "34": "Hérault", "35": "Ille-et-Vilaine",
    "36": "Indre", "37": "Indre-et-Loire", "38": "Isère", "39": "Jura",
    "40": "Landes", "41": "Loir-et-Cher", "42": "Loire", "43": "Haute-Loire",
    "44": "Loire-Atlantique", "45": "Loiret", "46": "Lot", "47": "Lot-et-Garonne",
    "48": "Lozère", "49": "Maine-et-Loire", "50": "Manche", "51": "Marne",
    "52": "Haute-Marne", "53": "Mayenne", "54": "Meurthe-et-Moselle", "55": "Meuse",
    "56": "Morbihan", "57": "Moselle", "58": "Nièvre", "59": "Nord",
    "60": "Oise", "61": "Orne", "62": "Pas-de-Calais", "63": "Puy-de-Dôme",
    "64": "Pyrénées-Atlantiques", "65": "Hautes-Pyrénées", "66": "Pyrénées-Orientales",
    "67": "Bas-Rhin", "68": "Haut-Rhin", "69": "Rhône", "70": "Haute-Saône",
    "71": "Saône-et-Loire", "72": "Sarthe", "73": "Savoie", "74": "Haute-Savoie",
    "75": "Paris", "76": "Seine-Maritime", "77": "Seine-et-Marne", "78": "Yvelines",
    "79": "Deux-Sèvres", "80": "Somme", "81": "Tarn", "82": "Tarn-et-Garonne",
    "83": "Var", "84": "Vaucluse", "85": "Vendée", "86": "Vienne",
    "87": "Haute-Vienne", "88": "Vosges", "89": "Yonne", "90": "Territoire de Belfort",
    "91": "Essonne", "92": "Hauts-de-Seine", "93": "Seine-Saint-Denis",
    "94": "Val-de-Marne", "95": "Val-d'Oise",
    "971": "Guadeloupe", "972": "Martinique", "973": "Guyane",
    "974": "La Réunion", "976": "Mayotte",
}


# Centroïde (lat, lon) de chaque département, calculé comme la moyenne des
# centres de ses communes (source : geo.api.gouv.fr). Table statique et hors
# ligne : l'API geo.api.gouv.fr ne renvoie plus le champ `centre` en réponse
# inline, ce qui faisait échouer le géocodage des vigilances Météo-France (tous
# les départements retombaient en "national", sans pastille sur la carte). Un
# centroïde départemental est une constante géographique : pas besoin de réseau.
DEPT_CENTROIDS: dict[str, tuple[float, float]] = {
    "01": (46.0899, 5.3201),        # Ain
    "02": (49.5554, 3.5302),        # Aisne
    "03": (46.3518, 3.1835),        # Allier
    "04": (44.0751, 6.1451),        # Alpes-de-Haute-Provence
    "05": (44.5794, 6.1319),        # Hautes-Alpes
    "06": (43.8478, 7.1058),        # Alpes-Maritimes
    "07": (44.783, 4.4573),         # Ardèche
    "08": (49.6147, 4.6544),        # Ardennes
    "09": (42.9682, 1.5247),        # Ariège
    "10": (48.3015, 4.1841),        # Aube
    "11": (43.1205, 2.3339),        # Aude
    "12": (44.2874, 2.5989),        # Aveyron
    "13": (43.5579, 5.2297),        # Bouches-du-Rhône
    "14": (49.1516, -0.3242),       # Calvados
    "15": (45.0472, 2.6539),        # Cantal
    "16": (45.7004, 0.1514),        # Charente
    "17": (45.7738, -0.6495),       # Charente-Maritime
    "18": (47.0333, 2.5216),        # Cher
    "19": (45.3149, 1.8436),        # Corrèze
    "21": (47.3802, 4.7907),        # Côte-d'Or
    "22": (48.4836, -2.8551),       # Côtes-d'Armor
    "23": (46.0923, 2.0334),        # Creuse
    "24": (45.0635, 0.7424),        # Dordogne
    "25": (47.2275, 6.3671),        # Doubs
    "26": (44.694, 5.1332),         # Drôme
    "27": (49.1412, 1.0036),        # Eure
    "28": (48.4389, 1.39),          # Eure-et-Loir
    "29": (48.294, -4.1351),        # Finistère
    "2A": (41.9023, 8.9493),        # Corse-du-Sud
    "2B": (42.4386, 9.28),          # Haute-Corse
    "30": (44.0235, 4.1973),        # Gard
    "31": (43.3346, 1.1378),        # Haute-Garonne
    "32": (43.6627, 0.462),         # Gers
    "33": (44.817, -0.3447),        # Gironde
    "34": (43.5876, 3.4228),        # Hérault
    "35": (48.1882, -1.6349),       # Ille-et-Vilaine
    "36": (46.7705, 1.6106),        # Indre
    "37": (47.2607, 0.6648),        # Indre-et-Loire
    "38": (45.3182, 5.4878),        # Isère
    "39": (46.7683, 5.6756),        # Jura
    "40": (43.81, -0.7348),         # Landes
    "41": (47.6483, 1.3068),        # Loir-et-Cher
    "42": (45.7221, 4.1965),        # Loire
    "43": (45.1401, 3.7618),        # Haute-Loire
    "44": (47.3381, -1.6804),       # Loire-Atlantique
    "45": (47.9622, 2.341),         # Loiret
    "46": (44.6449, 1.633),         # Lot
    "47": (44.3916, 0.4809),        # Lot-et-Garonne
    "48": (44.5502, 3.4896),        # Lozère
    "49": (47.3796, -0.4871),       # Maine-et-Loire
    "50": (49.1076, -1.3446),       # Manche
    "51": (48.9614, 4.1937),        # Marne
    "52": (48.1111, 5.2569),        # Haute-Marne
    "53": (48.1454, -0.6711),       # Mayenne
    "54": (48.7823, 6.1682),        # Meurthe-et-Moselle
    "55": (49.0167, 5.3826),        # Meuse
    "56": (47.8101, -2.7807),       # Morbihan
    "57": (49.0468, 6.6223),        # Moselle
    "58": (47.1441, 3.4907),        # Nièvre
    "59": (50.4173, 3.2592),        # Nord
    "60": (49.4298, 2.4218),        # Oise
    "61": (48.6399, 0.1028),        # Orne
    "62": (50.4594, 2.3379),        # Pas-de-Calais
    "63": (45.7314, 3.1734),        # Puy-de-Dôme
    "64": (43.324, -0.6631),        # Pyrénées-Atlantiques
    "65": (43.1361, 0.2095),        # Hautes-Pyrénées
    "66": (42.6075, 2.557),         # Pyrénées-Orientales
    "67": (48.6762, 7.5462),        # Bas-Rhin
    "68": (47.8007, 7.2742),        # Haut-Rhin
    "69": (45.8539, 4.6639),        # Rhône
    "70": (47.6273, 6.1003),        # Haute-Saône
    "71": (46.6179, 4.6221),        # Saône-et-Loire
    "72": (48.0412, 0.2257),        # Sarthe
    "73": (45.5427, 6.1842),        # Savoie
    "74": (46.0704, 6.2975),        # Haute-Savoie
    "75": (48.8589, 2.347),         # Paris
    "76": (49.666, 0.9833),         # Seine-Maritime
    "77": (48.6624, 2.916),         # Seine-et-Marne
    "78": (48.8527, 1.8396),        # Yvelines
    "79": (46.5013, -0.3049),       # Deux-Sèvres
    "80": (49.9407, 2.3105),        # Somme
    "81": (43.8035, 2.1128),        # Tarn
    "82": (44.0628, 1.2157),        # Tarn-et-Garonne
    "83": (43.4315, 6.2179),        # Var
    "84": (44.0117, 5.1626),        # Vaucluse
    "85": (46.6513, -1.2544),       # Vendée
    "86": (46.6085, 0.4146),        # Vienne
    "87": (45.8863, 1.2378),        # Haute-Vienne
    "88": (48.2336, 6.322),         # Vosges
    "89": (47.8519, 3.6098),        # Yonne
    "90": (47.6252, 6.9332),        # Territoire de Belfort
    "91": (48.5507, 2.2625),        # Essonne
    "92": (48.8447, 2.2531),        # Hauts-de-Seine
    "93": (48.9104, 2.4666),        # Seine-Saint-Denis
    "94": (48.7829, 2.4569),        # Val-de-Marne
    "95": (49.0764, 2.1496),        # Val-d'Oise
    "971": (16.1547, -61.5487),     # Guadeloupe
    "972": (14.6622, -61.0382),     # Martinique
    "973": (4.5221, -53.0446),      # Guyane
    "974": (-21.1273, 55.5083),     # La Réunion
    "976": (-12.8176, 45.1476),     # Mayotte
}
