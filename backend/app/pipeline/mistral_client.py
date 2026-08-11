"""Appel unique à l'API Mistral, avec reprise sur limitation de débit.

Extracteur et brief interrogeaient tous deux Mistral avec un `except Exception`
qui renvoyait None : un HTTP 429 — « trop de requêtes, réessayez » — était donc
traité comme un échec définitif. Conséquences observées le 11/08/2026 sur un
échantillon de 15 articles, dont 3 en 429 :

  - l'extracteur retombait sur les règles, produisant un résumé tronqué en
    milieu de phrase (« Le procès d'un réseau de stupéfiants, dont le »),
    aucun tag et un lieu « national » ;
  - le brief, lui, n'aurait tout simplement pas été produit.

Or un 429 se résout en attendant. Le distinguer d'une vraie panne est la
différence entre une dégradation silencieuse et un service fiable.
"""
import asyncio
import logging
import random
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_URL = "https://api.mistral.ai/v1/chat/completions"

# Codes qui méritent une seconde chance : limitation de débit et pannes
# transitoires côté serveur. Un 401 ou un 400 ne se répareront pas en attendant.
_CODES_REESSAYABLES = frozenset({429, 500, 502, 503, 504})


def _delai_avant_reprise(resp: Optional[httpx.Response], tentative: int) -> float:
    """Combien de temps patienter avant la tentative suivante.

    Respecte l'en-tête `Retry-After` quand l'API le fournit — elle sait mieux
    que nous quand sa fenêtre se rouvre. À défaut, recul exponentiel. Le bruit
    aléatoire évite que les appels concurrents, tous repoussés ensemble, ne
    repartent à la même seconde et ne provoquent un nouveau 429.
    """
    if resp is not None:
        brut = resp.headers.get("Retry-After")
        if brut:
            try:
                # Borné : une API qui annonce 300 s ne doit pas figer l'ingestion.
                return min(float(brut), 30.0)
            except ValueError:
                pass
    return min(2.0 ** tentative, 16.0) + random.uniform(0, 0.5)


async def chat(
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float,
    response_format: Optional[dict[str, str]] = None,
    timeout: float = 30.0,
    etiquette: str = "",
) -> Optional[str]:
    """Une complétion Mistral. Retourne le texte, ou None si tout a échoué.

    `etiquette` n'apparaît que dans les journaux, pour situer l'appel.
    """
    if not settings.MISTRAL_API_KEY:
        return None

    charge: dict[str, Any] = {
        "model": settings.MISTRAL_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        charge["response_format"] = response_format

    tentatives = max(1, settings.MISTRAL_MAX_RETRIES)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for tentative in range(tentatives):
            resp = None
            try:
                resp = await client.post(
                    _URL,
                    headers={
                        "Authorization": f"Bearer {settings.MISTRAL_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json=charge,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"].strip()

            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                if code not in _CODES_REESSAYABLES or tentative == tentatives - 1:
                    logger.warning("Mistral %s : HTTP %d%s", etiquette, code,
                                   " (dernière tentative)" if code in _CODES_REESSAYABLES else "")
                    return None
                attente = _delai_avant_reprise(exc.response, tentative)
                logger.info("Mistral %s : HTTP %d, reprise dans %.1f s (%d/%d)",
                            etiquette, code, attente, tentative + 1, tentatives)
                await asyncio.sleep(attente)

            except (httpx.TimeoutException, httpx.TransportError) as exc:
                # Coupure réseau : même traitement qu'un 5xx.
                if tentative == tentatives - 1:
                    logger.warning("Mistral %s : %s (dernière tentative)", etiquette, exc)
                    return None
                attente = _delai_avant_reprise(None, tentative)
                logger.info("Mistral %s : %s, reprise dans %.1f s (%d/%d)",
                            etiquette, type(exc).__name__, attente, tentative + 1, tentatives)
                await asyncio.sleep(attente)

            except Exception as exc:
                # Réponse illisible, JSON inattendu… : rien à gagner à insister.
                logger.warning("Mistral %s : %s", etiquette, exc)
                return None

    return None
