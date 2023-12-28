import json
from pathlib import Path
from typing import Union

from pydantic import BaseModel


class EventState(BaseModel):
    transcribee_doc: str | None = None
    transcription_finished: bool = False

    amara_doc: str | None = None
    subtitles_finished: bool = False


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
            json_str = copy.model_dump_json(indent=2, exclude_unset=True)
            file.write(json_str)
            self._last_saved = copy
