# ACP Brevet Control Times Calculator with MongoDB

A web replacement for the RUSA ACP control time calculator
(<https://rusa.org/octime_acp.html>). Enter control distances and the page
fills in each control's open and close times as you type. **Submit** saves
the brevet to a MongoDB database, and **Display** shows every saved brevet
on a separate page.

Author: Jasper Riggs, jasr@uoregon.edu
Repository: https://github.com/Greebled/proj5-mongo.git

## Using the calculator

1. Choose the brevet distance (200, 300, 400, 600 or 1000 km).
2. Set the start date and time.
3. Type each control's distance in miles or kilometers, and optionally a
   location name. The other unit, the open time and the close time fill
   in automatically.
4. Click **Submit** to save the brevet. A message under the buttons says
   whether it was saved or what is wrong.
5. Click **Display** to see all saved brevets, newest first.

Changing the brevet distance or start time recalculates every row.
Times are shown in the same clock as the start time you entered; no time
zone conversion is done.

### What Submit rejects

Nothing is saved if any of these are true. The message names the row
with the problem.

- No row has a distance or location (no controls to submit).
- A row has a location but no distance.
- A distance is not a number.
- A distance is negative.
- A distance is more than 20% past the brevet distance.
- Two rows have the same distance.
- A location is longer than 100 characters.
- The brevet distance is not one of the five official distances.
- The start date or time is missing or invalid.
- The request isn't valid JSON (only possible outside the page).
- The database can't be reached (the page says so instead of hanging).

Other behavior:

- Controls are saved in order of distance, whatever order they were
  typed in.
- Open and close times are recalculated by the server on Submit, so a
  saved brevet is always consistent with the rules, even if the page's
  displayed times were stale.
- The Submit button is disabled while a submission is in progress, so a
  double click doesn't save the brevet twice.
- Pressing Enter in a field does nothing, instead of reloading the page
  and losing what was entered.

### What Display shows

- Every saved brevet, newest first, with its distance, start time, and a
  table of its controls (km, miles, location, open, close).
- A message if nothing has been saved yet.
- An error message (status 503) if the database can't be reached.
- Location names exactly as typed; any HTML in them is shown as text,
  not run.

## Control time rules

These are the rules from
<https://rusa.org/pages/acp-brevet-control-times-calculator>, written out
where the original is ambiguous.

### Speed table

| Control location (km) | Minimum speed (km/h) | Maximum speed (km/h) |
|-----------------------|----------------------|----------------------|
| 0 – 200               | 15                   | 34                   |
| 200 – 400             | 15                   | 32                   |
| 400 – 600             | 15                   | 30                   |
| 600 – 1000            | 11.428               | 28                   |
| 1000 – 1300           | 13.333               | 26                   |

### Opening time

The opening time is the time needed to ride to the control at the
**maximum** speed. The speed changes along the route: each stretch of road
is ridden at the speed for the band it lies in. For a control at 350 km:

    200/34 + 150/32 = 5.882 + 4.688 = 10.570 h  →  10H34

### Closing time

The closing time is the time needed at the **minimum** speed, worked out the
same way, band by band. For a control at 890 km:

    600/15 + 290/11.428 = 40 + 25.377 = 65.377 h  →  65H23

### Rounding

Total hours are converted to minutes and rounded to the nearest whole
minute (halves round up). Rounding is done once, on the total, not
separately for each band.

### Special cases

- **Start control (0 km):** opens at the start, closes one hour later.
- **Controls up to 60 km:** close at `distance / 20 + 1` hours, which
  gives riders more time at early controls. At 60 km this equals the
  normal 15 km/h rule (4H00), so there is no jump. Opening times are not
  affected.
- **Finish control:** closes at the overall time limit for the brevet,
  not the table value: 13H30 for 200 km, 20H00 for 300 km, 27H00 for
  400 km, 40H00 for 600 km and 75H00 for 1000 km. A control at 200 km on
  a 600 km brevet is *not* a finish and closes at 13H20.
- **Finish past the nominal distance:** a control may be up to 20% past
  the brevet distance; it gets the same open and close times as a control
  at exactly the brevet distance (205 km on a 200 km brevet: 5H53 / 13H30).
- **Rejected input:** a negative distance, a control more than 20% past
  the brevet distance, or a brevet distance other than the five official
  ones raises `ValueError` in `acp_times.py`.

## For developers

### Layout

| File | Purpose |
|------|---------|
| `acp_times.py` | `open_time` and `close_time`: all the rules above |
| `flask_brevets.py` | Flask app: pages, Ajax endpoints, database access |
| `templates/calc.html` | Calculator page, with the Submit and Display buttons |
| `templates/display.html` | Page listing saved brevets |
| `config.py`, `credentials.ini` | Configuration (port, secret key, debug) |
| `test_acp_times.py` | Tests for the time rules |
| `test_flask_brevets.py` | Tests for the Submit and Display buttons |
| `Dockerfile`, `docker-compose.yml` | Container setup for the app and MongoDB |

### Endpoints

- `GET /` – the calculator.
- `GET /_calc_times?km=&brevet_dist_km=&begin_date=&begin_time=` –
  times for one control: `{"result": {"open", "close", "note"}}` or
  `{"error": message}`.
- `POST /_submit_brevet` (Submit button) – JSON body
  `{"brevet_dist_km", "begin_date", "begin_time", "controls": [{"row", "km", "location"}]}`.
  Returns `{"message"}`, or `{"error"}` with status 400 (bad input) or
  503 (database down).
- `GET /display` (Display button) – the saved brevets page.

### Database

Database `brevetsdb`, collection `brevets`, one document per submission:

```json
{
  "brevet_dist_km": 200,
  "begin": "2017-01-01T00:00:00+00:00",
  "submitted": "2026-11-14T18:00:00+00:00",
  "controls": [
    {"km": 60.0, "miles": 37.3, "location": "Coburg",
     "open": "2017-01-01T01:46:00+00:00",
     "close": "2017-01-01T04:00:00+00:00"}
  ]
}
```

The app finds MongoDB at the host in the `MONGO_HOST` environment
variable (`db` under docker-compose, `localhost` otherwise).

### Running

Fill in `credentials.ini` (author, repo, port, and a real `SECRET_KEY`).
Then, from this directory:

    docker compose up --build

Open <http://localhost:5000>. Stop with Ctrl+C, or `docker compose down`.
Saved brevets are kept in a Docker volume between runs; to erase them,
use `docker compose down -v`.

### Testing

    docker compose run --rm --entrypoint nosetests web

This runs both test files. The button tests replace the database with
an in-memory fake, so they don't need MongoDB running.

The button tests check that Submit saves controls with the correct
times, sorts them and keeps locations; that it rejects every error case
listed above and saves nothing when it does; and that it reports a
database outage. For Display, they check the empty message, the saved
times and locations, newest-first order, HTML escaping, and a database
outage.
