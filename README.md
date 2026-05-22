# radarr-ai

KI-Assistent für [Radarr](https://radarr.video/), der über die OpenAI API
Filme zur bestehenden Bibliothek vorschlägt und sie per Klick zu Radarr
hinzufügt. Läuft als kleiner FastAPI-Service in Docker, mit Web-GUI auf
Port `8090`.

## Features

- **Empfehlungen aus Freitext-Wunsch**: „3 düstere Thriller mit Twist",
  „5 unterschätzte Filme vor 2010", „Sci-Fi Mindfuck" – die KI bekommt
  deine Radarr-Library als Kontext und schlägt nur Filme vor, die du noch
  nicht hast.
- **Cover-Preview & 1-Klick zu Radarr**: Jeder Vorschlag kommt mit Poster,
  TMDB-ID und Begründung. Per Knopf landet er mit deinem gewählten
  Qualitätsprofil und Root Folder in Radarr.
- **„Schon gesehen"-Liste**: Vorschläge, die du schon kennst oder
  ablehnst, markierst du mit einem Klick. Sie landen in `seen_movies.json`
  und werden bei künftigen Empfehlungen ausgeschlossen.
- **Manuelle Suche**: Klassischer Radarr `movie/lookup` über die GUI.
- **Library-Analyse & Setup-Chat**: Die KI prüft Quality Profiles, Root
  Folders, Queue und Custom Formats und gibt priorisierte Hinweise.

## Setup

### Voraussetzungen

- Eine laufende Radarr-Instanz mit aktivierter API
- Einen OpenAI API-Key
- Docker / Docker Compose (das Beispiel-Compose ist für Synology gedacht,
  läuft aber überall)

### Environment Variablen

| Variable          | Zweck                                                       |
| ----------------- | ----------------------------------------------------------- |
| `RADARR_URL`      | Basis-URL deiner Radarr-Instanz, z. B. `http://radarr:7878` |
| `RADARR_API_KEY`  | API-Key aus Radarr → Settings → General                     |
| `OPENAI_API_KEY`  | Key aus platform.openai.com                                 |
| `OPENAI_MODEL`    | Modellname, z. B. `gpt-5.1` (Default falls leer)            |
| `TZ`              | Zeitzone, z. B. `Europe/Berlin`                             |
| `SEEN_FILE`       | Optional. Pfad der „Schon gesehen"-Datei. Default `/app/seen_movies.json` |

Lege die Werte als `.env` neben `compose.yaml` ab oder trage sie in deiner
Compose-/Portainer-UI ein.

### Start

```bash
docker compose up -d
```

Die GUI ist danach unter `http://<host>:8090` erreichbar. Beim ersten
Aufruf werden Quality Profiles und Root Folders aus Radarr geladen –
einmal das Ziel auswählen und es ist gespeichert für alle weiteren
Empfehlungen.

Die Compose-Datei mountet `/volume1/docker/radarr-ai/app` nach `/app` und
installiert die Python-Dependencies beim Start. Damit liegt sowohl die
App selbst als auch `seen_movies.json` persistent auf dem Host.

## Benutzung

1. Filmwunsch ins große Eingabefeld tippen oder einen der Chips
   („Liebesdrama-Thriller", „3 krasse Actionfilme", …) klicken.
2. Anzahl wählen (oder „automatisch") und „Empfehlungen holen".
3. Bei jedem Vorschlag:
   - **Details** öffnet ein Modal mit Beschreibung und geplanter Aktion.
   - **Zu Radarr** legt den Film mit deinem Ziel-Profil/Root Folder an.
   - **✓ Schon gesehen** (oben rechts auf der Karte) markiert ihn als
     bekannt, entfernt die Karte und sorgt dafür, dass die KI ihn künftig
     nicht mehr vorschlägt.
4. Unter **Setup & Tools → Gesehen-Liste** kannst du Einträge wieder
   entfernen, falls du es dir anders überlegt hast.

## API

Alle Endpoints sprechen JSON.

| Methode | Pfad                | Zweck                                                              |
| ------- | ------------------- | ------------------------------------------------------------------ |
| GET     | `/`                 | Web-GUI                                                            |
| GET     | `/health`           | Healthcheck                                                        |
| GET     | `/config`           | Quality Profiles + Root Folders aus Radarr                         |
| POST    | `/lookup-movie`     | Body: `{term}` – Radarr `movie/lookup`                             |
| POST    | `/recommend-movies` | Body: `{message, count}` – KI-Empfehlungen                         |
| POST    | `/add-movie`        | Body: `{tmdbId, qualityProfileId, rootFolderPath, searchForMovie}` |
| GET     | `/seen-movies`      | Inhalt der „Schon gesehen"-Datei                                   |
| POST    | `/mark-seen`        | Body: `{tmdbId, title?, year?}` – als gesehen markieren            |
| POST    | `/unmark-seen`      | Body: `{tmdbId}` – aus der Liste entfernen                         |
| POST    | `/analyze-library`  | KI-Analyse von Library, Profilen, Queue                            |
| POST    | `/chat`             | Body: `{message}` – freier Setup-Chat                              |

## Datenformat `seen_movies.json`

Reine JSON-Datei mit einer Liste, ein Eintrag pro Film:

```json
[
  {
    "tmdbId": 27205,
    "title": "Inception",
    "year": 2010,
    "markedAt": "2026-05-22T12:09:40.189826+00:00"
  }
]
```

Du kannst die Datei jederzeit von Hand editieren – beim nächsten Request
greift die neue Version automatisch.

## Entwicklung

```bash
cd radarr-ai/app
pip install -r requirements.txt
RADARR_URL=... RADARR_API_KEY=... OPENAI_API_KEY=... \
  uvicorn main:app --reload --port 8090
```
