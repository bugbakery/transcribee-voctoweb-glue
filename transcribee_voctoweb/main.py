import asyncio
from contextlib import asynccontextmanager
import datetime
import logging
import os
from pathlib import Path
import tempfile
import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import requests
from starlette.responses import RedirectResponse

from transcribee_voctoweb.subtitle_formatting import format_subtitle_vtt
from transcribee_voctoweb.config import settings
from transcribee_voctoweb.helpers.periodic_tasks import run_periodic
from transcribee_voctoweb.persistent_data import EventState, PersistentData
from transcribee_voctoweb.transcribee_api.client import (
    DocumentBodyWithFile,
    TranscribeeApiClient,
)
from transcribee_voctoweb.transcribee_api.model import CreateShareToken, TaskResponse, TaskState, TaskTypeModel
import urllib.parse

from transcribee_voctoweb.voc_api.client import VocPublishingApiClient

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

    global voc_api
    voc_api = VocPublishingApiClient(
        base_url=settings.voc_api_url,
        token=settings.voc_token,
    )

    def continous_save():
        persistent_data.save_json(data_path, only_if_changed=True)

    asyncio.create_task(run_periodic(continous_save, seconds=1))
    asyncio.create_task(run_periodic(update_conference, seconds=60))

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

def transcription_finished(tasks: list[TaskResponse]):
    # has at leas one finished automatic transcription
    has_completed_transcribe_task = any(
        task.task_type == TaskTypeModel.TRANSCRIBE and task.state == TaskState.COMPLETED
        for task in tasks
    )

    if not has_completed_transcribe_task:
        return False

    has_align_task = any(
        task.task_type == TaskTypeModel.ALIGN
        for task in tasks
    )

    has_finished_align_task = any(
        task.task_type == TaskTypeModel.ALIGN and task.state == TaskState.COMPLETED
        for task in tasks
    )

    # if there is an align task, it must be finished
    if has_align_task and not has_finished_align_task:
        return False

    return True

async def update_conference():
    logging.debug("Updating conference...")
    global conference
    new_conference = await voc_api.get_conference(settings.conference)
    new_conference.events = sorted(
        new_conference.events, key=lambda event: event.date
    )
    if settings.limit_events is not None:
        new_conference.events = new_conference.events[:settings.limit_events]

    conference = new_conference
    global events
    events = conference.events


    global persistent_data

    for event in events:
        guid = event.guid
        if guid not in persistent_data.event_states:
            print(f"Adding event {guid}")
            persistent_data.event_states[guid] = EventState()

        trancribee_doc = persistent_data.event_states[guid].transcribee_doc
        if trancribee_doc:
            try:
                logging.debug(f"Checking status of {trancribee_doc}")
                tasks = await transcribee_api.get_tasks_for_document(trancribee_doc)

                if transcription_finished(tasks):
                    if not persistent_data.event_states[guid].transcription_finished:
                        persistent_data.event_states[guid].transcription_finished = True
                        logging.info(f"{guid} just finished automatic transcription")
                    else:
                        logging.debug(f"{guid} has already finished automatic transcription")
                else:
                    logging.debug(f"{guid} has not finished automatic transcription")
            except Exception:
                logging.error(f"Failed to check status of {trancribee_doc}")
                traceback.print_exc()


        if not persistent_data.event_states[guid].transcribee_doc:
            event_details = await voc_api.get_event(settings.conference, guid)

            mp4_recording = next(
                (
                    recording
                    for recording in event_details.recordings
                    if recording.mime_type == "video/mp4"
                    and recording.high_quality is False
                ),
                None,
            )

            if mp4_recording is None:
                logging.debug(f"Event {guid} has no mp4 recording")
                continue

            _fd, video_file = tempfile.mkstemp(suffix=".mp4")
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, download_file, mp4_recording.recording_url, video_file
                )

                doc = await transcribee_api.create_document(
                    DocumentBodyWithFile(
                        name=event_details.title,
                        file=Path(video_file),
                        model="large-v3",
                        language="auto",
                        number_of_speakers=None,
                    ),
                )

                persistent_data.event_states[guid].transcribee_doc = doc.id

                share_token = await transcribee_api.create_share_token(
                    doc.id,
                    CreateShareToken(
                        name="voctoweb-glue",
                        can_write=True,
                        valid_until=None,
                    ),
                )

                persistent_data.event_states[guid].transcribee_share_token = share_token.token
            except Exception:
                traceback.print_exc()
            finally:
                os.remove(video_file)


def download_file(url, local_path):
    # NOTE the stream=True parameter below
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                # If you have chunk encoded response uncomment if
                # and set chunk_size parameter to None.
                # if chunk:
                f.write(chunk)
    return local_path


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "home.html", {"request": request, "events": events}
    )


@app.get("/events/{id}", response_class=HTMLResponse)
async def event(request: Request, id: str):
    event = await voc_api.get_event(settings.conference, id)

    transcribee_url = None
    state = persistent_data.event_states.get(id)

    if state and state.transcribee_share_token:
        encoded_token = urllib.parse.quote_plus(state.transcribee_share_token)
        transcribee_url = f"{settings.transcribee_api_url}/document/{state.transcribee_doc}?share_token={encoded_token}"

    return templates.TemplateResponse(
        "event.html",
        {
            "request": request,
            "event": event,
            "state": persistent_data.event_states.get(id, {}),
            "transcribee_url": transcribee_url,
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


@app.get("/events/{id}/vtt", response_class=HTMLResponse)
async def vtt(request: Request, id: str):
    state = persistent_data.event_states.get(id)

    if state is None or state.transcribee_doc is None:
        raise HTTPException(status_code=404, detail="No transcribee document created yet")

    vtt = await transcribee_api.export(state.transcribee_doc, format="VTT", include_word_timing=True)
    return format_subtitle_vtt(vtt)

@app.get("/events/{id}/upload-vtt")
async def upload_vtt(request: Request, id: str):
    state = persistent_data.event_states.get(id)

    if state is None or state.transcribee_doc is None:
        raise HTTPException(status_code=404, detail="No transcribee document created yet")

    vtt = await transcribee_api.export(state.transcribee_doc, format="VTT", include_word_timing=True)
    formatted_vtt = format_subtitle_vtt(vtt)
    await voc_api.upload_vtt(
        conference=settings.conference,
        event=id,
        vtt=formatted_vtt,
        language="de",
    )

    return "Success"
