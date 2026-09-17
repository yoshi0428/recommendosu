import threading
import uuid

_recommendation_cancellations: dict[str, threading.Event] = {}
_recommendation_cancellations_lock = threading.Lock()


def create_cancellation_event(
    recommendation_id: str | None = None,
) -> tuple[str, threading.Event]:
    if recommendation_id is None:
        recommendation_id = uuid.uuid4().hex

    event = threading.Event()

    with _recommendation_cancellations_lock:
        _recommendation_cancellations[recommendation_id] = event

    return recommendation_id, event


def cancel_recommendation(recommendation_id: str) -> bool:
    with _recommendation_cancellations_lock:
        event = _recommendation_cancellations.get(recommendation_id)

    if event is None:
        return False

    event.set()
    return True


def remove_cancellation_event(recommendation_id: str) -> None:
    with _recommendation_cancellations_lock:
        _recommendation_cancellations.pop(recommendation_id, None)


class RecommendationCancelled(Exception):
    pass


def check_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise RecommendationCancelled