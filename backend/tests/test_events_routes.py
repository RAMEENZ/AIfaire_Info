"""Regression : la route SSE /events/stream doit etre declaree AVANT la route
parametree /events/{event_id}. Starlette resout les routes dans l'ordre de
declaration ; si l'ordre s'inverse, GET /api/events/stream est capture par
/events/{event_id} qui tente de parser "stream" comme un UUID -> 422, et le
flux temps reel ne se connecte plus jamais.
"""
from app.api.routes.events import router


def _paths_in_order():
    return [getattr(r, "path", None) for r in router.routes]


def test_stream_route_is_registered():
    assert "/events/stream" in _paths_in_order()


def test_stream_route_declared_before_event_id():
    paths = _paths_in_order()
    assert paths.index("/events/stream") < paths.index("/events/{event_id}")
