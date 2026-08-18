#!/usr/bin/env python3
import re
import sys
from datetime import datetime, timedelta
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
    "User-Agent": "SVSC-Personal-Calendar/3.2 (+GitHub Actions; personal calendar subscription)"
})

EVENT_ID_RE = re.compile(r"/event-(\d+)")
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b")
TIME_RANGE_RE = re.compile(
    r"\b(\d{1,2}:\d{2}\s*[AP]M)\s*-\s*(\d{1,2}:\d{2}\s*[AP]M)\b",
    re.IGNORECASE,
)
SESSION_RE = re.compile(
    r"\b(\d{1,2}/\d{1,2}/\d{4}),\s*"
    r"(\d{1,2}:\d{2}\s*[AP]M)\s+"
    r"(\d{1,2}:\d{2}\s*[AP]M)"
    r"(?:\s*\([A-Z]{2,5}\))?",
    re.IGNORECASE,
)

FOOTER_PREFIXES = (
    "PO Box ",
    "Powered by Wild Apricot",
)


def fetch(url: str) -> str:
    r = SESSION.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def event_links_from_list(html: str):
    soup = BeautifulSoup(html, "html.parser")
    links = {}

    for a in soup.find_all("a", href=True):
        m = EVENT_ID_RE.search(a["href"])
        if m:
            links[m.group(1)] = urljoin(BASE, a["href"])

    return sorted(links.items(), key=lambda x: int(x[0]))


def clean_lines(soup: BeautifulSoup):
    text = soup.get_text("\n", strip=True)
    return [
        re.sub(r"\s+", " ", x).strip()
        for x in text.splitlines()
        if x.strip()
    ]


def parse_clock(value: str):
    return datetime.strptime(
        re.sub(r"\s+", "", value.upper()),
        "%I:%M%p"
    ).time()


def make_datetimes(date_text: str, start_text: str, end_text: str):
    date_obj = datetime.strptime(date_text, "%m/%d/%Y").date()
    start = datetime.combine(date_obj, parse_clock(start_text), TZ)
    end = datetime.combine(date_obj, parse_clock(end_text), TZ)

    if end <= start:
        end += timedelta(days=1)

    return start, end


def value_after_label(lines, label):
    for i, line in enumerate(lines):
        if line.strip().lower() == label.lower() and i + 1 < len(lines):
            return lines[i + 1]

    return None


def find_location(lines):
    candidate = value_after_label(lines, "Location")

    if candidate and candidate not in {
        "Log in",
        "Back",
        "When",
        "Registration",
        "Spaces left",
        "Registered",
    }:
        return candidate

    return None


def trim_footer(lines):
    output = []

    for line in lines:
        if any(line.startswith(prefix) for prefix in FOOTER_PREFIXES):
            break

        output.append(line)

    return output


def extract_registration(lines):
    """
    Capture the public registration choices exactly as Wild Apricot displays
    them. We intentionally do not try to reconcile conflicting fee text in
    the event body; the source page remains authoritative.
    """
    try:
        start = next(
            i for i, line in enumerate(lines)
            if line.lower() == "registration"
        )
    except StopIteration:
        return []

    result = []

    for line in lines[start + 1:]:
        lower = line.lower()

        if lower == "register":
            break

        if lower.startswith("registration is "):
            result.append(line)
            break

        if line.startswith("PO Box ") or line.startswith("Powered by Wild Apricot"):
            break

        if line not in {
            "Back",
            "When",
            "Location",
            "Spaces left",
            "Registered",
        }:
            result.append(line)

    deduped = []

    for item in result:
        if not deduped or deduped[-1] != item:
            deduped.append(item)

    return deduped


def find_description_start(lines):
    """
    The narrative normally begins immediately after the Register control or
    'Registration is closed'. For events without registration, begin after
    the last known metadata value.
    """
    for i, line in enumerate(lines):
        if line.lower() == "register":
            return i + 1

    for i, line in enumerate(lines):
        if line.lower().startswith("registration is "):
            return i + 1

    metadata_end = -1

    for label in ("Location", "Spaces left", "Registered"):
        for i, line in enumerate(lines):
            if line.lower() == label.lower() and i + 1 < len(lines):
                metadata_end = max(metadata_end, i + 1)

    for i, line in enumerate(lines):
        if SESSION_RE.search(line):
            metadata_end = max(metadata_end, i)

    for i, line in enumerate(lines):
        if DATE_RE.fullmatch(line):
            metadata_end = max(metadata_end, i)

        if TIME_RANGE_RE.fullmatch(line):
            metadata_end = max(metadata_end, i)

    return metadata_end + 1


def extract_description(lines):
    start = find_description_start(lines)
    body = trim_footer(lines[start:])

    skip_exact = {
        "Back",
        "Log in",
        "Registration",
        "Register",
    }

    cleaned = []

    for line in body:
        if line in skip_exact:
            continue

        if line.startswith("#") and line[1:].rstrip(".").isdigit():
            continue

        cleaned.append(line)

    deduped = []

    for line in cleaned:
        if not deduped or deduped[-1] != line:
            deduped.append(line)

    return "\n\n".join(deduped).strip()


def extract_related_links(soup, event_url):
    """
    Include useful public links from the event body such as PDFs and email
    addresses. The main event URL itself is stored in the iCalendar URL field.
    """
    links = []

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()

        label = re.sub(
            r"\s+",
            " ",
            a.get_text(" ", strip=True)
        ).strip()

        absolute = urljoin(event_url, href)

        useful = (
            href.lower().startswith("mailto:")
            or ".pdf" in href.lower()
        )

        if not useful:
            continue

        if href.lower().startswith("mailto:"):
            absolute = href[7:]
            label = label or "Email"

        entry = (
            f"{label}: {absolute}"
            if label and label != absolute
            else absolute
        )

        if entry not in links:
            links.append(entry)

    return links


def build_notes(
    location,
    spaces_left,
    registered,
    registration,
    description,
    related_links,
):
    parts = []

    if description:
        parts.append(
            "EVENT DETAILS:\n\n"
            + description
        )

    registration_lines = []

    if spaces_left:
        registration_lines.append(
            f"Spaces left: {spaces_left}"
        )

    if registered:
        registration_lines.append(
            f"Registered: {registered}"
        )

    if registration:
        if registration_lines:
            registration_lines.append("")

        registration_lines.extend(registration)

    if registration_lines:
        parts.append(
            "REGISTRATION:\n\n"
            + "\n".join(registration_lines)
        )

    if location:
        parts.append(
            "LOCATION:\n\n"
            + location
        )

    if related_links:
        parts.append(
            "RELATED LINKS / CONTACT:\n\n"
            + "\n".join(related_links)
        )

    # Three line breaks give Apple Calendar an extra blank line
    # between each major section.
    return "\n\n\n".join(parts)


def parse_event(event_id: str, url: str):
    soup = BeautifulSoup(fetch(url), "html.parser")

    h1 = soup.find("h1")

    title = (
        h1.get_text(" ", strip=True)
        if h1
        else f"SVSC Event {event_id}"
    )

    lines = clean_lines(soup)
    joined = "\n".join(lines)

    location = find_location(lines)
    spaces_left = value_after_label(lines, "Spaces left")
    registered = value_after_label(lines, "Registered")
    registration = extract_registration(lines)
    description = extract_description(lines)
    related_links = extract_related_links(soup, url)

    notes = build_notes(
        location=location,
        spaces_left=spaces_left,
        registered=registered,
        registration=registration,
        description=description,
        related_links=related_links,
    )

    session_matches = list(
        SESSION_RE.finditer(joined)
    )

    if session_matches:
        occurrences = []
        seen = set()

        for index, match in enumerate(session_matches):
            date_text, start_text, end_text = match.groups()

            start, end = make_datetimes(
                date_text,
                start_text,
                end_text
            )

            key = (start, end)

            if key in seen:
                continue

            seen.add(key)

            uid = (
                f"svsc-event-{event_id}@scottsvalleysportsmen.com"
                if index == 0
                else (
                    f"svsc-event-{event_id}-"
                    f"{start:%Y%m%dT%H%M}"
                    f"@scottsvalleysportsmen.com"
                )
            )

            occurrences.append({
                "uid": uid,
                "url": url,
                "title": title,
                "start": start,
                "end": end,
                "location": location,
                "notes": notes,
            })

        if occurrences:
            return occurrences

    dm = DATE_RE.search(joined)
    tm = TIME_RANGE_RE.search(joined)

    if not dm or not tm:
        raise ValueError(
            f"Could not parse date/time for {url}"
        )

    start, end = make_datetimes(
        dm.group(1),
        tm.group(1),
        tm.group(2)
    )

    return [{
        "uid": f"svsc-event-{event_id}@scottsvalleysportsmen.com",
        "url": url,
        "title": title,
        "start": start,
        "end": end,
        "location": location,
        "notes": notes,
    }]


def build_calendar(events):
    cal = Calendar()

    cal.add(
        "prodid",
        "-//Personal SVSC Calendar//scottsvalleysportsmen.com//EN"
    )
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", "SVSC Events")
    cal.add(
        "x-wr-timezone",
        "America/Los_Angeles"
    )

    for item in sorted(
        events,
        key=lambda x: x["start"]
    ):
        ev = Event()

        ev.add("uid", item["uid"])
        ev.add("summary", item["title"])
        ev.add("dtstart", item["start"])
        ev.add("dtend", item["end"])

        if item["location"]:
            ev.add(
                "location",
                item["location"]
            )

        # Keep the original SVSC event page in Apple's dedicated URL field.
        ev.add(
            "url",
            item["url"]
        )

        if item["notes"]:
            ev.add(
                "description",
                item["notes"]
            )

        cal.add_component(ev)

    return cal


def main():
    print(
        f"Fetching event list: {LIST_URL}"
    )

    links = event_links_from_list(
        fetch(LIST_URL)
    )

    print(
        f"Found {len(links)} event pages"
    )

    events = []
    failures = []

    for event_id, url in links:
        try:
            occurrences = parse_event(
                event_id,
                url
            )

            events.extend(occurrences)

            if len(occurrences) > 1:
                print(
                    f"OK recurring "
                    f"({len(occurrences)} sessions) "
                    f"{occurrences[0]['title']}"
                )

            else:
                ev = occurrences[0]

                print(
                    f"OK "
                    f"{ev['start']:%Y-%m-%d %H:%M}-"
                    f"{ev['end']:%H:%M} "
                    f"{ev['title']}"
                )

        except Exception as exc:
            failures.append(
                (url, str(exc))
            )

            print(
                f"WARN {url}: {exc}",
                file=sys.stderr
            )

    if not events:
        raise SystemExit(
            "No events could be parsed; "
            "refusing to overwrite the calendar."
        )

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    OUT.write_bytes(
        build_calendar(events).to_ical()
    )

    print(
        f"Wrote {OUT} with "
        f"{len(events)} calendar occurrences"
    )

    if failures:
        print(
            f"{len(failures)} event page(s) "
            f"could not be parsed.",
            file=sys.stderr
        )


if __name__ == "__main__":
    main()
