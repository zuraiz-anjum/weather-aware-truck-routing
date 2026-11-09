# Weather-Aware Truck Routing

A React and Django web app for a dispatcher planning a truck's run. Give it
an origin, a destination, a departure time and the load, and it comes back
with three road routes, the weather each one meets at the hour the truck
gets there, a risk level for every stretch, a recommendation, and a heatmap
of the corridor that can be slid through the next forty-eight hours.

Deployed as described at the end, it runs as one free Render service, at
https://weather-aware-truck-routing.onrender.com once that service is up;
the first request after a quiet spell takes half a minute while it wakes.
Everything is in this repository: `backend/` is the Django project,
`frontend/` the React app, and the `Dockerfile` builds both into one image.

## Running it on your own machine

You need Python 3.12 or newer, Node 22 or newer, and an internet connection:
the app talks to three public services (routing, weather, place names) that
need no keys.

Backend, in one terminal:

```
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS and Linux: source .venv/bin/activate
pip install -r requirements.txt
python manage.py test           # 152 tests, no network needed
python manage.py runserver
```

Frontend, in another:

```
cd frontend
npm ci
npm test                        # 27 tests
npm run dev
```

Open http://localhost:5173. Vite serves the React app and proxies `/api` to
Django on port 8000. There is no database and nothing to migrate.

Or build the image and run the whole thing from one container:

```
docker build -t truckweather .
docker run --rm -p 8000:8000 -e DJANGO_SECRET_KEY=$(openssl rand -hex 32) truckweather
```

and open http://localhost:8000. Django serves the built React app from the
same process.

## What it does, in order

**Places.** The two boxes suggest places as you type, from Photon (komoot's
geocoder over OpenStreetMap), limited to the United States. A name typed
without picking a suggestion is looked up the same way when you plan.

**Three routes.** One request to OSRM, the public OpenStreetMap router,
asks for alternatives and for every step of each route: the geometry, how
long the step takes, and what road it is on. OSRM usually offers one or two
routes. For the rest, the planner routes through a point off to one side
of the straight line between the ends: a fifth of the way out at the
middle, then a third of the way from each end, then further out at the
middle again. Such a point is an arbitrary spot the road has to leave and
come back to, so a candidate whose new road gets somewhere is routed once
more through a point on that new road itself, which gives the road
without the excursion (Phoenix to Tucson by AZ-79 comes out at 1.36 times
the interstate's time this way rather than 2.1); candidates are looked at
quickest first and the second routing is asked for only when one is
reached. A candidate is kept when its longest stretch of new road is at
least ten miles long with its ends at least half that far apart as the
crow flies, so that the new road is at most twice the straight line
between its ends (the genuine alternatives tried measure 0.52 to 1.0, a
fifty-mile farm-road loop off I-27 0.39, and an out-and-back excursion
next to nothing), no more than half of that
stretch is on minor roads, meaning roads without a route number and county
and forest roads whatever their number (OSRM routes a car, and will send it
down a gravel county road or a parkway that no truck may use; a road whose
name says highway, freeway or turnpike counts as one, since the map data
sometimes leaves the number off), less than 85% of it runs within a mile
of a route already in hand, and it is no more than 1.6 times slower than
the quickest. Routes found this way are marked as such in the response and
the card. Every route also reports how many of its miles are on minor
roads and names the longest of them; the card says so when it is more than
a few miles, since even OSRM's own first choice can be a parkway. Between
some places there are honestly fewer than three distinct roads, and the
app says so; when a routing request failed along the way it says that
instead, and keeps the short set for ten minutes rather than a day.

**Checkpoints and ETAs.** Checkpoints sit every 10, 25 or 50 miles along
each route, with the destination as the last. The spacing follows the trip
length unless you choose one; very long trips are coarsened so that a route
has at most a hundred checkpoints. The time of arrival at each comes from
OSRM's per-step driving times, interpolated by distance within a step and
nudged so the last vertex lands on the route's own time, added to the
departure. Each checkpoint stands for the stretch of road from it to the
next, which is how a level becomes miles.

**Weather.** Open-Meteo gives hourly wind at 10 m in mph and rain and snow
in inches for the hour, for many points in one request; the app asks for a
hundred at a time, so the checkpoints of all three routes and the cells of
the heatmap go out in a few parallel requests. Rain is Open-Meteo's large-scale rain plus its
convective showers, which it reports separately and which carry most of
the heavy rates. At a checkpoint, wind is read between the two surrounding
hours and rain and snow are the totals for the hour ahead of the truck: a
checkpoint stands for the road after it, so a truck passing at 14:20, or at
14:00 exactly, gets the hour that ends at 15:00.

**Risk.** The thresholds from the brief, applied to every checkpoint and
every heatmap cell:

| Condition | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind | < 25 mph | 25–34 | 35–44 | 45–54 | ≥ 55 mph |
| Rain | < 0.10 in/h | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | > 1.00 |
| Snow | < 0.5 in/h | 0.5–1.0 | 1.0–2.0 | 2.0–3.0 | > 3.0 |

Each band owns its lower bound, so 35 mph is High and 0.25 in/h is High;
the top band follows the brief's own signs (wind from 55 mph, rain over
1.00, snow over 3.0). Values are judged as they are shown, wind to the mile
an hour and rain and snow to the hundredth of an inch, so a figure that
reads 25 mph or 0.10 in/h is in the band it appears to be in. The worst of
the three factors is the level. The load
rules then apply to wind: 55 mph or more is No Travel for any load, 45–54
mph with more than 30,000 lb is No Travel, and 35–44 mph with more than
40,000 lb is Severe. When a load rule has changed a checkpoint's level the
API says which one, and the table marks the row.

**Recommendation.** Routes are ordered by fewest miles rated No Travel,
then fewest Severe, fewest High, lowest average risk (a mile-weighted mean
of the levels, 0 to 4, compared to a tenth: a longer route that meets the
same trouble has a lower mean only for carrying more calm miles after it,
so means that close fall through to time), then shortest driving time. The brief lists the last
four; No Travel miles go first because a route with any is not one the
truck can take, and ranking it above a route with a few Severe miles would
be absurd. The recommended route's card says why it beat the quickest one
("40 min slower than Route B, but fewer miles rated High"), since that is
the trade a dispatcher is weighing. When even the best route has No Travel
miles nothing is recommended: the plan carries a warning, the top card is
marked "Not clear to drive", and the ranking is still shown so the least
bad option and the reason for it are plain.

**Heatmap.** The corridor is a lattice of latitude and longitude cells, a
band of three along every route, sized so a trip is about thirty cells
long; the legend says how wide they came out. A cell the road runs through
is forecast at a point on the road, so it reads the same forecast as a
checkpoint inside it, though at the slider's hour rather than the truck's
minute; a cell beside the road is forecast at its centre. Each cell
carries its risk level at every hour of the slider, computed once on the
server with the same rules and the same load. Moving the slider only swaps
a paint expression on the GPU, so it is instant, and the truck markers move
to where each route has the truck at that hour. Calm cells are a faint
wash; trouble is solid.

## The API

`POST /api/plan/` with a JSON body:

```json
{
  "origin": {"text": "Amarillo, Texas", "lat": 35.207, "lon": -101.834},
  "destination": {"text": "Oklahoma City"},
  "departure": "2026-11-12T14:00:00Z",
  "load_lb": 36000,
  "interval_miles": 25
}
```

`lat` and `lon` are optional (text alone is geocoded), `interval_miles` is
optional and one of 10, 25 or 50, and the departure may be up to an hour in
the past or thirteen days less an hour ahead, which with the two days of
slider after it is what Open-Meteo's sixteen-day forecast allows at any
time of day. The answer holds the two
places as resolved, `routes` ranked best first (each with its name,
distance, miles on minor roads and the names of the longest of those,
driving time, arrival, GeoJSON geometry, checkpoints
with ETA, weather, levels and any load rule, and a summary with miles by
level, average risk, rank, whether it is recommended, and the reason), `heatmap`
as a GeoJSON FeatureCollection of cells with a `levels` array per hour,
`notes` for anything worth saying, such as only two routes existing, and
`warning` when no route is clear to drive.

`GET /api/places/?q=den` returns up to six matching places in the United
States. `GET /api/health/` answers `{"status": "ok"}` without touching any
outside service.

Errors are `{"detail": "..."}`: 400 for a bad request (with the field errors
under `errors`), 422 when a plan cannot be made (no road between the places,
an unknown place, the two places being the same, or a trip running past
the sixteen-day forecast), 502 when one of the outside services fails, 503
with `Retry-After` when Open-Meteo's free allowance for the minute, the
hour or the day is spent, and 429 past 20 plans a minute from one address
(rejected requests count too).

## Things worth knowing

- Driving times are OSRM's, for a car, with no stops. A real run has hours
  of service and slower truck speeds, which would push the later ETAs
  later; the model is the brief's, and the checkpoint times are consistent
  with the route times shown.
- Open-Meteo's free tier counts each point of a request against six
  hundred a minute, five thousand an hour and ten thousand a day. A plan
  uses one point per distinct checkpoint and heatmap cell, so the heatmap
  is kept to two hundred cells and a route to a hundred checkpoints, and
  forecasts are cached for half an hour in windows that run from midnight
  of the departure day to the first midnight after the trip and the
  slider, and at least three days, so that departures on the same day for
  the same trip usually share one fetch; routes for a pair of places are
  kept for a day. Two or three fresh plans in one minute are fine, and a
  few dozen a day; past an allowance the API answers 503 with a
  `Retry-After` and says whether to wait a minute, an hour or a day.
- The model runs sixteen days out from its own start, so between midnight
  UTC and the arrival of the day's first run, around 04:30, the last few
  hours of the sixteenth day come back empty. They are cut off the end of
  the series and matter only if the trip ran into them, which the latest
  departure the form allows does not. An hour the model has no value for
  inside the trip refuses the plan rather than reading as calm.
- Routes are cached without regard to the load, since OSRM routes a car:
  the load only enters the risk rules. A pair costs OSRM one request when
  it offers three routes itself, four or five when one side point is
  needed, and up to seventeen when every round is tried; that is paid once
  a day per pair.
- Wind is sustained wind at 10 m. Gusts are higher; the brief's thresholds
  are for wind, so that is what is used.
- The map is MapLibre GL over OpenFreeMap's vector tiles, which need no key.
- There are no accounts and no database. Everything the app knows it is
  told in the request or fetches for it.

## Deploying

`render.yaml` describes one free Docker web service on Render: connect the
repository as a Blueprint and it builds from the `Dockerfile`, generates
`DJANGO_SECRET_KEY`, and checks `/api/health/`. Free services sleep after
fifteen idle minutes; the `keep-warm` workflow in `.github/workflows` pings
the service every ten minutes once the repository variable `APP_URL` is set
to its address.

The image runs anywhere Docker does. It needs `DJANGO_SECRET_KEY`, honours
`PORT`, and takes `DJANGO_ALLOWED_HOSTS` (Render's own hostname is picked up
by itself), `NUM_PROXIES` (1 behind a proxy that sets `X-Forwarded-For`),
`CACHE_DIR`, and `OSRM_URL`, `OPEN_METEO_URL` and `PHOTON_URL` for
self-hosted copies of the services.

## Tests and checks

`python manage.py test` runs the backend's 152 tests: the risk table at
every boundary, checkpoint placement, the heatmap lattice, the polyline
decoder against the format's reference, the OSRM stitching, the side-route
search with its spur and unnumbered-road rules and second routing,
Open-Meteo windows, chunking, caching and the hours past the model's
reach, the planner's ranking, and the API end to end with the services
stubbed. Three more run against
the real services when `LIVE_SERVICES=1` is set: the forecast window at
both ends of the allowed range, and a short trip through the whole
planner. They exist because the stubs can only check what the code
expects, not what the services accept. `npm test` runs the frontend's 27:
time and distance helpers, the form's validation and payload, the place
suggestions, the route cards, and the app's planning flow with the map
stubbed out, since jsdom has no WebGL. CI runs both suites, the live tests
as an advisory job, type-checks and lints the frontend, builds the image,
starts it, and checks that it serves the API and the page.

## Layout

```
backend/
  truckweather/      settings, urls, wsgi
  trips/
    risk.py          the thresholds and load rules
    osrm.py          routes, and side routes when OSRM offers fewer than three
    weather.py       Open-Meteo in chunks, with the hour-reading rules
    geocoding.py     Photon suggestions and lookups
    checkpoints.py   where along a route, and when
    corridor.py      the heatmap lattice
    planner.py       the plan: assessment, ranking, heatmap levels
    geometry.py      distances, positions, thinning, overlap
    polyline.py      OSRM's encoded geometry
    views.py, serializers.py, urls.py
    tests/
frontend/src/
  App.tsx            state and layout
  components/        TripForm, PlaceInput, RouteCards, CheckpointTable,
                     HourSlider, Legend, RouteMap (MapLibre)
  api.ts, types.ts, risk.ts, time.ts, progress.ts
Dockerfile, render.yaml, .github/workflows/
```
