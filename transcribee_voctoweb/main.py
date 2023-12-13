import asyncio
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import requests

from transcribee_voctoweb.config import settings
from transcribee_voctoweb.helpers.periodic_tasks import run_periodic

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    update_conference()
    asyncio.create_task(run_periodic(update_conference, seconds=15))

    yield

    # shutdown
    # ...


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

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
    return templates.TemplateResponse("event.html", { "request": request, "event": event})
