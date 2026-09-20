"""In-process Card probe / Well-Known refresh. Never invokes skills."""

from __future__ import annotations

import threading
from typing import Callable, Optional

from .config import Settings
from .store import Store


def start_sweep(store: Store, settings: Settings) -> Optional[Callable[[], None]]:
    interval = float(getattr(settings, "sweep_s", 0) or 0)
    if interval <= 0:
        return None
    stop = threading.Event()

    def beat() -> None:
        if stop.is_set():
            return
        try:
            store.sweep_once()
        except Exception:
            pass
        if not stop.is_set():
            timer = threading.Timer(interval, beat)
            timer.daemon = True
            timer.start()
            store.sweep_timer = timer

    first = threading.Timer(interval, beat)
    first.daemon = True
    first.start()
    store.sweep_timer = first

    def cancel() -> None:
        stop.set()
        timer = getattr(store, "sweep_timer", None)
        if timer:
            timer.cancel()

    return cancel
