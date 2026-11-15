"""
Tests for the Submit and Display buttons.

The Submit button POSTs to /_submit_brevet; the Display button opens
/display. These tests call those endpoints with Flask's test client and
replace the MongoDB collection with an in-memory fake, so no database
is needed.

Run with:  nosetests
"""
import arrow
from pymongo.errors import ServerSelectionTimeoutError

import flask_brevets

START_DATE = "2017-01-01"
START_TIME = "00:00"


class FakeCollection:
    """Just enough of a pymongo collection for the app."""

    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        self.docs.append(dict(doc))

    def find(self):
        return list(self.docs)


class DownCollection:
    """A collection whose database can't be reached."""

    def insert_one(self, doc):
        raise ServerSelectionTimeoutError("db: connection refused")

    def find(self):
        raise ServerSelectionTimeoutError("db: connection refused")


def setup_client(collection):
    flask_brevets.get_collection = lambda: collection
    flask_brevets.app.config["TESTING"] = True
    return flask_brevets.app.test_client()


def submit(client, controls, brevet="200",
           date=START_DATE, time=START_TIME):
    return client.post("/_submit_brevet", json={
        "brevet_dist_km": brevet,
        "begin_date": date,
        "begin_time": time,
        "controls": controls,
    })


def rows(*kms):
    return [{"row": i + 1, "km": str(km), "location": ""}
            for i, km in enumerate(kms)]


def assert_rejected(response, coll, text):
    assert response.status_code == 400, response.status_code
    error = response.get_json()["error"]
    assert text in error, "expected '{}' in '{}'".format(text, error)
    assert coll.docs == [], "nothing should be saved"


#
# Submit button
#

def test_submit_saves_controls_with_correct_times():
    coll = FakeCollection()
    client = setup_client(coll)
    r = submit(client, rows(60, 120, 175, 205))
    assert r.status_code == 200
    assert "Saved 4 controls" in r.get_json()["message"]
    assert len(coll.docs) == 1
    doc = coll.docs[0]
    assert doc["brevet_dist_km"] == 200
    start = arrow.get("2017-01-01T00:00:00+00:00")
    first = doc["controls"][0]
    assert first["km"] == 60
    assert arrow.get(first["open"]) == start.shift(hours=1, minutes=46)
    assert arrow.get(first["close"]) == start.shift(hours=4)
    last = doc["controls"][-1]
    assert arrow.get(last["close"]) == start.shift(hours=13, minutes=30)


def test_submit_sorts_controls_and_keeps_locations():
    coll = FakeCollection()
    client = setup_client(coll)
    r = submit(client, [
        {"row": 1, "km": "175", "location": "Junction City"},
        {"row": 2, "km": "60", "location": "Coburg"},
    ])
    assert r.status_code == 200
    controls = coll.docs[0]["controls"]
    assert [c["km"] for c in controls] == [60, 175]
    assert controls[0]["location"] == "Coburg"
    assert controls[0]["miles"] == 37.3


def test_submit_with_no_controls_is_rejected():
    coll = FakeCollection()
    assert_rejected(submit(setup_client(coll), []), coll, "no controls")


def test_submit_with_non_numeric_distance_is_rejected():
    coll = FakeCollection()
    r = submit(setup_client(coll), [{"row": 3, "km": "abc", "location": ""}])
    assert_rejected(r, coll, "Row 3")


def test_submit_with_location_but_no_distance_is_rejected():
    coll = FakeCollection()
    r = submit(setup_client(coll),
               [{"row": 2, "km": "", "location": "Coburg"}])
    assert_rejected(r, coll, "location but no distance")


def test_submit_with_control_too_far_is_rejected():
    coll = FakeCollection()
    assert_rejected(submit(setup_client(coll), rows(60, 241)),
                    coll, "more than 20%")


def test_submit_with_negative_distance_is_rejected():
    coll = FakeCollection()
    assert_rejected(submit(setup_client(coll), rows(-5)), coll, "negative")


def test_submit_with_duplicate_distances_is_rejected():
    coll = FakeCollection()
    assert_rejected(submit(setup_client(coll), rows(60, 60)),
                    coll, "both at 60 km")


def test_submit_with_bad_brevet_distance_is_rejected():
    coll = FakeCollection()
    assert_rejected(submit(setup_client(coll), rows(60), brevet="250"),
                    coll, "Brevet distance")


def test_submit_with_bad_start_time_is_rejected():
    coll = FakeCollection()
    assert_rejected(submit(setup_client(coll), rows(60), date="not-a-date"),
                    coll, "Start date/time")


def test_submit_without_json_is_rejected():
    coll = FakeCollection()
    client = setup_client(coll)
    r = client.post("/_submit_brevet", data="km=60")
    assert_rejected(r, coll, "JSON")


def test_submit_with_database_down_reports_error():
    client = setup_client(DownCollection())
    r = submit(client, rows(60))
    assert r.status_code == 503
    assert "database" in r.get_json()["error"]


#
# Display button
#

def test_display_with_nothing_saved():
    client = setup_client(FakeCollection())
    r = client.get("/display")
    assert r.status_code == 200
    assert "No brevets have been saved yet" in r.get_data(as_text=True)


def test_display_shows_saved_brevet():
    coll = FakeCollection()
    client = setup_client(coll)
    submit(client, [{"row": 1, "km": "60", "location": "Coburg"},
                    {"row": 2, "km": "205", "location": "Finish"}])
    page = client.get("/display").get_data(as_text=True)
    assert "200 km brevet" in page
    assert "Coburg" in page
    assert "Sun 1/1/2017 1:46" in page    # 60 km open
    assert "Sun 1/1/2017 13:30" in page   # finish close
    assert page.count('class="saved_control"') == 2


def test_display_shows_newest_brevet_first():
    coll = FakeCollection()
    client = setup_client(coll)
    submit(client, rows(60), brevet="200")
    submit(client, rows(60), brevet="400")
    coll.docs[0]["submitted"] = "2020-01-01T00:00:00+00:00"
    coll.docs[1]["submitted"] = "2021-01-01T00:00:00+00:00"
    page = client.get("/display").get_data(as_text=True)
    assert page.index("400 km brevet") < page.index("200 km brevet")


def test_display_escapes_html_in_locations():
    coll = FakeCollection()
    client = setup_client(coll)
    submit(client, [{"row": 1, "km": "60", "location": "<b>Coburg</b>"}])
    page = client.get("/display").get_data(as_text=True)
    assert "<b>Coburg</b>" not in page
    assert "&lt;b&gt;Coburg&lt;/b&gt;" in page


def test_display_with_database_down_reports_error():
    client = setup_client(DownCollection())
    r = client.get("/display")
    assert r.status_code == 503
    assert "database is not available" in r.get_data(as_text=True)
