"""
Replacement for RUSA ACP brevet time calculator
(see https://rusa.org/octime_acp.html),
with control times saved to and displayed from MongoDB.
"""

import math
import os
import logging

import flask
from flask import request
import arrow  # Replacement for datetime, based on moment.js
from pymongo import MongoClient
from pymongo.errors import PyMongoError

import acp_times  # Brevet time calculations
import config

###
# Globals
###
app = flask.Flask(__name__)
# Read the command line only when run as a script; when imported
# (for example by the test suite) the command line isn't ours.
CONFIG = config.configuration(proxied=(__name__ != "__main__"))
app.secret_key = CONFIG.SECRET_KEY

# docker-compose sets MONGO_HOST to the database service name
MONGO_HOST = os.environ.get("MONGO_HOST", "localhost")
MONGO_PORT = int(os.environ.get("MONGO_PORT", 27017))

MAX_LOCATION_LEN = 100
TIME_DISPLAY_FORMAT = "ddd M/D/YYYY H:mm"

_client = None


def get_collection():
    """The MongoDB collection holding saved brevets.
    The client is created on first use so the app can start (and the
    tests can run) without a database.
    """
    global _client
    if _client is None:
        _client = MongoClient(MONGO_HOST, MONGO_PORT,
                              serverSelectionTimeoutMS=3000)
    return _client.brevetsdb.brevets


###
# Helpers
###

def parse_start(begin_date, begin_time):
    """Combine the form's date and time fields into an Arrow object.
    Browsers send the time as HH:mm, or HH:mm:ss if seconds are shown.
    The time is taken as given, with no time zone conversion.
    """
    for fmt in ("YYYY-MM-DD HH:mm", "YYYY-MM-DD HH:mm:ss"):
        try:
            return arrow.get("{} {}".format(begin_date, begin_time), fmt)
        except ValueError:  # arrow.ParserError is a ValueError
            continue
    raise ValueError("Start date/time is not valid")


def build_brevet(data):
    """Check a submission from the page and build the document to store.

    data is the JSON sent by the Submit button:
      {"brevet_dist_km": "200", "begin_date": "2017-01-01",
       "begin_time": "00:00",
       "controls": [{"row": 1, "km": "60", "location": "Coburg"}, ...]}

    Open and close times are recalculated here rather than trusted from
    the page. Raises ValueError with a message for the user if anything
    is wrong.
    """
    if not isinstance(data, dict):
        raise ValueError("Request must be a JSON object")

    try:
        brevet = int(data.get("brevet_dist_km"))
    except (TypeError, ValueError):
        raise ValueError("Brevet distance is missing")
    if brevet not in acp_times.BREVET_DISTANCES:
        raise ValueError("Brevet distance must be one of {}".format(
            ", ".join(str(d) for d in acp_times.BREVET_DISTANCES)))

    start = parse_start(data.get("begin_date", ""), data.get("begin_time", ""))
    start_iso = start.isoformat()

    rows = data.get("controls")
    if not isinstance(rows, list) or not rows:
        raise ValueError("There are no controls to submit. "
                         "Enter at least one control distance.")

    controls = []
    seen = {}
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError("Control {} is not valid".format(i))
        label = "Row {}".format(row.get("row", i))
        km_text = str(row.get("km", "")).strip()
        location = str(row.get("location", "")).strip()

        if km_text == "":
            raise ValueError("{} has {}no distance".format(
                label, "a location but " if location else ""))
        try:
            km = float(km_text)
        except ValueError:
            raise ValueError("{}: distance '{}' is not a number"
                             .format(label, km_text))
        if not math.isfinite(km):
            raise ValueError("{}: distance is not a number".format(label))
        if len(location) > MAX_LOCATION_LEN:
            raise ValueError("{}: location is longer than {} characters"
                             .format(label, MAX_LOCATION_LEN))

        key = round(km, 1)
        if key in seen:
            raise ValueError("{} and {} are both at {:g} km"
                             .format(seen[key], label, key))
        seen[key] = label

        try:
            open_t = acp_times.open_time(km, brevet, start_iso)
            close_t = acp_times.close_time(km, brevet, start_iso)
        except ValueError as err:
            raise ValueError("{}: {}".format(label, err))

        controls.append({
            "km": round(km, 1),
            "miles": round(km * 0.621371, 1),
            "location": location,
            "open": open_t,
            "close": close_t,
        })

    controls.sort(key=lambda c: c["km"])
    return {
        "brevet_dist_km": brevet,
        "begin": start_iso,
        "submitted": arrow.utcnow().isoformat(),
        "controls": controls,
    }


@app.template_filter("brevet_time")
def brevet_time(iso):
    """Format a stored ISO time for display, keeping its own clock."""
    return arrow.get(iso).format(TIME_DISPLAY_FORMAT)


###
# Pages
###


@app.route("/")
@app.route("/index")
def index():
    app.logger.debug("Main page entry")
    return flask.render_template('calc.html')


@app.route("/display")
def display():
    """Show every saved brevet, newest first."""
    try:
        brevets = list(get_collection().find())
    except PyMongoError as err:
        app.logger.error("Database error on display: {}".format(err))
        return flask.render_template(
            'display.html', brevets=[],
            error="The database is not available right now."), 503
    brevets.sort(key=lambda b: b.get("submitted", ""), reverse=True)
    return flask.render_template('display.html', brevets=brevets, error=None)


@app.errorhandler(404)
def page_not_found(error):
    app.logger.debug("Page not found")
    flask.session['linkback'] = flask.url_for("index")
    return flask.render_template('404.html'), 404


###############
#
# AJAX request handlers
#   These return JSON, rather than rendering pages.
#
###############

@app.route("/_calc_times")
def _calc_times():
    """
    Calculates open/close times for one control.
    Expects URL-encoded arguments:
      km              control distance in kilometers
      brevet_dist_km  200, 300, 400, 600 or 1000
      begin_date      YYYY-MM-DD
      begin_time      HH:mm
    Returns JSON {"result": {"open": iso, "close": iso, "note": str}}
    or {"error": message} if the input can't be used.
    """
    app.logger.debug("request.args: {}".format(request.args))
    km = request.args.get('km', None, type=float)
    brevet_dist_km = request.args.get('brevet_dist_km', 200, type=int)
    begin_date = request.args.get('begin_date', '')
    begin_time = request.args.get('begin_time', '')

    if km is None:
        return flask.jsonify(error="Distance must be a number")
    try:
        start = parse_start(begin_date, begin_time).isoformat()
        open_time = acp_times.open_time(km, brevet_dist_km, start)
        close_time = acp_times.close_time(km, brevet_dist_km, start)
    except ValueError as err:
        return flask.jsonify(error=str(err))

    note = ""
    if km > brevet_dist_km:
        note = "Past {} km; finish times apply".format(brevet_dist_km)
    result = {"open": open_time, "close": close_time, "note": note}
    return flask.jsonify(result=result)


@app.route("/_submit_brevet", methods=["POST"])
def _submit_brevet():
    """Save the brevet on the page to the database.
    Returns {"message": ...} on success, or {"error": ...} with
    status 400 for bad input and 503 if the database is down.
    """
    data = request.get_json(silent=True)
    try:
        doc = build_brevet(data)
    except ValueError as err:
        return flask.jsonify(error=str(err)), 400

    try:
        get_collection().insert_one(doc)
    except PyMongoError as err:
        app.logger.error("Database error on submit: {}".format(err))
        return flask.jsonify(
            error="Could not save: the database is not available."), 503

    n = len(doc["controls"])
    return flask.jsonify(message="Saved {} control{} for a {} km brevet."
                         .format(n, "" if n == 1 else "s",
                                 doc["brevet_dist_km"]))


#############

app.debug = getattr(CONFIG, "DEBUG", False)
if app.debug:
    app.logger.setLevel(logging.DEBUG)

if __name__ == "__main__":
    print("Opening for global access on port {}".format(CONFIG.PORT))
    app.run(port=CONFIG.PORT, host="0.0.0.0")