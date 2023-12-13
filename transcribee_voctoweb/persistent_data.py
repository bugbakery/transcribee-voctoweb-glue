import json
from pathlib import Path

from pydantic import BaseModel


class EventState(BaseModel):
    transcribee_doc: str | None = None
    transcription_finished: bool = False

    amara_doc: str | None = None
    subtitles_finished: bool = False


class PersistentData(BaseModel):
    event_states: dict[str, EventState] = {}

    @staticmethod
    def load_json(state_path: Path):
        if not state_path.exists():
            return PersistentData()

        with open(state_path, "r") as file:
            loaded = json.load(file)

        return PersistentData(**loaded)

    def save_json(self, state_path: Path):
        with open(state_path, "w") as file:
            file.write(self.model_dump_json(indent=2))
