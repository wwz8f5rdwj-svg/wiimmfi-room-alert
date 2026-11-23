
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
    "User-Agent": "Mozilla/5.0 MKWii-HNS-Catalogue/4.0"
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

# Diese Seiten ausdrücklich ergänzen,
# falls sie in der Übersicht nicht erkannt werden.
EXTRA_PACKS = {
    "Xenøn's HNS: Horizon":
        BASE + "/wiki/Xen%C3%B8n%27s_HNS%3A_Horizon",

    "Xenøn's HNS: Beyond":
        BASE + "/wiki/Xen%C3%B8n%27s_HNS%3A_Beyond"
}


def clean(value):
    return re.sub(
        r"\s+",
        " ",
        (value or "")
    ).strip()


def normalize(value):
    value = clean(value).lower()
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(
        r"\bv?\d+(?:\.\d+)*(?:[a-z-]+)?\b",
        " ",
        value
    )
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return clean(value)


def is_hns_name(value):
    value = (value or "").lower()

    return any(
        term in value
        for term in HNS_TERMS
    )


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

    for link in soup.select("a[href*='/wiki/']"):

        visible_name = clean(
            link.get_text(" ", strip=True)
        )

        title_attribute = clean(
            link.get("title", "")
        )

        href = link.get("href", "")

        if not href:
            continue

        # Sichtbaren Namen bevorzugen.
        title = visible_name or title_attribute

        if not title:
            continue

        if title.lower() in EXCLUDED:
            continue

        if ":" in title:
            continue

        if not is_hns_name(title):
            continue

        full_url = urljoin(BASE, href)

        found[title] = full_url

    # Fehlende bekannte Seiten ergänzen.
    for name, url in EXTRA_PACKS.items():
        found[name] = url

    return found


def get_declared_count(soup, label):

    for table in soup.select("table.infobox"):

        for row in table.select("tr"):

            cells = [
                clean(cell.get_text(" ", strip=True))
                for cell in row.select("th, td")
            ]

            if len(cells) < 2:
                continue

            if cells[0].lower().rstrip(":") == label.lower():

                match = re.search(
                    r"\d+",
                    cells[1]
                )

                if match:
                    return int(match.group())

    text = clean(
        soup.get_text(" ", strip=True)
    )[:10000]

    match = re.search(
        rf"\b{re.escape(label)}\s*:?\s*(\d+)\b",
        text,
        re.IGNORECASE
    )

    if match:
        return int(match.group(1))

    return None


def expand_table_rows(table):
    """
    Berücksichtigt rowspan und colspan.
    Dadurch bleiben zusammengeführte Cup-
    und Stage-Zellen an der richtigen Position.
    """

    active_spans = {}
    expanded_rows = []

    for row in table.select("tr"):

        current = {}

        # Vorhandene Rowspans übernehmen.
        for column, data in list(active_spans.items()):

            value, remaining = data

            current[column] = value

            if remaining > 1:
                active_spans[column] = (
                    value,
                    remaining - 1
                )
            else:
                del active_spans[column]

        cells = row.find_all(
            ["th", "td"],
            recursive=False
        )

        column = 0

        for cell in cells:

            while column in current:
                column += 1

            value = clean(
                cell.get_text(" ", strip=True)
            )

            try:
                colspan = int(
                    cell.get("colspan", 1)
                )
            except ValueError:
                colspan = 1

            try:
                rowspan = int(
                    cell.get("rowspan", 1)
                )
            except ValueError:
                rowspan = 1

            colspan = max(1, colspan)
            rowspan = max(1, rowspan)

            for offset in range(colspan):

                target = column + offset

                current[target] = value

                if rowspan > 1:
                    active_spans[target] = (
                        value,
                        rowspan - 1
                    )

            column += colspan

        if current:
            max_column = max(current.keys())

            expanded = [
                current.get(i, "")
                for i in range(max_column + 1)
            ]

            expanded_rows.append(expanded)

    return expanded_rows


def extract_table_items(soup, wanted_column):

    results = []

    for table in soup.select("table"):

        rows = expand_table_rows(table)

        header_index = None
        column_index = None

        # Passende Tabellenüberschrift suchen.
        for row_index, row in enumerate(rows):

            for index, value in enumerate(row):

                if clean(value).lower().rstrip(":") == wanted_column.lower():

                    header_index = row_index
                    column_index = index
                    break

            if header_index is not None:
                break

        if header_index is None:
            continue

        # Werte aus der passenden Spalte sammeln.
        for row in rows[header_index + 1:]:

            if len(row) <= column_index:
                continue

            value = clean(row[column_index])

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

    page_title = unquote(
        url.split("/wiki/", 1)[1]
    ).replace("_", " ")

    html = wiki_parse(page_title)

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    tracks = extract_table_items(
        soup,
        "Track"
    )

    arenas = extract_table_items(
        soup,
        "Arena"
    )

    declared_tracks = get_declared_count(
        soup,
        "Tracks"
    )

    declared_arenas = get_declared_count(
        soup,
        "Arenas"
    )

    track_count = len(tracks)
    arena_count = len(arenas)

    track_complete = (
        declared_tracks is not None
        and track_count == declared_tracks
    )

    arena_complete = (
        declared_arenas is None
        or arena_count == declared_arenas
    )

    if track_count == 0 and arena_count == 0:

        status = "needs_manual_review"

    elif track_complete and arena_complete:

        status = "complete"

    else:

        status = "partial"

    return {
        "name": title,
        "url": url,

        "declared_tracks": declared_tracks,
        "declared_arenas": declared_arenas,

        "tracks": tracks,
        "arenas": arenas,

        "track_count_extracted": track_count,
        "arena_count_extracted": arena_count,

        "track_complete": track_complete,
        "arena_complete": arena_complete,

        "status": status
    }


def main():

    print("================================")
    print("MKWII HNS CATALOGUE VERSION 4")
    print("================================")

    pack_links = extract_pack_links()

    print(
        "Gefundene Pack-Seiten:",
        len(pack_links)
    )

    catalogue = {
        "source": INDEX,

        "generated_utc": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime()
        ),

        "version": 4,

        "packs": []
    }

    report = []

    errors = 0
    complete = 0
    partial = 0
    manual = 0

    for name, url in sorted(
        pack_links.items(),
        key=lambda item: item[0].lower()
    ):

        try:

            pack = extract_pack_page(
                name,
                url
            )

            catalogue["packs"].append(pack)

            if pack["status"] == "complete":
                complete += 1

            elif pack["status"] == "partial":
                partial += 1

            else:
                manual += 1

            track_expected = (
                str(pack["declared_tracks"])
                if pack["declared_tracks"] is not None
                else "?"
            )

            arena_expected = (
                str(pack["declared_arenas"])
                if pack["declared_arenas"] is not None
                else "?"
            )

            report.append(
                f"{name}\n"
                f"  Strecken: "
                f"{pack['track_count_extracted']}"
                f"/{track_expected}\n"
                f"  Arenen: "
                f"{pack['arena_count_extracted']}"
                f"/{arena_expected}\n"
                f"  Status: {pack['status']}\n"
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
                f"{name}\n"
                f"  FEHLER: {error}\n"
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
        "MKWII HNS PACK-KATALOG VERSION 4\n"
        f"Quelle: {INDEX}\n"
        f"Pack-Seiten: {len(pack_links)}\n"
        f"Vollständig: {complete}\n"
        f"Unvollständig: {partial}\n"
        f"Manuelle Prüfung: {manual}\n"
        f"Fehler: {errors}\n\n"
        + "\n".join(report),
        encoding="utf-8"
    )

    print("--------------------------------")
    print("FERTIG!")
    print("Packs:", len(catalogue["packs"]))
    print("Vollständig:", complete)
    print("Unvollständig:", partial)
    print("Manuelle Prüfung:", manual)
    print("Fehler:", errors)
    print("Datenbank:", OUTPUT)
    print("Bericht:", REPORT)
    print("--------------------------------")


if __name__ == "__main__":
    main()
