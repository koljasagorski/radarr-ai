import os
import json
import re
from datetime import datetime, timezone
from typing import Optional
import requests
from urllib.parse import quote
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from openai import OpenAI

load_dotenv()

RADARR_URL = os.getenv("RADARR_URL", "").rstrip("/")
RADARR_API_KEY = os.getenv("RADARR_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.1")
SEEN_FILE = os.getenv("SEEN_FILE", "/app/seen_movies.json")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
app = FastAPI(title="Radarr KI Assistent")


class ChatRequest(BaseModel):
    message: str


class LookupRequest(BaseModel):
    term: str


class AddMovieRequest(BaseModel):
    tmdbId: int
    qualityProfileId: int
    rootFolderPath: str
    searchForMovie: bool = True


class RecommendRequest(BaseModel):
    message: str
    count: int = 5


class MarkSeenRequest(BaseModel):
    tmdbId: int
    title: Optional[str] = None
    year: Optional[int] = None


class UnmarkSeenRequest(BaseModel):
    tmdbId: int


def radarr_headers():
    return {"X-Api-Key": RADARR_API_KEY}


def radarr_get(endpoint: str):
    url = f"{RADARR_URL}/api/v3/{endpoint.lstrip('/')}"
    r = requests.get(url, headers=radarr_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def radarr_post(endpoint: str, payload: dict):
    url = f"{RADARR_URL}/api/v3/{endpoint.lstrip('/')}"
    r = requests.post(url, headers=radarr_headers(), json=payload, timeout=30)
    if r.status_code >= 400:
        raise Exception(f"Radarr Fehler {r.status_code}: {r.text}")
    return r.json()


def extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```json", "", text)
    text = re.sub(r"^```", "", text)
    text = re.sub(r"```$", "", text)
    return json.loads(text.strip())


def get_poster_url(movie: dict):
    for img in movie.get("images", []):
        if img.get("coverType") == "poster":
            return img.get("remoteUrl") or img.get("url")
    return None


def load_seen_movies():
    try:
        if not os.path.exists(SEEN_FILE):
            return []
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def save_seen_movies(items):
    os.makedirs(os.path.dirname(SEEN_FILE) or ".", exist_ok=True)
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def seen_tmdb_ids():
    return {item.get("tmdbId") for item in load_seen_movies() if item.get("tmdbId")}


def get_radarr_context():
    movies = radarr_get("movie")
    quality_profiles = radarr_get("qualityprofile")
    root_folders = radarr_get("rootfolder")
    queue = radarr_get("queue")
    custom_formats = radarr_get("customformat")

    simplified_movies = [
        {
            "title": m.get("title"),
            "year": m.get("year"),
            "tmdbId": m.get("tmdbId"),
            "qualityProfileId": m.get("qualityProfileId"),
            "monitored": m.get("monitored"),
            "hasFile": m.get("hasFile"),
            "path": m.get("path"),
            "sizeOnDisk": m.get("sizeOnDisk"),
            "quality": m.get("movieFile", {}).get("quality", {}).get("quality", {}).get("name")
            if m.get("movieFile") else None,
        }
        for m in movies[:300]
    ]

    return {
        "movies": simplified_movies,
        "qualityProfiles": quality_profiles,
        "rootFolders": root_folders,
        "queue": queue,
        "customFormats": custom_formats,
    }


@app.get("/", response_class=HTMLResponse)
def gui():
    return r"""
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>Filmempfehlungen für Radarr</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
:root {
    --bg: #050812;
    --bg2: #0b1020;
    --panel: rgba(16, 23, 40, .82);
    --panelStrong: rgba(13, 19, 34, .96);
    --glass: rgba(255,255,255,.07);
    --border: rgba(148, 163, 184, .20);
    --borderStrong: rgba(255,255,255,.18);
    --text: #f8fafc;
    --muted: #aab4c8;
    --muted2: #77849b;
    --orange: #ff6a2a;
    --orange2: #ff3d2e;
    --green: #28d17c;
    --blue: #60a5fa;
    --danger: #ff5d6c;
    --shadow: 0 28px 90px rgba(0,0,0,.48);
    --radius: 28px;
}

* { box-sizing: border-box; }

html {
    min-height: 100%;
    background: var(--bg);
    scroll-behavior: smooth;
}

body {
    margin: 0;
    min-height: 100%;
    color: var(--text);
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background:
        radial-gradient(circle at 12% 18%, rgba(255,106,42,.33), transparent 28rem),
        radial-gradient(circle at 86% 12%, rgba(59,130,246,.23), transparent 34rem),
        radial-gradient(circle at 72% 82%, rgba(14,165,233,.10), transparent 28rem),
        linear-gradient(115deg, rgba(255,106,42,.18) 0%, transparent 23%, transparent 72%, rgba(37,99,235,.12) 100%),
        #050812;
    overflow-x: hidden;
}

body::before {
    content: "";
    position: fixed;
    inset: 0;
    z-index: -2;
    background:
        linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
    background-size: 38px 38px;
    mask-image: linear-gradient(to bottom, rgba(0,0,0,.95), rgba(0,0,0,.18));
    pointer-events: none;
}

body::after {
    content: "";
    position: fixed;
    inset: 0;
    z-index: -1;
    background:
        radial-gradient(ellipse at center, transparent 0%, rgba(0,0,0,.20) 58%, rgba(0,0,0,.68) 100%),
        linear-gradient(to bottom, rgba(5,8,18,.1), rgba(5,8,18,.78));
    pointer-events: none;
}

button,
input,
textarea,
select {
    font: inherit;
}

button {
    border: 0;
    border-radius: 999px;
    padding: 12px 18px;
    color: white;
    background: linear-gradient(135deg, var(--orange), var(--orange2));
    cursor: pointer;
    font-weight: 900;
    font-size: 14px;
    box-shadow: 0 14px 34px rgba(255,90,42,.24);
    transition: transform .16s ease, filter .16s ease, background .16s ease, opacity .16s ease, border-color .16s ease;
}

button:hover {
    transform: translateY(-1px);
    filter: brightness(1.06);
}

button:active {
    transform: translateY(0);
}

button:disabled {
    opacity: .55;
    cursor: not-allowed;
    transform: none;
    filter: none;
}

button.secondary {
    color: #e5e7eb;
    background: rgba(255,255,255,.085);
    border: 1px solid var(--border);
    box-shadow: inset 0 1px 0 rgba(255,255,255,.08), 0 10px 26px rgba(0,0,0,.22);
}

button.secondary:hover {
    background: rgba(255,255,255,.13);
    border-color: rgba(255,255,255,.28);
}

button.green {
    background: linear-gradient(135deg, #22c55e, #16a34a);
    box-shadow: 0 16px 35px rgba(34,197,94,.20);
}

input,
textarea,
select {
    width: 100%;
    color: var(--text);
    background: rgba(2,6,23,.72);
    border: 1px solid rgba(148,163,184,.20);
    border-radius: 18px;
    padding: 13px 14px;
    outline: none;
}

input:focus,
textarea:focus,
select:focus {
    border-color: rgba(255,106,42,.56);
    box-shadow: 0 0 0 4px rgba(255,106,42,.12);
}

textarea {
    resize: vertical;
    min-height: 130px;
    line-height: 1.45;
}

label {
    display: block;
    color: var(--muted);
    margin: 0 0 8px;
    font-size: 14px;
    font-weight: 700;
}

.app {
    width: min(1680px, calc(100% - 56px));
    margin: 0 auto;
    padding: 22px 0 56px;
    position: relative;
}

.topbar {
    height: 54px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 18px;
    margin-bottom: 18px;
}

.brand {
    display: flex;
    align-items: center;
    gap: 13px;
    min-width: 0;
}

.logo {
    width: 38px;
    height: 38px;
    border-radius: 14px;
    background:
        radial-gradient(circle at 32% 25%, rgba(255,255,255,.36), transparent 20%),
        linear-gradient(135deg, #fb923c, #9a3412 70%, #111827);
    box-shadow: 0 16px 38px rgba(249,115,22,.32);
    flex: 0 0 auto;
}

.brandTitle {
    margin: 0;
    font-size: 18px;
    letter-spacing: -.02em;
}

.brandSub {
    margin: 2px 0 0;
    color: var(--muted);
    font-size: 13px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.topActions {
    display: flex;
    align-items: center;
    gap: 10px;
    flex: 0 0 auto;
}

.statusPill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: #dbeafe;
    background: rgba(96,165,250,.13);
    border: 1px solid rgba(96,165,250,.24);
    border-radius: 999px;
    padding: 9px 12px;
    font-size: 13px;
    font-weight: 800;
}

.dot {
    width: 9px;
    height: 9px;
    background: var(--green);
    border-radius: 50%;
    box-shadow: 0 0 18px var(--green);
}

main {
    position: relative;
}

.hero {
    min-height: calc(100svh - 94px);
    display: flex;
    align-items: stretch;
    margin-bottom: 44px;
}

.heroCard {
    position: relative;
    width: 100%;
    min-height: calc(100svh - 126px);
    overflow: hidden;
    border-radius: 38px;
    border: 1px solid rgba(255,255,255,.14);
    background:
        linear-gradient(135deg, rgba(255,255,255,.085), rgba(255,255,255,.025)),
        linear-gradient(120deg, rgba(15,23,42,.92) 0%, rgba(21,31,53,.86) 58%, rgba(12,18,32,.92) 100%);
    box-shadow: var(--shadow);
    backdrop-filter: blur(22px);
}

.heroCard::before {
    content: "";
    position: absolute;
    inset: 0;
    background:
        radial-gradient(circle at 84% 18%, rgba(255,106,42,.25), transparent 20rem),
        radial-gradient(circle at 48% 30%, rgba(96,165,250,.11), transparent 24rem),
        linear-gradient(90deg, rgba(255,106,42,.08), transparent 30%, transparent 68%, rgba(59,130,246,.10));
    pointer-events: none;
}

.heroCard::after {
    content: "";
    position: absolute;
    inset: 0;
    background:
        linear-gradient(rgba(255,255,255,.022) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.018) 1px, transparent 1px);
    background-size: 54px 54px;
    opacity: .62;
    pointer-events: none;
}

.heroLayout {
    position: relative;
    z-index: 1;
    min-height: inherit;
    display: grid;
    grid-template-columns: minmax(0, .98fr) minmax(330px, .82fr);
    gap: clamp(28px, 5vw, 82px);
    align-items: center;
    padding: clamp(32px, 5.4vw, 82px);
}

.heroCopy {
    max-width: 880px;
}

.eyebrow {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: #fed7aa;
    background: rgba(249,115,22,.14);
    border: 1px solid rgba(249,115,22,.30);
    border-radius: 999px;
    padding: 9px 13px;
    font-size: 13px;
    font-weight: 900;
    margin-bottom: 24px;
}

.hero h1 {
    margin: 0;
    max-width: 900px;
    font-size: clamp(58px, 5.4vw, 104px);
    line-height: .88;
    letter-spacing: -.075em;
    color: var(--text);
    text-shadow: 0 18px 55px rgba(0,0,0,.38);
}

.heroLead {
    max-width: 740px;
    margin: 22px 0 26px;
    color: #cbd5e1;
    font-size: clamp(16px, 1.05vw, 20px);
    line-height: 1.62;
}

.promptPanel {
    display: grid;
    gap: 14px;
    max-width: 860px;
}

.promptBox {
    border: 1px solid rgba(255,255,255,.16);
    background:
        linear-gradient(180deg, rgba(2,6,23,.78), rgba(2,6,23,.66)),
        rgba(2,6,23,.75);
    border-radius: 26px;
    padding: 15px;
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.05),
        0 22px 55px rgba(0,0,0,.28);
}

.promptBox textarea {
    min-height: 130px;
    border: 0;
    border-radius: 18px;
    background: transparent;
    padding: 6px 6px 14px;
    font-size: 18px;
    color: #f8fafc;
}

.promptBox textarea::placeholder {
    color: rgba(203,213,225,.58);
}

.promptBottom {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding-top: 11px;
    border-top: 1px solid rgba(148,163,184,.15);
}

.promptOptions {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 10px;
}

.countSelect {
    min-width: 160px;
    border-radius: 999px;
    font-weight: 900;
    background: rgba(2,6,23,.86);
    padding: 11px 14px;
}

.targetMini {
    max-width: 380px;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    color: var(--muted);
    font-size: 13px;
    border: 1px solid rgba(148,163,184,.18);
    border-radius: 999px;
    padding: 10px 12px;
    background: rgba(2,6,23,.38);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.quick {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
}

.chip {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 10px 13px;
    border-radius: 999px;
    color: #e2e8f0;
    background: rgba(255,255,255,.075);
    border: 1px solid rgba(255,255,255,.16);
    cursor: pointer;
    font-size: 14px;
    font-weight: 760;
    transition: border .16s ease, background .16s ease, transform .16s ease;
}

.chip:hover {
    transform: translateY(-1px);
    background: rgba(255,255,255,.12);
    border-color: rgba(255,255,255,.30);
}

.heroShowcase {
    position: relative;
    min-height: 560px;
    align-self: stretch;
    border-radius: 34px;
    border: 1px solid rgba(255,255,255,.13);
    background:
        radial-gradient(circle at 50% 15%, rgba(255,106,42,.16), transparent 18rem),
        linear-gradient(180deg, rgba(255,255,255,.08), rgba(255,255,255,.025));
    box-shadow:
        inset 0 1px 0 rgba(255,255,255,.08),
        0 22px 80px rgba(0,0,0,.20);
    overflow: hidden;
}

.heroShowcase::before {
    content: "";
    position: absolute;
    inset: 0;
    background:
        linear-gradient(120deg, transparent 0 45%, rgba(255,255,255,.05) 45% 46%, transparent 46% 100%),
        radial-gradient(circle at 50% 52%, rgba(255,255,255,.08), transparent 20rem);
    pointer-events: none;
}

.showcaseTop {
    position: absolute;
    top: 24px;
    left: 24px;
    right: 24px;
    display: flex;
    justify-content: space-between;
    gap: 12px;
    color: #e5e7eb;
    z-index: 2;
}

.showcaseTitle {
    display: grid;
    gap: 3px;
}

.showcaseTitle b {
    font-size: 15px;
}

.showcaseTitle span {
    color: var(--muted);
    font-size: 13px;
}

.pulseBadge {
    display: inline-flex;
    align-items: center;
    height: 34px;
    padding: 0 12px;
    border-radius: 999px;
    background: rgba(34,197,94,.13);
    color: #bbf7d0;
    border: 1px solid rgba(34,197,94,.22);
    font-size: 13px;
    font-weight: 900;
}

.posterStack {
    position: absolute;
    inset: 92px 38px 118px;
}

.fakePoster {
    position: absolute;
    width: min(240px, 44%);
    aspect-ratio: 2 / 3;
    border-radius: 24px;
    border: 1px solid rgba(255,255,255,.16);
    overflow: hidden;
    box-shadow: 0 34px 70px rgba(0,0,0,.35);
    display: flex;
    flex-direction: column;
    justify-content: end;
    padding: 18px;
    isolation: isolate;
}

.fakePoster::before {
    content: "";
    position: absolute;
    inset: 0;
    z-index: -1;
}

.fakePoster::after {
    content: "";
    position: absolute;
    inset: 0;
    z-index: -1;
    background:
        linear-gradient(to top, rgba(0,0,0,.76), transparent 55%),
        radial-gradient(circle at 50% 15%, rgba(255,255,255,.18), transparent 45%);
}

.fakePoster b {
    font-size: 19px;
    line-height: 1.05;
}

.fakePoster span {
    margin-top: 5px;
    color: #cbd5e1;
    font-size: 13px;
    line-height: 1.25;
}

.posterOne {
    left: 6%;
    top: 10%;
    transform: rotate(-8deg);
}

.posterOne::before {
    background:
        radial-gradient(circle at 70% 20%, rgba(255,255,255,.16), transparent 21%),
        linear-gradient(145deg, #7f1d1d, #fb923c 52%, #111827);
}

.posterTwo {
    left: 34%;
    top: 0;
    width: min(270px, 48%);
    transform: rotate(2deg);
    z-index: 2;
}

.posterTwo::before {
    background:
        radial-gradient(circle at 42% 20%, rgba(255,255,255,.19), transparent 22%),
        linear-gradient(145deg, #1e3a8a, #0f172a 42%, #7c2d12);
}

.posterThree {
    right: 4%;
    top: 18%;
    transform: rotate(8deg);
}

.posterThree::before {
    background:
        radial-gradient(circle at 55% 28%, rgba(255,255,255,.18), transparent 23%),
        linear-gradient(145deg, #064e3b, #0f172a 45%, #581c87);
}

.showcaseBottom {
    position: absolute;
    left: 24px;
    right: 24px;
    bottom: 24px;
    z-index: 2;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
}

.miniMetric {
    min-height: 72px;
    display: grid;
    align-content: center;
    gap: 4px;
    padding: 13px;
    border-radius: 20px;
    background: rgba(2,6,23,.48);
    border: 1px solid rgba(255,255,255,.11);
}

.miniMetric b {
    font-size: 18px;
}

.miniMetric span {
    color: var(--muted);
    font-size: 12px;
    line-height: 1.25;
}

.advanced {
    margin: 24px 0 12px;
    border: 1px solid var(--border);
    border-radius: 30px;
    background: rgba(15,23,42,.82);
    box-shadow: 0 20px 70px rgba(0,0,0,.32);
    overflow: hidden;
}

.advancedHead {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    padding: 20px 22px;
    border-bottom: 1px solid rgba(148,163,184,.15);
}

.advanced h2,
.sectionHead h2 {
    margin: 0;
    font-size: 30px;
    letter-spacing: -.04em;
}

.smallMuted,
.sectionHead p {
    color: var(--muted);
    margin: 4px 0 0;
    font-size: 14px;
}

.iconButton {
    width: 42px;
    height: 42px;
    padding: 0;
    display: inline-grid;
    place-items: center;
    font-size: 22px;
}

.tabs {
    display: flex;
    gap: 8px;
    padding: 14px 18px 0;
    flex-wrap: wrap;
}

.tabButton {
    background: transparent;
    border: 1px solid var(--border);
    box-shadow: none;
    color: var(--muted);
}

.tabButton.active {
    color: white;
    background: rgba(255,106,42,.16);
    border-color: rgba(255,106,42,.32);
}

.toolPanel {
    display: none;
    padding: 20px 22px 24px;
}

.toolPanel.active {
    display: block;
}

.formGrid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 14px;
}

.checkboxLine {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    margin: 16px 0;
    color: #e5e7eb;
    font-weight: 700;
}

.checkboxLine input {
    width: auto;
}

.actions {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
    margin-top: 14px;
}

#chat,
#analysis {
    white-space: pre-wrap;
    background: rgba(2,6,23,.58);
    border: 1px solid var(--border);
    border-radius: 20px;
    padding: 16px;
    min-height: 130px;
    max-height: 430px;
    overflow: auto;
    color: #dbeafe;
}

.msg {
    margin-bottom: 13px;
    line-height: 1.52;
}

.user { color: #93c5fd; }
.bot { color: #d1fae5; }
.err { color: #fca5a5; }

.sectionHead {
    display: flex;
    justify-content: space-between;
    gap: 16px;
    align-items: end;
    margin: 0 0 18px;
}

.resultsTools {
    flex: 0 0 auto;
}

.emptyState,
.loading {
    min-height: 120px;
    display: grid;
    place-items: center;
    gap: 8px;
    text-align: center;
    color: var(--muted);
    border: 1px dashed rgba(148,163,184,.30);
    border-radius: 26px;
    background: rgba(2,6,23,.38);
    padding: 24px;
}

.emptyState b,
.loading b {
    color: var(--text);
    display: block;
}

.movieGrid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(224px, 1fr));
    gap: 20px;
}

.movieCard {
    position: relative;
    min-width: 0;
    border-radius: 26px;
    overflow: hidden;
    background: rgba(15,23,42,.82);
    border: 1px solid rgba(255,255,255,.12);
    box-shadow: 0 18px 60px rgba(0,0,0,.32);
    display: flex;
    flex-direction: column;
    transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}

.movieCard:hover {
    transform: translateY(-4px);
    border-color: rgba(255,255,255,.24);
    box-shadow: 0 26px 82px rgba(0,0,0,.42);
}

.posterWrap {
    position: relative;
    width: 100%;
    aspect-ratio: 2 / 3;
    background: rgba(2,6,23,.8);
    overflow: hidden;
}

.poster {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}

.posterShade {
    position: absolute;
    inset: 0;
    background: linear-gradient(to top, rgba(2,6,23,.52), transparent 45%);
    pointer-events: none;
}

.noPoster {
    min-height: 100%;
    display: grid;
    place-items: center;
    padding: 20px;
    text-align: center;
    color: var(--muted);
    background:
        radial-gradient(circle at 50% 28%, rgba(255,106,42,.17), transparent 40%),
        #0f172a;
}

.badges {
    position: absolute;
    left: 12px;
    right: 12px;
    bottom: 12px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
}

.badge {
    color: #fff;
    background: rgba(2,6,23,.72);
    border: 1px solid rgba(255,255,255,.18);
    border-radius: 999px;
    padding: 6px 9px;
    font-size: 12px;
    font-weight: 900;
    backdrop-filter: blur(10px);
}

.seenToggle {
    position: absolute;
    top: 10px;
    right: 10px;
    z-index: 3;
    padding: 7px 11px;
    border-radius: 999px;
    color: #fff;
    background: rgba(2,6,23,.72);
    border: 1px solid rgba(255,255,255,.20);
    backdrop-filter: blur(10px);
    cursor: pointer;
    font-size: 12px;
    font-weight: 800;
    box-shadow: 0 8px 22px rgba(0,0,0,.32);
    transition: background .16s ease, border-color .16s ease, transform .16s ease;
}

.seenToggle:hover {
    background: rgba(40,209,124,.36);
    border-color: rgba(40,209,124,.55);
    transform: translateY(-1px);
}

.seenList {
    display: grid;
    gap: 10px;
}

.seenItem {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 14px;
    border-radius: 18px;
    background: rgba(2,6,23,.45);
    border: 1px solid var(--border);
}

.seenItem b {
    font-size: 14px;
}

.seenItem span {
    color: var(--muted);
    font-size: 12px;
}

.seenItem button {
    padding: 8px 12px;
    font-size: 12px;
}

.movieContent {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 16px;
    flex: 1;
}

.movieTitle {
    font-size: 17px;
    font-weight: 950;
    line-height: 1.16;
    letter-spacing: -.02em;
}

.reason {
    color: #fed7aa;
    background: rgba(249,115,22,.10);
    border: 1px solid rgba(249,115,22,.18);
    border-radius: 16px;
    padding: 10px;
    font-size: 13px;
    line-height: 1.36;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

.overview {
    color: #cbd5e1;
    font-size: 13px;
    line-height: 1.45;
    display: -webkit-box;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

.movieActions {
    margin-top: auto;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 9px;
    padding-top: 4px;
}

.movieActions button {
    padding: 10px 11px;
    font-size: 13px;
}

.modalBackdrop {
    position: fixed;
    inset: 0;
    display: none;
    place-items: center;
    padding: 24px;
    background: rgba(2,6,23,.72);
    backdrop-filter: blur(18px);
    z-index: 50;
}

.modalBackdrop.active {
    display: grid;
}

.modal {
    width: min(900px, 100%);
    max-height: min(760px, calc(100vh - 48px));
    overflow: auto;
    border-radius: 30px;
    border: 1px solid rgba(255,255,255,.14);
    background: rgba(15,23,42,.96);
    box-shadow: 0 40px 120px rgba(0,0,0,.55);
}

.modalHero {
    display: grid;
    grid-template-columns: 260px minmax(0, 1fr);
    gap: 24px;
    padding: 24px;
}

.modalPoster {
    width: 100%;
    border-radius: 22px;
    object-fit: cover;
    box-shadow: 0 20px 60px rgba(0,0,0,.36);
}

.modalBody {
    display: flex;
    flex-direction: column;
    gap: 14px;
}

.modalBody h2 {
    margin: 0;
    font-size: 32px;
    line-height: 1;
    letter-spacing: -.04em;
}

.modalMeta {
    color: var(--muted);
    margin-top: 6px;
}

.modalReason,
.modalText {
    color: #dbeafe;
    line-height: 1.5;
}

.modalReason {
    color: #fed7aa;
    padding: 13px;
    border-radius: 18px;
    background: rgba(249,115,22,.10);
    border: 1px solid rgba(249,115,22,.18);
}

.modalActions {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    margin-top: auto;
}

.toast {
    position: fixed;
    right: 22px;
    bottom: 22px;
    z-index: 80;
    display: grid;
    gap: 10px;
    pointer-events: none;
}

.toastItem {
    max-width: 380px;
    color: white;
    background: rgba(15,23,42,.94);
    border: 1px solid rgba(255,255,255,.16);
    border-radius: 18px;
    padding: 13px 15px;
    box-shadow: 0 18px 60px rgba(0,0,0,.42);
}

.toastItem.ok {
    border-color: rgba(34,197,94,.32);
}

.toastItem.err {
    border-color: rgba(239,68,68,.42);
    color: #fecaca;
}

@media (max-width: 1180px) {
    .heroLayout {
        grid-template-columns: 1fr;
        align-items: start;
    }

    .heroShowcase {
        min-height: 330px;
    }

    .posterStack {
        inset: 78px 28px 96px;
    }

    .fakePoster {
        width: min(190px, 34%);
    }
}

@media (max-width: 760px) {
    .app {
        width: min(100% - 22px, 1680px);
        padding-top: 14px;
    }

    .topbar {
        height: auto;
        align-items: flex-start;
        flex-direction: column;
        margin-bottom: 16px;
    }

    .topActions {
        width: 100%;
        justify-content: space-between;
    }

    .brandSub {
        white-space: normal;
    }

    .hero {
        min-height: auto;
        margin-bottom: 32px;
    }

    .heroCard {
        min-height: auto;
        border-radius: 28px;
    }

    .heroLayout {
        padding: 26px;
        gap: 24px;
    }

    .hero h1 {
        font-size: clamp(44px, 13vw, 66px);
    }

    .heroLead {
        font-size: 15px;
        margin: 16px 0 20px;
    }

    .promptBox textarea {
        font-size: 15px;
        min-height: 116px;
    }

    .promptBottom,
    .promptOptions {
        align-items: stretch;
        flex-direction: column;
        width: 100%;
    }

    .targetMini {
        max-width: 100%;
        white-space: normal;
    }

    .heroShowcase {
        display: none;
    }

    .sectionHead {
        align-items: start;
        flex-direction: column;
    }

    .formGrid {
        grid-template-columns: 1fr;
    }

    .movieGrid {
        grid-template-columns: repeat(auto-fill, minmax(158px, 1fr));
        gap: 13px;
    }

    .movieActions {
        grid-template-columns: 1fr;
    }

    .modalHero {
        grid-template-columns: 1fr;
    }

    .modalPoster {
        max-width: 260px;
    }
}
</style>
</head>
<body>
<div class="app">

    <header class="topbar">
        <div class="brand">
            <div class="logo"></div>
            <div>
                <h1 class="brandTitle">KI-Empfehlungen für Radarr</h1>
                <p class="brandSub">Filmwunsch rein, Cover prüfen, per Klick zu Radarr hinzufügen.</p>
            </div>
        </div>
        <div class="topActions">
            <div class="statusPill"><span class="dot"></span><span id="topStatus">bereit</span></div>
            <button class="secondary" onclick="toggleAdvanced()">Setup & Tools</button>
        </div>
    </header>

    <main>

        <section class="hero">
            <div class="heroCard">
                <div class="heroLayout">
                    <div class="heroCopy">
                        <div class="eyebrow">Fokus: Empfehlungen</div>
                        <h1>Was willst du heute schauen?</h1>
                        <p class="heroLead">
                            Sag einfach, worauf du Bock hast: Genre-Mix, Stimmung, Härtegrad, Zeitraum, Regisseur
                            oder „3 richtig krasse Actionfilme“. Vorhandene Filme werden möglichst rausgefiltert.
                        </p>

                        <div class="promptPanel">
                            <div class="promptBox">
                                <textarea id="recommendPrompt" placeholder="z. B. Empfiehl mir einen Liebesdrama-Thriller mit starkem Twist, den ich noch nicht habe."></textarea>
                                <div class="promptBottom">
                                    <div class="promptOptions">
                                        <select id="countSelect" class="countSelect">
                                            <option value="auto">Anzahl: automatisch</option>
                                            <option value="1">1 Film</option>
                                            <option value="3">3 Filme</option>
                                            <option value="5" selected>5 Filme</option>
                                            <option value="10">10 Filme</option>
                                            <option value="15">15 Filme</option>
                                        </select>
                                        <span class="targetMini" id="targetSummary">Radarr-Ziel wird geladen...</span>
                                    </div>
                                    <div class="promptOptions">
                                        <button class="secondary" onclick="clearResults()">Leeren</button>
                                        <button onclick="recommendMovies()">Empfehlungen holen</button>
                                    </div>
                                </div>
                            </div>

                            <div class="quick">
                                <span class="chip" onclick="setPrompt('Empfiehl mir einen Liebesdrama-Thriller mit starkem Twist, der nicht kitschig ist', 1)">Liebesdrama-Thriller</span>
                                <span class="chip" onclick="setPrompt('Empfiehl mir 3 richtig krasse Actionfilme mit harter Inszenierung und hohem Wiedersehwert', 3)">3 krasse Actionfilme</span>
                                <span class="chip" onclick="setPrompt('5 düstere Thriller, die intelligent sind und lange nachwirken', 5)">Düstere Thriller</span>
                                <span class="chip" onclick="setPrompt('5 Sci-Fi Mindfuck Filme mit cleverem Konzept', 5)">Sci-Fi Mindfuck</span>
                                <span class="chip" onclick="setPrompt('3 starke Filme aus Korea oder Japan, die zu meiner Bibliothek passen', 3)">Asia-Perlen</span>
                                <span class="chip" onclick="setPrompt('10 unterschätzte Filme vor 2010, die ich noch nicht habe', 10)">Unter 2010</span>
                            </div>
                        </div>
                    </div>

                    <aside class="heroShowcase" aria-hidden="true">
                        <div class="showcaseTop">
                            <div class="showcaseTitle">
                                <b>Recommendation Mode</b>
                                <span>Wunsch → Cover → Radarr</span>
                            </div>
                            <div class="pulseBadge">bereit</div>
                        </div>

                        <div class="posterStack">
                            <div class="fakePoster posterOne">
                                <b>Action</b>
                                <span>hart, ikonisch, hoher Wiedersehwert</span>
                            </div>
                            <div class="fakePoster posterTwo">
                                <b>Thriller</b>
                                <span>düster, clever, mit Twist</span>
                            </div>
                            <div class="fakePoster posterThree">
                                <b>Drama</b>
                                <span>emotional, intensiv, nicht kitschig</span>
                            </div>
                        </div>

                        <div class="showcaseBottom">
                            <div class="miniMetric">
                                <b>1 Klick</b>
                                <span>Film zu Radarr hinzufügen</span>
                            </div>
                            <div class="miniMetric">
                                <b>Cover</b>
                                <span>vorher sauber prüfen</span>
                            </div>
                            <div class="miniMetric">
                                <b>Filter</b>
                                <span>vorhandene Filme raus</span>
                            </div>
                        </div>
                    </aside>
                </div>
            </div>
        </section>


        <section class="advanced" id="advancedPanel" hidden>
            <div class="advancedHead">
                <div>
                    <h2>Setup & Tools</h2>
                    <div class="smallMuted">Nur öffnen, wenn du Zielprofil, Root Folder, Chat oder Analyse brauchst.</div>
                </div>
                <button class="iconButton secondary" onclick="toggleAdvanced()" title="Schließen">×</button>
            </div>

            <div class="tabs">
                <button class="tabButton active" id="tab-config" onclick="switchTool('config')">Radarr-Ziel</button>
                <button class="tabButton" id="tab-search" onclick="switchTool('search')">Manuelle Suche</button>
                <button class="tabButton" id="tab-seen" onclick="switchTool('seen')">Gesehen-Liste</button>
                <button class="tabButton" id="tab-chat" onclick="switchTool('chat')">Setup-Chat</button>
                <button class="tabButton" id="tab-analysis" onclick="switchTool('analysis')">Library-Analyse</button>
            </div>

            <div class="toolPanel active" id="tool-config">
                <div class="formGrid">
                    <div>
                        <label>Qualitätsprofil für neue Filme</label>
                        <select id="qualityProfile" onchange="updateTargetSummary()"></select>
                    </div>
                    <div>
                        <label>Root Folder</label>
                        <select id="rootFolder" onchange="updateTargetSummary()"></select>
                    </div>
                </div>
                <label class="checkboxLine">
                    <input type="checkbox" id="searchForMovie" checked onchange="updateTargetSummary()">
                    Nach dem Hinzufügen direkt in Radarr suchen
                </label>
                <div class="actions">
                    <button class="secondary" onclick="loadConfig()">Radarr-Konfiguration neu laden</button>
                </div>
                <p class="smallMuted" id="configStatus">Noch nicht geladen.</p>
            </div>

            <div class="toolPanel" id="tool-search">
                <div class="formGrid">
                    <div>
                        <label>Film manuell über Radarr suchen</label>
                        <input id="movieSearch" placeholder="z. B. Heat, Drive, The Handmaiden">
                    </div>
                    <div style="align-self:end">
                        <button onclick="lookupMovie()">Suchen</button>
                    </div>
                </div>
                <p class="smallMuted">Suchergebnisse erscheinen unten in denselben Cover-Karten und können ebenfalls zu Radarr hinzugefügt werden.</p>
            </div>

            <div class="toolPanel" id="tool-seen">
                <p class="smallMuted">
                    Hier sammelst du Filme, die du schon gesehen hast oder nicht (mehr) vorgeschlagen bekommen willst.
                    Die KI bekommt diese Liste bei jeder neuen Anfrage mit und schlägt sie nicht erneut vor.
                    Gespeichert in <code id="seenFilePath">seen_movies.json</code>.
                </p>
                <div class="actions">
                    <button class="secondary" onclick="loadSeenList()">Liste neu laden</button>
                    <span class="smallMuted" id="seenStatus">noch nicht geladen</span>
                </div>
                <div id="seenList" style="margin-top:14px;"></div>
            </div>

            <div class="toolPanel" id="tool-chat">
                <div id="chat">
                    <div class="msg bot"><b>KI:</b> Frag z. B.: „Analysiere meine Qualitätsprofile“ oder „Warum werden keine Upgrades gemacht?“</div>
                </div>
                <textarea id="message" placeholder="Setup-Frage eingeben..."></textarea>
                <div class="actions">
                    <button id="send" onclick="sendMessage()">Chat senden</button>
                </div>
            </div>

            <div class="toolPanel" id="tool-analysis">
                <div class="actions">
                    <button onclick="runLibraryAnalysis()">Library analysieren</button>
                </div>
                <div id="analysis">Noch keine Analyse gestartet.</div>
            </div>
        </section>

        <section>
            <div class="sectionHead">
                <div>
                    <h2>Empfehlungen</h2>
                    <p id="resultInfo">Noch keine Ergebnisse. Starte oben mit deinem Filmwunsch.</p>
                </div>
                <div class="resultsTools">
                    <button class="secondary" onclick="openTool('config')">Radarr-Ziel ändern</button>
                </div>
            </div>
            <div id="results">
                <div class="emptyState">
                    <b>Bereit für deinen nächsten Filmabend.</b>
                    Beispiele: „Liebesdrama-Thriller“, „3 krasse Actionfilme“, „5 düstere Thriller“, „Sci-Fi Mindfuck“.
                </div>
            </div>
        </section>
    </main>
</div>

<div class="modalBackdrop" id="movieModal" onclick="closeMovieDetails(event)">
    <div class="modal" onclick="event.stopPropagation()">
        <div id="modalContent"></div>
    </div>
</div>

<div class="toast" id="toast"></div>

<script>
let movieCache = new Map();

window.onload = () => {
    loadConfig();
    document.getElementById("recommendPrompt").addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
            recommendMovies();
        }
    });
};

function setStatus(text) {
    document.getElementById("topStatus").innerText = text;
}

function setPrompt(text, count) {
    document.getElementById("recommendPrompt").value = text;
    if (count) document.getElementById("countSelect").value = String(count);
    document.getElementById("recommendPrompt").focus();
}

function toggleAdvanced() {
    const panel = document.getElementById("advancedPanel");
    panel.hidden = !panel.hidden;
    if (!panel.hidden) panel.scrollIntoView({behavior: "smooth", block: "nearest"});
}

function openTool(tool) {
    const panel = document.getElementById("advancedPanel");
    panel.hidden = false;
    switchTool(tool);
    panel.scrollIntoView({behavior: "smooth", block: "nearest"});
}

function switchTool(tool) {
    ["config","search","seen","chat","analysis"].forEach(name => {
        document.getElementById("tool-" + name).classList.toggle("active", name === tool);
        document.getElementById("tab-" + name).classList.toggle("active", name === tool);
    });
    if (tool === "seen") loadSeenList();
}

function clearResults() {
    movieCache.clear();
    document.getElementById("results").innerHTML = `
        <div class="emptyState">
            <b>Bereit für deinen nächsten Filmabend.</b>
            Beispiele: „Liebesdrama-Thriller“, „3 krasse Actionfilme“, „5 düstere Thriller“, „Sci-Fi Mindfuck“.
        </div>`;
    document.getElementById("resultInfo").innerText = "Noch keine Ergebnisse. Starte oben mit deinem Filmwunsch.";
}

async function loadConfig() {
    const status = document.getElementById("configStatus");
    status.innerText = "Lade Radarr-Konfiguration...";
    setStatus("lade Radarr-Ziel");

    try {
        const res = await fetch("/config");
        const data = await res.json();

        if (data.error) {
            status.innerText = "Fehler: " + data.error;
            document.getElementById("targetSummary").innerText = "Radarr-Ziel nicht geladen";
            setStatus("Fehler");
            toast("Radarr-Konfiguration konnte nicht geladen werden.", "err");
            return;
        }

        const qp = document.getElementById("qualityProfile");
        const rf = document.getElementById("rootFolder");

        qp.innerHTML = "";
        rf.innerHTML = "";

        data.qualityProfiles.forEach(p => {
            const option = document.createElement("option");
            option.value = p.id;
            option.textContent = p.name;
            qp.appendChild(option);
        });

        data.rootFolders.forEach(f => {
            const option = document.createElement("option");
            option.value = f.path;
            option.textContent = `${f.path} · ${formatBytes(f.freeSpace)} frei`;
            rf.appendChild(option);
        });

        status.innerText = `${data.qualityProfiles.length} Profile, ${data.rootFolders.length} Root Folder geladen.`;
        updateTargetSummary();
        setStatus("bereit");
    } catch (err) {
        status.innerText = "Fehler: " + err.toString();
        document.getElementById("targetSummary").innerText = "Radarr-Ziel nicht geladen";
        setStatus("Fehler");
        toast("Fehler beim Laden der Radarr-Konfiguration.", "err");
    }
}

function updateTargetSummary() {
    const qp = document.getElementById("qualityProfile");
    const rf = document.getElementById("rootFolder");
    const search = document.getElementById("searchForMovie")?.checked;
    const profile = qp && qp.selectedIndex >= 0 ? qp.options[qp.selectedIndex].text : "kein Profil";
    const folder = rf && rf.value ? compactPath(rf.value) : "kein Root Folder";
    document.getElementById("targetSummary").innerText = `${profile} · ${folder} · Suche: ${search ? "an" : "aus"}`;
}

async function recommendMovies() {
    const results = document.getElementById("results");
    const prompt = document.getElementById("recommendPrompt").value.trim()
        || "Empfiehl mir 5 passende Filme, die perfekt zu meiner vorhandenen Bibliothek passen und noch fehlen.";

    results.innerHTML = `<div class="loading"><b>KI sucht passende Filme...</b>Ich prüfe deine Anfrage gegen die vorhandene Radarr-Bibliothek.</div>`;
    document.getElementById("resultInfo").innerText = "Empfehlungen werden generiert...";
    setStatus("KI arbeitet");

    try {
        const selectedCount = document.getElementById("countSelect").value;
        const count = selectedCount === "auto" ? (extractWantedCount(prompt) || 5) : parseInt(selectedCount);

        const res = await fetch("/recommend-movies", {
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({message: prompt, count})
        });

        const data = await res.json();

        if (data.error) {
            results.innerHTML = `<div class="errorState"><b>Fehler bei der Empfehlung.</b>${escapeHtml(data.error)}</div>`;
            document.getElementById("resultInfo").innerText = "Fehler.";
            setStatus("Fehler");
            toast("Empfehlung fehlgeschlagen.", "err");
            return;
        }

        renderMovies(data.recommendations || [], "KI-Empfehlungen");
        setStatus("bereit");
    } catch (err) {
        results.innerHTML = `<div class="errorState"><b>Fehler.</b>${escapeHtml(err.toString())}</div>`;
        document.getElementById("resultInfo").innerText = "Fehler.";
        setStatus("Fehler");
        toast("Empfehlung fehlgeschlagen.", "err");
    }
}

async function lookupMovie() {
    const term = document.getElementById("movieSearch").value.trim();
    const results = document.getElementById("results");
    if (!term) return;

    results.innerHTML = `<div class="loading"><b>Suche läuft...</b>Radarr Lookup wird abgefragt.</div>`;
    document.getElementById("resultInfo").innerText = "Suche läuft...";
    setStatus("suche");

    try {
        const res = await fetch("/lookup-movie", {
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({term})
        });

        const data = await res.json();

        if (data.error) {
            results.innerHTML = `<div class="errorState"><b>Fehler bei der Suche.</b>${escapeHtml(data.error)}</div>`;
            document.getElementById("resultInfo").innerText = "Fehler.";
            setStatus("Fehler");
            return;
        }

        renderMovies(data.results || [], "Suchergebnisse");
        setStatus("bereit");
    } catch (err) {
        results.innerHTML = `<div class="errorState"><b>Fehler.</b>${escapeHtml(err.toString())}</div>`;
        document.getElementById("resultInfo").innerText = "Fehler.";
        setStatus("Fehler");
    }
}

function renderMovies(movies, heading) {
    const results = document.getElementById("results");
    const info = document.getElementById("resultInfo");
    movieCache.clear();

    if (!movies.length) {
        results.innerHTML = `<div class="emptyState"><b>Keine passenden Filme gefunden.</b>Formuliere den Wunsch etwas breiter oder erhöhe die Anzahl.</div>`;
        info.innerText = "0 Ergebnisse.";
        return;
    }

    info.innerText = `${movies.length} Ergebnis(se) · ${heading}`;

    let html = `<div class="movieGrid">`;

    movies.forEach(movie => {
        movieCache.set(String(movie.tmdbId), movie);
        const poster = movie.posterUrl
            ? `<img class="poster" src="${escapeAttr(movie.posterUrl)}" alt="Poster von ${escapeAttr(movie.title || "Film")}">`
            : `<div class="noPoster">Kein Cover verfügbar</div>`;

        const reason = movie.reason ? `<div class="reason">${escapeHtml(movie.reason)}</div>` : "";
        const overview = movie.overview ? `<div class="overview">${escapeHtml(movie.overview)}</div>` : `<div class="overview">Keine Beschreibung vorhanden.</div>`;

        html += `
        <article class="movieCard" id="movie-${movie.tmdbId}">
            <button class="seenToggle" title="Als schon gesehen markieren - wird nicht mehr vorgeschlagen" onclick="markSeen(${Number(movie.tmdbId)}, this)">✓ Schon gesehen</button>
            <div class="posterWrap">
                ${poster}
                <div class="posterShade"></div>
                <div class="badges">
                    <span class="badge">${movie.year || "?"}</span>
                    <span class="badge">TMDB ${movie.tmdbId || "?"}</span>
                </div>
            </div>
            <div class="movieContent">
                <div class="movieTitle">${escapeHtml(movie.title || "Unbekannter Film")}</div>
                ${reason}
                ${overview}
                <div class="movieActions">
                    <button class="secondary" onclick="openMovieDetails(${Number(movie.tmdbId)})">Details</button>
                    <button class="green" onclick="addMovie(${Number(movie.tmdbId)}, this)">Zu Radarr</button>
                </div>
            </div>
        </article>`;
    });

    html += `</div>`;
    results.innerHTML = html;
}

function openMovieDetails(tmdbId) {
    const movie = movieCache.get(String(tmdbId));
    if (!movie) return;

    const poster = movie.posterUrl
        ? `<img class="modalPoster" src="${escapeAttr(movie.posterUrl)}" alt="Poster">`
        : `<div class="modalPoster noPoster">Kein Cover verfügbar</div>`;

    const qp = document.getElementById("qualityProfile");
    const rf = document.getElementById("rootFolder");
    const profile = qp && qp.selectedIndex >= 0 ? qp.options[qp.selectedIndex].text : "kein Profil";
    const root = rf && rf.value ? rf.value : "kein Root Folder";
    const search = document.getElementById("searchForMovie").checked ? "Ja" : "Nein";

    document.getElementById("modalContent").innerHTML = `
        <div class="modalHero">
            ${poster}
            <div class="modalBody">
                <div>
                    <h2>${escapeHtml(movie.title || "Unbekannter Film")}</h2>
                    <div class="modalMeta">${movie.year || "?"} · TMDB ${movie.tmdbId || "?"}</div>
                </div>
                ${movie.reason ? `<div class="modalReason"><b>Warum diese Empfehlung:</b><br>${escapeHtml(movie.reason)}</div>` : ""}
                <div class="modalText">${escapeHtml(movie.overview || "Keine Beschreibung vorhanden.")}</div>
                <div class="smallMuted">
                    Geplante Radarr-Aktion:<br>
                    Profil: ${escapeHtml(profile)}<br>
                    Root Folder: ${escapeHtml(root)}<br>
                    Direkt suchen: ${escapeHtml(search)}
                </div>
                <div class="modalActions">
                    <button class="green" onclick="addMovie(${Number(movie.tmdbId)}, this)">Zu Radarr hinzufügen</button>
                    <button class="secondary" onclick="closeMovieDetails()">Schließen</button>
                </div>
            </div>
        </div>`;
    document.getElementById("movieModal").classList.add("active");
}

function closeMovieDetails(event) {
    if (event && event.target.id !== "movieModal") return;
    document.getElementById("movieModal").classList.remove("active");
}

async function addMovie(tmdbId, button) {
    const qualityProfileId = parseInt(document.getElementById("qualityProfile").value);
    const rootFolderPath = document.getElementById("rootFolder").value;
    const searchForMovie = document.getElementById("searchForMovie").checked;

    if (!qualityProfileId || !rootFolderPath) {
        toast("Bitte zuerst Qualitätsprofil und Root Folder im Setup wählen.", "err");
        openTool("config");
        return;
    }

    const movie = movieCache.get(String(tmdbId));
    const title = movie?.title || "diesen Film";

    if (!confirm(`${title} wirklich zu Radarr hinzufügen?`)) return;

    const oldText = button ? button.innerText : "";
    if (button) {
        button.disabled = true;
        button.innerText = "Füge hinzu...";
    }

    setStatus("füge hinzu");

    try {
        const res = await fetch("/add-movie", {
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({tmdbId, qualityProfileId, rootFolderPath, searchForMovie})
        });

        const data = await res.json();

        if (data.error) {
            toast("Fehler: " + data.error, "err");
            setStatus("Fehler");
            if (button) {
                button.disabled = false;
                button.innerText = oldText;
            }
        } else {
            toast(`Hinzugefügt: ${data.title} (${data.year})`, "ok");
            setStatus("bereit");
            markMovieAdded(tmdbId);
            if (button) {
                button.innerText = "Hinzugefügt";
            }
        }
    } catch (err) {
        toast("Fehler: " + err.toString(), "err");
        setStatus("Fehler");
        if (button) {
            button.disabled = false;
            button.innerText = oldText;
        }
    }
}

function markMovieAdded(tmdbId) {
    const card = document.getElementById("movie-" + tmdbId);
    if (!card) return;
    card.style.opacity = ".68";
    card.querySelectorAll("button.green").forEach(btn => {
        btn.disabled = true;
        btn.innerText = "Hinzugefügt";
    });
}

async function markSeen(tmdbId, button) {
    const movie = movieCache.get(String(tmdbId));
    const title = movie?.title || "Film";
    const year = movie?.year || null;

    if (button) {
        button.disabled = true;
        button.innerText = "...";
    }

    try {
        const res = await fetch("/mark-seen", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({tmdbId, title, year})
        });
        const data = await res.json();

        if (data.error) {
            toast("Fehler: " + data.error, "err");
            if (button) {
                button.disabled = false;
                button.innerText = "✓ Schon gesehen";
            }
            return;
        }

        toast(`Als gesehen markiert: ${title}`, "ok");
        const card = document.getElementById("movie-" + tmdbId);
        if (card) {
            card.style.transition = "opacity .25s ease, transform .25s ease";
            card.style.opacity = "0";
            card.style.transform = "scale(.96)";
            setTimeout(() => card.remove(), 260);
        }
    } catch (err) {
        toast("Fehler: " + err.toString(), "err");
        if (button) {
            button.disabled = false;
            button.innerText = "✓ Schon gesehen";
        }
    }
}

async function loadSeenList() {
    const box = document.getElementById("seenList");
    const status = document.getElementById("seenStatus");
    box.innerHTML = `<div class="loading"><b>Lade Liste...</b></div>`;
    status.innerText = "lade...";

    try {
        const res = await fetch("/seen-movies");
        const data = await res.json();

        if (data.error) {
            box.innerHTML = `<div class="emptyState"><b>Fehler.</b>${escapeHtml(data.error)}</div>`;
            status.innerText = "Fehler";
            return;
        }

        const items = data.items || [];
        status.innerText = `${items.length} Eintrag/Einträge`;

        if (!items.length) {
            box.innerHTML = `<div class="emptyState"><b>Liste ist leer.</b>Markiere Empfehlungen mit „✓ Schon gesehen“, damit sie hier landen.</div>`;
            return;
        }

        let html = `<div class="seenList">`;
        items.forEach(item => {
            const id = Number(item.tmdbId);
            const date = item.markedAt ? new Date(item.markedAt).toLocaleDateString("de-DE") : "";
            html += `
                <div class="seenItem" id="seen-${id}">
                    <div>
                        <b>${escapeHtml(item.title || "Unbekannt")}</b>
                        <span> · ${item.year || "?"} · TMDB ${id}${date ? " · markiert " + escapeHtml(date) : ""}</span>
                    </div>
                    <button class="secondary" onclick="unmarkSeen(${id}, this)">Entfernen</button>
                </div>`;
        });
        html += `</div>`;
        box.innerHTML = html;
    } catch (err) {
        box.innerHTML = `<div class="emptyState"><b>Fehler.</b>${escapeHtml(err.toString())}</div>`;
        status.innerText = "Fehler";
    }
}

async function unmarkSeen(tmdbId, button) {
    if (button) {
        button.disabled = true;
        button.innerText = "...";
    }

    try {
        const res = await fetch("/unmark-seen", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({tmdbId})
        });
        const data = await res.json();

        if (data.error) {
            toast("Fehler: " + data.error, "err");
            if (button) {
                button.disabled = false;
                button.innerText = "Entfernen";
            }
            return;
        }

        toast("Aus Gesehen-Liste entfernt", "ok");
        loadSeenList();
    } catch (err) {
        toast("Fehler: " + err.toString(), "err");
        if (button) {
            button.disabled = false;
            button.innerText = "Entfernen";
        }
    }
}

async function sendMessage() {
    const input = document.getElementById("message");
    const button = document.getElementById("send");
    const chat = document.getElementById("chat");
    const message = input.value.trim();
    if (!message) return;

    chat.innerHTML += `<div class="msg user"><b>Du:</b> ${escapeHtml(message)}</div>`;
    input.value = "";
    button.disabled = true;
    button.innerText = "Analysiere...";
    setStatus("KI arbeitet");

    try {
        const res = await fetch("/chat", {
            method:"POST",
            headers:{"Content-Type":"application/json"},
            body:JSON.stringify({message})
        });
        const data = await res.json();
        chat.innerHTML += `<div class="msg bot"><b>KI:</b> ${escapeHtml(data.answer || data.error || "Keine Antwort")}</div>`;
    } catch (err) {
        chat.innerHTML += `<div class="msg err"><b>Fehler:</b> ${escapeHtml(err.toString())}</div>`;
    }

    button.disabled = false;
    button.innerText = "Chat senden";
    chat.scrollTop = chat.scrollHeight;
    setStatus("bereit");
}

async function runLibraryAnalysis() {
    const box = document.getElementById("analysis");
    box.innerHTML = "Analysiere Library...";
    setStatus("analysiere");

    try {
        const res = await fetch("/analyze-library", {method:"POST"});
        const data = await res.json();
        box.innerHTML = escapeHtml(data.answer || data.error || "Keine Antwort");
    } catch (err) {
        box.innerHTML = "Fehler: " + escapeHtml(err.toString());
    }

    setStatus("bereit");
}

function extractWantedCount(text) {
    const match = String(text).match(/\b(\d{1,2})\b/);
    if (!match) return null;
    const n = parseInt(match[1]);
    if (n < 1) return 1;
    if (n > 20) return 20;
    return n;
}

function compactPath(path) {
    const parts = String(path).split("/").filter(Boolean);
    if (parts.length <= 2) return path;
    return "…/" + parts.slice(-2).join("/");
}

function toast(message, type) {
    const box = document.getElementById("toast");
    const item = document.createElement("div");
    item.className = "toastItem " + (type || "");
    item.textContent = message;
    box.appendChild(item);
    setTimeout(() => {
        item.style.opacity = "0";
        item.style.transform = "translateY(6px)";
        item.style.transition = "opacity .22s ease, transform .22s ease";
        setTimeout(() => item.remove(), 260);
    }, 4200);
}

function escapeHtml(text) {
    return String(text ?? "")
        .replaceAll("&","&amp;")
        .replaceAll("<","&lt;")
        .replaceAll(">","&gt;");
}

function escapeAttr(text) {
    return String(text ?? "")
        .replaceAll("&","&amp;")
        .replaceAll("\\", "\\\\")
        .replaceAll('"', "&quot;")
        .replaceAll("'","&#39;")
        .replaceAll("<","&lt;")
        .replaceAll(">","&gt;")
        .replaceAll("\n", " ");
}

function formatBytes(bytes) {
    if (!bytes && bytes !== 0) return "?";
    const units = ["B","KB","MB","GB","TB"];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) {
        bytes /= 1024;
        i++;
    }
    return bytes.toFixed(1) + " " + units[i];
}
</script>
</body>
</html>
"""



@app.get("/config")
def config():
    try:
        return {
            "qualityProfiles": [
                {"id": p.get("id"), "name": p.get("name")}
                for p in radarr_get("qualityprofile")
            ],
            "rootFolders": [
                {
                    "path": f.get("path"),
                    "freeSpace": f.get("freeSpace"),
                }
                for f in radarr_get("rootfolder")
            ],
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/lookup-movie")
def lookup_movie(req: LookupRequest):
    try:
        results = radarr_get(f"movie/lookup?term={quote(req.term)}")
        return {
            "results": [
                {
                    "title": m.get("title"),
                    "year": m.get("year"),
                    "tmdbId": m.get("tmdbId"),
                    "overview": m.get("overview"),
                    "posterUrl": get_poster_url(m),
                }
                for m in results[:20]
            ]
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/recommend-movies")
def recommend_movies(req: RecommendRequest):
    try:
        context = get_radarr_context()
        existing_tmdb = {m.get("tmdbId") for m in context["movies"] if m.get("tmdbId")}

        seen_items = load_seen_movies()
        seen_ids = {i.get("tmdbId") for i in seen_items if i.get("tmdbId")}
        already_seen = [
            {"title": i.get("title"), "year": i.get("year"), "tmdbId": i.get("tmdbId")}
            for i in seen_items
            if i.get("title") or i.get("tmdbId")
        ]

        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": """
Du bist ein Filmempfehlungs-Assistent für Radarr.
Empfiehl Filme, die zur vorhandenen Bibliothek und exakt zur Nutzeranfrage passen.
Beachte Anzahl, Genre, Regisseur, Schauspieler, Zeitraum, Erscheinungsjahr, Stimmung und Stil.
Keine Filme empfehlen, die bereits in der Bibliothek vorhanden sind.
Keine Filme empfehlen, die in der Liste "alreadySeen" stehen - diese hat der Nutzer schon gesehen oder bewusst abgelehnt.
Gib ausschließlich gültiges JSON zurück. Kein Markdown.
Format:
{
  "recommendations": [
    {
      "title": "Filmname",
      "year": 2000,
      "reason": "kurze Begründung"
    }
  ]
}
"""
                },
                {
                    "role": "user",
                    "content": f"""
Nutzerwunsch:
{req.message}

Maximale Anzahl:
{req.count}

Radarr-Kontext:
{json.dumps(context, ensure_ascii=False)}

alreadySeen (NICHT erneut empfehlen):
{json.dumps(already_seen, ensure_ascii=False)}
"""
                }
            ],
        )

        data = extract_json(response.output_text)
        enriched = []

        for rec in data.get("recommendations", []):
            title = rec.get("title")
            year = rec.get("year")

            if not title:
                continue

            lookup_term = f"{title} {year or ''}".strip()
            lookup = radarr_get(f"movie/lookup?term={quote(lookup_term)}")

            if not lookup:
                continue

            best = lookup[0]
            tmdb_id = best.get("tmdbId")

            if not tmdb_id or tmdb_id in existing_tmdb or tmdb_id in seen_ids:
                continue

            enriched.append({
                "title": best.get("title"),
                "year": best.get("year"),
                "tmdbId": tmdb_id,
                "overview": best.get("overview"),
                "posterUrl": get_poster_url(best),
                "reason": rec.get("reason"),
            })

        return {"recommendations": enriched[:req.count]}

    except Exception as e:
        return {"error": str(e)}


@app.get("/seen-movies")
def get_seen_movies():
    try:
        items = load_seen_movies()
        items.sort(key=lambda x: x.get("markedAt", ""), reverse=True)
        return {"items": items, "count": len(items)}
    except Exception as e:
        return {"error": str(e)}


@app.post("/mark-seen")
def mark_seen(req: MarkSeenRequest):
    try:
        items = load_seen_movies()
        items = [i for i in items if i.get("tmdbId") != req.tmdbId]
        items.append({
            "tmdbId": req.tmdbId,
            "title": req.title,
            "year": req.year,
            "markedAt": datetime.now(timezone.utc).isoformat(),
        })
        save_seen_movies(items)
        return {"status": "ok", "count": len(items)}
    except Exception as e:
        return {"error": str(e)}


@app.post("/unmark-seen")
def unmark_seen(req: UnmarkSeenRequest):
    try:
        items = load_seen_movies()
        before = len(items)
        items = [i for i in items if i.get("tmdbId") != req.tmdbId]
        save_seen_movies(items)
        return {"status": "ok", "count": len(items), "removed": before - len(items)}
    except Exception as e:
        return {"error": str(e)}


@app.post("/add-movie")
def add_movie(req: AddMovieRequest):
    try:
        existing_movies = radarr_get("movie")

        for movie in existing_movies:
            if movie.get("tmdbId") == req.tmdbId:
                return {"error": f"Film ist bereits in Radarr: {movie.get('title')}"}

        movie_payload = radarr_get(f"movie/lookup/tmdb?tmdbId={req.tmdbId}")

        movie_payload["qualityProfileId"] = req.qualityProfileId
        movie_payload["rootFolderPath"] = req.rootFolderPath
        movie_payload["monitored"] = True
        movie_payload["minimumAvailability"] = "released"
        movie_payload["addOptions"] = {"searchForMovie": req.searchForMovie}

        added = radarr_post("movie", movie_payload)

        return {
            "status": "ok",
            "title": added.get("title"),
            "year": added.get("year"),
            "tmdbId": added.get("tmdbId"),
            "searched": req.searchForMovie,
        }

    except Exception as e:
        return {"error": str(e)}


@app.post("/analyze-library")
def analyze_library():
    try:
        context = get_radarr_context()

        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": """
Du bist ein sehr kritischer Radarr-Setup-Analyst.
Prüfe Library, Queue, Root Folder, Quality Profiles und Custom Formats.
Sei direkt. Wenn etwas Murks ist, sag es.
Gib priorisierte Maßnahmen:
1. Sofort ändern
2. Optional verbessern
3. Nur prüfen
4. Auffällige Filme / Profile
"""
                },
                {
                    "role": "user",
                    "content": json.dumps(context, ensure_ascii=False)
                }
            ],
        )

        return {"answer": response.output_text}

    except Exception as e:
        return {"error": str(e)}


@app.post("/chat")
def chat(req: ChatRequest):
    try:
        context = get_radarr_context()

        response = client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": """
Du bist ein Radarr- und Arr-Setup-Assistent.
Analysiere die bestehende Radarr-Bibliothek.
Gib klare Empfehlungen.
Keine destruktiven Änderungen.
Keine ungeprüften Download-Aktionen.
Wenn Filme hinzugefügt werden sollen, erkläre, dass der Nutzer die Vorschläge über die GUI bestätigen soll.
Strukturiere Antworten mit:
1. Einschätzung
2. Probleme
3. Empfehlungen
4. Nächste Schritte
"""
                },
                {
                    "role": "user",
                    "content": f"""
Nutzerfrage:
{req.message}

Radarr-Kontext:
{json.dumps(context, ensure_ascii=False)}
"""
                }
            ],
        )

        return {"answer": response.output_text}

    except Exception as e:
        return {"error": str(e)}


@app.get("/health")
def health():
    return {"status": "ok"}