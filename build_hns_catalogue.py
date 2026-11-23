
import json
import re
import time
import unicodedata
from urllib.parse import unquote, urlparse, quote

import requests
from bs4 import BeautifulSoup


VERSION = 7

BASE = "https://mkwiiki.org"
API = BASE + "/w/api.php"
INDEX_URL = BASE + "/wiki/Custom_Track_Distribution"

HEADERS = {
    "User-Agent": "HNS-Pack-Catalogue/7.0"
}

session = requests.Session()
session.headers.update(HEADERS)

EXTRA_PACKS = {
    "Xenøn's HNS: Horizon":
        BASE + "/wiki/Xen%C3%B8n%27s_HNS%3A_Horizon",
    "Xenøn's HNS: Beyond":
        BASE + "/wiki/Xen%C3%B8n%27s_HNS%3A_Beyond",
}


# --------------------------------------------------
# GRUNDLAGEN
# --------------------------------------------------

def get(url, params=None):
    response = session.get(
        url,
        params=params,
        timeout=45
    )
    response.raise_for_status()
    return response


def clean_text(value):
    value = value.replace("\xa0", " ")
    value = re.sub(r"\[[0-9]+\]", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \t\r\n|")


def normalize(value):
    value = clean_text(value).lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )
    value = value.replace("_", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def page_title_from_url(url):
    path = urlparse(url).path
    title = path.split("/wiki/", 1)[-1]
    return unquote(title).replace("_", " ")


def page_key(value):
    value = normalize(value)
    value = value.replace("'", "")
    value = re.sub(r"[^a-z0-9 ]", "", value)
    return re.sub(r"\s+", " ", value).strip()


# --------------------------------------------------
# WIKI API
# --------------------------------------------------

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
            json.dumps(
                result,
                ensure_ascii=False
            )[:1200]
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
    seen_titles = set()

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
        name = clean_text(
            link.get_text(" ", strip=True)
        )

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

        key = page_key(title)

        if key in seen_titles:
            continue

        seen_titles.add(key)
        packs[name] = BASE + href

    # Zusatzseiten nur hinzufügen, wenn sie nicht
    # bereits über den Index gefunden wurden.
    for name, url in EXTRA_PACKS.items():
        key = page_key(
            page_title_from_url(url)
        )

        if key not in seen_titles:
            packs[name] = url
            seen_titles.add(key)

    print("Gefundene Pack-Seiten:", len(packs))
    print("Index-Quelle:", source)

    return packs


# --------------------------------------------------
# FILTER FÜR TABELLENZELLEN
# --------------------------------------------------

GENERIC_CELLS = {
    "",
    "#",
    "-",
    "—",
    "–",
    "track",
    "tracks",
    "track name",
    "track listing",
    "track list",
    "arena",
    "arenas",
    "arena name",
    "arena listing",
    "arena list",
    "name",
    "author",
    "version",
    "date",
    "download",
    "cup",
    "stage",
    "type",
    "information",
    "first release",
    "track count",
    "number of tracks",
    "arena count",
    "number of arenas"
}


def is_noise(value):
    value = normalize(value)

    if value in GENERIC_CELLS:
        return True

    # Reine Versionsnummern und Dateiendungen
    if re.fullmatch(
        r"(?:v|version\s*)?\d+(?:\.\d+)*(?:[-+][a-z0-9._-]+)?(?:\.(?:scp|mkd|hns|ikw|ctgp|opt|item|lctp|ytpdx|mko2|briz|night))?",
        value,
        re.IGNORECASE
    ):
        return True

    # Reine Beta-, Alpha- und RC-Bezeichnungen
    if re.fullmatch(
        r"(?:beta|alpha|rc)(?:[\s._-]*[a-z0-9]+)*",
        value,
        re.IGNORECASE
    ):
        return True

    # Versionsangaben mit Zusatztext
    if re.fullmatch(
        r"(?:pre[- ]?\d+(?:\.\d+)*|v\d+(?:\.\d+)*\s+[\w.-]+)",
        value,
        re.IGNORECASE
    ):
        return True

    # Platzhalter und reine Dateinamen
    if re.fullmatch(
        r"[\w.-]+\.(?:scp|mkd|hns|ikw|opt|item|ctgp|lctp)",
        value,
        re.IGNORECASE
    ):
        return True

    return False


def is_generic_header(value):
    value = normalize(value)

    return value in {
        "track",
        "tracks",
        "track name",
        "arena",
        "arenas",
        "arena name",
        "name",
        "author",
        "version",
        "date",
        "download",
        "cup",
        "stage",
        "type",
        "information"
    }


# --------------------------------------------------
# TABELLEN-STRUKTUR
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
    caption = table.find(
        "caption",
        recursive=False
    )

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

        th_cells = row.find_all(
            "th",
            recursive=False
        )

        if not th_cells:
            continue

        values = [
            normalize(
                cell.get_text(" ", strip=True)
            )
            for cell in cells
        ]

        if len(th_cells) >= 2:
            return values

        if all(
            cell.name == "th"
            for cell in cells
        ):
            return values

    return []


def find_target_column(headers, keyword):
    exact = (
        ("track", "tracks", "track name", "course", "course name", "name")
        if keyword == "track"
        else ("arena", "arenas", "arena name", "battle stage", "name")
    )

    for index, heading in enumerate(headers):
        if heading in exact:
            return index

    for index, heading in enumerate(headers):
        if keyword in heading:
            return index

    return None


def section_matches(text, keyword):
    text = normalize(text)

    if keyword == "track":
        terms = (
            "track listing",
            "track list",
            "tracks",
            "custom tracks",
            "track"
        )
    else:
        terms = (
            "arena listing",
            "arena list",
            "arenas",
            "arena"
        )

    return any(
        term in text
        for term in terms
    )


# --------------------------------------------------
# ZELLEN AUSLESEN
# --------------------------------------------------

def cell_candidates(cell):
    candidates = []

    # Verlinkte Namen zuerst prüfen.
    for link in cell.find_all("a"):
        value = clean_text(
            link.get_text(" ", strip=True)
        )

        if value and not is_noise(value):
            candidates.append(value)

    # Falls keine brauchbaren Links vorhanden sind,
    # den gesamten Zellinhalt verwenden.
    full_value = clean_text(
        cell.get_text(" ", strip=True)
    )

    if full_value and not is_noise(full_value):
        candidates.append(full_value)

    return list(dict.fromkeys(candidates))


def candidate_score(value, cell):
    score = 0

    if cell.find("a"):
        score += 4

    if " " in value:
        score += 2

    if len(value) >= 8:
        score += 2

    if len(value) < 3:
        score -= 5

    if is_noise(value):
        score -= 100

    return score


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

    if (
        column_index is None
        and not section_matches(section_text, keyword)
    ):
        return []

    results = []

    for row in rows:
        cells = direct_cells(row)

        if not cells:
            continue

        # Echte Kopfzeilen überspringen.
        if all(
            cell.name == "th"
            for cell in cells
        ):
            continue

        if column_index is not None:
            if column_index >= len(cells):
                continue

            target_cells = [cells[column_index]]

        else:
            # Ohne eindeutige Spaltenüberschrift alle
            # Zellen bewerten und den besten Namen nehmen.
            target_cells = [
                cell
                for cell in cells
                if cell.name == "td"
            ]

        row_candidates = []

        for cell in target_cells:
            if cell.find("table"):
                continue

            for value in cell_candidates(cell):
                row_candidates.append(
                    (
                        candidate_score(value, cell),
                        value
                    )
                )

        if not row_candidates:
            continue

        row_candidates.sort(
            key=lambda item: item[0],
            reverse=True
        )

        best_value = row_candidates[0][1]

        if not is_noise(best_value):
            results.append(best_value)

    return list(dict.fromkeys(results))


# --------------------------------------------------
# MEHRERE PASSENDE TABELLEN SAMMELN
# --------------------------------------------------

def extract_table_items(soup, keyword):
    candidates = []

    for table in soup.find_all("table"):
        section = preceding_section_heading(table)
        caption = table_caption(table)
        headers = get_table_headers(table)

        section_text = section + " " + caption

        section_match = section_matches(
            section_text,
            keyword
        )

        column_match = (
            find_target_column(
                headers,
                keyword
            ) is not None
        )

        if not section_match and not column_match:
            continue

        items = extract_rows_from_table(
            table,
            keyword,
            section_text
        )

        if not items:
            continue

        score = 0

        if section_match:
            score += 5

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

    # Alle passenden Tabellen berücksichtigen,
    # nicht nur die Tabelle mit dem höchsten Score.
    candidates.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    results = []

    for candidate in candidates:
        for item in candidate["items"]:
            if item not in results:
                results.append(item)

    print(
        "  Tabellen:",
        keyword,
        "| Kandidaten:",
        len(candidates),
        "| Einträge:",
        len(results)
    )

    return results, True


# --------------------------------------------------
# ANGEGEBENE ANZAHLEN
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
# EINZELNE PACK-SEITE
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

    tracks = [
        item
        for item in dict.fromkeys(tracks)
        if not is_noise(item)
    ]

    arenas = [
        item
        for item in dict.fromkeys(arenas)
        if not is_noise(item)
    ]

    track_count = len(tracks)
    arena_count = len(arenas)

    # Ohne Sollzahlen kann keine vollständige
    # Erkennung bestätigt werden.
    if not track_table_found or track_count == 0:
        status = "manual_check"

    elif declared_tracks is None:
        status = "partial"

    elif track_count != declared_tracks:
        status = "partial"

    elif declared_arenas is None:
        status = "partial"

    elif arena_count != declared_arenas:
        status = "partial"

    elif declared_arenas > 0 and not arena_table_found:
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
