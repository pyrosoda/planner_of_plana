"""
Application-level state definitions and transition validation.
"""

from __future__ import annotations

import threading
from datetime import datetime
from enum import Enum, auto
from typing import Optional

from core.logger import get_logger, LOG_APP

_log = get_logger(LOG_APP)


class AppState(Enum):
    INIT = auto()
    IDLE = auto()
    WATCHING = auto()
    SCANNING = auto()
    PAUSED = auto()
    ERROR = auto()
    STOPPING = auto()


class WatcherState(Enum):
    IDLE = auto()
    RUNNING = auto()
    PAUSED = auto()
    STOPPED = auto()


class ScanPhase(Enum):
    IDLE = auto()
    RESOURCES = auto()
    ITEMS = auto()
    EQUIPMENT = auto()
    STUDENTS = auto()
    IDENTIFY = auto()
    READ_SKILLS = auto()
    READ_WEAPON = auto()
    READ_EQUIP = auto()
    READ_LEVEL = auto()
    READ_STAR = auto()
    READ_STATS = auto()
    DONE = auto()
    STOPPED = auto()


ALLOWED_TRANSITIONS: dict[AppState, set[AppState]] = {
    AppState.INIT: {AppState.IDLE, AppState.STOPPING},
    AppState.IDLE: {AppState.WATCHING, AppState.STOPPING},
    AppState.WATCHING: {AppState.IDLE, AppState.SCANNING, AppState.STOPPING},
    AppState.SCANNING: {
        AppState.WATCHING,
        AppState.PAUSED,
        AppState.STOPPING,
    },
    AppState.PAUSED: {
        AppState.SCANNING,
        AppState.WATCHING,
        AppState.STOPPING,
    },
    AppState.ERROR: {AppState.IDLE, AppState.WATCHING, AppState.STOPPING},
    AppState.STOPPING: {AppState.IDLE, AppState.WATCHING, AppState.ERROR},
}


def is_valid_transition(from_: AppState, to: AppState) -> bool:
    """
    Return whether a state transition is allowed.

    ERROR is treated as an emergency sink state from anywhere except STOPPING.
    """
    if from_ == to:
        return True
    if to == AppState.ERROR and from_ != AppState.STOPPING:
        return True
    return to in ALLOWED_TRANSITIONS.get(from_, set())


def can_transition(from_: AppState, to: AppState) -> bool:
    return is_valid_transition(from_, to)


class StateTransitionError(Exception):
    pass


class StateMachine:
    MAX_HISTORY = 50

    def __init__(
        self,
        initial: AppState,
        name: str = "App",
        strict: bool = False,
    ):
        self._state = initial
        self._name = name
        self._strict = strict
        self._lock = threading.Lock()
        self._history: list[dict] = []
        self._record(None, initial, "initial")

    @property
    def state(self) -> AppState:
        with self._lock:
            return self._state

    @property
    def history(self) -> list[dict]:
        with self._lock:
            return list(self._history)

    def is_in(self, *states: AppState) -> bool:
        return self.state in states

    def transition(self, new_state: AppState, reason: str = "") -> bool:
        with self._lock:
            old = self._state
            if old == new_state:
                return True

            if not is_valid_transition(old, new_state):
                msg = (
                    f"[{self._name}] invalid transition: "
                    f"{old.name} -> {new_state.name}"
                    + (f" ({reason})" if reason else "")
                )
                _log.warning(msg)
                if self._strict:
                    raise StateTransitionError(msg)
                return False

            self._state = new_state
            self._record(old, new_state, reason)

        _log.info(
            f"STATE: {old.name} -> {new_state.name}"
            + (f" ({reason})" if reason else "")
        )
        return True

    def force(self, new_state: AppState, reason: str = "") -> None:
        with self._lock:
            old = self._state
            self._state = new_state
            self._record(old, new_state, f"FORCE: {reason}")

        _log.warning(
            f"STATE: {old.name} -> {new_state.name}"
            + (f" ({reason})" if reason else "")
        )

    def _record(
        self,
        from_: Optional[AppState],
        to: AppState,
        reason: str,
    ) -> None:
        self._history.append(
            {
                "from": from_.name if from_ else None,
                "to": to.name,
                "reason": reason,
                "at": datetime.now().isoformat(),
            }
        )
        if len(self._history) > self.MAX_HISTORY:
            self._history.pop(0)

    def last_transition(self) -> Optional[dict]:
        with self._lock:
            return self._history[-1] if self._history else None

    def transitions_to(self, state: AppState) -> list[dict]:
        with self._lock:
            return [h for h in self._history if h["to"] == state.name]
