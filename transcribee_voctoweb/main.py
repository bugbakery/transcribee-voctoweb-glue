import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import requests

from transcribee_voctoweb.config import settings
from transcribee_voctoweb.helpers.periodic_tasks import run_periodic

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

conference = requests.get("https://api.media.ccc.de/public/conferences/35c3").json()
events = conference["events"]

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request, "title": "Some title", "events": events})


@app.get("/events/{id}", response_class=HTMLResponse)
async def event(request: Request, id: str):
    event = next((event for event in events if event["guid"] == id), None)
    return templates.TemplateResponse("event.html", { "request": request, "title": "Some title", "event": event})


def periodic_task():
    print("periodic task")

@app.on_event("startup")
async def setup_periodic_tasks():
    asyncio.create_task(run_periodic(periodic_task, seconds=10))
