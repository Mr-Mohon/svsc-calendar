#!/usr/bin/env python3
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from icalendar import Calendar, Event

BASE = "https://scottsvalleysportsmen.com"
LIST_URL = BASE + "/events?EventListViewMode=1&EventViewMode=1"
OUT = Path("public/svsc.ics")
TZ = ZoneInfo("America/Los_Angeles")

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "SVSC-Personal-Calendar/1.0 (+GitHub Actions; personal calendar subscription)"
})

DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
TIME_RANGE_RE = re.compile(
    r"\b(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)\b",
    re.IGNORECASE,
)
EVENT_ID_RE = re.compile(r"/event-(\d+)")


def fetch(url: str) -> str:
    r = SESSION.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def event_links_from_list(html: str):
    soup = BeautifulSoup(html, "html.parser")
    links = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = EVENT_ID_RE.search(href)
        if not m:
            continue
        event_id = m.group(1)
        links[event_id] = urljoin(BASE, href)
    return sorted(links.items(), key=lambda x: int(x[0]))


def clean_lines(soup: BeautifulSoup):
    text = soup.get_text("\n", strip=True)
    return [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]


def parse_event(event_id: str, url: str):
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else f"SVSC Event {event_id}"

    lines = clean_lines(soup)
    joined = "\n".join(lines)

    dm = DATE_RE.search(joined)
    tm = TIME_RANGE_RE.search(joined)
    if not dm or not tm:
        raise ValueError(f"Could not parse date/time for {url}")

    date_text = dm.group(1)
    start_text = tm.group(1).upper().replace(" ", "")
    end_text = tm.group(2).upper().replace(" ", "")

    date_obj = datetime.strptime(date_text, "%m/%d/%Y").date()
    start_time = datetime.strptime(start_text, "%I:%M%p").time()
    end_time = datetime.strptime(end_text, "%I:%M%p").time()

    start = datetime.combine(date_obj, start_time, TZ)
    end = datetime.combine(date_obj, end_time, TZ)
    if end <= start:
        # Handles an event that crosses midnight.
        from datetime import timedelta
        end += timedelta(days=1)

    location = None
    for i, line in enumerate(lines):
        if line == "Location" and i + 1 < len(lines):
            candidate = lines[i + 1]
            if candidate not in {"Log in", "Back", "When"}:
                location = candidate
            break

    return {
        "id": event_id,
        "url": url,
        "title": title,
        "start": start,
        "end": end,
        "location": location,
    }


def build_calendar(events):
    cal = Calendar()
    cal.add("prodid", "-//Personal SVSC Calendar//scottsvalleysportsmen.com//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "SVSC Events")
    cal.add("x-wr-timezone", "America/Los_Angeles")

    for item in sorted(events, key=lambda x: x["start"]):
        ev = Event()
        ev.add("uid", f"svsc-event-{item['id']}@scottsvalleysportsmen.com")
        ev.add("summary", item["title"])
        ev.add("dtstart", item["start"])
        ev.add("dtend", item["end"])
        if item["location"]:
            ev.add("location", item["location"])
        ev.add("url", item["url"])
        ev.add("description", f"SVSC event details: {item['url']}")
        cal.add_component(ev)

    return cal


def main():
    print(f"Fetching event list: {LIST_URL}")
    list_html = fetch(LIST_URL)
    links = event_links_from_list(list_html)
    print(f"Found {len(links)} event links")

    events = []
    failures = []
    for event_id, url in links:
        try:
            ev = parse_event(event_id, url)
            events.append(ev)
            print(f"OK {ev['start']:%Y-%m-%d %H:%M}-{ev['end']:%H:%M}  {ev['title']}")
        except Exception as exc:
            failures.append((url, str(exc)))
            print(f"WARN {url}: {exc}", file=sys.stderr)

    if not events:
        raise SystemExit("No events could be parsed; refusing to overwrite the calendar.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(build_calendar(events).to_ical())
    print(f"Wrote {OUT} with {len(events)} events")

    if failures:
        print(f"{len(failures)} event(s) could not be parsed.", file=sys.stderr)


if __name__ == "__main__":
    main()
