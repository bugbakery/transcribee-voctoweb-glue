import asyncio
from contextlib import asynccontextmanager
import datetime
import logging
from pathlib import Path
import tempfile
import traceback
from typing import IO

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic
import httpx
from starlette.responses import RedirectResponse

from transcribee_voctoweb.subtitle_formatting import format_subtitle_vtt
from transcribee_voctoweb.config import settings
from transcribee_voctoweb.helpers.periodic_tasks import run_periodic
from transcribee_voctoweb.persistent_data import EventState, PersistentData, State
from transcribee_voctoweb.transcribee_api.client import (
    DocumentBodyWithFile,
    TranscribeeApiClient,
)
from transcribee_voctoweb.transcribee_api.model import CreateShareToken, TaskResponse, TaskState, TaskTypeModel
import urllib.parse

from transcribee_voctoweb.voc_api.client import VocPublishingApiClient

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

security = HTTPBasic()

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
    asyncio.create_task(run_periodic(process_events, seconds=10))

    yield

    # shutdown
    persistent_data.save_json(data_path)


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")



templates = Jinja2Templates(directory="templates")

def format_seconds(value):
    duration = datetime.timedelta(seconds=value)
    return str(duration)

templates.env.filters["format_seconds"] = format_seconds

def format_state(value: State):
    return value.name

templates.env.filters["format_state"] = format_state


class IllegalEventStateError(ValueError):
    def __init__(self, state: EventState, reason: str):
        super().__init__("Illegal event state")


class RecoverableDependencyError(ValueError):
    def __init__(self, state: EventState, reason: str):
        super().__init__("Illegal event state")


async def process_events():
    async with asyncio.TaskGroup() as tg:
        for event in events:
            state = persistent_data.event_states[event.guid]

            if state.state != State.DONE and not state.failed:
                tg.create_task(wrapped_process(event.guid, state))


async def wrapped_process(event_id: str, event_state: EventState):
    try:
        await process(event_id, event_state)
    except IllegalEventStateError:
        logging.error("Illegal event state")
        event_state.add_log("Illegal event state")
        event_state.failed = True
    except RecoverableDependencyError:
        logging.warn("Recoverable dependency error")
        event_state.add_log("Recoverable dependency error")
    except Exception as e:
        logging.error("Unknown error", exc_info=e)
        event_state.add_log(f"Unknown error: {traceback.format_exc()}")
        event_state.try_count += 1
        if event_state.try_count >= 3:
            logging.error("Failed after 3 tries")
            event_state.failed = True
            event_state.add_log("Failed after 3 tries")


async def process(event_id: str, event_state: EventState):
    if event_state.state == State.NEW:
        event_details = await voc_api.get_event(settings.conference, event_id)
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
            raise RecoverableDependencyError(event_state, "Event has no mp4 recording")

        with tempfile.NamedTemporaryFile() as video_file:
            logging.debug(f"Downloading {mp4_recording.recording_url}")
            await download_file(mp4_recording.recording_url, video_file)
            video_file.flush()
            video_file.seek(0)

            doc = await transcribee_api.create_document(
                DocumentBodyWithFile(
                    name=event_details.title,
                    file=video_file,
                    model="large-v3",
                    language="auto",
                    number_of_speakers=None,
                ),
            )
            event_state.transcribee_doc = doc.id

            share_token = await transcribee_api.create_share_token(
                doc.id,
                CreateShareToken(
                    name="voctoweb-glue",
                    can_write=True,
                    valid_until=None,
                ),
            )
            event_state.transcribee_share_token = share_token.token
            event_state.switch_state(State.TRANSCRIBING)

    elif event_state.state == State.TRANSCRIBING:
        if event_state.transcribee_doc is None:
            raise IllegalEventStateError(event_state, "transcribee_doc is None")

        logging.debug(f"Checking status of {event_state.transcribee_doc}")
        tasks = await transcribee_api.get_tasks_for_document(event_state.transcribee_doc)

        if transcription_finished(tasks):
            await export_transcribee_document_to_voc(event_id, event_state.transcribee_doc)

            event_state.switch_state(State.NEEDS_CORRECTION)
            logging.info(f"{event_id} just finished automatic transcription")

    elif event_state.state == State.NEEDS_CORRECTION:
        # only manual actions in this state
        pass

    elif event_state.state == State.CORRECTING:
        # only manual actions in this state
        pass

    elif event_state.state == State.DONE:
        pass

    else:
        raise IllegalEventStateError(event_state, "unknown state")


def transcription_finished(tasks: list[TaskResponse]):
    transcribe_tasks = [task for task in tasks if task.task_type == TaskTypeModel.TRANSCRIBE]

    # has at leas one finished automatic transcription
    has_completed_transcribe_task = any(
        task.state == TaskState.COMPLETED
        for task in transcribe_tasks
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
            logging.info(f"Adding event {guid}")
            persistent_data.event_states[guid] = EventState()
            persistent_data.event_states[guid].add_log("Event added")


async def download_file(url, file: IO[bytes]):
    async with httpx.AsyncClient(timeout=10.0).stream('GET', url, follow_redirects=True) as res:
        res.raise_for_status()
        async for chunk in res.aiter_bytes():
            file.write(chunk)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "home.html", {"request": request, "events": events, "state": persistent_data.event_states}
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


@app.post("/events/{id}/mark_corrected", response_class=HTMLResponse)
async def finish_subtitles(request: Request, id: str):
    persistent_data.event_states[id].switch_state(State.DONE)

    return RedirectResponse(f"/events/{id}", status_code=303)


@app.post("/events/{id}/upload_to_voc", response_class=HTMLResponse)
async def upload_to_voc(request: Request, id: str):
    transcribee_doc = persistent_data.event_states[id].transcribee_doc
    if transcribee_doc is None:
        raise HTTPException(status_code=400, detail="No transcribee document created yet")

    await export_transcribee_document_to_voc(id, transcribee_doc)

    return RedirectResponse(f"/events/{id}", status_code=303)


@app.post("/events/{id}/reset_failed", response_class=HTMLResponse)
async def reset_failed(request: Request, id: str):
    persistent_data.event_states[id].failed = False
    persistent_data.event_states[id].try_count = 0
    persistent_data.event_states[id].add_log("Reset failed state")

    return RedirectResponse(f"/events/{id}", status_code=303)


@app.get("/events/{id}/vtt", response_class=HTMLResponse)
async def vtt(request: Request, id: str):
    state = persistent_data.event_states.get(id)

    if state is None or state.transcribee_doc is None:
        raise HTTPException(status_code=404, detail="No transcribee document created yet")

    vtt = await transcribee_api.export(state.transcribee_doc, format="VTT", include_word_timing=True)
    return format_subtitle_vtt(vtt)


async def export_transcribee_document_to_voc(event_id: str, transcribee_doc: str):
    event = await voc_api.get_event(settings.conference, event_id)
    vtt = await transcribee_api.export(transcribee_doc, format="VTT", include_word_timing=True)
    formatted_vtt = format_subtitle_vtt(vtt)
    await voc_api.upload_vtt(
        conference=settings.conference,
        event=event_id,
        vtt=formatted_vtt,
        language=event.original_language,
    )
