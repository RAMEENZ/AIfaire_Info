import asyncio
import html as _html
import re as _re
import unicodedata
import feedparser
import httpx
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from app.config import settings
from app.connectors.base import BaseConnector

# Flux RSS accessibles depuis un serveur.
# Les PQR peuvent bloquer les IPs de datacenter (403) mais fonctionnent
# généralement depuis une VM domestique ou un VPS résidentiel.
RSS_FEEDS: list[dict[str, Any]] = [
    # ── Flux ajoutes (presse nationale + Outre-mer) ──
    {"name": "Le Journal du Dimanche", "url": "https://www.lejdd.fr/rss.xml", "region": None},
    {"name": "L'Express", "url": "https://www.lexpress.fr/rss/alaune.xml", "region": None},
    {"name": "Slate", "url": "https://www.slate.fr/rss.xml", "region": None},
    {"name": "Mediapart", "url": "https://www.mediapart.fr/articles/feed", "region": None},
    {"name": "Les Inrockuptibles", "url": "https://www.lesinrocks.com/feed/", "region": None},
    {"name": "Télérama", "url": "https://www.telerama.fr/rss/une.xml", "region": None},
    {"name": "France Guyane", "url": "https://www.franceguyane.fr/actualite/vielocale/rss.xml", "region": "Guyane"},
    # ── ACTUALITÉS NATIONALES — GÉNÉRALISTES ─────────────────────────────────
    {"name": "France Info",         "url": "https://www.francetvinfo.fr/titres.rss",               "region": None},
    {"name": "France 24",           "url": "https://www.france24.com/fr/rss",                       "region": None},
    {"name": "France Inter",        "url": "https://www.radiofrance.fr/franceinter/rss",             "region": None},
    {"name": "RFI",                 "url": "https://www.rfi.fr/fr/rss",                              "region": None},
    {"name": "Euronews France",     "url": "https://fr.euronews.com/rss",                            "region": None},
    {"name": "CNews",               "url": "https://www.cnews.fr/rss.xml",                           "region": None},
    {"name": "20 Minutes",          "url": "https://www.20minutes.fr/rss/actu-france.xml",           "region": None},
    {"name": "Le Monde",            "url": "https://www.lemonde.fr/rss/une.xml",                     "region": None},
    {"name": "Le Figaro",           "url": "https://plus.lefigaro.fr/page/flux-rss",                 "region": None},
    {"name": "Libération",          "url": "https://www.liberation.fr/arc/outboundfeeds/rss-all/",  "region": None},
    {"name": "L'Humanité",          "url": "https://www.humanite.fr/feed/",                          "region": None},
    {"name": "Vie Publique",        "url": "https://www.vie-publique.fr/rss/tous",                   "region": None},
    {"name": "Google News France",  "url": "https://news.google.com/rss/search?q=france+actualit%C3%A9&hl=fr&gl=FR&ceid=FR:fr",         "region": None},
    {"name": "Google News Régions", "url": "https://news.google.com/rss/search?q=r%C3%A9gion+commune+france&hl=fr&gl=FR&ceid=FR:fr",    "region": None},

    # ── ACTUALITÉS NATIONALES — AUDIOVISUEL ──────────────────────────────────
    {"name": "BFM TV",              "url": "https://www.bfmtv.com/rss/news-24-7/",                  "region": None},

    # ── ACTUALITÉS ÉCONOMIQUES ET TECH ───────────────────────────────────────
    {"name": "Les Échos",           "url": "https://www.lesechos.fr/rss",                           "region": None},
    {"name": "Le Journal du Net",   "url": "https://www.journaldunet.com/rss/",                     "region": None},
    {"name": "L'Usine Nouvelle",    "url": "https://www.usinenouvelle.com/rss/",                    "region": None},

    # ── SOURCES GOUVERNEMENTALES ET OFFICIELLES ───────────────────────────────
    {"name": "Gouvernement.fr",       "url": "https://www.gouvernement.fr/rss",                     "region": None},
    {"name": "Santé Publique France", "url": "https://www.santepubliquefrance.fr/rss.xml",           "region": None},
    {"name": "Ministère Intérieur",   "url": "https://www.interieur.gouv.fr/rss.xml",               "region": None},

    # ── ACTUALITÉS RÉGIONALES — RÉSEAU ACTU.FR ──────────────────────────────
    {"name": "Actu Bretagne",                "url": "https://actu.fr/bretagne/rss.xml",                      "region": "Bretagne"},
    {"name": "Actu Normandie",               "url": "https://actu.fr/normandie/rss.xml",                     "region": "Normandie"},
    {"name": "Actu Île-de-France",           "url": "https://actu.fr/ile-de-france/rss.xml",                 "region": "Île-de-France"},
    {"name": "Actu Occitanie",               "url": "https://actu.fr/occitanie/rss.xml",                     "region": "Occitanie"},
    {"name": "Actu Pays de la Loire",        "url": "https://actu.fr/pays-de-la-loire/rss.xml",              "region": "Pays de la Loire"},
    {"name": "Actu Hauts-de-France",         "url": "https://actu.fr/hauts-de-france/rss.xml",               "region": "Hauts-de-France"},
    {"name": "Actu Auvergne-Rhône-Alpes",    "url": "https://actu.fr/auvergne-rhone-alpes/rss.xml",          "region": "Auvergne-Rhône-Alpes"},
    {"name": "Actu Grand Est",               "url": "https://actu.fr/grand-est/rss.xml",                     "region": "Grand Est"},
    {"name": "Actu Nouvelle-Aquitaine",      "url": "https://actu.fr/nouvelle-aquitaine/rss.xml",            "region": "Nouvelle-Aquitaine"},
    {"name": "Actu Centre-Val de Loire",     "url": "https://actu.fr/centre-val-de-loire/rss.xml",           "region": "Centre-Val de Loire"},
    {"name": "Actu Bourgogne-Franche-Comté", "url": "https://actu.fr/bourgogne-franche-comte/rss.xml",       "region": "Bourgogne-Franche-Comté"},
    {"name": "Actu PACA",                    "url": "https://actu.fr/provence-alpes-cote-d-azur/rss.xml",    "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Actu Corse",                   "url": "https://actu.fr/corse/rss.xml",                          "region": "Corse"},

    # ── DOM-TOM — LA 1ÈRE (France Télévisions) ───────────────────────────────
    {"name": "La 1ère Guadeloupe",        "url": "https://la1ere.francetvinfo.fr/guadeloupe/rss",               "region": "Guadeloupe"},
    {"name": "La 1ère Martinique",        "url": "https://la1ere.francetvinfo.fr/martinique/rss",               "region": "Martinique"},
    {"name": "La 1ère Guyane",            "url": "https://la1ere.francetvinfo.fr/guyane/rss",                   "region": "Guyane"},
    {"name": "La 1ère Réunion",           "url": "https://la1ere.francetvinfo.fr/reunion/rss",                  "region": "La Réunion"},
    {"name": "La 1ère Mayotte",           "url": "https://la1ere.francetvinfo.fr/mayotte/rss",                  "region": "Mayotte"},
    {"name": "La 1ère Nouvelle-Calédonie","url": "https://la1ere.francetvinfo.fr/nouvellecaledonie/rss",        "region": "Nouvelle-Calédonie"},
    {"name": "La 1ère Polynésie",         "url": "https://la1ere.francetvinfo.fr/polynesie/rss",                "region": "Polynésie française"},
    {"name": "La 1ère St-Pierre",         "url": "https://la1ere.franceinfo.fr/saintpierremiquelon/actu/rss",   "region": "Saint-Pierre-et-Miquelon"},
    {"name": "La 1ère St-Martin",         "url": "https://la1ere.francetvinfo.fr/saint-martin/rss",             "region": "Saint-Martin"},

    # ── GRANDS QUOTIDIENS RÉGIONAUX (PQR) ────────────────────────────────────
    {"name": "Ouest-France",                  "url": "https://www.ouest-france.fr/rss/une",                "region": None},
    {"name": "Le Parisien",                   "url": "https://feeds.leparisien.fr/leparisien/rss",         "region": "Île-de-France"},
    {"name": "Sud Ouest",                     "url": "https://www.sudouest.fr/rss.xml",                    "region": "Nouvelle-Aquitaine"},
    {"name": "La Provence",                   "url": "https://www.laprovence.com/rss/une.xml",             "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Nice-Matin",                    "url": "https://www.nicematin.com/rss",                      "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "La Dépêche du Midi",            "url": "https://www.ladepeche.fr/rss.xml",                   "region": "Occitanie"},
    {"name": "Midi Libre",                    "url": "https://www.midilibre.fr/rss.xml",                   "region": "Occitanie"},
    {"name": "L'Indépendant",                 "url": "https://www.lindependant.fr/rss.xml",                "region": "Occitanie"},
    {"name": "Dernières Nouvelles d'Alsace",  "url": "https://www.dna.fr/rss",                             "region": "Grand Est"},
    {"name": "L'Alsace",                      "url": "https://www.lalsace.fr/rss",                         "region": "Grand Est"},
    {"name": "L'Est Républicain",             "url": "https://www.estrepublicain.fr/rss",                  "region": "Grand Est"},
    {"name": "Républicain Lorrain",           "url": "https://www.republicain-lorrain.fr/rss",             "region": "Grand Est"},
    {"name": "Le Progrès",                    "url": "https://www.leprogres.fr/rss",                       "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Dauphiné Libéré",            "url": "https://www.ledauphine.com/rss",                     "region": "Auvergne-Rhône-Alpes"},
    # ── 20MINUTES ─────────────────────────────────────────────────────────────────
    {"name": "20minutes : Alpes-Maritimes", "url": "https://www.20minutes.fr/feeds/rss-alpes-maritimes.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "20minutes : Auvergne-Rhône-Alpes", "url": "https://www.20minutes.fr/feeds/rss-auvergne-rhone-alpes.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "20minutes : Bordeaux", "url": "https://www.20minutes.fr/feeds/rss-bordeaux.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "20minutes : Bourgogne-Franche-Comté", "url": "https://www.20minutes.fr/feeds/rss-bourgogne-franche-comte.xml", "region": "Bourgogne-Franche-Comté"},
    {"name": "20minutes : Bretagne", "url": "https://www.20minutes.fr/feeds/rss-bretagne.xml", "region": "Bretagne"},
    {"name": "20minutes : Corse", "url": "https://www.20minutes.fr/feeds/rss-corse.xml", "region": "Corse"},
    {"name": "20minutes : Grand Est", "url": "https://www.20minutes.fr/feeds/rss-grand-est.xml", "region": "Grand Est"},
    {"name": "20minutes : Hérault", "url": "https://www.20minutes.fr/feeds/rss-herault.xml", "region": "Occitanie"},
    {"name": "20minutes : Lille", "url": "https://www.20minutes.fr/feeds/rss-lille.xml", "region": "Hauts-de-France"},
    {"name": "20minutes : Lyon", "url": "https://www.20minutes.fr/feeds/rss-lyon.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "20minutes : Marseille", "url": "https://www.20minutes.fr/feeds/rss-marseille.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "20minutes : Montpellier", "url": "https://www.20minutes.fr/feeds/rss-montpellier.xml", "region": "Occitanie"},
    {"name": "20minutes : Nantes", "url": "https://www.20minutes.fr/feeds/rss-nantes.xml", "region": "Pays de la Loire"},
    {"name": "20minutes : Nice", "url": "https://www.20minutes.fr/feeds/rss-nice.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "20minutes : Normandie", "url": "https://www.20minutes.fr/feeds/rss-normandie.xml", "region": "Normandie"},
    {"name": "20minutes : Nouvelle-Aquitaine", "url": "https://www.20minutes.fr/feeds/rss-nouvelle-aquitaine.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "20minutes : Occitanie", "url": "https://www.20minutes.fr/feeds/rss-occitanie.xml", "region": "Occitanie"},
    {"name": "20minutes : Paris", "url": "https://www.20minutes.fr/feeds/rss-paris.xml", "region": "Île-de-France"},
    {"name": "20minutes : Provence-Alpes-Côte d’Azur", "url": "https://www.20minutes.fr/feeds/rss-provence-alpes-cote-azur.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "20minutes : Rennes", "url": "https://www.20minutes.fr/feeds/rss-rennes.xml", "region": "Bretagne"},
    {"name": "20minutes : Toulouse", "url": "https://www.20minutes.fr/feeds/rss-toulouse.xml", "region": "Occitanie"},
    {"name": "20minutes : Île-de-France", "url": "https://www.20minutes.fr/feeds/rss-ile-de-france.xml", "region": "Île-de-France"},

    # ── 37 DEGRÉS MAG ─────────────────────────────────────────────────────────────────
    {"name": "37 degrés mag", "url": "https://www.37degres-mag.fr/feed/", "region": "Centre-Val de Loire"},

    # ── 76ACTU ─────────────────────────────────────────────────────────────────
    {"name": "76actu", "url": "https://actu.fr/76actu/rss.xml", "region": "Normandie"},

    # ── 78ACTU ─────────────────────────────────────────────────────────────────
    {"name": "78actu", "url": "https://actu.fr/78actu/rss.xml", "region": "Île-de-France"},

    # ── 7A LIMOGES ─────────────────────────────────────────────────────────────────
    {"name": "7A Limoges", "url": "https://www.7alimoges.tv/xml/syndication.rss", "region": "Nouvelle-Aquitaine"},

    # ── ACTU 44 ─────────────────────────────────────────────────────────────────
    {"name": "Actu 44", "url": "https://www.actu44.fr/feed/", "region": "Pays de la Loire"},

    # ── ACTU.FR ─────────────────────────────────────────────────────────────────
    {"name": "Actu.fr : Bordeaux", "url": "https://actu.fr/bordeaux/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Actu.fr : Béarn", "url": "https://actu.fr/bearn/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Actu.fr : Chartres", "url": "https://actu.fr/chartres/rss.xml", "region": "Centre-Val de Loire"},
    {"name": "Actu.fr : Dijon", "url": "https://actu.fr/dijon/rss.xml", "region": "Bourgogne-Franche-Comté"},
    {"name": "Actu.fr : Essonne", "url": "https://actu.fr/essonne/rss.xml", "region": "Île-de-France"},
    {"name": "Actu.fr : Grenoble", "url": "https://actu.fr/grenoble/rss.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Actu.fr : Hauts-de-Seine", "url": "https://actu.fr/hauts-de-seine/rss.xml", "region": "Île-de-France"},
    {"name": "Actu.fr : La Rochelle", "url": "https://actu.fr/la-rochelle/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Actu.fr : Le Mans", "url": "https://actu.fr/le-mans/rss.xml", "region": "Pays de la Loire"},
    {"name": "Actu.fr : Lille", "url": "https://actu.fr/lille/rss.xml", "region": "Hauts-de-France"},
    {"name": "Actu.fr : Lorraine", "url": "https://actu.fr/lorraine/rss.xml", "region": "Grand Est"},
    {"name": "Actu.fr : Lot", "url": "https://actu.fr/lot/rss.xml", "region": "Occitanie"},
    {"name": "Actu.fr : Lyon", "url": "https://actu.fr/lyon/rss.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Actu.fr : Marseille", "url": "https://actu.fr/marseille/rss.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Actu.fr : Morbihan", "url": "https://actu.fr/morbihan/rss.xml", "region": "Bretagne"},
    {"name": "Actu.fr : Nantes", "url": "https://actu.fr/nantes/rss.xml", "region": "Pays de la Loire"},
    {"name": "Actu.fr : Nice", "url": "https://actu.fr/nice/rss.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Actu.fr : Oise", "url": "https://actu.fr/oise/rss.xml", "region": "Hauts-de-France"},
    {"name": "Actu.fr : Orléans", "url": "https://actu.fr/orleans/rss.xml", "region": "Centre-Val de Loire"},
    {"name": "Actu.fr : Paris", "url": "https://actu.fr/paris/rss.xml", "region": "Île-de-France"},
    {"name": "Actu.fr : Pas-de-Calais", "url": "https://actu.fr/pas-de-calais/rss.xml", "region": "Hauts-de-France"},
    {"name": "Actu.fr : Pays Basque", "url": "https://actu.fr/pays-basque/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Actu.fr : Perpignan", "url": "https://actu.fr/perpignan/rss.xml", "region": "Occitanie"},
    {"name": "Actu.fr : Rennes", "url": "https://actu.fr/rennes/rss.xml", "region": "Bretagne"},
    {"name": "Actu.fr : Saint Étienne", "url": "https://actu.fr/saint-etienne/rss.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Actu.fr : Seine-Saint-Denis", "url": "https://actu.fr/seine-saint-denis/rss.xml", "region": "Île-de-France"},
    {"name": "Actu.fr : Strasbourg", "url": "https://actu.fr/strasbourg/rss.xml", "region": "Grand Est"},
    {"name": "Actu.fr : Toulon", "url": "https://actu.fr/toulon/rss.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Actu.fr : Toulouse", "url": "https://actu.fr/toulouse/rss.xml", "region": "Occitanie"},
    {"name": "Actu.fr : Val-de-Marne", "url": "https://actu.fr/val-de-marne/rss.xml", "region": "Île-de-France"},
    {"name": "Actu.fr : Vaucluse", "url": "https://actu.fr/vaucluse/rss.xml", "region": "Provence-Alpes-Côte d'Azur"},

    # ── AISNE NOUVELLE ─────────────────────────────────────────────────────────────────
    {"name": "Aisne nouvelle", "url": "https://www.aisnenouvelle.fr/rss.xml", "region": "Hauts-de-France"},

    # ── ALTA FREQUENZA ─────────────────────────────────────────────────────────────────
    {"name": "Alta Frequenza : audio", "url": "https://www.alta-frequenza.corsica/rss/feed/actu", "region": "Corse"},

    # ── ANGERS VILLEACTU ─────────────────────────────────────────────────────────────────
    {"name": "Angers VilleActu", "url": "https://www.angers.villactu.fr/feed/", "region": "Pays de la Loire"},

    # ── ANNUDÀ ─────────────────────────────────────────────────────────────────
    {"name": "Annudà : ViaStella", "url": "http://flussi.annuda.saynete.net/corse_viastella_rss.xml", "region": "Corse"},
    {"name": "Annudà : presse", "url": "http://flussi.annuda.saynete.net/corse_presse_rss.xml", "region": "Corse"},

    # ── AQUITAINE ONLINE ─────────────────────────────────────────────────────────────────
    {"name": "Aquitaine online : Dordogne", "url": "https://www.aquitaineonline.com/actualites-en-aquitaine/dordogne/feed/rss/", "region": "Nouvelle-Aquitaine"},
    {"name": "Aquitaine online : Euskal Herria", "url": "https://www.aquitaineonline.com/actualites-en-aquitaine/euskal-herria/feed/rss/", "region": "Nouvelle-Aquitaine"},
    {"name": "Aquitaine online : Gironde", "url": "https://www.aquitaineonline.com/actualites-en-aquitaine/gironde/feed/rss/", "region": "Nouvelle-Aquitaine"},
    {"name": "Aquitaine online : Landes", "url": "https://www.aquitaineonline.com/actualites-en-aquitaine/landes/feed/rss/", "region": "Nouvelle-Aquitaine"},
    {"name": "Aquitaine online : Occitanie", "url": "https://www.aquitaineonline.com/actualites-en-aquitaine/occitanie/feed/rss/", "region": "Occitanie"},
    {"name": "Aquitaine online : Poitou-Charentes", "url": "https://www.aquitaineonline.com/actualites-en-aquitaine/poitou-charentes/feed/rss/", "region": "Nouvelle-Aquitaine"},
    {"name": "Aquitaine online : Sud-Ouest", "url": "https://www.aquitaineonline.com/actualites-en-aquitaine/sud-ouest/feed/rss/", "region": "Nouvelle-Aquitaine"},

    # ── AUDE TRIBUNE ─────────────────────────────────────────────────────────────────
    {"name": "Aude Tribune : Narbonne", "url": "https://echo-des-tribunes.com/aude-tribune/narbonne/feed", "region": "Occitanie"},

    # ── BFM ─────────────────────────────────────────────────────────────────
    {"name": "BFM : Bastia", "url": "https://www.bfmtv.com/rss/bastia/", "region": "Corse"},
    {"name": "BFM : Bordeaux", "url": "https://www.bfmtv.com/rss/bordeaux/", "region": "Nouvelle-Aquitaine"},
    {"name": "BFM : Brest", "url": "https://www.bfmtv.com/rss/brest/", "region": "Bretagne"},
    {"name": "BFM : Clermont-Ferrand", "url": "https://www.bfmtv.com/rss/clermont-ferrand/", "region": "Auvergne-Rhône-Alpes"},
    {"name": "BFM : Côte d’Azur", "url": "https://www.bfmtv.com/rss/cote-d-azur/", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "BFM : Grand Lille", "url": "https://www.bfmtv.com/rss/grand-lille/", "region": "Hauts-de-France"},
    {"name": "BFM : Grand Littoral", "url": "https://www.bfmtv.com/rss/grand-littoral/", "region": "Hauts-de-France"},
    {"name": "BFM : Lyon", "url": "https://www.bfmtv.com/rss/lyon/", "region": "Auvergne-Rhône-Alpes"},
    {"name": "BFM : Marseille", "url": "https://www.bfmtv.com/rss/marseille/", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "BFM : Montpellier", "url": "https://www.bfmtv.com/rss/montpellier/", "region": "Occitanie"},
    {"name": "BFM : Nancy", "url": "https://www.bfmtv.com/rss/nancy/", "region": "Grand Est"},
    {"name": "BFM : Normandie", "url": "https://www.bfmtv.com/rss/normandie/", "region": "Normandie"},
    {"name": "BFM : Paris", "url": "https://www.bfmtv.com/rss/paris/", "region": "Île-de-France"},
    {"name": "BFM : Rennes", "url": "https://www.bfmtv.com/rss/rennes/", "region": "Bretagne"},
    {"name": "BFM : Saint Étienne", "url": "https://www.bfmtv.com/rss/saint-etienne/", "region": "Auvergne-Rhône-Alpes"},
    {"name": "BFM : Toulouse", "url": "https://www.bfmtv.com/rss/toulouse/", "region": "Occitanie"},
    {"name": "BFM : Tours", "url": "https://www.bfmtv.com/rss/tours/", "region": "Centre-Val de Loire"},
    {"name": "BFM : Var", "url": "https://www.bfmtv.com/rss/var/", "region": "Provence-Alpes-Côte d'Azur"},

    # ── BONDAMANJAK ─────────────────────────────────────────────────────────────────
    {"name": "Bondamanjak", "url": "https://www.bondamanjak.com/feed/", "region": "Martinique"},
    {"name": "Bondamanjak : Guadeloupe", "url": "https://www.bondamanjak.com/category/guadeloupe/aujourdhui-en-guadeloupe/feed/", "region": "Guadeloupe"},
    {"name": "Bondamanjak : Martinique", "url": "https://www.bondamanjak.com/category/martinique/aujourdhui-en-martinique/feed/", "region": "Martinique"},

    # ── BORDEAUX GAZETTE ─────────────────────────────────────────────────────────────────
    {"name": "Bordeaux Gazette", "url": "https://www.bordeaux-gazette.com/spip.php?page=backend", "region": "Nouvelle-Aquitaine"},

    # ── CENTRE PRESSE ─────────────────────────────────────────────────────────────────
    {"name": "Centre presse : actualité", "url": "https://www.centrepresseaveyron.fr/rss.xml", "region": "Occitanie"},

    # ── CORSE NET INFOS ─────────────────────────────────────────────────────────────────
    {"name": "Corse Net Infos : actualités", "url": "https://www.corsenetinfos.corsica/xml/syndication.rss", "region": "Corse"},

    # ── CORSICA RADIO ─────────────────────────────────────────────────────────────────
    {"name": "Corsica Radio", "url": "https://feeds.feedburner.com/corsicaradio/zTWqscbKAfj", "region": "Corse"},

    # ── COURRIER INTERNATIONAL ─────────────────────────────────────────────────────────────────
    {"name": "Courrier international : Bretagne", "url": "https://www.courrierinternational.com/feed/rubrique/bretagne/rss.xml", "region": "Bretagne"},

    # ── CÔTÉ BREST ─────────────────────────────────────────────────────────────────
    {"name": "Côté Brest", "url": "https://actu.fr/cote-brest/rss.xml", "region": "Bretagne"},

    # ── CÔTÉ LA FLÈCHE ─────────────────────────────────────────────────────────────────
    {"name": "Côté La Flèche", "url": "https://actu.fr/cote-la-fleche/rss.xml", "region": "Pays de la Loire"},

    # ── CÔTÉ MANCHE ─────────────────────────────────────────────────────────────────
    {"name": "Côté Manche", "url": "https://actu.fr/cote-manche/rss.xml", "region": "Normandie"},

    # ── CÔTÉ QUIMPER ─────────────────────────────────────────────────────────────────
    {"name": "Côté Quimper", "url": "https://actu.fr/cote-quimper/rss.xml", "region": "Bretagne"},

    # ── C’EST À CHERBOURG ─────────────────────────────────────────────────────────────────
    {"name": "C’est à Cherbourg", "url": "https://actu.fr/c-est-a-cherbourg/rss.xml", "region": "Normandie"},

    # ── DEMAIN VENDÉE ─────────────────────────────────────────────────────────────────
    {"name": "Demain Vendée", "url": "https://demain-vendee.fr/feed/", "region": "Pays de la Loire"},

    # ── DERNIÈRES NOUVELLES D’ALSACE ─────────────────────────────────────────────────────────────────
    {"name": "Dernières Nouvelles d’Alsace : Alsace", "url": "https://www.dna.fr/region/alsace/rss", "region": "Grand Est"},
    {"name": "Dernières Nouvelles d’Alsace : Bas-Rhin", "url": "https://www.dna.fr/region/bas-rhin/rss", "region": "Grand Est"},
    {"name": "Dernières Nouvelles d’Alsace : Haguenau Wissembourg", "url": "https://www.dna.fr/edition-haguenau-wissembourg/rss", "region": "Grand Est"},
    {"name": "Dernières Nouvelles d’Alsace : Haut-Rhin", "url": "https://www.dna.fr/region/haut-rhin/rss", "region": "Grand Est"},
    {"name": "Dernières Nouvelles d’Alsace : Strasbourg", "url": "https://www.dna.fr/edition-strasbourg/rss", "region": "Grand Est"},
    {"name": "Dernières Nouvelles d’Alsace : édito", "url": "https://www.dna.fr/actualite/edito/rss", "region": "Grand Est"},

    # ── DIS-LEUR ─────────────────────────────────────────────────────────────────
    {"name": "Dis-leur", "url": "https://dis-leur.fr/feed/", "region": "Occitanie"},

    # ── ESPRIT OCCITANIE ─────────────────────────────────────────────────────────────────
    {"name": "Esprit Occitanie", "url": "https://www.espritoccitanie.fr/rss-feed-7", "region": "Occitanie"},

    # ── EURONEWS - FR ─────────────────────────────────────────────────────────────────
    {"name": "Euronews - FR : Guyane française", "url": "https://fr.euronews.com/rss?level=tag&name=guyane-francaise", "region": "Guyane"},
    {"name": "Euronews - FR : Lyon", "url": "https://fr.euronews.com/rss?level=tag&name=lyon", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Euronews - FR : Marseille", "url": "https://fr.euronews.com/rss?level=tag&name=marseille", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Euronews - FR : Paris", "url": "https://fr.euronews.com/rss?level=tag&name=paris", "region": "Île-de-France"},

    # ── FRANCE ANTILLES ─────────────────────────────────────────────────────────────────
    {"name": "France Antilles : Guadeloupe : environnement", "url": "https://www.guadeloupe.franceantilles.fr/actualite/environnement/rss.xml", "region": "Guadeloupe"},
    {"name": "France Antilles : Guadeloupe : faits divers", "url": "https://www.guadeloupe.franceantilles.fr/actualite/faits-divers/rss.xml", "region": "Guadeloupe"},
    {"name": "France Antilles : Guadeloupe : société", "url": "https://www.guadeloupe.franceantilles.fr/actualite/societe/rss.xml", "region": "Guadeloupe"},
    {"name": "France Antilles : Martinique : faits divers", "url": "https://www.martinique.franceantilles.fr/actualite/faitsdivers/rss.xml", "region": "Martinique"},
    {"name": "France Antilles : Martinique : société", "url": "https://www.martinique.franceantilles.fr/actualite/societe/rss.xml", "region": "Martinique"},
    {"name": "France Antilles : Martinique : vie locale", "url": "https://www.martinique.franceantilles.fr/actualite/vielocale/rss.xml", "region": "Martinique"},

    # ── FRANCE INFO ─────────────────────────────────────────────────────────────────
    {"name": "France Info : Alpes-Maritimes", "url": "https://www.franceinfo.fr/alpes-maritimes.rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France Info : Alpes-de-Haute-Provence", "url": "https://www.franceinfo.fr/alpes-de-haute-provence.rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France Info : Auvergne-Rhône-Alpes", "url": "https://www.franceinfo.fr/france/auvergne-rhone-alpes.rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "France Info : Bouches-du-Rhône", "url": "https://www.franceinfo.fr/bouches-du-rhone.rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France Info : Bourgogne-Franche-Comté", "url": "https://www.franceinfo.fr/france/bourgogne-franche-comte.rss", "region": "Bourgogne-Franche-Comté"},
    {"name": "France Info : Bretagne", "url": "https://www.franceinfo.fr/france/bretagne.rss", "region": "Bretagne"},
    {"name": "France Info : Centre-Val de Loire", "url": "https://www.franceinfo.fr/france/centre-val-de-loire.rss", "region": "Centre-Val de Loire"},
    {"name": "France Info : Corse", "url": "https://www.franceinfo.fr/france/corse.rss", "region": "Corse"},
    {"name": "France Info : Grand Est", "url": "https://www.franceinfo.fr/france/grand-est.rss", "region": "Grand Est"},
    {"name": "France Info : Hautes-Alpes", "url": "https://www.franceinfo.fr/hautes-alpes.rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France Info : Hauts-de-France", "url": "https://www.franceinfo.fr/france/hauts-de-france.rss", "region": "Hauts-de-France"},
    {"name": "France Info : La Réunion", "url": "https://www.franceinfo.fr/france/la-reunion.rss", "region": "La Réunion"},
    {"name": "France Info : Lille", "url": "https://www.franceinfo.fr/france/hauts-de-france/nord/lille.rss", "region": "Hauts-de-France"},
    {"name": "France Info : Lyon", "url": "https://www.franceinfo.fr/france/auvergne-rhone-alpes/rhone/lyon.rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "France Info : Marseille", "url": "https://www.franceinfo.fr/marseille.rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France Info : Martinique", "url": "https://www.franceinfo.fr/france/martinique.rss", "region": "Martinique"},
    {"name": "France Info : Mayotte", "url": "https://www.franceinfo.fr/france/mayotte.rss", "region": "Mayotte"},
    {"name": "France Info : Montpellier", "url": "https://www.franceinfo.fr/france/occitanie/herault/montpellier.rss", "region": "Occitanie"},
    {"name": "France Info : Nantes", "url": "https://www.franceinfo.fr/france/pays-de-loire/loire-atlantique/nantes.rss", "region": "Pays de la Loire"},
    {"name": "France Info : Nice", "url": "https://www.franceinfo.fr/nice.rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France Info : Normandie", "url": "https://www.franceinfo.fr/france/normandie.rss", "region": "Normandie"},
    {"name": "France Info : Nouvelle-Aquitaine", "url": "https://www.franceinfo.fr/france/nouvelle-aquitaine.rss", "region": "Nouvelle-Aquitaine"},
    {"name": "France Info : Nouvelle-Calédonie", "url": "https://www.franceinfo.fr/france/nouvelle-caledonie.rss", "region": "Nouvelle-Calédonie"},
    {"name": "France Info : Occitanie", "url": "https://www.franceinfo.fr/france/occitanie.rss", "region": "Occitanie"},
    {"name": "France Info : Paris", "url": "https://www.franceinfo.fr/france/ile-de-france/paris.rss", "region": "Île-de-France"},
    {"name": "France Info : Pays de la Loire", "url": "https://www.franceinfo.fr/france/pays-de-la-loire.rss", "region": "Pays de la Loire"},
    {"name": "France Info : Provence-Alpes-Côte d’Azur", "url": "https://www.franceinfo.fr/france/provence-alpes-cote-d-azur.rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France Info : Rennes", "url": "https://www.franceinfo.fr/france/bretagne/ille-et-vilaine/rennes.rss", "region": "Bretagne"},
    {"name": "France Info : Toulon", "url": "https://www.franceinfo.fr/toulon.rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France Info : Toulouse", "url": "https://www.franceinfo.fr/france/occitanie/haute-garonne/toulouse.rss", "region": "Occitanie"},
    {"name": "France Info : Vaucluse", "url": "https://www.franceinfo.fr/vaucluse.rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France Info : Île-de-France", "url": "https://www.franceinfo.fr/france/ile-de-france.rss", "region": "Île-de-France"},

    # ── FRANCE24 ─────────────────────────────────────────────────────────────────
    {"name": "France24 : Bretagne", "url": "https://www.france24.com/fr/tag/bretagne/rss", "region": "Bretagne"},
    {"name": "France24 : Corse", "url": "https://www.france24.com/fr/tag/corse/rss", "region": "Corse"},
    {"name": "France24 : Guadeloupe", "url": "https://www.france24.com/fr/tag/guadeloupe/rss", "region": "Guadeloupe"},
    {"name": "France24 : Guyane", "url": "https://www.france24.com/fr/tag/guyane/rss", "region": "Guyane"},
    {"name": "France24 : Lyon", "url": "https://www.france24.com/fr/tag/lyon/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "France24 : Marseille", "url": "https://www.france24.com/fr/tag/marseille/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France24 : Martinique", "url": "https://www.france24.com/fr/tag/martinique/rss", "region": "Martinique"},
    {"name": "France24 : Nice", "url": "https://www.france24.com/fr/tag/nice/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France24 : Paris", "url": "https://www.france24.com/fr/tag/paris/rss", "region": "Île-de-France"},
    {"name": "France24 : Rennes", "url": "https://www.france24.com/fr/tag/rennes/rss", "region": "Bretagne"},
    {"name": "France24 : Toulouse", "url": "https://www.france24.com/fr/tag/toulouse/rss", "region": "Occitanie"},

    # ── FRANCE3 ─────────────────────────────────────────────────────────────────
    {"name": "France3 : Aisne", "url": "https://france3-regions.franceinfo.fr/hauts-de-france/aisne/rss", "region": "Hauts-de-France"},
    {"name": "France3 : Aix-en-Provence", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/bouches-du-rhone/aix-en-provence/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Alpes-Maritimes", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/alpes-maritimes/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Alpes-de-Haute-Provence", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/alpes-de-haute-provence/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Alsace", "url": "https://france3-regions.franceinfo.fr/grand-est/alsace/rss", "region": "Grand Est"},
    {"name": "France3 : Antibes", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/alpes-maritimes/antibes/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Arles", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/bouches-du-rhone/arles/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Aude", "url": "https://france3-regions.franceinfo.fr/occitanie/aude/rss", "region": "Occitanie"},
    {"name": "France3 : Auvergne Rhône-Alpes", "url": "https://france3-regions.franceinfo.fr/auvergne-rhone-alpes/actu/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "France3 : Avignon", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/vaucluse/avignon/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Bouches-du-Rhône", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/bouches-du-rhone/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Bourgogne-Franche-Comté", "url": "https://france3-regions.franceinfo.fr/bourgogne-franche-comte/actu/rss", "region": "Bourgogne-Franche-Comté"},
    {"name": "France3 : Bretagne", "url": "https://france3-regions.franceinfo.fr/bretagne/actu/rss", "region": "Bretagne"},
    {"name": "France3 : Calais", "url": "https://france3-regions.franceinfo.fr/hauts-de-france/pas-calais/calais/rss", "region": "Hauts-de-France"},
    {"name": "France3 : Cannes", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/alpes-maritimes/cannes/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Centre-Val de Loire", "url": "https://france3-regions.franceinfo.fr/centre-val-de-loire/actu/rss", "region": "Centre-Val de Loire"},
    {"name": "France3 : Champagne-Ardenne", "url": "https://france3-regions.franceinfo.fr/grand-est/champagne-ardenne/rss", "region": "Grand Est"},
    {"name": "France3 : Cher", "url": "https://france3-regions.franceinfo.fr/centre-val-de-loire/cher/rss", "region": "Centre-Val de Loire"},
    {"name": "France3 : Digne-les-Bains", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/alpes-de-haute-provence/digne-les-bains/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Draguignan", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/var/draguignan/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Eure-et-Loir", "url": "https://france3-regions.franceinfo.fr/centre-val-de-loire/eure-et-loir/rss", "region": "Centre-Val de Loire"},
    {"name": "France3 : Gap", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/hautes-alpes/gap/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Grand Est", "url": "https://france3-regions.franceinfo.fr/grand-est/rss", "region": "Grand Est"},
    {"name": "France3 : Haute-Garonne", "url": "https://france3-regions.franceinfo.fr/occitanie/haute-garonne/rss", "region": "Occitanie"},
    {"name": "France3 : Hautes-Alpes", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/hautes-alpes/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Hauts-de-France", "url": "https://france3-regions.franceinfo.fr/hauts-de-france/actu/rss", "region": "Hauts-de-France"},
    {"name": "France3 : Hauts-de-France : société", "url": "https://france3-regions.franceinfo.fr/societe/rss?r=hauts-de-france", "region": "Hauts-de-France"},
    {"name": "France3 : Hérault", "url": "https://france3-regions.franceinfo.fr/occitanie/herault/rss", "region": "Occitanie"},
    {"name": "France3 : Indre", "url": "https://france3-regions.franceinfo.fr/centre-val-de-loire/indre/rss", "region": "Centre-Val de Loire"},
    {"name": "France3 : La Baule", "url": "https://france3-regions.franceinfo.fr/pays-de-la-loire/loire-atlantique/la-baule/rss", "region": "Pays de la Loire"},
    {"name": "France3 : Lille", "url": "https://france3-regions.franceinfo.fr/hauts-de-france/nord-0/lille/rss", "region": "Hauts-de-France"},
    {"name": "France3 : Lille métropole", "url": "https://france3-regions.franceinfo.fr/hauts-de-france/nord-0/lille-metropole/rss", "region": "Hauts-de-France"},
    {"name": "France3 : Loir-et-Cher", "url": "https://france3-regions.franceinfo.fr/centre-val-de-loire/loir-cher/rss", "region": "Centre-Val de Loire"},
    {"name": "France3 : Loiret", "url": "https://france3-regions.franceinfo.fr/centre-val-de-loire/loiret/rss", "region": "Centre-Val de Loire"},
    {"name": "France3 : Lorraine", "url": "https://france3-regions.franceinfo.fr/grand-est/lorraine/rss", "region": "Grand Est"},
    {"name": "France3 : Marseille", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/bouches-du-rhone/marseille/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Montpellier", "url": "https://france3-regions.franceinfo.fr/occitanie/herault/montpellier/rss", "region": "Occitanie"},
    {"name": "France3 : Nantes", "url": "https://france3-regions.franceinfo.fr/pays-de-la-loire/loire-atlantique/nantes/rss", "region": "Pays de la Loire"},
    {"name": "France3 : Nice", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/alpes-maritimes/nice/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Nord Pas-de-Calais", "url": "https://france3-regions.franceinfo.fr/hauts-de-france/nord-pas-calais/rss", "region": "Hauts-de-France"},
    {"name": "France3 : Normandie", "url": "https://france3-regions.franceinfo.fr/normandie/actu/rss", "region": "Normandie"},
    {"name": "France3 : Nouvelle-Aquitaine", "url": "https://france3-regions.franceinfo.fr/nouvelle-aquitaine/actu/rss", "region": "Nouvelle-Aquitaine"},
    {"name": "France3 : Nîmes", "url": "https://france3-regions.franceinfo.fr/occitanie/gard/nimes/rss", "region": "Occitanie"},
    {"name": "France3 : Occitanie", "url": "https://france3-regions.franceinfo.fr/occitanie/actu/rss", "region": "Occitanie"},
    {"name": "France3 : Pays de la Loire", "url": "https://france3-regions.franceinfo.fr/pays-de-la-loire/actu/rss", "region": "Pays de la Loire"},
    {"name": "France3 : Pays de la Loire : Mayenne", "url": "https://france3-regions.franceinfo.fr/pays-de-la-loire/mayenne/rss", "region": "Pays de la Loire"},
    {"name": "France3 : Provence-Alpes Côte d’Azur", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/actu/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Provence-Alpes-Côte d’Azur : société", "url": "https://france3-regions.franceinfo.fr/societe/rss?r=provence-alpes-cote-d-azur", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Rennes", "url": "https://france3-regions.franceinfo.fr/bretagne/ille-et-vilaine/rennes/rss", "region": "Bretagne"},
    {"name": "France3 : Saint-Nazaire", "url": "https://france3-regions.franceinfo.fr/pays-de-la-loire/loire-atlantique/saint-nazaire/rss", "region": "Pays de la Loire"},
    {"name": "France3 : Toulon", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/var/toulon/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Toulouse", "url": "https://france3-regions.franceinfo.fr/occitanie/haute-garonne/toulouse/rss", "region": "Occitanie"},
    {"name": "France3 : Var", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/var/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Vaucluse", "url": "https://france3-regions.franceinfo.fr/provence-alpes-cote-d-azur/vaucluse/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "France3 : Île-de-France", "url": "https://france3-regions.franceinfo.fr/paris-ile-de-france/actu/rss", "region": "Île-de-France"},

    # ── FRANCE3 BOURGOGNE-FRANCHE-COMTÉ ─────────────────────────────────────────────────────────────────
    {"name": "France3 Bourgogne-Franche-Comté : Montbéliard", "url": "https://france3-regions.franceinfo.fr/bourgogne-franche-comte/doubs/pays-de-montbeliard/rss", "region": "Bourgogne-Franche-Comté"},

    # ── FREE DOM ─────────────────────────────────────────────────────────────────
    {"name": "Free Dom", "url": "https://freedom.fr/feed/", "region": "La Réunion"},

    # ── FREQUENZA NOSTRA ─────────────────────────────────────────────────────────────────
    {"name": "Frequenza Nostra : ausha", "url": "https://feed.ausha.co/nr0vlHJvw4MO", "region": "Corse"},

    # ── GOMET’ ─────────────────────────────────────────────────────────────────
    {"name": "Gomet’", "url": "https://gomet.net/feed/", "region": "Provence-Alpes-Côte d'Azur"},

    # ── GUYAWEB ─────────────────────────────────────────────────────────────────
    {"name": "GuyaWeb", "url": "https://www.guyaweb.com/feed/", "region": "Guyane"},

    # ── HUFFPOST ─────────────────────────────────────────────────────────────────
    {"name": "HuffPost : Lyon", "url": "https://www.huffingtonpost.fr/lyon/rss_headline.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "HuffPost : Marseille", "url": "https://www.huffingtonpost.fr/marseille/rss_headline.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "HuffPost : Montpellier", "url": "https://www.huffingtonpost.fr/montpellier/rss_headline.xml", "region": "Occitanie"},
    {"name": "HuffPost : Nice", "url": "https://www.huffingtonpost.fr/nice/rss_headline.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "HuffPost : Paris", "url": "https://www.huffingtonpost.fr/paris/rss_headline.xml", "region": "Île-de-France"},
    {"name": "HuffPost : Rennes", "url": "https://www.huffingtonpost.fr/rennes/rss_headline.xml", "region": "Bretagne"},
    {"name": "HuffPost : Toulouse", "url": "https://www.huffingtonpost.fr/toulouse/rss_headline.xml", "region": "Occitanie"},

    # ── HÉRAULT TRIBUNE ─────────────────────────────────────────────────────────────────
    {"name": "Hérault Tribune", "url": "https://echo-des-tribunes.com/herault-tribune/articles/feed", "region": "Occitanie"},
    {"name": "Hérault Tribune : Communauté de communes de la vallée de l’Hérault", "url": "https://echo-des-tribunes.com/herault-tribune/vallee-de-l-herault/feed", "region": "Occitanie"},
    {"name": "Hérault Tribune : Communauté d’Agglomération Hérault Méditerranée", "url": "https://echo-des-tribunes.com/herault-tribune/l-agglo-herault-mediterranee/feed", "region": "Occitanie"},
    {"name": "Hérault Tribune : Métropole de Montpellier", "url": "https://echo-des-tribunes.com/herault-tribune/metropole-de-montpellier/feed", "region": "Occitanie"},

    # ── IF SAINT-ÉTIENNE ─────────────────────────────────────────────────────────────────
    {"name": "If Saint-Étienne", "url": "https://www.if-saint-etienne.fr/feed", "region": "Auvergne-Rhône-Alpes"},

    # ── IMAZ PRESS RÉUNION ─────────────────────────────────────────────────────────────────
    {"name": "Imaz Press Réunion", "url": "https://imazpress.com/feed", "region": "La Réunion"},

    # ── INFO TOURS ─────────────────────────────────────────────────────────────────
    {"name": "Info Tours", "url": "https://info-tours.fr/feed/", "region": "Centre-Val de Loire"},

    # ── JOURNAL DE MILLAU ─────────────────────────────────────────────────────────────────
    {"name": "Journal de Millau", "url": "https://www.journaldemillau.fr/rss.xml", "region": "Occitanie"},

    # ── LA 1ÈRE ─────────────────────────────────────────────────────────────────
    {"name": "La 1ère : Martinique", "url": "https://la1ere.franceinfo.fr/martinique/actu/rss", "region": "Martinique"},
    {"name": "La 1ère : Wallis-et-Futuna", "url": "https://la1ere.franceinfo.fr/wallisfutuna/actu/rss", "region": "Wallis-et-Futuna"},
    {"name": "La 1ère : environnement", "url": "https://la1ere.franceinfo.fr/environnement/rss", "region": None},
    {"name": "La 1ère : société", "url": "https://la1ere.franceinfo.fr/societe/rss", "region": None},
    {"name": "La 1ère : toute l’actualité", "url": "https://la1ere.franceinfo.fr/actu/rss", "region": None},

    # ── LA CHRONIQUE RÉPUBLICAINE ─────────────────────────────────────────────────────────────────
    {"name": "La Chronique Républicaine", "url": "https://actu.fr/la-chronique-republicaine/rss.xml", "region": "Bretagne"},

    # ── LA CROIX ─────────────────────────────────────────────────────────────────
    {"name": "La Croix : Lyon", "url": "https://www.la-croix.com/feeds/rss/France/lyon-actualite-information.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "La Croix : Marseille", "url": "https://www.la-croix.com/feeds/rss/France/marseille-actualite-information.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "La Croix : Montpellier", "url": "https://www.la-croix.com/feeds/rss/France/montpellier-actualite-info.xml", "region": "Occitanie"},
    {"name": "La Croix : Nice", "url": "https://www.la-croix.com/feeds/rss/France/nice-actualite-info.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "La Croix : Paris", "url": "https://www.la-croix.com/feeds/rss/France/paris-actualite-information.xml", "region": "Île-de-France"},
    {"name": "La Croix : Provence-Alpes-Côte d’Azur", "url": "https://www.la-croix.com/feeds/rss/France/region-paca-provence-alpes-cote-dazur-actu-info.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "La Croix : Rennes", "url": "https://www.la-croix.com/feeds/rss/France/rennes-info-actualite.xml", "region": "Bretagne"},
    {"name": "La Croix : Toulon", "url": "https://www.la-croix.com/feeds/rss/France/toulon-information-actualite.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "La Croix : Toulouse", "url": "https://www.la-croix.com/feeds/rss/France/toulouse-actualite-info.xml", "region": "Occitanie"},

    # ── LA DÉPÊCHE ─────────────────────────────────────────────────────────────────
    {"name": "La Dépêche", "url": "https://actu.fr/la-depeche-louviers/rss.xml", "region": "Normandie"},
    {"name": "La Dépêche : Agen", "url": "https://www.ladepeche.fr/communes/agen,47001/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "La Dépêche : Albi", "url": "https://www.ladepeche.fr/communes/albi,81004/rss.xml", "region": "Occitanie"},
    {"name": "La Dépêche : Ariège", "url": "https://www.ladepeche.fr/communes/ariege,09/rss.xml", "region": "Occitanie"},
    {"name": "La Dépêche : Auch", "url": "https://www.ladepeche.fr/communes/auch,32013/rss.xml", "region": "Occitanie"},
    {"name": "La Dépêche : Cahors", "url": "https://www.ladepeche.fr/communes/cahors,46042/rss.xml", "region": "Occitanie"},
    {"name": "La Dépêche : Carcassonne", "url": "https://www.ladepeche.fr/communes/carcassonne,11069/rss.xml", "region": "Occitanie"},
    {"name": "La Dépêche : Castres", "url": "https://www.ladepeche.fr/communes/castres,81065/rss.xml", "region": "Occitanie"},
    {"name": "La Dépêche : Foix", "url": "https://www.ladepeche.fr/communes/foix,09122/rss.xml", "region": "Occitanie"},
    {"name": "La Dépêche : La gazette du Comminges", "url": "https://www.ladepeche.fr/la-gazette-du-comminges/rss.xml", "region": "Occitanie"},
    {"name": "La Dépêche : Lot-et-Garonne", "url": "https://www.ladepeche.fr/communes/lot-et-garonne,47/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "La Dépêche : Montauban", "url": "https://www.ladepeche.fr/communes/montauban,82121/rss.xml", "region": "Occitanie"},
    {"name": "La Dépêche : Narbonne", "url": "https://www.ladepeche.fr/communes/narbonne,11262/rss.xml", "region": "Occitanie"},
    {"name": "La Dépêche : Pamiers", "url": "https://www.ladepeche.fr/communes/pamiers,09225/rss.xml", "region": "Occitanie"},
    {"name": "La Dépêche : Pennautier", "url": "https://www.ladepeche.fr/communes/pennautier,11279/rss.xml", "region": "Occitanie"},
    {"name": "La Dépêche : Provence-Alpes-Côte d’Azur", "url": "https://www.ladepeche.fr/provence-alpes-cote-dazur/rss.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "La Dépêche : Rodez", "url": "https://www.ladepeche.fr/communes/rodez,12202/rss.xml", "region": "Occitanie"},
    {"name": "La Dépêche : Tarn", "url": "https://www.ladepeche.fr/communes/tarn,81/rss.xml", "region": "Occitanie"},
    {"name": "La Dépêche : Toulouse", "url": "https://www.ladepeche.fr/communes/toulouse,31555/rss.xml", "region": "Occitanie"},

    # ── LA GAZETTE DE LA MANCHE ─────────────────────────────────────────────────────────────────
    {"name": "La Gazette de la Manche", "url": "https://actu.fr/la-gazette-de-la-manche/rss.xml", "region": "Normandie"},

    # ── LA GAZETTE DU CENTRE MORBIHAN ─────────────────────────────────────────────────────────────────
    {"name": "La Gazette du Centre Morbihan", "url": "https://actu.fr/la-gazette-du-centre-morbihan/rss.xml", "region": "Bretagne"},

    # ── LA GAZETTE DU VAL-D’OISE ─────────────────────────────────────────────────────────────────
    {"name": "La Gazette du Val-d’Oise", "url": "https://actu.fr/la-gazette-du-val-d-oise/rss.xml", "region": "Île-de-France"},

    # ── LA MARNE ─────────────────────────────────────────────────────────────────
    {"name": "La Marne", "url": "https://actu.fr/la-marne/rss.xml", "region": "Île-de-France"},

    # ── LA NOUVELLE RÉPUBLIQUE ─────────────────────────────────────────────────────────────────
    {"name": "La Nouvelle République", "url": "https://www.lanouvellerepublique.fr/api/v1/rss/592bf255489a4555008b4568", "region": "Centre-Val de Loire"},
    {"name": "La Nouvelle République : Centre Presse", "url": "https://www.lanouvellerepublique.fr/api/v1/rss/670536b0605bd4c91a8b4583", "region": "Nouvelle-Aquitaine"},
    {"name": "La Nouvelle République : Deux-Sèvres", "url": "https://www.lanouvellerepublique.fr/api/v1/rss/5e2072f9f30f8cdd4c8b4594", "region": "Nouvelle-Aquitaine"},
    {"name": "La Nouvelle République : Indre", "url": "https://www.lanouvellerepublique.fr/api/v1/rss/5e20725dcc4d8d75408b458d", "region": "Centre-Val de Loire"},
    {"name": "La Nouvelle République : Indre-et-Loire", "url": "https://www.lanouvellerepublique.fr/api/v1/rss/5e206fd2fb1714762f8b4592", "region": "Centre-Val de Loire"},
    {"name": "La Nouvelle République : Loir-et-Cher", "url": "https://www.lanouvellerepublique.fr/api/v1/rss/5e2072c23915ea8c028b4582", "region": "Centre-Val de Loire"},
    {"name": "La Nouvelle République : Val de Loire TV", "url": "https://www.valdeloire.tv/feed/", "region": "Centre-Val de Loire"},
    {"name": "La Nouvelle République : Vienne", "url": "https://www.lanouvellerepublique.fr/api/v1/rss/5e20732239a34f77578b457c", "region": "Nouvelle-Aquitaine"},

    # ── LA NOUVELLE RÉPUBLIQUE DES PYRÉNÉES ─────────────────────────────────────────────────────────────────
    {"name": "La Nouvelle République des Pyrénées", "url": "https://www.nrpyrenees.fr/rss.xml", "region": "Occitanie"},

    # ── LA PRESSE DE LA MANCHE ─────────────────────────────────────────────────────────────────
    {"name": "La Presse de la Manche", "url": "https://actu.fr/la-presse-de-la-manche/rss.xml", "region": "Normandie"},

    # ── LA PRESSE D’ARMOR ─────────────────────────────────────────────────────────────────
    {"name": "La Presse d’Armor", "url": "https://actu.fr/la-presse-d-armor/rss.xml", "region": "Bretagne"},

    # ── LA RENAISSANCE LE BESSIN ─────────────────────────────────────────────────────────────────
    {"name": "La Renaissance le Bessin", "url": "https://actu.fr/la-renaissance-le-bessin/rss.xml", "region": "Normandie"},

    # ── LA RÉPUBLIQUE DE SEINE-ET-MARNE ─────────────────────────────────────────────────────────────────
    {"name": "La République de Seine-et-Marne", "url": "https://actu.fr/la-republique-de-seine-et-marne/rss.xml", "region": "Île-de-France"},

    # ── LA VOIX LE BOCAGE ─────────────────────────────────────────────────────────────────
    {"name": "La Voix le Bocage", "url": "https://actu.fr/la-voix-le-bocage/rss.xml", "region": "Normandie"},

    # ── LA JOURNAL DU GERS ─────────────────────────────────────────────────────────────────
    {"name": "La journal du Gers : Auch", "url": "https://lejournaldugers.fr/ville/12-auch.xml", "region": "Occitanie"},
    {"name": "La journal du Gers : Lomagne Gascogne Toulousaine", "url": "https://lejournaldugers.fr/lomagne-gascogne-toulousaine.xml", "region": "Occitanie"},

    # ── LA SEMAINE DU ROUSSILLON ─────────────────────────────────────────────────────────────────
    {"name": "La semaine du Roussillon", "url": "https://www.lasemaineduroussillon.com/feed/", "region": "Occitanie"},

    # ── LAPROVENCE ─────────────────────────────────────────────────────────────────
    {"name": "LaProvence : Aix-en-Provence", "url": "https://www.laprovence.com/rss/aix-en-provence.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "LaProvence : Arles", "url": "https://www.laprovence.com/rss/arles.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "LaProvence : Marseille", "url": "https://www.laprovence.com/rss/marseille.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "LaProvence : Vitrolles", "url": "https://www.laprovence.com/rss/vitrolles.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "LaProvence : région", "url": "https://www.laprovence.com/rss/Region.xml", "region": "Provence-Alpes-Côte d'Azur"},

    # ── LE BERRY RÉPUBLICAIN ─────────────────────────────────────────────────────────────────
    {"name": "Le Berry Républicain : les derniers articles", "url": "https://feeds.feedburner.com/leberry/9HCcPsTtECI", "region": "Centre-Val de Loire"},

    # ── LE BIEN PUBLIC ─────────────────────────────────────────────────────────────────
    {"name": "Le Bien Public : Côte-d’Or", "url": "https://www.bienpublic.com/cote-d-or/rss", "region": "Bourgogne-Franche-Comté"},

    # ── LE COURRIER INDÉPENDANT ─────────────────────────────────────────────────────────────────
    {"name": "Le Courrier Indépendant", "url": "https://actu.fr/le-courrier-independant/rss.xml", "region": "Bretagne"},

    # ── LE COURRIER DE L’EURE ─────────────────────────────────────────────────────────────────
    {"name": "Le Courrier de l’Eure", "url": "https://actu.fr/le-courrier-de-l-eure/rss.xml", "region": "Normandie"},

    # ── LE COURRIER DU PAYS DE RETZ ─────────────────────────────────────────────────────────────────
    {"name": "Le Courrier du Pays de Retz", "url": "https://actu.fr/le-courrier-du-pays-de-retz/rss.xml", "region": "Pays de la Loire"},

    # ── LE COURRIER VENDÉEN ─────────────────────────────────────────────────────────────────
    {"name": "Le Courrier vendéen", "url": "https://actu.fr/le-courrier-vendeen/rss.xml", "region": "Pays de la Loire"},

    # ── LE CRESTOIS ─────────────────────────────────────────────────────────────────
    {"name": "Le Crestois", "url": "https://le-crestois.fr/index.php?format=feed&type=rss", "region": "Auvergne-Rhône-Alpes"},

    # ── LE DAUPHINÉ ─────────────────────────────────────────────────────────────────
    {"name": "Le Dauphiné : Grenoble", "url": "https://www.ledauphine.com/c/isere/38185-grenoble/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Dauphiné : Haute-Savoie", "url": "https://www.ledauphine.com/haute-savoie/rss", "region": "Auvergne-Rhône-Alpes"},

    # ── LE DAUPHINÉ LIBÉRÉ ─────────────────────────────────────────────────────────────────
    {"name": "Le Dauphiné Libéré : Gap", "url": "https://www.ledauphine.com/c/hautes-alpes/05061-gap/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Le Dauphiné Libéré : Isère", "url": "https://www.ledauphine.com/isere/rss", "region": "Auvergne-Rhône-Alpes"},

    # ── LE DÉMOCRATE VERNONNAIS ─────────────────────────────────────────────────────────────────
    {"name": "Le Démocrate vernonnais", "url": "https://actu.fr/le-democrate-vernonnais/rss.xml", "region": "Normandie"},

    # ── LE DÉPÊCHE ÉVREUX ─────────────────────────────────────────────────────────────────
    {"name": "Le Dépêche Évreux", "url": "https://actu.fr/la-depeche-evreux/rss.xml", "region": "Normandie"},
    {"name": "Le Dépêche Évreux", "url": "https://www.evreux.fr/actualites/feed/", "region": "Normandie"},

    # ── LE GLOB JOURNAL ─────────────────────────────────────────────────────────────────
    {"name": "Le Glob Journal", "url": "https://leglob-journal.fr/feed/", "region": "Pays de la Loire"},

    # ── LE JOURNAL DE L’ORNE ─────────────────────────────────────────────────────────────────
    {"name": "Le Journal de L’Orne", "url": "https://actu.fr/le-journal-de-l-orne/rss.xml", "region": "Normandie"},

    # ── LE JOURNAL DE VITRÉ ─────────────────────────────────────────────────────────────────
    {"name": "Le Journal de Vitré", "url": "https://actu.fr/le-journal-de-vitre/rss.xml", "region": "Bretagne"},

    # ── LE JOURNAL DES SABLES ─────────────────────────────────────────────────────────────────
    {"name": "Le Journal des Sables", "url": "https://actu.fr/le-journal-des-sables/rss.xml", "region": "Pays de la Loire"},

    # ── LE JOURNAL DU PAYS YONNAIS ─────────────────────────────────────────────────────────────────
    {"name": "Le Journal du Pays Yonnais", "url": "https://actu.fr/le-journal-du-pays-yonnais/rss.xml", "region": "Pays de la Loire"},

    # ── LE JOURNAL D’ABBEVILLE ─────────────────────────────────────────────────────────────────
    {"name": "Le Journal d’Abbeville", "url": "https://actu.fr/le-journal-d-abbeville/rss.xml", "region": "Hauts-de-France"},

    # ── LE JOURNAL D’ELBEUF ─────────────────────────────────────────────────────────────────
    {"name": "Le Journal d’Elbeuf", "url": "https://actu.fr/le-journal-d-elbeuf/rss.xml", "region": "Normandie"},

    # ── LE MONDE ─────────────────────────────────────────────────────────────────
    {"name": "Le Monde : Aix-en-Provence", "url": "https://www.lemonde.fr/aix-en-provence/rss_full.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Le Monde : Angers", "url": "https://www.lemonde.fr/angers/rss_full.xml", "region": "Pays de la Loire"},
    {"name": "Le Monde : Bordeaux", "url": "https://www.lemonde.fr/bordeaux/rss_full.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Le Monde : Brest", "url": "https://www.lemonde.fr/brest/rss_full.xml", "region": "Bretagne"},
    {"name": "Le Monde : Clermont-Ferrand", "url": "https://www.lemonde.fr/clermont-ferrand/rss_full.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Monde : Corse", "url": "https://www.lemonde.fr/corse/rss_full.xml", "region": "Corse"},
    {"name": "Le Monde : Grenoble", "url": "https://www.lemonde.fr/grenoble/rss_full.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Monde : Guadeloupe", "url": "https://www.lemonde.fr/guadeloupe/rss_full.xml", "region": "Guadeloupe"},
    {"name": "Le Monde : Guyane", "url": "https://www.lemonde.fr/guyane/rss_full.xml", "region": "Guyane"},
    {"name": "Le Monde : Le Havre", "url": "https://www.lemonde.fr/le-havre/rss_full.xml", "region": "Normandie"},
    {"name": "Le Monde : Lille", "url": "https://www.lemonde.fr/lille/rss_full.xml", "region": "Hauts-de-France"},
    {"name": "Le Monde : Lyon", "url": "https://www.lemonde.fr/lyon/rss_full.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Monde : Marseille", "url": "https://www.lemonde.fr/marseille/rss_full.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Le Monde : Martinique", "url": "https://www.lemonde.fr/martinique/rss_full.xml", "region": "Martinique"},
    {"name": "Le Monde : Mayotte", "url": "https://www.lemonde.fr/mayotte/rss_full.xml", "region": "Mayotte"},
    {"name": "Le Monde : Nantes", "url": "https://www.lemonde.fr/nantes/rss_full.xml", "region": "Pays de la Loire"},
    {"name": "Le Monde : Nice", "url": "https://www.lemonde.fr/nice/rss_full.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Le Monde : Nouvelle-Calédonie", "url": "https://www.lemonde.fr/referendum-en-nouvelle-caledonie/rss_full.xml", "region": "Nouvelle-Calédonie"},
    {"name": "Le Monde : Outre-mer", "url": "https://www.lemonde.fr/outre-mer/rss_full.xml", "region": None},
    {"name": "Le Monde : Paris", "url": "https://www.lemonde.fr/paris/rss_full.xml", "region": "Île-de-France"},
    {"name": "Le Monde : Perpignan", "url": "https://www.lemonde.fr/perpignan/rss_full.xml", "region": "Occitanie"},
    {"name": "Le Monde : Polynésie française", "url": "https://www.lemonde.fr/polynesie-francaise/rss_full.xml", "region": "Polynésie française"},
    {"name": "Le Monde : Rennes", "url": "https://www.lemonde.fr/rennes/rss_full.xml", "region": "Bretagne"},
    {"name": "Le Monde : Saint Étienne", "url": "https://www.lemonde.fr/saint-etienne/rss_full.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Monde : Saint-Denis", "url": "https://www.lemonde.fr/saint-denis/rss_full.xml", "region": "Île-de-France"},
    {"name": "Le Monde : Strasbourg", "url": "https://www.lemonde.fr/strasbourg/rss_full.xml", "region": "Grand Est"},
    {"name": "Le Monde : Toulon", "url": "https://www.lemonde.fr/toulon/rss_full.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Le Monde : Toulouse", "url": "https://www.lemonde.fr/toulouse/rss_full.xml", "region": "Occitanie"},

    # ── LE MONDE DIPLOMATIQUE ─────────────────────────────────────────────────────────────────
    {"name": "Le Monde Diplomatique : Basques", "url": "https://www.monde-diplomatique.fr/spip.php?page=backend&id_mot=158", "region": "Nouvelle-Aquitaine"},
    {"name": "Le Monde Diplomatique : Corse", "url": "https://www.monde-diplomatique.fr/spip.php?page=backend&id_mot=45", "region": "Corse"},
    {"name": "Le Monde Diplomatique : France Outre-mer", "url": "https://www.monde-diplomatique.fr/spip.php?page=backend&id_mot=47", "region": None},
    {"name": "Le Monde Diplomatique : Guadeloupe", "url": "https://www.monde-diplomatique.fr/spip.php?page=backend&id_mot=65", "region": "Guadeloupe"},
    {"name": "Le Monde Diplomatique : Guyane", "url": "https://www.monde-diplomatique.fr/spip.php?page=backend&id_mot=67", "region": "Guyane"},

    # ── LE MÉRIDIONAL ─────────────────────────────────────────────────────────────────
    {"name": "Le Méridional", "url": "https://lemeridional.com/feed/", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Le Méridional : Marseille", "url": "https://lemeridional.com/sujets/societe/marseille/feed/", "region": "Provence-Alpes-Côte d'Azur"},

    # ── LE NOUVELOBS ─────────────────────────────────────────────────────────────────
    {"name": "Le NouvelObs : Nouvelle-Calédonie", "url": "https://www.nouvelobs.com/nouvelle-caledonie/rss.xml", "region": "Nouvelle-Calédonie"},

    # ── LE PARISIEN ─────────────────────────────────────────────────────────────────
    {"name": "Le Parisien : Essonne", "url": "https://feeds.leparisien.fr/leparisien/rss/essonne-91", "region": "Île-de-France"},
    {"name": "Le Parisien : Haute-Corse", "url": "https://feeds.leparisien.fr/arc/outboundfeeds/leparisien/rss/haute-corse-2b/?outputType=xml", "region": "Corse"},
    {"name": "Le Parisien : Hauts-de-Seine", "url": "https://feeds.leparisien.fr/leparisien/rss/hauts-de-seine-92", "region": "Île-de-France"},
    {"name": "Le Parisien : L’Oise", "url": "https://feeds.leparisien.fr/leparisien/rss/oise-60", "region": "Hauts-de-France"},
    {"name": "Le Parisien : Paris", "url": "https://feeds.leparisien.fr/leparisien/rss/paris-75", "region": "Île-de-France"},
    {"name": "Le Parisien : Paris Île-de-France", "url": "https://feeds.leparisien.fr/leparisien/rss/info-paris-ile-de-france-oise", "region": "Île-de-France"},
    {"name": "Le Parisien : Seine-Saint-Denis", "url": "https://feeds.leparisien.fr/leparisien/rss/seine-saint-denis-93", "region": "Île-de-France"},
    {"name": "Le Parisien : Seine-et-Marne", "url": "https://feeds.leparisien.fr/leparisien/rss/seine-et-marne-77", "region": "Île-de-France"},
    {"name": "Le Parisien : Val de Marne", "url": "https://feeds.leparisien.fr/leparisien/rss/val-de-marne-94", "region": "Île-de-France"},
    {"name": "Le Parisien : Val d’Oise", "url": "https://feeds.leparisien.fr/leparisien/rss/val-d-oise-95", "region": "Île-de-France"},
    {"name": "Le Parisien : Yvelines", "url": "https://feeds.leparisien.fr/leparisien/rss/yvelines-78", "region": "Île-de-France"},

    # ── LE PAYS BRIARD ─────────────────────────────────────────────────────────────────
    {"name": "Le Pays Briard", "url": "https://actu.fr/le-pays-briard/rss.xml", "region": "Île-de-France"},

    # ── LE PAYS MALOUIN ─────────────────────────────────────────────────────────────────
    {"name": "Le Pays Malouin", "url": "https://actu.fr/le-pays-malouin/rss.xml", "region": "Bretagne"},

    # ── LE PAYS D’AUGE ─────────────────────────────────────────────────────────────────
    {"name": "Le Pays d’Auge", "url": "https://actu.fr/le-pays-d-auge/rss.xml", "region": "Normandie"},

    # ── LE PENTHIÈVRE ─────────────────────────────────────────────────────────────────
    {"name": "Le Penthièvre", "url": "https://actu.fr/le-penthievre/rss.xml", "region": "Bretagne"},

    # ── LE PERCHE ─────────────────────────────────────────────────────────────────
    {"name": "Le Perche", "url": "https://actu.fr/le-perche/rss.xml", "region": "Normandie"},

    # ── LE PETIT BLEU ─────────────────────────────────────────────────────────────────
    {"name": "Le Petit Bleu", "url": "https://actu.fr/le-petit-bleu/rss.xml", "region": "Bretagne"},

    # ── LE PETIT COURRIER - L’ÉCHO DE LA VALLÉE DU LOIR ─────────────────────────────────────────────────────────────────
    {"name": "Le Petit Courrier - L’Écho de la Vallée du Loir", "url": "https://actu.fr/le-courrier-l-echo/rss.xml", "region": "Pays de la Loire"},

    # ── LE PETIT JOURNAL ─────────────────────────────────────────────────────────────────
    {"name": "Le Petit Journal : Ariège", "url": "https://www.lepetitjournal.net/09-ariege/feed/", "region": "Occitanie"},
    {"name": "Le Petit Journal : Aveyron", "url": "https://www.lepetitjournal.net/12-aveyron/feed/", "region": "Occitanie"},
    {"name": "Le Petit Journal : Gers", "url": "https://www.lepetitjournal.net/32-gers/feed/", "region": "Occitanie"},
    {"name": "Le Petit Journal : Hautes-Pyrénées", "url": "https://www.lepetitjournal.net/65-hautes-pyrenees/feed/", "region": "Occitanie"},
    {"name": "Le Petit Journal : Hérault", "url": "https://www.lepetitjournal.net/34-herault/feed/", "region": "Occitanie"},
    {"name": "Le Petit Journal : Lot", "url": "https://www.lepetitjournal.net/46-lot/feed/", "region": "Occitanie"},
    {"name": "Le Petit Journal : Lot-et-Garonne", "url": "https://www.lepetitjournal.net/47-lot-et-garonne/feed/", "region": "Nouvelle-Aquitaine"},
    {"name": "Le Petit Journal : Pyrénées-Orientales", "url": "https://www.lepetitjournal.net/66-pyrenees-orientales/feed/", "region": "Occitanie"},
    {"name": "Le Petit Journal : Tarn-et-Garonne", "url": "https://www.lepetitjournal.net/82-tarn-et-garonne/feed/", "region": "Occitanie"},
    {"name": "Le Petit Journal : département", "url": "https://www.lepetitjournal.net/thematique/departement/feed/", "region": "Occitanie"},
    {"name": "Le Petit Journal : faits divers", "url": "https://www.lepetitjournal.net/thematique/faits-divers/feed/", "region": "Occitanie"},

    # ── LE PLOËRMELAIS ─────────────────────────────────────────────────────────────────
    {"name": "Le Ploërmelais", "url": "https://actu.fr/le-ploermelais/rss.xml", "region": "Bretagne"},

    # ── LE POINT ─────────────────────────────────────────────────────────────────
    {"name": "Le Point : Lyon", "url": "https://www.lepoint.fr/arc/outboundfeeds/rss/tags_slug/lyon/", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Point : Marseille", "url": "https://www.lepoint.fr/arc/outboundfeeds/rss/tags_slug/marseille/", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Le Point : Nantes", "url": "https://www.lepoint.fr/arc/outboundfeeds/rss/tags_slug/nantes/", "region": "Pays de la Loire"},
    {"name": "Le Point : Paris", "url": "https://www.lepoint.fr/arc/outboundfeeds/rss/tags_slug/paris/", "region": "Île-de-France"},
    {"name": "Le Point : Rennes", "url": "https://www.lepoint.fr/arc/outboundfeeds/rss/tags_slug/rennes/", "region": "Bretagne"},
    {"name": "Le Point : Toulon", "url": "https://www.lepoint.fr/arc/outboundfeeds/rss/tags_slug/toulon/", "region": "Provence-Alpes-Côte d'Azur"},

    # ── LE PROGRÈS ─────────────────────────────────────────────────────────────────
    {"name": "Le Progrès : Ain", "url": "https://www.leprogres.fr/ain/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Progrès : Bresse - Dombes - Val de Saône - Côtière", "url": "https://www.leprogres.fr/edition-ain-ouest/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Progrès : Bugey et Haut-Bugey", "url": "https://www.leprogres.fr/edition-ain-est/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Progrès : Est Lyonnais", "url": "https://www.leprogres.fr/edition-est-lyonnais/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Progrès : Haute-Loire", "url": "https://www.leprogres.fr/haute-loire/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Progrès : Jura", "url": "https://www.leprogres.fr/jura/rss", "region": "Bourgogne-Franche-Comté"},
    {"name": "Le Progrès : Jura Nord", "url": "https://www.leprogres.fr/edition-jura-nord/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Progrès : Loire", "url": "https://www.leprogres.fr/loire/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Progrès : Lons et Jura Sud", "url": "https://www.leprogres.fr/edition-jura-sud/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Progrès : Lyon Villeurbanne", "url": "https://www.leprogres.fr/edition-lyon-villeurbanne/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Progrès : Nord Isère", "url": "https://www.leprogres.fr/isere/nord-isere/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Progrès : Ouest Lyonnais", "url": "https://www.leprogres.fr/edition-ouest-lyonnais/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Progrès : Rhône", "url": "https://www.leprogres.fr/rhone/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Progrès : Tarare", "url": "https://www.leprogres.fr/edition-tarare/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le Progrès : Villefranche", "url": "https://www.leprogres.fr/edition-villefranche/rss", "region": "Auvergne-Rhône-Alpes"},

    # ── LE PUBLICATEUR LIBRE ─────────────────────────────────────────────────────────────────
    {"name": "Le Publicateur libre", "url": "https://actu.fr/le-publicateur-libre/rss.xml", "region": "Normandie"},

    # ── LE RÉPUBLICAIN LORRAIN ─────────────────────────────────────────────────────────────────
    {"name": "Le Républicain Lorrain : Metz ville", "url": "https://www.republicain-lorrain.fr/edition-metz-et-agglomeration/rss", "region": "Grand Est"},

    # ── LE RÉPUBLICAIN LOT-ET-GARONNE ─────────────────────────────────────────────────────────────────
    {"name": "Le Républicain Lot-et-Garonne", "url": "https://actu.fr/le-republicain-lot-et-garonne/rss.xml", "region": "Nouvelle-Aquitaine"},

    # ── LE RÉPUBLICAIN SUD GIRONDE ─────────────────────────────────────────────────────────────────
    {"name": "Le Républicain Sud Gironde", "url": "https://actu.fr/le-republicain-sud-gironde/rss.xml", "region": "Nouvelle-Aquitaine"},

    # ── LE RÉVEIL NORMAND ─────────────────────────────────────────────────────────────────
    {"name": "Le Réveil Normand", "url": "https://actu.fr/le-reveil-normand/rss.xml", "region": "Normandie"},

    # ── LE RÉVEIL DE NEUFCHÂTEL ─────────────────────────────────────────────────────────────────
    {"name": "Le Réveil de Neufchâtel", "url": "https://actu.fr/le-reveil-de-neufchatel/rss.xml", "region": "Normandie"},

    # ── LE SINGULIER ─────────────────────────────────────────────────────────────────
    {"name": "Le Singulier", "url": "https://lesinguliersete.fr/feed/", "region": "Occitanie"},

    # ── LE TREGOR ─────────────────────────────────────────────────────────────────
    {"name": "Le Tregor", "url": "https://actu.fr/le-tregor/rss.xml", "region": "Bretagne"},

    # ── LE TÉLÉGRAMME ─────────────────────────────────────────────────────────────────
    {"name": "Le Télégramme", "url": "https://www.letelegramme.fr/rss.xml", "region": "Bretagne"},
    {"name": "Le Télégramme : Auray", "url": "https://www.letelegramme.fr/morbihan/auray-56400/rss.xml", "region": "Bretagne"},
    {"name": "Le Télégramme : Brest", "url": "https://www.letelegramme.fr/finistere/brest-29200/rss.xml", "region": "Bretagne"},
    {"name": "Le Télégramme : Bretagne", "url": "https://www.letelegramme.fr/bretagne/rss.xml", "region": "Bretagne"},
    {"name": "Le Télégramme : Carhaix", "url": "https://www.letelegramme.fr/finistere/carhaix-29270/rss.xml", "region": "Bretagne"},
    {"name": "Le Télégramme : Côtes d’Armor", "url": "https://www.letelegramme.fr/cotes-d-armor/rss.xml", "region": "Bretagne"},
    {"name": "Le Télégramme : Finistère", "url": "https://www.letelegramme.fr/finistere/rss.xml", "region": "Bretagne"},
    {"name": "Le Télégramme : Guidel", "url": "https://www.letelegramme.fr/morbihan/guidel-56520/rss.xml", "region": "Bretagne"},
    {"name": "Le Télégramme : Lannion", "url": "https://www.letelegramme.fr/cotes-d-armor/lannion-22300/rss.xml", "region": "Bretagne"},
    {"name": "Le Télégramme : Morbihan", "url": "https://www.letelegramme.fr/morbihan/rss.xml", "region": "Bretagne"},
    {"name": "Le Télégramme : Saint-Brieuc", "url": "https://www.letelegramme.fr/cotes-d-armor/saint-brieuc-22000/rss.xml", "region": "Bretagne"},

    # ── LE VILLEFRANCHOIS ─────────────────────────────────────────────────────────────────
    {"name": "Le Villefranchois", "url": "https://www.ladepeche.fr/le-villefranchois/rss.xml", "region": "Occitanie"},

    # ── LE CRIEUR ─────────────────────────────────────────────────────────────────
    {"name": "Le crieur", "url": "https://www.lecrieur.net/feed/", "region": "Auvergne-Rhône-Alpes"},

    # ── LE JOURNAL DE SAÔNE-ET-LOIRE ─────────────────────────────────────────────────────────────────
    {"name": "Le journal de Saône-et-Loire : Autun", "url": "https://www.lejsl.com/edition-autun/rss", "region": "Bourgogne-Franche-Comté"},
    {"name": "Le journal de Saône-et-Loire : Bresse", "url": "https://www.lejsl.com/edition-bresse/rss", "region": "Bourgogne-Franche-Comté"},
    {"name": "Le journal de Saône-et-Loire : Chalon-sur-Saône", "url": "https://www.lejsl.com/edition-chalon-sur-saone/rss", "region": "Bourgogne-Franche-Comté"},
    {"name": "Le journal de Saône-et-Loire : Charolais - Brionnais", "url": "https://www.lejsl.com/edition-charolais-brionnais/rss", "region": "Bourgogne-Franche-Comté"},
    {"name": "Le journal de Saône-et-Loire : Le Creusot", "url": "https://www.lejsl.com/edition-le-creusot/rss", "region": "Bourgogne-Franche-Comté"},
    {"name": "Le journal de Saône-et-Loire : Macon", "url": "https://www.lejsl.com/edition-macon/rss", "region": "Bourgogne-Franche-Comté"},
    {"name": "Le journal de Saône-et-Loire : Montceau-les-Mines", "url": "https://www.lejsl.com/edition-montceau-les-mines/rss", "region": "Bourgogne-Franche-Comté"},
    {"name": "Le journal de Saône-et-Loire : Saône-et-Loire", "url": "https://www.lejsl.com/saone-et-loire/rss", "region": "Bourgogne-Franche-Comté"},
    {"name": "Le journal de Saône-et-Loire : à la une", "url": "https://www.lejsl.com/rss", "region": "Bourgogne-Franche-Comté"},

    # ── LE JOURNAL DE LA HAUTE-MARNE ─────────────────────────────────────────────────────────────────
    {"name": "Le journal de la Haute-Marne", "url": "https://jhm.fr/feed/", "region": "Grand Est"},

    # ── LE JOURNAL DU GERS ─────────────────────────────────────────────────────────────────
    {"name": "Le journal du Gers", "url": "https://lejournaldugers.fr/fluxrss.xml", "region": "Occitanie"},

    # ── LE JOURNAL DU GRAND PARIS ─────────────────────────────────────────────────────────────────
    {"name": "Le journal du Grand Paris", "url": "https://www.lejournaldugrandparis.fr/feed/", "region": "Île-de-France"},
    {"name": "Le journal du Grand Paris : Paris", "url": "https://www.lejournaldugrandparis.fr/articles/territoires/grand-paris/feed/", "region": "Île-de-France"},

    # ── LE JOURNAL TOULOUSAIN ─────────────────────────────────────────────────────────────────
    {"name": "Le journal toulousain", "url": "https://www.lejournaltoulousain.fr/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Agde", "url": "https://www.lejournaltoulousain.fr/occitanie/herault/agde/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Alpes-de-Haute-Provence", "url": "https://www.lejournaltoulousain.fr/provence-alpes-cote-dazur/alpes-de-haute-provence/feed/", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Le journal toulousain : Ardèche", "url": "https://www.lejournaltoulousain.fr/auvergne-rhone-alpes/ardeche/feed/", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Le journal toulousain : Ariège", "url": "https://www.lejournaltoulousain.fr/occitanie/ariege/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Aude", "url": "https://www.lejournaltoulousain.fr/occitanie/aude/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Aveyron", "url": "https://www.lejournaltoulousain.fr/occitanie/aveyron/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Béziers", "url": "https://www.lejournaltoulousain.fr/occitanie/herault/beziers/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Essonne", "url": "https://www.lejournaltoulousain.fr/ile-de-france/essonne/feed/", "region": "Île-de-France"},
    {"name": "Le journal toulousain : Frontignan", "url": "https://www.lejournaltoulousain.fr/occitanie/herault/frontignan/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Gard", "url": "https://www.lejournaltoulousain.fr/occitanie/gard/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Gers", "url": "https://www.lejournaltoulousain.fr/occitanie/gers/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Haute-Garonne", "url": "https://www.lejournaltoulousain.fr/occitanie/haute-garonne/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Hautes-Pyrénées", "url": "https://www.lejournaltoulousain.fr/occitanie/hautes-pyrenees/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Hauts-de-Seine", "url": "https://www.lejournaltoulousain.fr/ile-de-france/hauts-de-seine/feed/", "region": "Île-de-France"},
    {"name": "Le journal toulousain : Hérault", "url": "https://www.lejournaltoulousain.fr/occitanie/herault/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Hérault : actualités", "url": "https://www.lejournaltoulousain.fr/occitanie/herault/actualites-herault/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Lot", "url": "https://www.lejournaltoulousain.fr/occitanie/lot/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Lot-et-Garonne", "url": "https://www.lejournaltoulousain.fr/aquitaine/lot-et-garonne/feed/", "region": "Nouvelle-Aquitaine"},
    {"name": "Le journal toulousain : Lozère", "url": "https://www.lejournaltoulousain.fr/occitanie/lozere/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Lunel", "url": "https://www.lejournaltoulousain.fr/occitanie/herault/lunel/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Montpellier", "url": "https://www.lejournaltoulousain.fr/occitanie/herault/montpellier/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Pyrénées-Orientales", "url": "https://www.lejournaltoulousain.fr/occitanie/pyrenees-orientales/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Seine-Saint-Denis", "url": "https://www.lejournaltoulousain.fr/ile-de-france/seine-saint-denis/feed/", "region": "Île-de-France"},
    {"name": "Le journal toulousain : Seine-et-Marne", "url": "https://www.lejournaltoulousain.fr/ile-de-france/seine-et-marne/feed/", "region": "Île-de-France"},
    {"name": "Le journal toulousain : Sète", "url": "https://www.lejournaltoulousain.fr/occitanie/herault/sete/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Tarn", "url": "https://www.lejournaltoulousain.fr/occitanie/tarn/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Tarn-et-Garonne", "url": "https://www.lejournaltoulousain.fr/occitanie/tarn-et-garonne/feed/", "region": "Occitanie"},
    {"name": "Le journal toulousain : Val-de-Marne", "url": "https://www.lejournaltoulousain.fr/ile-de-france/val-de-marne/feed/", "region": "Île-de-France"},

    # ── LE PETIT BLEU D’AGEN ─────────────────────────────────────────────────────────────────
    {"name": "Le petit bleu d’Agen", "url": "https://www.petitbleu.fr/rss.xml", "region": "Nouvelle-Aquitaine"},

    # ── LES ALPES MANCELLES ─────────────────────────────────────────────────────────────────
    {"name": "Les Alpes Mancelles", "url": "https://actu.fr/les-alpes-mancelles/rss.xml", "region": "Pays de la Loire"},

    # ── LES INFORMATIONS DIEPPOISES ─────────────────────────────────────────────────────────────────
    {"name": "Les Informations Dieppoises", "url": "https://actu.fr/les-informations-dieppoises/rss.xml", "region": "Normandie"},

    # ── LES INFOS DU PAYS DE REDON ─────────────────────────────────────────────────────────────────
    {"name": "Les Infos du Pays de Redon", "url": "https://actu.fr/infosredon/rss.xml", "region": "Bretagne"},

    # ── LES NOUVELLES DE FALAISE ─────────────────────────────────────────────────────────────────
    {"name": "Les Nouvelles de Falaise", "url": "https://actu.fr/les-nouvelles-de-falaise/rss.xml", "region": "Normandie"},

    # ── LES NOUVELLES DE SABLÉ ─────────────────────────────────────────────────────────────────
    {"name": "Les Nouvelles de Sablé", "url": "https://actu.fr/les-nouvelles-de-sable/rss.xml", "region": "Pays de la Loire"},

    # ── LES INFOS DU PAYS GALLO ─────────────────────────────────────────────────────────────────
    {"name": "Les infos du pays gallo", "url": "https://www.lesinfosdupaysgallo.com/feed/", "region": "Bretagne"},

    # ── LIBERTÉ CAEN ─────────────────────────────────────────────────────────────────
    {"name": "Liberté Caen", "url": "https://actu.fr/liberte-caen/rss.xml", "region": "Normandie"},

    # ── LIBÉRATION ─────────────────────────────────────────────────────────────────
    {"name": "Libération : Corse", "url": "https://www.liberation.fr/arc/outboundfeeds/rss/tags_slug/corse/?outputType=xml", "region": "Corse"},
    {"name": "Libération : Lyon", "url": "https://www.liberation.fr/arc/outboundfeeds/rss/tags_slug/lyon/?outputType=xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Libération : Marseille", "url": "https://www.liberation.fr/arc/outboundfeeds/rss/tags_slug/marseille/?outputType=xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Libération : Mayotte", "url": "https://www.liberation.fr/arc/outboundfeeds/rss/tags_slug/mayotte/?outputType=xml", "region": "Mayotte"},
    {"name": "Libération : Montpellier", "url": "https://www.liberation.fr/arc/outboundfeeds/rss/tags_slug/montpellier/?outputType=xml", "region": "Occitanie"},
    {"name": "Libération : Nice", "url": "https://www.liberation.fr/arc/outboundfeeds/rss/tags_slug/nice/?outputType=xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Libération : Paris", "url": "https://www.liberation.fr/arc/outboundfeeds/rss/tags_slug/paris/?outputType=xml", "region": "Île-de-France"},
    {"name": "Libération : Provence-Alpes-Côte d’Azur", "url": "https://www.liberation.fr/arc/outboundfeeds/rss/tags_slug/provence-alpes-cote-d-azur/?outputType=xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Libération : Rennes", "url": "https://www.liberation.fr/arc/outboundfeeds/rss/tags_slug/rennes/?outputType=xml", "region": "Bretagne"},
    {"name": "Libération : Toulon", "url": "https://www.liberation.fr/arc/outboundfeeds/rss/tags_slug/toulon/?outputType=xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Libération : Toulouse", "url": "https://www.liberation.fr/arc/outboundfeeds/rss/tags_slug/toulouse/?outputType=xml", "region": "Occitanie"},

    # ── LYON PEOPLE ─────────────────────────────────────────────────────────────────
    {"name": "Lyon People : actualité", "url": "https://www.lyonpeople.com/feed", "region": "Auvergne-Rhône-Alpes"},

    # ── LYON PREMIÈRE ─────────────────────────────────────────────────────────────────
    {"name": "Lyon Première", "url": "https://www.lyonpremiere.fr/feed/", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Lyon Première : L’info à Lyon", "url": "https://feed.ausha.co/B4dp7hpNwv9p", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Lyon Première : société", "url": "https://www.lyonpremiere.fr/category/societe/feed/", "region": "Auvergne-Rhône-Alpes"},

    # ── LYON CAPITALE ─────────────────────────────────────────────────────────────────
    {"name": "Lyon capitale", "url": "https://feeds.feedburner.com/lyoncapitale/8O4kDE6tmy9", "region": "Auvergne-Rhône-Alpes"},

    # ── LYONMAG ─────────────────────────────────────────────────────────────────
    {"name": "LyonMag", "url": "https://www.lyonmag.com/rss", "region": "Auvergne-Rhône-Alpes"},
    {"name": "LyonMag : faits divers", "url": "https://www.lyonmag.com/rss/category/36/faits-divers", "region": "Auvergne-Rhône-Alpes"},
    {"name": "LyonMag : société", "url": "https://www.lyonmag.com/rss/category/8/societe", "region": "Auvergne-Rhône-Alpes"},

    # ── L’ACTION - L’ÉCHO SARTHOIS ─────────────────────────────────────────────────────────────────
    {"name": "L’Action - L’Écho Sarthois", "url": "https://actu.fr/l-echo-sarthois/rss.xml", "region": "Pays de la Loire"},

    # ── L’ACTION RÉPUBLICAINE ─────────────────────────────────────────────────────────────────
    {"name": "L’Action Républicaine", "url": "https://actu.fr/l-action-republicaine/rss.xml", "region": "Centre-Val de Loire"},

    # ── L’AGATHOIS ─────────────────────────────────────────────────────────────────
    {"name": "L’Agathois", "url": "https://www.lagathois.fr/rssfeed.php", "region": "Occitanie"},

    # ── L’ALSACE ─────────────────────────────────────────────────────────────────
    {"name": "L’Alsace : Alsace", "url": "https://www.lalsace.fr/region/alsace/rss", "region": "Grand Est"},

    # ── L’EST RÉPUBLICAIN ─────────────────────────────────────────────────────────────────
    {"name": "L’Est Républicain : Belfort Héricourt-Montbéliard", "url": "https://www.estrepublicain.fr/edition-belfort-hericourt-montbeliard/rss", "region": "Bourgogne-Franche-Comté"},
    {"name": "L’Est Républicain : Franche-Comté", "url": "https://www.estrepublicain.fr/region/region-franche-comte/rss", "region": "Bourgogne-Franche-Comté"},
    {"name": "L’Est Républicain : Lorraine", "url": "https://www.estrepublicain.fr/region/region-lorraine/rss", "region": "Grand Est"},

    # ── L’HEBDO DE SÈVRE ET MAINE ─────────────────────────────────────────────────────────────────
    {"name": "L’Hebdo de Sèvre et Maine", "url": "https://actu.fr/l-hebdo-de-sevre-et-maine/rss.xml", "region": "Pays de la Loire"},

    # ── L’HUMANITÉ ─────────────────────────────────────────────────────────────────
    {"name": "L’Humanité : Bretagne", "url": "https://www.humanite.fr/mot-cle/bretagne/feed", "region": "Bretagne"},
    {"name": "L’Humanité : Corse", "url": "https://www.humanite.fr/mot-cle/corse/feed", "region": "Corse"},
    {"name": "L’Humanité : Hauts-de-France", "url": "https://www.humanite.fr/mot-cle/hauts-de-france/feed", "region": "Hauts-de-France"},
    {"name": "L’Humanité : Lyon", "url": "https://www.humanite.fr/mot-cle/lyon/feed", "region": "Auvergne-Rhône-Alpes"},
    {"name": "L’Humanité : Marseille", "url": "https://www.humanite.fr/mot-cle/marseille/feed", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "L’Humanité : Nice", "url": "https://www.humanite.fr/mot-cle/nice/feed", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "L’Humanité : Outre-mer", "url": "https://www.humanite.fr/mot-cle/outre-mer/feed", "region": None},
    {"name": "L’Humanité : Paris", "url": "https://www.humanite.fr/mot-cle/paris/feed", "region": "Île-de-France"},
    {"name": "L’Humanité : Rennes", "url": "https://www.humanite.fr/mot-cle/rennes/feed", "region": "Bretagne"},
    {"name": "L’Humanité : Île-de-France", "url": "https://www.humanite.fr/mot-cle/ile-de-france/feed", "region": "Île-de-France"},

    # ── L’IMPARTIAL ─────────────────────────────────────────────────────────────────
    {"name": "L’Impartial", "url": "https://actu.fr/l-impartial/rss.xml", "region": "Normandie"},

    # ── L’INDÉPENDANT ─────────────────────────────────────────────────────────────────
    {"name": "L’Indépendant : Agly", "url": "https://www.lindependant.fr/pyrenees-orientales/agly/rss.xml", "region": "Occitanie"},
    {"name": "L’Indépendant : Argelès-sur-Mer", "url": "https://www.lindependant.fr/pyrenees-orientales/argeles-sur-mer/rss.xml", "region": "Occitanie"},
    {"name": "L’Indépendant : Aude", "url": "https://www.lindependant.fr/aude/rss.xml", "region": "Occitanie"},
    {"name": "L’Indépendant : Carcassonne", "url": "https://www.lindependant.fr/aude/carcassonne/rss.xml", "region": "Occitanie"},
    {"name": "L’Indépendant : Castelnaudary", "url": "https://www.lindependant.fr/aude/castelnaudary/rss.xml", "region": "Occitanie"},
    {"name": "L’Indépendant : Céret", "url": "https://www.lindependant.fr/pyrenees-orientales/ceret/rss.xml", "region": "Occitanie"},
    {"name": "L’Indépendant : Limoux", "url": "https://www.lindependant.fr/aude/limoux/rss.xml", "region": "Occitanie"},
    {"name": "L’Indépendant : Lézignan-Corbières", "url": "https://www.lindependant.fr/aude/lezignan-corbieres/rss.xml", "region": "Occitanie"},
    {"name": "L’Indépendant : Marseille", "url": "https://www.lindependant.fr/communes/marseille/rss.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "L’Indépendant : Montpellier", "url": "https://www.lindependant.fr/communes/montpellier/rss.xml", "region": "Occitanie"},
    {"name": "L’Indépendant : Narbonne", "url": "https://www.lindependant.fr/aude/narbonne/rss.xml", "region": "Occitanie"},
    {"name": "L’Indépendant : Perpignan", "url": "https://www.lindependant.fr/pyrenees-orientales/perpignan/rss.xml", "region": "Occitanie"},
    {"name": "L’Indépendant : Port-la-Nouvelle", "url": "https://www.lindependant.fr/aude/port-la-nouvelle/rss.xml", "region": "Occitanie"},
    {"name": "L’Indépendant : Prades", "url": "https://www.lindependant.fr/pyrenees-orientales/prades/rss.xml", "region": "Occitanie"},
    {"name": "L’Indépendant : Pyrénées Orientales", "url": "https://www.lindependant.fr/pyrenees-orientales/rss.xml", "region": "Occitanie"},
    {"name": "L’Indépendant : Vinça", "url": "https://www.lindependant.fr/pyrenees-orientales/vinca/rss.xml", "region": "Occitanie"},

    # ── L’INFORMATEUR D’EU ─────────────────────────────────────────────────────────────────
    {"name": "L’Informateur d’Eu", "url": "https://actu.fr/l-informateur-d-eu/rss.xml", "region": "Normandie"},

    # ── L’ORNE COMBATTANTE ─────────────────────────────────────────────────────────────────
    {"name": "L’Orne Combattante", "url": "https://actu.fr/l-orne-combattante/rss.xml", "region": "Normandie"},

    # ── L’ORNE HEBDO ─────────────────────────────────────────────────────────────────
    {"name": "L’Orne Hebdo", "url": "https://actu.fr/orne-hebdo/rss.xml", "region": "Normandie"},

    # ── L’YONNE RÉPUBLICAINE ─────────────────────────────────────────────────────────────────
    {"name": "L’Yonne Républicaine : temps forts", "url": "https://feeds.feedburner.com/lyonne/dRdKplSLYOx", "region": "Bourgogne-Franche-Comté"},

    # ── L’HEBDO DU VENDREDI ─────────────────────────────────────────────────────────────────
    {"name": "L’hebdo du vendredi", "url": "https://static.lhebdoduvendredi.com/rss/infos.xml", "region": "Grand Est"},

    # ── L’ÉCHO DE LA PRESQU’ÎLE ─────────────────────────────────────────────────────────────────
    {"name": "L’Écho de la Presqu’île", "url": "https://actu.fr/l-echo-de-la-presqu-ile/rss.xml", "region": "Pays de la Loire"},

    # ── L’ÉCHO DE L’ARGOAT ─────────────────────────────────────────────────────────────────
    {"name": "L’Écho de l’Argoat", "url": "https://actu.fr/echo-argoat/rss.xml", "region": "Bretagne"},

    # ── L’ÉCLAIREUR DE CHÂTEAUBRIANT ─────────────────────────────────────────────────────────────────
    {"name": "L’Éclaireur de Châteaubriant", "url": "https://actu.fr/l-eclaireur-de-chateaubriant/rss.xml", "region": "Pays de la Loire"},

    # ── L’ÉCLAIREUR DE VIMEU ─────────────────────────────────────────────────────────────────
    {"name": "L’Éclaireur de Vimeu", "url": "https://actu.fr/l-eclaireur-du-vimeu/rss.xml", "region": "Hauts-de-France"},

    # ── L’ÉCLAIREUR DE LA DÉPÊCHE ─────────────────────────────────────────────────────────────────
    {"name": "L’Éclaireur de la Dépêche", "url": "https://actu.fr/l-eclaireur-la-depeche/rss.xml", "region": "Normandie"},

    # ── L’ÉVEIL NORMAND ─────────────────────────────────────────────────────────────────
    {"name": "L’Éveil Normand", "url": "https://actu.fr/l-eveil-normand/rss.xml", "region": "Normandie"},

    # ── L’ÉVEIL DE PONT-AUDEMER ─────────────────────────────────────────────────────────────────
    {"name": "L’Éveil de Pont-Audemer", "url": "https://actu.fr/l-eveil-de-pont-audemer/rss.xml", "region": "Normandie"},

    # ── MA COMMUNE ─────────────────────────────────────────────────────────────────
    {"name": "Ma commune : faits divers", "url": "https://www.macommune.info/?feed=actualite-faits-divers", "region": "Bourgogne-Franche-Comté"},
    {"name": "Ma commune : société", "url": "https://www.macommune.info/?feed=actualite-societe", "region": "Bourgogne-Franche-Comté"},
    {"name": "Ma commune : vie locale", "url": "https://www.macommune.info/?feed=actualite-vie-locale", "region": "Bourgogne-Franche-Comté"},
    {"name": "Ma commune : vimeo", "url": "https://vimeo.com/user32847306/videos/rss", "region": "Bourgogne-Franche-Comté"},
    {"name": "Ma commune : à la une", "url": "https://www.macommune.info/feed/", "region": "Bourgogne-Franche-Comté"},

    # ── MAVILLE ─────────────────────────────────────────────────────────────────
    {"name": "MaVille : Alençon", "url": "https://alencon.maville.com/flux/rss/actu.php?xtor=RSS-18&code=al", "region": "Normandie"},
    {"name": "MaVille : Angers", "url": "https://angers.maville.com/flux/rss/actu.php?xtor=RSS-18&code=an", "region": "Pays de la Loire"},
    {"name": "MaVille : Brest", "url": "https://brest.maville.com/flux/rss/actu.php?xtor=RSS-18&code=br", "region": "Bretagne"},
    {"name": "MaVille : Cannes", "url": "https://cannes.maville.com/flux/rss/actu.php?xtor=RSS-18&code=cn", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "MaVille : Cherbourg", "url": "https://cherbourg.maville.com/flux/rss/actu.php?xtor=RSS-18&code=ch", "region": "Normandie"},
    {"name": "MaVille : Cholet", "url": "https://cholet.maville.com/flux/rss/actu.php?xtor=RSS-18&code=co", "region": "Pays de la Loire"},
    {"name": "MaVille : Dinan", "url": "https://dinan.maville.com/flux/rss/actu.php?xtor=RSS-18&code=di", "region": "Bretagne"},
    {"name": "MaVille : Les Sables d’Olonne", "url": "https://lessablesdolonne.maville.com/flux/rss/actu.php?xtor=RSS-18&code=ls", "region": "Pays de la Loire"},
    {"name": "MaVille : Lille", "url": "https://lille.maville.com/flux/rss/actu.php?c=loc&code=li", "region": "Hauts-de-France"},
    {"name": "MaVille : Lille : actualité locale", "url": "https://lille.maville.com/flux/rss/actu.php?xtor=RSS-18&c=loc&code=li", "region": "Hauts-de-France"},
    {"name": "MaVille : Marseille", "url": "https://marseille.maville.com/flux/rss/actu.php?c=actu&code=om", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "MaVille : Nantes", "url": "https://nantes.maville.com/flux/rss/actu.php?xtor=RSS-18&code=na", "region": "Pays de la Loire"},
    {"name": "MaVille : Rennes", "url": "https://rennes.maville.com/flux/rss/actu.php?xtor=RSS-18&c=loc", "region": "Bretagne"},
    {"name": "MaVille : Saint-Brieuc", "url": "https://saint-brieuc.maville.com/flux/rss/actu.php?xtor=RSS-18&code=sb", "region": "Bretagne"},
    {"name": "MaVille : Saint-Lô", "url": "https://saint-lo.maville.com/flux/rss/actu.php?xtor=RSS-18&code=sl", "region": "Normandie"},
    {"name": "MaVille : Saint-Malo", "url": "https://saint-malo.maville.com/flux/rss/actu.php?xtor=RSS-18&code=sm", "region": "Bretagne"},
    {"name": "MaVille : Saint-Nazaire", "url": "https://saint-nazaire.maville.com/flux/rss/actu.php?xtor=RSS-18&code=sn", "region": "Pays de la Loire"},

    # ── MADE IN MARSEILLE ─────────────────────────────────────────────────────────────────
    {"name": "Made in Marseille", "url": "https://madeinmarseille.net/feed/", "region": "Provence-Alpes-Côte d'Azur"},

    # ── MAGCENTRE ─────────────────────────────────────────────────────────────────
    {"name": "MagCentre", "url": "https://www.magcentre.fr/feed/", "region": "Centre-Val de Loire"},

    # ── MARSACTU ─────────────────────────────────────────────────────────────────
    {"name": "MarsActu", "url": "https://marsactu.fr/feed/", "region": "Provence-Alpes-Côte d'Azur"},

    # ── MEDIABASK ─────────────────────────────────────────────────────────────────
    {"name": "Mediabask", "url": "https://www.mediabask.eus/es/rss/sections/mediabask.rss", "region": "Nouvelle-Aquitaine"},

    # ── MEDIALOT ─────────────────────────────────────────────────────────────────
    {"name": "Medialot", "url": "https://medialot.fr/feed/", "region": "Occitanie"},

    # ── MES INFOS ─────────────────────────────────────────────────────────────────
    {"name": "Mes infos : Provence-Alpes-Côte d’Azur", "url": "https://mesinfos.fr/provence-alpes-cote-d-azur/rss.xml", "region": "Provence-Alpes-Côte d'Azur"},

    # ── MIDI LIBRE ─────────────────────────────────────────────────────────────────
    {"name": "Midi Libre : Agde", "url": "https://www.midilibre.fr/herault/agde/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Alès", "url": "https://www.midilibre.fr/gard/ales/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Aude", "url": "https://www.midilibre.fr/aude/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Aveyron", "url": "https://www.midilibre.fr/aveyron/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Bagnols-sur-Cèze", "url": "https://www.midilibre.fr/gard/bagnols-sur-ceze/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Bretagne", "url": "https://www.midilibre.fr/communes/bretagne/rss.xml", "region": "Bretagne"},
    {"name": "Midi Libre : Béziers", "url": "https://www.midilibre.fr/herault/beziers/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Carcassonne", "url": "https://www.midilibre.fr/aude/carcassonne/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Gard", "url": "https://www.midilibre.fr/gard/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Hérault", "url": "https://www.midilibre.fr/herault/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Lozère", "url": "https://www.midilibre.fr/lozere/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Lunel", "url": "https://www.midilibre.fr/herault/lunel/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Mayotte", "url": "https://www.midilibre.fr/actu/monde/mayotte/rss.xml", "region": "Mayotte"},
    {"name": "Midi Libre : Mende", "url": "https://www.midilibre.fr/lozere/mende/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Millau", "url": "https://www.midilibre.fr/aveyron/millau/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Montpellier", "url": "https://www.midilibre.fr/herault/montpellier/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Narbonne", "url": "https://www.midilibre.fr/aude/narbonne/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Nîmes", "url": "https://www.midilibre.fr/gard/nimes/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Perpignan", "url": "https://www.midilibre.fr/pyrenees-orientales/perpignan/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Pyrénées-Orientales", "url": "https://www.midilibre.fr/pyrenees-orientales/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Rodez", "url": "https://www.midilibre.fr/aveyron/rodez/rss.xml", "region": "Occitanie"},
    {"name": "Midi Libre : Sète", "url": "https://www.midilibre.fr/herault/sete/rss.xml", "region": "Occitanie"},

    # ── MILLAVOIS ─────────────────────────────────────────────────────────────────
    {"name": "Millavois : actualité", "url": "https://millavois.com/feed/", "region": "Occitanie"},

    # ── MÉTROPOLITAIN ─────────────────────────────────────────────────────────────────
    {"name": "Métropolitain", "url": "https://actu.fr/metropolitain/rss.xml", "region": "Occitanie"},

    # ── NICE MAG ─────────────────────────────────────────────────────────────────
    {"name": "Nice Mag : actualités", "url": "https://www.nicemag.fr/rss", "region": "Provence-Alpes-Côte d'Azur"},

    # ── NICE PREMIUM ─────────────────────────────────────────────────────────────────
    {"name": "Nice premium : actualités", "url": "https://www.nicepremium.fr/feed/", "region": "Provence-Alpes-Côte d'Azur"},

    # ── NICE PRESSE ─────────────────────────────────────────────────────────────────
    {"name": "Nice presse : actualité", "url": "https://nicepresse.com/feed/", "region": "Provence-Alpes-Côte d'Azur"},

    # ── NICE-MATIN ─────────────────────────────────────────────────────────────────
    {"name": "Nice-Matin : 80 ans de Nice-Matin", "url": "https://www.nicematin.com/80-ans-de-nice-matin/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Nice-Matin : Antibes", "url": "https://www.nicematin.com/alpes-maritimes/antibes/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Nice-Matin : Cagnes-sur-Mer", "url": "https://www.nicematin.com/alpes-maritimes/cagnes/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Nice-Matin : Cannes", "url": "https://www.nicematin.com/alpes-maritimes/cannes/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Nice-Matin : Côte d’Azur", "url": "https://www.nicematin.com/ville/cote-d-azur/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Nice-Matin : Grasse", "url": "https://www.nicematin.com/alpes-maritimes/grasse/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Nice-Matin : Menton", "url": "https://www.nicematin.com/alpes-maritimes/menton/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Nice-Matin : Nice", "url": "https://www.nicematin.com/alpes-maritimes/nice/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Nice-Matin : Saint-Laurent-du-Var", "url": "https://www.nicematin.com/commune/saint-laurent-du-var/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Nice-Matin : Vallées", "url": "https://www.nicematin.com/alpes-maritimes/vallees/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Nice-Matin : Vence", "url": "https://www.nicematin.com/alpes-maritimes/vence/rss", "region": "Provence-Alpes-Côte d'Azur"},

    # ── OBJECTIF GARD ─────────────────────────────────────────────────────────────────
    {"name": "Objectif Gard", "url": "https://www.objectifgard.com/feed/", "region": "Occitanie"},
    {"name": "Objectif Gard : Arles", "url": "https://www.objectifgard.com/gard/arles/feed/", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Objectif Gard : Camargue", "url": "https://www.objectifgard.com/gard/camargue/feed/", "region": "Provence-Alpes-Côte d'Azur"},

    # ── ORIZONTE ─────────────────────────────────────────────────────────────────
    {"name": "Orizonte", "url": "https://www.orizonte.corsica/feed/", "region": "Corse"},

    # ── PARIS DÉPÊCHES ─────────────────────────────────────────────────────────────────
    {"name": "Paris Dépêches : Paris 75", "url": "https://www.parisdepeches.fr/128-Paris_75/rss.html", "region": "Île-de-France"},

    # ── PAROLES DE CORSE ─────────────────────────────────────────────────────────────────
    {"name": "Paroles de Corse", "url": "http://www.parolesdecorse.fr/feed/", "region": "Corse"},

    # ── PLACE GRE’NET ─────────────────────────────────────────────────────────────────
    {"name": "Place Gre’net", "url": "https://feeds.feedburner.com/placegrenet/e48RNVQMu5p", "region": "Auvergne-Rhône-Alpes"},

    # ── PONTIVY JOURNAL ─────────────────────────────────────────────────────────────────
    {"name": "Pontivy Journal", "url": "https://actu.fr/pontivy-journal/rss.xml", "region": "Bretagne"},

    # ── RCFM ─────────────────────────────────────────────────────────────────
    {"name": "RCFM : actualités", "url": "https://www.ici.fr/rss/rcfm/rubrique/infos.xml", "region": "Corse"},
    {"name": "RCFM : à la une", "url": "https://www.ici.fr/rss/rcfm/a-la-une.xml", "region": "Corse"},

    # ── RCI ─────────────────────────────────────────────────────────────────
    {"name": "RCI : émissions", "url": "https://rci.websiteradio.co/rss-feed-7", "region": "Corse"},

    # ── RCI - RADIO CARAÏBES INTERNATIONAL ─────────────────────────────────────────────────────────────────
    {"name": "RCI - Radio Caraïbes International : Guadeloupe", "url": "https://rci.fm/guadeloupe/fb/articles_rss_mq", "region": "Guadeloupe"},
    {"name": "RCI - Radio Caraïbes International : Martinique", "url": "https://rci.fm/martinique/fb/articles_rss_mq", "region": "Martinique"},

    # ── RFI ─────────────────────────────────────────────────────────────────
    {"name": "RFI : Guyane", "url": "https://www.rfi.fr/fr/tag/guyane/rss", "region": "Guyane"},
    {"name": "RFI : Martinique", "url": "https://www.rfi.fr/fr/tag/martinique/rss", "region": "Martinique"},
    {"name": "RFI : Nouvelle-Calédonie", "url": "https://www.rfi.fr/fr/tag/nouvelle-cal%C3%A9donie/rss", "region": "Nouvelle-Calédonie"},
    {"name": "RFI : Paris", "url": "https://www.rfi.fr/fr/tag/paris/rss", "region": "Île-de-France"},

    # ── RADIO CALVI ─────────────────────────────────────────────────────────────────
    {"name": "Radio Calvi", "url": "https://fetchrss.com/feed/1iIaFxGYM4cZ1tmygH1DiFbo.rss", "region": "Corse"},

    # ── REVUE FAR OUEST ─────────────────────────────────────────────────────────────────
    {"name": "Revue Far Ouest", "url": "https://www.revue-farouest.fr/feed/", "region": "Nouvelle-Aquitaine"},

    # ── RUE89 ─────────────────────────────────────────────────────────────────
    {"name": "Rue89 : Bordeaux", "url": "https://rue89bordeaux.com/feed/", "region": "Nouvelle-Aquitaine"},
    {"name": "Rue89 : Lyon", "url": "https://www.rue89lyon.fr/feed/", "region": "Auvergne-Rhône-Alpes"},
    {"name": "Rue89 : Strasbourg", "url": "https://www.rue89strasbourg.com/feed", "region": "Grand Est"},

    # ── RÉUSSIR LE PÉRIGORD ─────────────────────────────────────────────────────────────────
    {"name": "Réussir le Périgord", "url": "https://actu.fr/reussir-le-perigord/rss.xml", "region": "Nouvelle-Aquitaine"},

    # ── SUD OUEST ─────────────────────────────────────────────────────────────────
    {"name": "Sud Ouest : Agen", "url": "https://www.sudouest.fr/lot-et-garonne/agen/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Angoulême", "url": "https://www.sudouest.fr/charente/angouleme/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Arcachon", "url": "https://www.sudouest.fr/gironde/arcachon/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Bayonne", "url": "https://www.sudouest.fr/pyrenees-atlantiques/bayonne/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Biarritz", "url": "https://www.sudouest.fr/pyrenees-atlantiques/biarritz/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Bordeaux", "url": "https://www.sudouest.fr/gironde/bordeaux/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Cognac", "url": "https://www.sudouest.fr/charente/cognac/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Dax", "url": "https://www.sudouest.fr/landes/dax/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Gers", "url": "https://www.sudouest.fr/gers/rss.xml", "region": "Occitanie"},
    {"name": "Sud Ouest : La Rochelle", "url": "https://www.sudouest.fr/charente-maritime/la-rochelle/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Langon", "url": "https://www.sudouest.fr/gironde/langon/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Libourne", "url": "https://www.sudouest.fr/gironde/libourne/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Mont-de-Marsan", "url": "https://www.sudouest.fr/landes/mont-de-marsan/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Morcenx", "url": "https://www.sudouest.fr/landes/morcenx/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Pau", "url": "https://www.sudouest.fr/pyrenees-atlantiques/pau/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Périgueux", "url": "https://www.sudouest.fr/dordogne/perigueux/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Royan", "url": "https://www.sudouest.fr/charente-maritime/royan/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Saint-Etienne de Baigorry", "url": "https://www.sudouest.fr/pyrenees-atlantiques/saint-etienne-de-baigorry/rss.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "Sud Ouest : Saintes", "url": "https://www.sudouest.fr/charente-maritime/saintes/rss.xml", "region": "Nouvelle-Aquitaine"},

    # ── TV83 ─────────────────────────────────────────────────────────────────
    {"name": "TV83", "url": "https://www.tv83.info/feed/", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "TV83 : actualités varoises", "url": "https://www.tv83.info/category/actualites-varoises/feed/", "region": "Provence-Alpes-Côte d'Azur"},

    # ── TAHITI INFO ─────────────────────────────────────────────────────────────────
    {"name": "Tahiti info", "url": "https://www.tahiti-infos.com/xml/syndication.rss", "region": "Polynésie française"},

    # ── TERRA ─────────────────────────────────────────────────────────────────
    {"name": "Terra", "url": "https://actu.fr/terra/rss.xml", "region": "Bretagne"},

    # ── TOULOUSCOPE ─────────────────────────────────────────────────────────────────
    {"name": "Toulouscope", "url": "https://www.toulouscope.fr/rss.xml", "region": "Occitanie"},

    # ── TOULOUSE7 ─────────────────────────────────────────────────────────────────
    {"name": "Toulouse7", "url": "https://toulouse7.com/feed/", "region": "Occitanie"},

    # ── TOUT LYON ─────────────────────────────────────────────────────────────────
    {"name": "Tout Lyon", "url": "https://mesinfos.fr/tout-lyon/rss.xml", "region": "Auvergne-Rhône-Alpes"},

    # ── TÉLÉPAESE ─────────────────────────────────────────────────────────────────
    {"name": "TéléPaese", "url": "https://stampa-paese.com/rss.xml", "region": "Corse"},

    # ── VAR INFORMATION ─────────────────────────────────────────────────────────────────
    {"name": "Var Information", "url": "https://mesinfos.fr/var-information/rss.xml", "region": "Provence-Alpes-Côte d'Azur"},

    # ── VAR INFOS ─────────────────────────────────────────────────────────────────
    {"name": "Var infos", "url": "https://www.varinfos.fr/rss-feed-1", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Var infos : vie locale", "url": "https://www.varinfos.fr/rss-feed-1-141", "region": "Provence-Alpes-Côte d'Azur"},

    # ── VAR-MATIN ─────────────────────────────────────────────────────────────────
    {"name": "Var-Matin : Brignoles", "url": "https://www.nicematin.com/var/brignoles/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Var-Matin : Draguignan", "url": "https://www.nicematin.com/var/draguignan/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Var-Matin : Fréjus", "url": "https://www.nicematin.com/var/frejus/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Var-Matin : Hyères", "url": "https://www.nicematin.com/var/hyeres/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Var-Matin : La Seyne-sur-Mer", "url": "https://www.nicematin.com/var/la-seyne/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Var-Matin : Saint-Raphaël", "url": "https://www.nicematin.com/var/st-raphael/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Var-Matin : Saint-Tropez", "url": "https://www.nicematin.com/var/saint-tropez/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Var-Matin : Sainte-Maxime", "url": "https://www.nicematin.com/var/sainte-maxime/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Var-Matin : Sanary-sur-Mer", "url": "https://www.nicematin.com/var/sanary-sur-mer/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Var-Matin : Toulon", "url": "https://www.nicematin.com/var/toulon/rss", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "Var-Matin : Var", "url": "https://www.nicematin.com/var/rss", "region": "Provence-Alpes-Côte d'Azur"},

    # ── VAUCLUSE HEBDO ─────────────────────────────────────────────────────────────────
    {"name": "Vaucluse Hebdo", "url": "https://mesinfos.fr/vaucluse-hebdo/rss.xml", "region": "Provence-Alpes-Côte d'Azur"},

    # ── VENTOUX MAGAZINE ─────────────────────────────────────────────────────────────────
    {"name": "Ventoux magazine", "url": "http://www.ventoux-magazine.com/feed/", "region": "Provence-Alpes-Côte d'Azur"},

    # ── VIASTELLA ─────────────────────────────────────────────────────────────────
    {"name": "ViaStella : Ajaccio", "url": "https://france3-regions.franceinfo.fr/corse/corse-du-sud/ajaccio/rss", "region": "Corse"},
    {"name": "ViaStella : Corse-du-Sud", "url": "https://france3-regions.franceinfo.fr/corse/corse-du-sud/rss", "region": "Corse"},
    {"name": "ViaStella : Haute-Corse", "url": "https://france3-regions.franceinfo.fr/corse/haute-corse/rss", "region": "Corse"},
    {"name": "ViaStella : info", "url": "https://france3-regions.franceinfo.fr/corse/actu/rss", "region": "Corse"},

    # ── VOIX DU JURA ─────────────────────────────────────────────────────────────────
    {"name": "Voix du Jura", "url": "https://actu.fr/voix-du-jura/rss.xml", "region": "Bourgogne-Franche-Comté"},

    # ── VOIX DU MIDI LAURAGAIS ─────────────────────────────────────────────────────────────────
    {"name": "Voix du Midi Lauragais", "url": "https://actu.fr/voix-du-midi-lauragais/rss.xml", "region": "Occitanie"},

    # ── VOSGES INFO ─────────────────────────────────────────────────────────────────
    {"name": "Vosges Info : Gerardmer", "url": "https://vosgesinfo.fr/gerardmerinfo/feed/", "region": "Grand Est"},
    {"name": "Vosges Info : La Plaine", "url": "https://vosgesinfo.fr/laplainedesvosgesinfo/feed/", "region": "Grand Est"},
    {"name": "Vosges Info : Remiremont", "url": "https://vosgesinfo.fr/remiremontinfo/feed/", "region": "Grand Est"},
    {"name": "Vosges Info : Saint-Dié", "url": "https://vosgesinfo.fr/saintdieinfo/feed/", "region": "Grand Est"},
    {"name": "Vosges Info : Vosges", "url": "https://vosgesinfo.fr/feed/", "region": "Grand Est"},
    {"name": "Vosges Info : Épinal", "url": "https://vosgesinfo.fr/epinalinfo/feed/", "region": "Grand Est"},

    # ── VOSGES MATIN ─────────────────────────────────────────────────────────────────
    {"name": "Vosges Matin : Vosges", "url": "https://www.vosgesmatin.fr/vosges/rss", "region": "Grand Est"},

    # ── VOSGES TÉLÉVISION ─────────────────────────────────────────────────────────────────
    {"name": "Vosges Télévision", "url": "https://www.vosgestelevision.tv/rss/actus.php", "region": "Grand Est"},

    # ── ICI ─────────────────────────────────────────────────────────────────
    {"name": "ici : Alsace : actualités", "url": "https://www.ici.fr/rss/alsace/rubrique/infos.xml", "region": "Grand Est"},
    {"name": "ici : Alsace : à la une", "url": "https://www.ici.fr/rss/alsace/a-la-une.xml", "region": "Grand Est"},
    {"name": "ici : Armorique : actualités", "url": "https://www.ici.fr/rss/armorique/rubrique/infos.xml", "region": "Bretagne"},
    {"name": "ici : Armorique : à la une", "url": "https://www.ici.fr/rss/armorique/a-la-une.xml", "region": "Bretagne"},
    {"name": "ici : Azur : actualités", "url": "https://www.ici.fr/rss/azur/rubrique/infos.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "ici : Azur : à la une", "url": "https://www.ici.fr/rss/azur/a-la-une.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "ici : Belfort-Montbéliard : actualités", "url": "https://www.ici.fr/rss/belfort-montbeliard/rubrique/infos.xml", "region": "Bourgogne-Franche-Comté"},
    {"name": "ici : Belfort-Montbéliard : à la une", "url": "https://www.ici.fr/rss/belfort-montbeliard/a-la-une.xml", "region": "Bourgogne-Franche-Comté"},
    {"name": "ici : Berry : actualités", "url": "https://www.ici.fr/rss/berry/rubrique/infos.xml", "region": "Centre-Val de Loire"},
    {"name": "ici : Berry : à la une", "url": "https://www.ici.fr/rss/berry/a-la-une.xml", "region": "Centre-Val de Loire"},
    {"name": "ici : Besançon : actualités", "url": "https://www.ici.fr/rss/besancon/rubrique/infos.xml", "region": "Bourgogne-Franche-Comté"},
    {"name": "ici : Besançon : à la une", "url": "https://www.ici.fr/rss/besancon/a-la-une.xml", "region": "Bourgogne-Franche-Comté"},
    {"name": "ici : Bourgogne : actualités", "url": "https://www.ici.fr/rss/bourgogne/rubrique/infos.xml", "region": "Bourgogne-Franche-Comté"},
    {"name": "ici : Bourgogne : à la une", "url": "https://www.ici.fr/rss/bourgogne/a-la-une.xml", "region": "Bourgogne-Franche-Comté"},
    {"name": "ici : Breizh Izel : actualités", "url": "https://www.ici.fr/rss/breizh-izel/rubrique/infos.xml", "region": "Bretagne"},
    {"name": "ici : Breizh Izel : à la une", "url": "https://www.ici.fr/rss/breizh-izel/a-la-une.xml", "region": "Bretagne"},
    {"name": "ici : Béarn : actualités", "url": "https://www.ici.fr/rss/bearn/rubrique/infos.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Béarn : à la une", "url": "https://www.ici.fr/rss/bearn/a-la-une.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Calvados et Orne : actualités", "url": "https://www.ici.fr/rss/normandie-caen/rubrique/infos.xml", "region": "Normandie"},
    {"name": "ici : Calvados et Orne : à la une", "url": "https://www.ici.fr/rss/normandie-caen/a-la-une.xml", "region": "Normandie"},
    {"name": "ici : Champagne-Ardenne : actualités", "url": "https://www.ici.fr/rss/champagne-ardenne/rubrique/infos.xml", "region": "Grand Est"},
    {"name": "ici : Champagne-Ardenne : à la une", "url": "https://www.ici.fr/rss/champagne-ardenne/a-la-une.xml", "region": "Grand Est"},
    {"name": "ici : Cotentin : actualités", "url": "https://www.ici.fr/rss/cotentin/rubrique/infos.xml", "region": "Normandie"},
    {"name": "ici : Cotentin : à la une", "url": "https://www.ici.fr/rss/cotentin/a-la-une.xml", "region": "Normandie"},
    {"name": "ici : Creuse : actualités", "url": "https://www.ici.fr/rss/creuse/rubrique/infos.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Creuse : à la une", "url": "https://www.ici.fr/rss/creuse/a-la-une.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Drôme et Ardèche : actualités", "url": "https://www.ici.fr/rss/drome-ardeche/rubrique/infos.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "ici : Drôme et Ardèche : à la une", "url": "https://www.ici.fr/rss/drome-ardeche/a-la-une.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "ici : Elsass : actualités", "url": "https://www.ici.fr/rss/elsass/rubrique/infos.xml", "region": "Grand Est"},
    {"name": "ici : Elsass : à la une", "url": "https://www.ici.fr/rss/elsass/a-la-une.xml", "region": "Grand Est"},
    {"name": "ici : Gard Lozère : actualités", "url": "https://www.ici.fr/rss/gard-lozere/rubrique/infos.xml", "region": "Occitanie"},
    {"name": "ici : Gard Lozère : à la une", "url": "https://www.ici.fr/rss/gard-lozere/a-la-une.xml", "region": "Occitanie"},
    {"name": "ici : Gascogne : actualités", "url": "https://www.ici.fr/rss/gascogne/rubrique/infos.xml", "region": "Occitanie"},
    {"name": "ici : Gascogne : à la une", "url": "https://www.ici.fr/rss/gascogne/a-la-une.xml", "region": "Occitanie"},
    {"name": "ici : Gironde : actualités", "url": "https://www.ici.fr/rss/gironde/rubrique/infos.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Gironde : à la une", "url": "https://www.ici.fr/rss/gironde/a-la-une.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Hérault : actualités", "url": "https://www.ici.fr/rss/herault/rubrique/infos.xml", "region": "Occitanie"},
    {"name": "ici : Isère : actualités", "url": "https://www.ici.fr/rss/isere/rubrique/infos.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "ici : Isère : à la une", "url": "https://www.ici.fr/rss/isere/a-la-une.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "ici : La Rochelle : actualités", "url": "https://www.ici.fr/rss/la-rochelle/rubrique/infos.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : La Rochelle : à la une", "url": "https://www.ici.fr/rss/la-rochelle/a-la-une.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Limousin : actualités", "url": "https://www.ici.fr/rss/limousin/rubrique/infos.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Limousin : à la une", "url": "https://www.ici.fr/rss/limousin/a-la-une.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Loire Océan : actualités", "url": "https://www.ici.fr/rss/loire-ocean/rubrique/infos.xml", "region": "Pays de la Loire"},
    {"name": "ici : Loire Océan : à la une", "url": "https://www.ici.fr/rss/loire-ocean/a-la-une.xml", "region": "Pays de la Loire"},
    {"name": "ici : Lorraine, Meurthe-et-Moselle et Vosges : actualités", "url": "https://www.ici.fr/rss/sud-lorraine/rubrique/infos.xml", "region": "Grand Est"},
    {"name": "ici : Lorraine, Meurthe-et-Moselle et Vosges : à la une", "url": "https://www.ici.fr/rss/sud-lorraine/a-la-une.xml", "region": "Grand Est"},
    {"name": "ici : Lorraine, Moselle et Pays Haut : actualités", "url": "https://www.ici.fr/rss/lorraine-nord/rubrique/infos.xml", "region": "Grand Est"},
    {"name": "ici : Lorraine, Moselle et Pays Haut : à la une", "url": "https://www.ici.fr/rss/lorraine-nord/a-la-une.xml", "region": "Grand Est"},
    {"name": "ici : Maine : actualités", "url": "https://www.ici.fr/rss/maine/rubrique/infos.xml", "region": "Pays de la Loire"},
    {"name": "ici : Maine : à la une", "url": "https://www.ici.fr/rss/maine/a-la-une.xml", "region": "Pays de la Loire"},
    {"name": "ici : Mayenne : actualités", "url": "https://www.ici.fr/rss/mayenne/rubrique/infos.xml", "region": "Pays de la Loire"},
    {"name": "ici : Mayenne : à la une", "url": "https://www.ici.fr/rss/mayenne/a-la-une.xml", "region": "Pays de la Loire"},
    {"name": "ici : Nord : actualités", "url": "https://www.ici.fr/rss/nord/rubrique/infos.xml", "region": "Hauts-de-France"},
    {"name": "ici : Nord : à la une", "url": "https://www.ici.fr/rss/nord/a-la-une.xml", "region": "Hauts-de-France"},
    {"name": "ici : Occitanie : actualités", "url": "https://www.ici.fr/rss/toulouse/rubrique/infos.xml", "region": "Occitanie"},
    {"name": "ici : Occitanie : à la une", "url": "https://www.ici.fr/rss/toulouse/a-la-une.xml", "region": "Occitanie"},
    {"name": "ici : Orléans : actualités", "url": "https://www.ici.fr/rss/orleans/rubrique/infos.xml", "region": "Centre-Val de Loire"},
    {"name": "ici : Orléans : à la une", "url": "https://www.ici.fr/rss/orleans/a-la-une.xml", "region": "Centre-Val de Loire"},
    {"name": "ici : Paris : actualités", "url": "https://www.ici.fr/rss/107-1/rubrique/infos.xml", "region": "Île-de-France"},
    {"name": "ici : Paris : à la une", "url": "https://www.ici.fr/rss/107-1/a-la-une.xml", "region": "Île-de-France"},
    {"name": "ici : Pays basque : actualités", "url": "https://www.ici.fr/rss/pays-basque/rubrique/infos.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Pays basque : à la une", "url": "https://www.ici.fr/rss/pays-basque/a-la-une.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Pays de Savoie : actualités", "url": "https://www.ici.fr/rss/pays-de-savoie/rubrique/infos.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "ici : Pays de Savoie : à la une", "url": "https://www.ici.fr/rss/pays-de-savoie/a-la-une.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "ici : Pays d’Auvergne : actualités", "url": "https://www.ici.fr/rss/pays-d-auvergne/rubrique/infos.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "ici : Pays d’Auvergne : à la une", "url": "https://www.ici.fr/rss/pays-d-auvergne/a-la-une.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "ici : Picardie : actualités", "url": "https://www.ici.fr/rss/picardie/rubrique/infos.xml", "region": "Hauts-de-France"},
    {"name": "ici : Picardie : à la une", "url": "https://www.ici.fr/rss/picardie/a-la-une.xml", "region": "Hauts-de-France"},
    {"name": "ici : Poitou : actualités", "url": "https://www.ici.fr/rss/poitou/rubrique/infos.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Poitou : à la une", "url": "https://www.ici.fr/rss/poitou/a-la-une.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Provence : actualités", "url": "https://www.ici.fr/rss/provence/rubrique/infos.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "ici : Provence : à la une", "url": "https://www.ici.fr/rss/provence/a-la-une.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "ici : Périgord : actualités", "url": "https://www.ici.fr/rss/perigord/rubrique/infos.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Périgord : à la une", "url": "https://www.ici.fr/rss/perigord/a-la-une.xml", "region": "Nouvelle-Aquitaine"},
    {"name": "ici : Roussillon : actualité", "url": "https://www.ici.fr/rss/roussillon/rubrique/infos.xml", "region": "Occitanie"},
    {"name": "ici : Roussillon : à la une", "url": "https://www.ici.fr/rss/roussillon/a-la-une.xml", "region": "Occitanie"},
    {"name": "ici : Saint-Étienne Loire : actualités", "url": "https://www.ici.fr/rss/saint-etienne-loire/rubrique/infos.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "ici : Saint-Étienne Loire : à la une", "url": "https://www.ici.fr/rss/saint-etienne-loire/a-la-une.xml", "region": "Auvergne-Rhône-Alpes"},
    {"name": "ici : Seine-Maritime et Eure : actualité", "url": "https://www.ici.fr/rss/normandie-rouen/rubrique/infos.xml", "region": "Normandie"},
    {"name": "ici : Seine-Maritime et Eure : à la une", "url": "https://www.ici.fr/rss/normandie-rouen/a-la-une.xml", "region": "Normandie"},
    {"name": "ici : Touraine : actualités", "url": "https://www.ici.fr/rss/touraine/rubrique/infos.xml", "region": "Centre-Val de Loire"},
    {"name": "ici : Touraine : à la une", "url": "https://www.ici.fr/rss/touraine/a-la-une.xml", "region": "Centre-Val de Loire"},
    {"name": "ici : Vaucluse : actualités", "url": "https://www.ici.fr/rss/vaucluse/rubrique/infos.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "ici : Vaucluse : à la une", "url": "https://www.ici.fr/rss/vaucluse/a-la-une.xml", "region": "Provence-Alpes-Côte d'Azur"},
    {"name": "ici : Yonne : actualités", "url": "https://www.ici.fr/rss/auxerre/rubrique/infos.xml", "region": "Bourgogne-Franche-Comté"},
    {"name": "ici : Yonne : à la une", "url": "https://www.ici.fr/rss/auxerre/a-la-une.xml", "region": "Bourgogne-Franche-Comté"},

    # ── MLYON ─────────────────────────────────────────────────────────────────
    {"name": "mLyon", "url": "https://mlyon.fr/xml/news", "region": "Auvergne-Rhône-Alpes"},

    # ── FORMULE 1 ─────────────────────────────────────────────────────────────
    {"name": "Motorsport F1",      "url": "https://fr.motorsport.com/rss/f1/news/",            "region": None},
    {"name": "F1 Only",            "url": "https://f1only.fr/feed/",                            "region": None},
    {"name": "L'Équipe Auto/Moto", "url": "https://d3.lequipe.fr/rss/v2/rss_auto-moto.xml",    "region": None},

    # ── JEUX VIDÉO ────────────────────────────────────────────────────────────
    {"name": "Jeux Vidéo.com",     "url": "https://www.jeuxvideo.com/rss/rss.xml",              "region": None},
    {"name": "Gamekult",           "url": "https://www.gamekult.com/feed.xml",                  "region": None},
    {"name": "Dexerto Esport",     "url": "https://www.dexerto.fr/esport/feed/",                "region": None},

    # ── INFO POSITIVE ─────────────────────────────────────────────────────────
    {"name": "Positivr",           "url": "https://positivr.fr/feed/",                          "region": None},
    {"name": "L'Optimisme",        "url": "https://www.loptimisme.com/feed/",                   "region": None},
    {"name": "Good News Network",  "url": "https://www.goodnewsnetwork.org/feed/",              "region": None},

    # ── TECHNOLOGIE ───────────────────────────────────────────────────────────
    {"name": "Frandroid",          "url": "https://www.frandroid.com/feed",                     "region": None},
    {"name": "01net",              "url": "https://www.01net.com/feed/",                        "region": None},
    {"name": "Journal du Geek",    "url": "https://www.journaldugeek.com/feed/",                "region": None},

    # ── STREAMING ─────────────────────────────────────────────────────────────
    {"name": "Univers Freebox",    "url": "https://www.universfreebox.com/rss",                 "region": None},
    {"name": "Netflix Blog FR",    "url": "https://about.netflix.com/fr/feed",                  "region": None},
    {"name": "Dexerto Divertissement", "url": "https://www.dexerto.fr/divertissement/feed",     "region": None},

    # ── YOUTUBE ───────────────────────────────────────────────────────────────
    {"name": "YouTube : Journal du Geek", "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCofQxWvPrDk19gGMqZNM75A", "region": None},
    {"name": "YouTube : Frandroid",       "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC_oY_e-4m-Dk_2t3zQ3qQ9w", "region": None},

    # ── AUTOMOBILE ────────────────────────────────────────────────────────────
    {"name": "Caradisiac",         "url": "https://www.caradisiac.com/rss/",                   "region": None},
    {"name": "Automobile Propre",  "url": "https://www.automobile-propre.com/feed/",            "region": None},
    {"name": "Auto-Moto",          "url": "https://www.auto-moto.com/feed",                     "region": None},

    # ── ART ───────────────────────────────────────────────────────────────────
    {"name": "Beaux Arts Magazine",    "url": "https://www.beauxarts.com/feed/",                "region": None},
    {"name": "Connaissance des Arts",  "url": "https://www.connaissancedesarts.com/feed/",      "region": None},
    {"name": "Daily Art Magazine",     "url": "https://www.dailyartmagazine.com/feed/",         "region": None},

    # ── DESIGN ────────────────────────────────────────────────────────────────
    {"name": "Grapheine",          "url": "https://www.grapheine.com/feed",                     "region": None},
    {"name": "Étapes",             "url": "https://etapes.com/feed/",                           "region": None},
    {"name": "Abduzeedo",          "url": "https://abduzeedo.com/feed",                         "region": None},

    # ── INFORMATIQUE / IT ─────────────────────────────────────────────────────
    {"name": "Le Monde Informatique", "url": "https://www.lemondeinformatique.fr/rss/rss.xml", "region": None},
    {"name": "Developpez.com",        "url": "https://www.developpez.com/index/rss",            "region": None},
    {"name": "Next INpact",           "url": "https://www.nextinpact.com/rss/news.xml",         "region": None},

    # ── HARDWARE ──────────────────────────────────────────────────────────────
    {"name": "Cowcotland",         "url": "https://www.cowcotland.com/rss",                     "region": None},
    {"name": "Comptoir Hardware",  "url": "https://www.comptoir-hardware.com/home.xml",         "region": None},
    {"name": "Tom's Hardware FR",  "url": "https://www.tomshardware.fr/feed/",                  "region": None},

    # ── OPTIMISATION & TWEAKING ───────────────────────────────────────────────
    {"name": "Overclocking.com",   "url": "https://overclocking.com/feed/",                     "region": None},
    {"name": "Overclock.net News", "url": "https://www.overclock.net/forums/news.15/index.rss", "region": None},
    {"name": "PC Tuning (GitHub)", "url": "https://github.com/valleyofdoom/PC-Tuning/releases.atom", "region": None},
]

UA = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
# Articles older than this are skipped — matches presse_rss TTL in purge.py
_MAX_ARTICLE_AGE = timedelta(hours=72)

# Limit simultaneous HTTP requests to avoid overwhelming news sites or the local connection pool
_FETCH_SEMAPHORE = asyncio.Semaphore(20)

# Plafond d'articles conservés par flux (les plus récents). Évite qu'un flux
# volumineux (Google News renvoie ~100 entrées) ne monopolise à lui seul le
# budget de traitement IA au détriment de la diversité des sources.
_MAX_PER_FEED = 25


def _select_diverse(items: list[dict[str, Any]], max_n: int) -> list[dict[str, Any]]:
    """Sélectionne jusqu'à max_n articles en RÉPARTISSANT le plafond entre flux,
    au lieu de garder les N plus récents tous flux confondus.

    Le tri global par récence laissait les gros publicateurs (Le Parisien poste
    en continu) monopoliser le plafond et évinçait les ~870 flux régionaux. Ici,
    round-robin : on prend l'article le plus récent de chaque flux, puis le 2e,
    etc. — ce qui exploite la diversité géographique des sources (et capte plus
    d'actu.fr/Ouest-France, qui encodent l'INSEE/CP → commune exacte sur la carte).
    Les articles doivent porter une clé "_feed" identifiant leur flux d'origine.
    """
    by_feed: dict[Any, list[dict[str, Any]]] = {}
    for it in items:
        by_feed.setdefault(it.get("_feed"), []).append(it)
    for group in by_feed.values():
        group.sort(key=lambda it: it.get("date_publication") or "", reverse=True)
    # Flux ordonnés par récence de leur tête : les sources fraîches passent d'abord.
    ordered = sorted(by_feed.values(),
                     key=lambda g: g[0].get("date_publication") or "", reverse=True)
    selected: list[dict[str, Any]] = []
    depth = 0
    while len(selected) < max_n:
        advanced = False
        for group in ordered:
            if depth < len(group):
                selected.append(group[depth])
                advanced = True
                if len(selected) >= max_n:
                    break
        if not advanced:
            break
        depth += 1
    return selected


def _strip_html(text: str) -> str:
    """Supprime les balises HTML et décode les entités d'une chaîne RSS."""
    text = _re.sub(r'<[^>]+>', ' ', text)
    text = _html.unescape(text)
    return ' '.join(text.split())


# Balises éditoriales en tête de titre, à retirer avant déduplication : un même
# article publié par deux médias peut s'intituler "VIDÉO. X" chez l'un et "X"
# chez l'autre. On les neutralise pour que les variantes se regroupent.
_EDITORIAL_PREFIX_RE = _re.compile(
    r'^(?:'
    r'vid[ée]o|photos?|en\s+images?|en\s+direct|direct|live|replay|reportage|'
    r'interview|portrait|analyse|d[ée]cryptage|t[ée]moignage|exclusif|exclusivit[ée]|'
    r'info\s+\w+|carte|infographie|tribune|[ée]dito|chronique|podcast|enqu[êe]te|'
    r'r[ée]cit|fait\s+divers|insolite|bonne\s+nouvelle'
    r')\s*[:.\-–—]\s*',
    _re.IGNORECASE,
)


def _title_key(title: str) -> str:
    """Clé de normalisation pour déduplication par titre.

    Retire accents, balises éditoriales de tête ("VIDÉO.", "EN IMAGES :") et
    ponctuation, afin que le même sujet repris par plusieurs médias produise
    la même clé et soit dédupliqué.
    """
    t = title.lower().strip()
    # Retire une éventuelle balise éditoriale en tête (potentiellement répétée)
    prev = None
    while prev != t:
        prev = t
        t = _EDITORIAL_PREFIX_RE.sub('', t, count=1).strip()
    # Supprime les accents (é → e) pour fusionner "décès" / "deces"
    t = unicodedata.normalize('NFKD', t)
    t = ''.join(c for c in t if not unicodedata.combining(c))
    # Ne garde que les caractères alphanumériques
    return _re.sub(r'[^a-z0-9]', '', t)[:100]


def _parse_rss_date(entry: Any) -> datetime:
    for attr in ("published_parsed", "updated_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except Exception:
                pass
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                dt = parsedate_to_datetime(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    return datetime.now(timezone.utc)


async def _fetch_feed(
    client: httpx.AsyncClient,
    feed_cfg: dict[str, Any],
    feed_cache: dict[str, dict[str, str]] | None = None,
    logger: Any = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Récupère un flux RSS.

    Renvoie ``(items, not_modified)`` où ``not_modified`` indique un 304
    (flux inchangé) — dans ce cas ``items`` est vide. ``feed_cache`` conserve
    les validateurs conditionnels (ETag / Last-Modified) par URL de flux.
    """
    feed_name: str = feed_cfg["name"]
    feed_url: str = feed_cfg["url"]
    region: str | None = feed_cfg.get("region")

    # Construit les en-têtes conditionnels à partir du cache (si disponible).
    # Toute anomalie du cache est ignorée → GET inconditionnel (robustesse).
    req_headers: dict[str, str] = {}
    if feed_cache is not None:
        try:
            cached = feed_cache.get(feed_url)
            if isinstance(cached, dict):
                etag = cached.get("etag")
                last_modified = cached.get("last_modified")
                if etag:
                    req_headers["If-None-Match"] = etag
                if last_modified:
                    req_headers["If-Modified-Since"] = last_modified
        except Exception:
            req_headers = {}

    async with _FETCH_SEMAPHORE:
        try:
            resp = await client.get(feed_url, timeout=15.0, headers=req_headers or None)
            if resp.status_code == 304:
                # Flux inchangé : on conserve les validateurs et on ne parse rien.
                if logger is not None:
                    logger.debug("presse_rss: %s inchangé (304)", feed_url)
                return [], True
            resp.raise_for_status()
            content = resp.content
        except Exception as exc:
            raise RuntimeError(f"{feed_name}: fetch failed: {exc}") from exc

    # 200 OK : met à jour le cache avec les validateurs renvoyés (ou les efface
    # s'ils sont absents, pour ne pas réémettre des validateurs périmés).
    if feed_cache is not None:
        try:
            new_etag = resp.headers.get("ETag")
            new_last_modified = resp.headers.get("Last-Modified")
            if new_etag or new_last_modified:
                validators: dict[str, str] = {}
                if new_etag:
                    validators["etag"] = new_etag
                if new_last_modified:
                    validators["last_modified"] = new_last_modified
                feed_cache[feed_url] = validators
            else:
                feed_cache.pop(feed_url, None)
        except Exception:
            pass

    loop = asyncio.get_running_loop()
    parsed = await loop.run_in_executor(None, feedparser.parse, content)

    cutoff = datetime.now(timezone.utc) - _MAX_ARTICLE_AGE
    results: list[dict[str, Any]] = []
    for entry in parsed.entries:
        try:
            title: str = getattr(entry, "title", "").strip()
            if not title:
                continue
            link: str = getattr(entry, "link", "") or ""
            if not link:
                continue

            # Try full content first (richer), fall back to summary/description
            summary = ""
            content_list = getattr(entry, "content", None)
            if isinstance(content_list, list) and content_list:
                summary = _strip_html(content_list[0].get("value", ""))[:800]
            if not summary:
                for attr in ("summary", "description"):
                    val = getattr(entry, attr, None)
                    if isinstance(val, list) and val:
                        val = val[0].get("value", "")
                    if val and isinstance(val, str):
                        summary = _strip_html(val)[:500]
                        break

            date_pub = _parse_rss_date(entry)
            if date_pub < cutoff:
                continue

            results.append(
                {
                    "source": "presse_rss",
                    "source_url": link,
                    "titre": title,
                    "auteur": feed_name,
                    "date_publication": date_pub.isoformat(),
                    "date_evenement": None,
                    "categorie": "actualite",
                    "gravite": 0,
                    "lieu_nom": region,
                    "lieu_code_insee": None,
                    "lieu_niveau": "region" if region else "national",
                    "description": summary,
                }
            )
        except Exception:
            continue

    # Ne garde que les plus récents de ce flux (les chaînes ISO-8601 en UTC se
    # trient lexicographiquement dans l'ordre chronologique).
    results.sort(key=lambda r: r["date_publication"], reverse=True)
    return results[:_MAX_PER_FEED], False


class PresseRSSConnector(BaseConnector):
    def __init__(self) -> None:
        super().__init__()
        # Cache des validateurs HTTP conditionnels par URL de flux (ETag /
        # Last-Modified). Persiste entre les runs car ce connecteur est un
        # singleton instancié une seule fois dans le pipeline → permet aux
        # flux inchangés de répondre 304 (pas de corps) et d'économiser de la
        # bande passante / réduire le risque de 429.
        self._feed_cache: dict[str, dict[str, str]] = {}

    @property
    def name(self) -> str:
        return "presse_rss"

    async def fetch(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(headers={"User-Agent": UA}, follow_redirects=True) as client:
            tasks = [
                _fetch_feed(client, cfg, self._feed_cache, self._logger)
                for cfg in RSS_FEEDS
            ]
            feed_results = await asyncio.gather(*tasks, return_exceptions=True)

        raw: list[dict[str, Any]] = []
        n_not_modified = 0
        n_fetched = 0
        for i, res in enumerate(feed_results):
            if isinstance(res, Exception):
                self._logger.warning("Feed %s failed: %s", RSS_FEEDS[i]["name"], res)
            else:
                items, not_modified = res
                if not_modified:
                    n_not_modified += 1
                else:
                    n_fetched += 1
                for it in items:
                    it["_feed"] = i  # identité du flux, pour la sélection diversifiée
                raw.extend(items)

        # Déduplication par titre normalisé : préférer les articles avec une région
        seen: dict[str, dict[str, Any]] = {}
        for item in raw:
            key = _title_key(item.get("titre", ""))
            if not key:
                continue
            if key not in seen:
                seen[key] = item
            elif item.get("lieu_nom") and not seen[key].get("lieu_nom"):
                # Remplace la version nationale par la version régionale
                seen[key] = item

        # Plafond global : on ne traite que les N articles les plus récents
        # (chaque article coûte un appel LLM ~12 s sur CPU). Sans ce plafond, un
        # run de ~1000 articles sature le CPU plus d'une heure avant tout commit.
        # Sélection diversifiée (round-robin par flux) au lieu des N plus récents :
        # exploite la diversité régionale des ~870 sources au lieu de laisser les
        # gros publicateurs monopoliser le plafond.
        items = list(seen.values())
        capped = _select_diverse(items, settings.MAX_PRESSE_ARTICLES)
        for it in capped:
            it.pop("_feed", None)
        self._logger.info(
            "presse_rss: %d flux récupérés, %d inchangés (304) | "
            "%d raw → %d after title dedup → %d after cap (max=%d, round-robin par flux)",
            n_fetched, n_not_modified,
            len(raw), len(seen), len(capped), settings.MAX_PRESSE_ARTICLES,
        )
        return capped
