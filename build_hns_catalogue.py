
#!/usr/bin/env python3

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, unquote

import requests
from bs4 import BeautifulSoup

BASE = "https://mkwiiki.org"
INDEX = BASE + "/wiki/Custom_Track_Distribution"
API = BASE + "/w/api.php"

OUTPUT = Path("hns_packs.json")
REPORT = Path("hns_catalog_report.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 MKWii-HNS-Catalogue/2.0"
}

HNS_TERMS = [
    "hns",
    "hide and seek",
    "hide & seek",
    "hide-and-seek",
    "seek and hide",
    "hide n seek",
    "hide/seek"
]

EXCLUDED = {
    "riivolution",
    "my stuff",
    "custom track distribution",
    "edit",
    "history",
    "main page",
    "download"
}


def clean(value):
    return re.sub(r"\s+", " ", (value or "")).strip()


def normalize(value):
    value = clean(value).lower()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"\bv?\d+(?:\.\d+)*(?:[a-z-]+)?\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return clean(value)


def is_hns_name(value):
    value = (value or "").lower()
    return any(term in value for term in HNS_TERMS)


def get(url, params=None):
    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=30
    )
    response.raise_for_status()
    return response


def wiki_parse(title):
    result = get(
        API,
        {
            "action": "parse",
            "page": title,
            "prop": "text",
            "format": "json",
            "formatversion": "2"
        }
    ).json()

    return result["parse"]["text"]


def extract_pack_links():
    print("Lade Pack-Übersicht ...")

    result = get(
        API,
        {
            "action": "parse",
            "page": "Custom Track Distribution",
            "prop": "text",
            "format": "json",
            "formatversion": "2"
        }
    ).json()

    soup = BeautifulSoup(
        result["parse"]["text"],
        "html.parser"
    )

    found = {}

    # Nur Links übernehmen, deren eigener Name
    # auf ein Hide-and-Seek-Pack hinweist.
    for link in soup.select("a[href*='/wiki/']"):

        title = clean(
            link.get("title")
            or link.get_text(" ", strip=True)
        )

        href = link.get("href", "")

        if not title or not href:
            continue

        if title.lower() in EXCLUDED:
            continue

        if ":" in title:
            continue

        if not is_hns_name(title):
            continue

        full_url = urljoin(BASE, href)

        found[title] = full_url

    return found


def get_declared_count(soup, label):
    # Sucht die angegebene Gesamtzahl im Infokasten.
    for table in soup.select("table.infobox"):
        for row in table.select("tr"):
            cells = [
                clean(cell.get_text(" ", strip=True))
                for cell in row.select("th, td")
            ]

            if len(cells) >= 2:
                if cells[0].lower().rstrip(":") == label.lower():
                    match = re.search(r"\d+", cells[1])

                    if match:
                        return int(match.group())

    # Zusätzliche Suche im Seitenanfang.
    text = clean(soup.get_text(" ", strip=True))[:5000]

    match = re.search(
        rf"\b{re.escape(label)}\s*:?\s*(\d+)\b",
        text,
        re.IGNORECASE
    )

    if match:
        return int(match.group(1))

    return None


def extract_table_items(soup, wanted_column):
    results = []

    for table in soup.select("table.wikitable"):

        rows = table.select("tr")
        header_index = None
        column_index = None

        # Richtige Spalte anhand der Tabellenüberschrift finden.
        for row_index, row in enumerate(rows):

            cells = row.select("th, td")

            headings = [
                clean(cell.get_text(" ", strip=True)).lower()
                for cell in cells
            ]

            for index, heading in enumerate(headings):
                if heading.rstrip(":") == wanted_column.lower():
                    header_index = row_index
                    column_index = index
                    break

            if header_index is not None:
                break

        if header_index is None:
            continue

        # Nur die tatsächliche Track- bzw. Arena-Spalte lesen.
        for row in rows[header_index + 1:]:

            cells = row.select("th, td")

            if len(cells) <= column_index:
                continue

            value = clean(
                cells[column_index].get_text(" ", strip=True)
            )

            if not value:
                continue

            if value.lower() in {
                "track",
                "arena",
                "version",
                "author",
                "music",
                "cup",
                "stages"
            }:
                continue

            if value not in results:
                results.append(value)

    return results


def extract_pack_page(title, url):
    print("Lese:", title)

    html = wiki_parse(title)
    soup = BeautifulSoup(html, "html.parser")

    tracks = extract_table_items(soup, "Track")
    arenas = extract_table_items(soup, "Arena")

    declared_tracks = get_declared_count(soup, "Tracks")
    declared_arenas = get_declared_count(soup, "Arenas")

    return {
        "name": title,
        "url": url,
        "declared_tracks": declared_tracks,
        "declared_arenas": declared_arenas,
        "tracks": tracks,
        "arenas": arenas,
        "track_count_extracted": len(tracks),
        "arena_count_extracted": len(arenas),
        "status": (
            "candidate"
            if tracks or arenas
            else "needs_manual_review"
        )
    }


def main():
    print("================================")
    print("MKWII HNS CATALOGUE VERSION 2")
    print("================================")

    pack_links = extract_pack_links()

    print("Gefundene Pack-Seiten:", len(pack_links))

    catalogue = {
        "source": INDEX,
        "generated_utc": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime()
        ),
        "version": 2,
        "packs": []
    }

    report = []
    errors = 0

    for name, url in sorted(
        pack_links.items(),
        key=lambda item: item[0].lower()
    ):

        try:
            page_title = unquote(
                url.split("/wiki/", 1)[1]
            ).replace("_", " ")

            pack = extract_pack_page(page_title, url)

            catalogue["packs"].append(pack)

            track_status = ""

            if pack["declared_tracks"] is not None:
                if pack["track_count_extracted"] != pack["declared_tracks"]:
                    track_status = (
                        " | ABWEICHUNG: erwartet "
                        + str(pack["declared_tracks"])
                    )

            arena_status = ""

            if pack["declared_arenas"] is not None:
                if pack["arena_count_extracted"] != pack["declared_arenas"]:
                    arena_status = (
                        " | Arenen erwartet "
                        + str(pack["declared_arenas"])
                    )

            report.append(
                f"{name}: "
                f"{pack['track_count_extracted']} Strecken"
                f"{track_status} | "
                f"{pack['arena_count_extracted']} Arenen"
                f"{arena_status} | "
                f"{pack['status']}"
            )

        except Exception as error:
            errors += 1

            catalogue["packs"].append({
                "name": name,
                "url": url,
                "tracks": [],
                "arenas": [],
                "track_count_extracted": 0,
                "arena_count_extracted": 0,
                "status": "fetch_failed",
                "error": str(error)[:300]
            })

            report.append(
                f"{name}: FEHLER: {error}"
            )

        time.sleep(0.35)

    OUTPUT.write_text(
        json.dumps(
            catalogue,
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    REPORT.write_text(
        "MKWII HNS PACK-KATALOG VERSION 2\n"
        f"Quelle: {INDEX}\n"
        f"Pack-Seiten: {len(pack_links)}\n"
        f"Fehler: {errors}\n\n"
        + "\n".join(report)
        + "\n",
        encoding="utf-8"
    )

    print("--------------------------------")
    print("FERTIG!")
    print("Packs:", len(catalogue["packs"]))
    print("Fehler:", errors)
    print("Datenbank:", OUTPUT)
    print("Bericht:", REPORT)
    print("--------------------------------")


if __name__ == "__main__":
    main()
