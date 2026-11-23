
import json
import re
import time
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup


BASE = "https://mkwiiki.org"
API = BASE + "/w/api.php"
INDEX_URL = BASE + "/wiki/Custom_Track_Distribution"

HEADERS = {
    "User-Agent": "HNS-Pack-Catalogue/5.0"
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
        timeout=40
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

    # Diagnose: tatsächliche API-Fehlermeldung ausgeben
    if "parse" not in result:
        print(
            "\nWIKI API FEHLER:",
            json.dumps(result, ensure_ascii=False, indent=2)
        )
        raise RuntimeError(
            "Wiki API hat keine parse-Daten geliefert"
        )

    return result["parse"]["text"]


def page_title_from_url(url):
    path = urlparse(url).path
    title = path.split("/wiki/", 1)[-1]
    return unquote(title).replace("_", " ")


def extract_pack_links():
    print("Lade HNS-Pack-Index ...")

    html = wiki_parse("Custom Track Distribution")
    soup = BeautifulSoup(html, "html.parser")

    packs = {}

    for link in soup.find_all("a", href=True):
        name = link.get_text(" ", strip=True)
        href = link["href"]

        if not name or not href.startswith("/wiki/"):
            continue

        searchable = name.lower()

        if (
            "hns" not in searchable
            and "hide and seek" not in searchable
        ):
            continue

        if ":" in href and not href.startswith("/wiki/Xen"):
            continue

        full_url = BASE + href.split("#")[0]

        packs[name] = full_url

    # Zusätzliche bekannte Pack-Seiten
    packs.update(EXTRA_PACKS)

    print("Gefundene Pack-Seiten:", len(packs))

    return packs


def get_declared_counts(soup):
    text = soup.get_text(" ", strip=True)

    track_count = None
    arena_count = None

    patterns_tracks = [
        r"(\d+)\s+tracks?",
        r"tracks?[:\s]+(\d+)",
    ]

    patterns_arenas = [
        r"(\d+)\s+arenas?",
        r"arenas?[:\s]+(\d+)",
    ]

    for pattern in patterns_tracks:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            track_count = int(match.group(1))
            break

    for pattern in patterns_arenas:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            arena_count = int(match.group(1))
            break

    return track_count, arena_count


def extract_table_items(soup, keyword):
    results = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr", recursive=True)

        if not rows:
            continue

        header_row = None
        header_cells = []

        for row in rows:
            cells = row.find_all(
                ["th", "td"],
                recursive=False
            )

            if not cells:
                continue

            headers = [
                cell.get_text(" ", strip=True).lower()
                for cell in cells
            ]

            if any(keyword in h for h in headers):
                header_row = row
                header_cells = cells
                break

        if header_row is None:
            continue

        column_index = None

        for index, cell in enumerate(header_cells):
            heading = cell.get_text(" ", strip=True).lower()

            if keyword in heading:
                column_index = index
                break

        if column_index is None:
            continue

        active_spans = {}
        table_items = []

        for row in rows:
            if row is header_row:
                continue

            cells = row.find_all(
                ["th", "td"],
                recursive=False
            )

            if not cells:
                continue

            expanded = []
            current_index = 0

            for cell in cells:
                while current_index in active_spans:
                    expanded.append(active_spans[current_index]["text"])
                    active_spans[current_index]["remaining"] -= 1

                    if active_spans[current_index]["remaining"] <= 0:
                        del active_spans[current_index]

                    current_index += 1

                value = cell.get_text(" ", strip=True)
                colspan = int(cell.get("colspan", 1))
                rowspan = int(cell.get("rowspan", 1))

                for offset in range(colspan):
                    expanded.append(value)

                    if rowspan > 1:
                        active_spans[current_index] = {
                            "text": value,
                            "remaining": rowspan - 1
                        }

                    current_index += 1

            while current_index in active_spans:
                expanded.append(active_spans[current_index]["text"])
                active_spans[current_index]["remaining"] -= 1

                if active_spans[current_index]["remaining"] <= 0:
                    del active_spans[current_index]

                current_index += 1

            if column_index >= len(expanded):
                continue

            item = expanded[column_index].strip()

            if not item:
                continue

            if item.lower() in (
                "track",
                "tracks",
                "arena",
                "arenas",
                "cup",
                "stage"
            ):
                continue

            if item not in table_items:
                table_items.append(item)

        if len(table_items) > len(results):
            results = table_items

    return results


def extract_pack_page(name, url):
    print("\nLese:", name)

    title = page_title_from_url(url)

    html = wiki_parse(title)
    soup = BeautifulSoup(html, "html.parser")

    declared_tracks, declared_arenas = get_declared_counts(soup)

    tracks = extract_table_items(soup, "track")
    arenas = extract_table_items(soup, "arena")

    tracks = list(dict.fromkeys(tracks))
    arenas = list(dict.fromkeys(arenas))

    track_count = len(tracks)
    arena_count = len(arenas)

    if declared_tracks is None:
        status = "manual_check"
    elif track_count == declared_tracks:
        if declared_arenas is None or arena_count == declared_arenas:
            status = "complete"
        else:
            status = "partial"
    else:
        status = "partial"

    return {
        "name": name,
        "url": url,
        "declared_track_count": declared_tracks,
        "track_count_extracted": track_count,
        "tracks": tracks,
        "declared_arena_count": declared_arenas,
        "arena_count_extracted": arena_count,
        "arenas": arenas,
        "status": status
    }


def main():
    packs = extract_pack_links()

    results = []
    errors = []

    for name, url in sorted(
        packs.items(),
        key=lambda item: item[0].lower()
    ):
        try:
            result = extract_pack_page(name, url)
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

        time.sleep(0.3)

    complete = sum(
        1 for p in results
        if p["status"] == "complete"
    )

    partial = sum(
        1 for p in results
        if p["status"] == "partial"
    )

    manual = sum(
        1 for p in results
        if p["status"] == "manual_check"
    )

    report = []

    report.append("HNS PACK KATALOG – VERSION 5")
    report.append("=" * 50)
    report.append("")
    report.append(f"Pack-Seiten: {len(packs)}")
    report.append(f"Vollständig: {complete}")
    report.append(f"Unvollständig: {partial}")
    report.append(f"Manuelle Prüfung: {manual}")
    report.append(f"Fehler: {len(errors)}")
    report.append("")

    for pack in results:
        report.append("-" * 50)
        report.append(pack["name"])
        report.append("URL: " + pack["url"])

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
        report.append("=" * 50)
        report.append("FEHLER")
        report.append("=" * 50)

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
                "version": 5,
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
        file.write("\n".join(report))

    print("\n===== HNS KATALOG FERTIG =====")
    print("Pack-Seiten:", len(packs))
    print("Vollständig:", complete)
    print("Unvollständig:", partial)
    print("Manuelle Prüfung:", manual)
    print("Fehler:", len(errors))


if __name__ == "__main__":
    main()
