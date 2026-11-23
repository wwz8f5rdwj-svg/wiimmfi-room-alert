
import json
import re
import time
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup


VERSION = 6

BASE = "https://mkwiiki.org"
API = BASE + "/w/api.php"
INDEX_URL = BASE + "/wiki/Custom_Track_Distribution"

HEADERS = {
    "User-Agent": "HNS-Pack-Catalogue/6.0"
}

session = requests.Session()
session.headers.update(HEADERS)

EXTRA_PACKS = {
    "Xenøn's HNS: Horizon":
        BASE + "/wiki/Xen%C3%B8n%27s_HNS%3A_Horizon",

    "Xenøn's HNS: Beyond":
        BASE + "/wiki/Xen%C3%B8n%27s_HNS%3A_Beyond",
}


def get(url, params=None):
    response = session.get(
        url,
        params=params,
        timeout=45
    )
    response.raise_for_status()
    return response


def page_title_from_url(url):
    path = urlparse(url).path
    title = path.split("/wiki/", 1)[-1]
    return unquote(title).replace("_", " ")


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

    if "parse" not in result:
        raise RuntimeError(
            "Wiki API: " +
            json.dumps(result, ensure_ascii=False)[:1200]
        )

    return result["parse"]["text"]


def fetch_page_html(title, url):
    try:
        print("  Quelle: Wiki-API")
        return wiki_parse(title), "api"

    except Exception as api_error:
        print(
            "  API nicht verfügbar:",
            str(api_error)[:250]
        )

        print("  Versuche direkten Seitenabruf ...")

        response = get(url)
        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        content = (
            soup.select_one("#mw-content-text")
            or soup.select_one(".mw-parser-output")
            or soup.body
        )

        if content is None:
            raise RuntimeError(
                "Weder API noch direkte Wiki-Seite lieferte Inhalt"
            )

        return str(content), "direct_html"


# --------------------------------------------------
# PACK-INDEX
# --------------------------------------------------

def extract_pack_links():
    print("Lade HNS-Pack-Index ...")

    html, source = fetch_page_html(
        "Custom Track Distribution",
        INDEX_URL
    )

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    packs = {}

    ignored_namespaces = (
        "category:",
        "file:",
        "help:",
        "special:",
        "template:",
        "talk:",
        "user:",
        "mediawiki:"
    )

    for link in soup.find_all("a", href=True):
        name = link.get_text(" ", strip=True)
        href = link["href"].split("#")[0]

        if not name or not href.startswith("/wiki/"):
            continue

        title = page_title_from_url(
            BASE + href
        )

        if title.lower().startswith(ignored_namespaces):
            continue

        searchable = name.lower()

        if (
            "hns" not in searchable
            and "hide and seek" not in searchable
        ):
            continue

        packs[name] = BASE + href

    packs.update(EXTRA_PACKS)

    print("Gefundene Pack-Seiten:", len(packs))
    print("Index-Quelle:", source)

    return packs


# --------------------------------------------------
# TEXT-BEREINIGUNG
# --------------------------------------------------

def clean_text(value):
    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize(value):
    value = clean_text(value)
    return value.lower().replace("_", " ")


def is_generic_cell(value):
    value = normalize(value)

    return value in {
        "",
        "#",
        "track",
        "tracks",
        "track name",
        "track listing",
        "arena",
        "arenas",
        "arena name",
        "arena listing",
        "name",
        "author",
        "version",
        "date",
        "download",
        "cup",
        "stage",
        "type",
        "information",
        "first release"
    }


# --------------------------------------------------
# TABELLEN-HILFSFUNKTIONEN
# --------------------------------------------------

def direct_table_rows(table):
    return [
        row
        for row in table.find_all("tr")
        if row.find_parent("table") is table
    ]


def direct_cells(row):
    return row.find_all(
        ["th", "td"],
        recursive=False
    )


def preceding_section_heading(table):
    headings = table.find_all_previous(
        ["h1", "h2", "h3", "h4", "h5", "h6"]
    )

    if not headings:
        return ""

    return normalize(
        headings[0].get_text(" ", strip=True)
    )


def table_caption(table):
    caption = table.find("caption", recursive=False)

    if caption:
        return normalize(
            caption.get_text(" ", strip=True)
        )

    return ""


def get_table_headers(table):
    rows = direct_table_rows(table)

    for row in rows[:8]:
        cells = direct_cells(row)

        if not cells:
            continue

        if not row.find_all("th", recursive=False):
            continue

        return [
            normalize(
                cell.get_text(" ", strip=True)
            )
            for cell in cells
        ]

    return []


def find_target_column(headers, keyword):
    for index, heading in enumerate(headers):

        if keyword == "track":
            if (
                heading in ("track", "tracks", "track name")
                or heading.startswith("track ")
            ):
                return index

        if keyword == "arena":
            if (
                heading in ("arena", "arenas", "arena name")
                or heading.startswith("arena ")
            ):
                return index

    return None


def section_matches(text, keyword):
    text = normalize(text)

    if keyword == "track":
        return any(
            word in text
            for word in (
                "track listing",
                "track list",
                "tracks",
                "custom tracks",
                "track"
            )
        )

    if keyword == "arena":
        return any(
            word in text
            for word in (
                "arena listing",
                "arena list",
                "arenas",
                "arena"
            )
        )

    return False


# --------------------------------------------------
# TABELLEN-INHALT AUSLESEN
# --------------------------------------------------

def extract_rows_from_table(
    table,
    keyword,
    section_text
):
    rows = direct_table_rows(table)

    if not rows:
        return []

    headers = get_table_headers(table)

    column_index = find_target_column(
        headers,
        keyword
    )

    if column_index is None:
        if not section_matches(
            section_text,
            keyword
        ):
            return []

        column_index = 0

    results = []

    for row in rows:
        cells = direct_cells(row)

        if not cells:
            continue

        if row.find_all("th", recursive=False):
            continue

        if column_index >= len(cells):
            continue

        cell = cells[column_index]

        if cell.find("table"):
            continue

        value = clean_text(
            cell.get_text(" ", strip=True)
        )

        if is_generic_cell(value):
            continue

        if re.fullmatch(
            r"(v|version\s*)?\d+(\.\d+)*([a-z-]+)?",
            value,
            re.IGNORECASE
        ):
            continue

        if len(value) > 160:
            continue

        if value not in results:
            results.append(value)

    return results


def extract_table_items(soup, keyword):
    candidates = []

    for table in soup.find_all("table"):

        section = preceding_section_heading(table)
        caption = table_caption(table)
        headers = get_table_headers(table)

        section_match = section_matches(
            section + " " + caption,
            keyword
        )

        column_match = (
            find_target_column(headers, keyword)
            is not None
        )

        if not section_match and not column_match:
            continue

        items = extract_rows_from_table(
            table,
            keyword,
            section + " " + caption
        )

        if not items:
            continue

        score = 0

        if section_match:
            score += 3

        if column_match:
            score += 4

        if caption:
            score += 1

        score += min(len(items), 50) / 10

        candidates.append({
            "items": items,
            "score": score,
            "section": section,
            "caption": caption
        })

    if not candidates:
        return [], False

    candidates.sort(
        key=lambda item: (
            item["score"],
            len(item["items"])
        ),
        reverse=True
    )

    best = candidates[0]

    print(
        "  Tabelle:",
        keyword,
        "| Abschnitt:",
        best["section"],
        "| Einträge:",
        len(best["items"])
    )

    return best["items"], True


# --------------------------------------------------
# DEKLARIERTE ANZAHLEN
# --------------------------------------------------

def get_declared_counts(soup):
    track_count = None
    arena_count = None

    for table in soup.find_all("table"):

        for row in direct_table_rows(table):
            cells = direct_cells(row)

            if len(cells) < 2:
                continue

            first = normalize(
                cells[0].get_text(" ", strip=True)
            )

            second = clean_text(
                cells[1].get_text(" ", strip=True)
            )

            match = re.search(
                r"\b(\d+)\b",
                second
            )

            if not match:
                continue

            number = int(match.group(1))

            if first in (
                "tracks",
                "track count",
                "number of tracks"
            ):
                track_count = number

            if first in (
                "arenas",
                "arena count",
                "number of arenas"
            ):
                arena_count = number

    return track_count, arena_count


# --------------------------------------------------
# PACK-SEITE
# --------------------------------------------------

def extract_pack_page(name, url):
    print("\nLese:", name)

    title = page_title_from_url(url)

    html, source = fetch_page_html(
        title,
        url
    )

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    declared_tracks, declared_arenas = get_declared_counts(
        soup
    )

    tracks, track_table_found = extract_table_items(
        soup,
        "track"
    )

    arenas, arena_table_found = extract_table_items(
        soup,
        "arena"
    )

    tracks = list(dict.fromkeys(tracks))
    arenas = list(dict.fromkeys(arenas))

    track_count = len(tracks)
    arena_count = len(arenas)

    if not track_table_found or track_count == 0:
        status = "manual_check"

    elif (
        declared_tracks is not None
        and track_count != declared_tracks
    ):
        status = "partial"

    elif (
        declared_arenas is not None
        and arena_table_found
        and arena_count != declared_arenas
    ):
        status = "partial"

    elif (
        declared_arenas is not None
        and declared_arenas > 0
        and not arena_table_found
    ):
        status = "partial"

    else:
        status = "complete"

    return {
        "name": name,
        "url": url,
        "source": source,

        "declared_track_count": declared_tracks,
        "track_count_extracted": track_count,
        "track_table_found": track_table_found,
        "tracks": tracks,

        "declared_arena_count": declared_arenas,
        "arena_count_extracted": arena_count,
        "arena_table_found": arena_table_found,
        "arenas": arenas,

        "status": status
    }


# --------------------------------------------------
# HAUPTPROGRAMM
# --------------------------------------------------

def main():
    packs = extract_pack_links()

    results = []
    errors = []

    for name, url in sorted(
        packs.items(),
        key=lambda item: item[0].lower()
    ):

        try:
            result = extract_pack_page(
                name,
                url
            )

            results.append(result)

            print(
                "  Strecken:",
                result["track_count_extracted"],
                "/",
                result["declared_track_count"],
                "| Arenen:",
                result["arena_count_extracted"],
                "/",
                result["declared_arena_count"],
                "| Quelle:",
                result["source"],
                "|",
                result["status"]
            )

        except Exception as error:
            message = str(error)

            print("  FEHLER:", message)

            errors.append({
                "name": name,
                "url": url,
                "error": message
            })

        time.sleep(0.5)

    complete = sum(
        1 for pack in results
        if pack["status"] == "complete"
    )

    partial = sum(
        1 for pack in results
        if pack["status"] == "partial"
    )

    manual = sum(
        1 for pack in results
        if pack["status"] == "manual_check"
    )

    report = []

    report.append(
        "HNS PACK KATALOG – VERSION " + str(VERSION)
    )

    report.append("=" * 55)
    report.append("")

    report.append(f"Pack-Seiten: {len(packs)}")
    report.append(f"Vollständig: {complete}")
    report.append(f"Unvollständig: {partial}")
    report.append(f"Manuelle Prüfung: {manual}")
    report.append(f"Fehler: {len(errors)}")
    report.append("")

    for pack in results:

        report.append("-" * 55)
        report.append(pack["name"])
        report.append("URL: " + pack["url"])
        report.append("Quelle: " + pack["source"])

        report.append(
            "Strecken: "
            + str(pack["track_count_extracted"])
            + " / "
            + str(pack["declared_track_count"])
        )

        report.append(
            "Arenen: "
            + str(pack["arena_count_extracted"])
            + " / "
            + str(pack["declared_arena_count"])
        )

        report.append(
            "Track-Tabelle gefunden: "
            + str(pack["track_table_found"])
        )

        report.append(
            "Arena-Tabelle gefunden: "
            + str(pack["arena_table_found"])
        )

        report.append("Status: " + pack["status"])
        report.append("")

        report.append("STRECKEN:")

        for track in pack["tracks"]:
            report.append(" - " + track)

        report.append("")
        report.append("ARENEN:")

        for arena in pack["arenas"]:
            report.append(" - " + arena)

        report.append("")

    if errors:

        report.append("=" * 55)
        report.append("FEHLER")
        report.append("=" * 55)

        for error in errors:
            report.append(error["name"])
            report.append(error["error"])
            report.append(error["url"])
            report.append("")

    with open(
        "hns_packs.json",
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            {
                "version": VERSION,
                "packs": results,
                "errors": errors
            },
            file,
            ensure_ascii=False,
            indent=2
        )

    with open(
        "hns_catalog_report.txt",
        "w",
        encoding="utf-8"
    ) as file:

        file.write(
            "\n".join(report)
        )

    print("\n===== HNS KATALOG FERTIG =====")
    print("Pack-Seiten:", len(packs))
    print("Vollständig:", complete)
    print("Unvollständig:", partial)
    print("Manuelle Prüfung:", manual)
    print("Fehler:", len(errors))


if __name__ == "__main__":
    main()
