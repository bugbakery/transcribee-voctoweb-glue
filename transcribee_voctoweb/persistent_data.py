from enum import Enum
import json
from pathlib import Path
from typing import Union
from datetime import datetime

from pydantic import BaseModel

class State(Enum):
    NEW = "new"
    TRANSCRIBING = "transcribing"
    NEEDS_CORRECTION = "needs_correction"
    CORRECTING = "correcting"
    DONE  = "done"

class LogEntry(BaseModel):
    ts: datetime
    msg: str

class EventState(BaseModel):
    state: State = State.NEW
    failed: bool = False
    transcribee_doc: str | None = None
    transcribee_share_token: str | None = None
    transcription_finished: bool = False
    subtitles_finished: bool = False
    log: list[LogEntry] = []
    try_count: int = 0

    def switch_state(self, new_state: State):
        self.add_log(f"Switching from {self.state} to {new_state}")
        self.state = new_state

    def add_log(self, message: str):
        self.log.append(LogEntry(ts=datetime.now(), msg=message))


class PersistentData(BaseModel):
    event_states: dict[str, EventState] = {}
    _last_saved: Union["PersistentData", None] = None

    @staticmethod
    def load_json(state_path: Path):
        if not state_path.exists():
            return PersistentData()

        with open(state_path, "r") as file:
            loaded = json.load(file)

        return PersistentData(**loaded)

    def save_json(self, state_path: Path, only_if_changed=False):
        if (
            only_if_changed
            and self._last_saved
            and self._last_saved.model_dump() == self.model_dump()
        ):
            return

        with open(state_path, "w") as file:
            copy = self.model_copy(deep=True)
            json_str = copy.model_dump_json(indent=2)
            file.write(json_str)
            self._last_saved = copy
