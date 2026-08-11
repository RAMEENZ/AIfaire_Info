"""Regression : la route SSE /events/stream doit etre declaree AVANT la route
parametree /events/{event_id}. Starlette resout les routes dans l'ordre de
declaration ; si l'ordre s'inverse, GET /api/events/stream est capture par
/events/{event_id} qui tente de parser "stream" comme un UUID -> 422, et le
flux temps reel ne se connecte plus jamais.
"""
import pytest

from app.api.routes.events import router


def _paths_in_order():
    return [getattr(r, "path", None) for r in router.routes]


def test_stream_route_is_registered():
    assert "/events/stream" in _paths_in_order()


def test_stream_route_declared_before_event_id():
    paths = _paths_in_order()
    assert paths.index("/events/stream") < paths.index("/events/{event_id}")


# ── Validation du code département ──────────────────────────────────────────

def test_un_code_departement_a_un_chiffre_est_refuse():
    """Le code sert de PRÉFIXE dans un LIKE : « 7 » correspondait à « 75056 »,
    « 76540 »… et renvoyait silencieusement les départements 70 à 79."""
    from fastapi import HTTPException
    from app.api.routes.events import _validate_dept

    for mauvais in ("7", "1", "abc", "7A", "1234", "2C", ""):
        with pytest.raises(HTTPException) as exc:
            _validate_dept(mauvais)
        assert exc.value.status_code == 422, mauvais


@pytest.mark.parametrize("code,attendu", [
    ("75", "75"), ("13", "13"), ("2a", "2A"), ("2B", "2B"),
    ("971", "971"), ("976", "976"), (" 69 ", "69"),
])
def test_un_code_departement_valide_est_normalise(code, attendu):
    from app.api.routes.events import _validate_dept
    assert _validate_dept(code) == attendu


def test_absence_de_departement_reste_permise():
    from app.api.routes.events import _validate_dept
    assert _validate_dept(None) is None
