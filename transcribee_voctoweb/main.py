import asyncio
from contextlib import asynccontextmanager
import datetime
import logging
import os
from pathlib import Path
import tempfile
import traceback

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic.types import FilePath
import requests
from starlette.responses import RedirectResponse

from transcribee_voctoweb.config import settings
from transcribee_voctoweb.helpers.periodic_tasks import run_periodic
from transcribee_voctoweb.persistent_data import EventState, PersistentData
from transcribee_voctoweb.transcribee_api.client import (
    DocumentBodyWithFile,
    TranscribeeApiClient,
)

logging.basicConfig(level=logging.DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    global persistent_data
    data_path = Path("data.json")
    persistent_data = PersistentData.load_json(data_path)

    global transcribee_api
    transcribee_api = TranscribeeApiClient(
        base_url=settings.transcribee_api_url, token=settings.transcribee_pat
    )

    def continous_save():
        persistent_data.save_json(data_path, only_if_changed=True)

    asyncio.create_task(run_periodic(continous_save, seconds=1))

    # await update_conference()
    asyncio.create_task(run_periodic(update_conference, seconds=500))

    yield

    # shutdown
    persistent_data.save_json(data_path)


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


def format_seconds(value):
    duration = datetime.timedelta(seconds=value)
    return str(duration)


templates = Jinja2Templates(directory="templates")
templates.env.filters["format_seconds"] = format_seconds


async def update_conference():
    logging.debug("Updating conference...")
    global conference
    new_conference = requests.get(
        f"https://api.media.ccc.de/public/conferences/{settings.conference}"
    ).json()
    new_conference["events"] = sorted(
        new_conference["events"], key=lambda event: event["date"]
    )
    new_conference["events"] = new_conference["events"][: settings.limit_events]
    conference = new_conference
    global events
    events = conference["events"]

    for event in events:
        guid = event["guid"]
        if guid not in persistent_data.event_states:
            persistent_data.event_states[guid] = EventState()

        if not persistent_data.event_states[guid].transcribee_doc:
            event_details = requests.get(
                f"https://api.media.ccc.de/public/events/{guid}"
            ).json()

            mp4_recording = next(
                (
                    recording
                    for recording in event_details["recordings"]
                    if recording["mime_type"] == "video/mp4"
                    and recording["high_quality"] is False
                ),
                None,
            )

            if mp4_recording is None:
                logging.debug(f"Event {guid} has no mp4 recording")
                continue

            print(mp4_recording["recording_url"])

            _fd, video_file = tempfile.mkstemp(suffix=".mp4")
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, download_file, mp4_recording["recording_url"], video_file
                )

                doc = await asyncio.get_running_loop().run_in_executor(
                    None, transcribee_api.create_document,
                    DocumentBodyWithFile(
                        name=event["title"],
                        file=FilePath(video_file),
                        model="large-v3",
                        language="auto",
                        number_of_speakers=None,
                    )
                )

                persistent_data.event_states[guid].transcribee_doc = doc.id
            except Exception:
                traceback.print_exc()
            finally:
                os.remove(video_file)

def download_file(url, local_path):
    # NOTE the stream=True parameter below
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(local_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192): 
                # If you have chunk encoded response uncomment if
                # and set chunk_size parameter to None.
                #if chunk: 
                f.write(chunk)
    return local_path

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "home.html", {"request": request, "events": events}
    )


@app.get("/events/{id}", response_class=HTMLResponse)
async def event(request: Request, id: str):
    event = next((event for event in events if event["guid"] == id), None)
    return templates.TemplateResponse(
        "event.html",
        {
            "request": request,
            "event": event,
            "state": persistent_data.event_states.get(id, {}),
        },
    )


@app.post("/events/{id}/finish_transcript", response_class=HTMLResponse)
async def finish_transcript(request: Request, id: str):
    if id not in persistent_data.event_states:
        persistent_data.event_states[id] = EventState()

    persistent_data.event_states[id].transcription_finished = True

    return RedirectResponse(f"/events/{id}", status_code=303)


@app.post("/events/{id}/finish_subtitles", response_class=HTMLResponse)
async def finish_subtitles(request: Request, id: str):
    if id not in persistent_data.event_states:
        persistent_data.event_states[id] = EventState()

    persistent_data.event_states[id].subtitles_finished = True

    return RedirectResponse(f"/events/{id}", status_code=303)
