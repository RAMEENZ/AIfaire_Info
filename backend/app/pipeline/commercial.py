"""Détection des contenus marchands dans les flux de presse.

Certains flux mêlent à l'actualité des articles d'affiliation — bons plans,
promotions, comparatifs de prix — qui n'ont rien à faire sur une carte
d'information géolocalisée : ils sont sans lieu, sans gravité, et poussent des
achats. Relevés en production le 03/08/2026 : « Ce ventilateur de plafond
Philips est 40 € moins cher », « Le meilleur prix sur le pack de 3 SSD ».

Le filtre est volontairement PRUDENT. Écarter un vrai article coûte une
information perdue, en laisser passer un ne coûte qu'une ligne de bruit : on
exige donc DEUX signaux concordants, un prix et un vocabulaire d'offre. « Le
carburant 10 centimes moins cher » (vraie information) ne comporte pas de prix
au format commerçant et passe donc sans encombre.
"""
import re

# Prix au format commerçant : « 129,91 € », « 40 € », « 19.99€ », « 15 euros ».
# Pas de `\b` final : « € » n'est pas un caractère de mot, la limite ne pourrait
# jamais s'établir devant l'espace qui suit et « 199,99 € au lieu de » échappait
# à la détection.
_PRIX_RE = re.compile(r"\b\d{1,4}(?:[.,]\d{1,2})?\s?(?:€|euros?\b)", re.IGNORECASE)

# Réduction chiffrée : « -30 % », « 30% de remise ».
_REMISE_RE = re.compile(r"-\s?\d{1,2}\s?%|\b\d{1,2}\s?%\s+(?:de\s+)?(?:remise|réduction)\b", re.IGNORECASE)

# Vocabulaire de l'offre commerciale. Chaque terme est un signal FAIBLE : pris
# isolément, plusieurs figurent dans de vrais articles (« les soldes démarrent
# lundi » est une information économique légitime).
_OFFRE_RE = re.compile(
    r"\b(bon plan|bons plans|code promo|prix cassé|prix barré|"
    r"meilleur prix|à prix réduit|profitez-en|dernier jour pour|"
    r"french days|black friday|cyber monday|ventes? flash|"
    r"en promotion|notre sélection de|on a trouvé|à saisir|moins cher|"
    r"au lieu de|remise immédiate|livraison offerte)\b",
    re.IGNORECASE,
)

# Marchands cités dans le titre : signal fort d'affiliation.
_MARCHAND_RE = re.compile(
    r"\b(amazon|cdiscount|fnac|darty|boulanger|rakuten|aliexpress|"
    r"pc componentes|pccomponentes|leclerc high-?tech|e\.?leclerc)\b",
    re.IGNORECASE,
)


def is_commercial(titre: str, description: str = "") -> bool:
    """Le titre relève-t-il d'une offre commerciale plutôt que d'une information ?

    N'examine que le TITRE pour les signaux d'offre : une mention de prix dans
    le corps d'un article est banale (chiffrage d'un budget, montant d'une
    amende), alors qu'un titre construit autour d'un prix vend quelque chose.
    """
    if not titre:
        return False

    a_un_prix = bool(_PRIX_RE.search(titre)) or bool(_REMISE_RE.search(titre))
    marqueurs_offre = {m.group(0).lower() for m in _OFFRE_RE.finditer(titre)}
    a_une_offre = bool(marqueurs_offre)
    a_un_marchand = bool(_MARCHAND_RE.search(titre))

    # Un prix seul ne suffit pas (« Une amende de 135 € pour les contrevenants »),
    # ni un mot d'offre seul (« Les soldes démarrent lundi »). Il faut la
    # conjonction — ou la mention d'un marchand, qui à elle seule ne laisse
    # guère de doute sur la nature du texte.
    # Deux marqueurs d'offre DISTINCTS valent la conjonction prix + offre :
    # « French days : notre sélection à prix cassé » ne cite aucun montant mais
    # ne laisse aucun doute.
    return (
        (a_un_prix and (a_une_offre or a_un_marchand))
        or (a_un_marchand and a_une_offre)
        or len(marqueurs_offre) >= 2
    )
