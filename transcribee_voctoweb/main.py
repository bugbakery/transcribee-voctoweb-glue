import asyncio
from contextlib import asynccontextmanager
import datetime
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import requests
from starlette.responses import RedirectResponse

from transcribee_voctoweb.config import settings
from transcribee_voctoweb.helpers.periodic_tasks import run_periodic
from transcribee_voctoweb.persistent_data import EventState, PersistentData

logging.basicConfig(level=logging.DEBUG)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    global persistent_data
    data_path = Path("data.json")
    persistent_data = PersistentData.load_json(data_path)

    update_conference()
    asyncio.create_task(run_periodic(update_conference, seconds=15))

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

def update_conference():
    logging.debug("Updating conference...")
    global conference
    conference = requests.get("https://api.media.ccc.de/public/conferences/35c3").json()
    global events
    events = conference["events"]


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request, "events": events})


@app.get("/events/{id}", response_class=HTMLResponse)
async def event(request: Request, id: str):
    event = next((event for event in events if event["guid"] == id), None)
    return templates.TemplateResponse("event.html", {
        "request": request,
        "event": event,
        "state": persistent_data.event_states.get(id, {}),
    })


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
