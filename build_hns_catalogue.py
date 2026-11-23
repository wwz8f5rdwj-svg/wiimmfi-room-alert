
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
    "User-Agent": "MKWii-HNS-Pack-Scanner/1.0"
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


def clean(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def normalize(text):
    text = clean(text).lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\bv?\d+(?:\.\d+)*(?:[a-z-]+)?\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return clean(text)


def get(url, params=None):
    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=30
    )
    response.raise_for_status()
    return response


def get_index_html():
    try:
        result = get(API, {
            "action": "parse",
            "page": "Custom Track Distribution",
            "prop": "text",
            "format": "json",
            "formatversion": "2"
        }).json()

        return result["parse"]["text"]

    except Exception as error:
        print("MediaWiki API nicht verfügbar:", error)
        print("Versuche direkten Seitenabruf ...")
        return get(INDEX).text


def extract_pack_links():
    html = get_index_html()
    soup = BeautifulSoup(html, "html.parser")

    found = {}

    for row in soup.select("tr"):
        row_text = clean(row.get_text(" ", strip=True)).lower()

        if not any(term in row_text for term in HNS_TERMS):
            continue

        for link in row.select("a[href]"):
            href = link.get("href", "")
            title = clean(
                link.get("title") or link.get_text(" ", strip=True)
            )

            if not title or not href:
                continue

            if "/wiki/" not in href:
                continue

            if title.lower() in ["edit", "history"]:
                continue

            if ":" in title:
                continue

            found[title] = urljoin(BASE, href)
            break

    for link in soup.select("a[href]"):
        href = link.get("href", "")
        title = clean(
            link.get("title") or link.get_text(" ", strip=True)
        )

        if not title or "/wiki/" not in href:
            continue

        if any(term in title.lower() for term in HNS_TERMS):
            if ":" not in title:
                found[title] = urljoin(BASE, href)

    return found


def get_page_html(title):
    result = get(API, {
        "action": "parse",
        "page": title,
        "prop": "text",
        "format": "json",
        "formatversion": "2"
    }).json()

    return result["parse"]["text"]


def extract_tracks(html):
    soup = BeautifulSoup(html, "html.parser")
    tracks = []

    for table in soup.select("table.wikitable"):
        for row in table.select("tr"):
            cells = [
                clean(cell.get_text(" ", strip=True))
                for cell in row.select("th, td")
            ]

            if len(cells) < 2:
                continue

            candidates = cells[1:]

            for candidate in candidates:
                lower = candidate.lower()

                if not candidate or len(candidate) < 3:
                    continue

                if lower in [
                    "track",
                    "arena",
                    "author",
                    "music",
                    "version",
                    "slot",
                    "cup"
                ]:
                    continue

                if any(word in lower for word in [
                    "track listing",
                    "download",
                    "credits",
                    "overview"
                ]):
                    continue

                if candidate not in tracks:
                    tracks.append(candidate)

                break

    return tracks


def main():
    print("Starte HNS-Pack-Suche ...")

    try:
        pack_links = extract_pack_links()
    except Exception as error:
        raise SystemExit(
            "Fehler beim Laden der HNS-Pack-Übersicht: "
            + str(error)
        )

    print("Gefundene mögliche HNS-Packs:", len(pack_links))

    catalogue = {
        "source": INDEX,
        "generated_utc": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime()
        ),
        "matching_note": (
            "Erste automatische Sammlung. "
            "Streckennamen müssen bei Bedarf manuell überprüft werden."
        ),
        "packs": []
    }

    report = []

    for name, url in sorted(
        pack_links.items(),
        key=lambda item: item[0].lower()
    ):
        print("Lese Pack:", name)

        try:
            title = unquote(
                url.split("/wiki/", 1)[1]
            ).replace("_", " ")

            html = get_page_html(title)
            tracks = extract_tracks(html)

            catalogue["packs"].append({
                "name": name,
                "url": url,
                "tracks": tracks,
                "track_count_extracted": len(tracks),
                "status": (
                    "candidate"
                    if tracks
                    else "needs_manual_review"
                )
            })

            report.append(
                f"{name}: {len(tracks)} Strecken gefunden"
            )

        except Exception as error:
            catalogue["packs"].append({
                "name": name,
                "url": url,
                "tracks": [],
                "track_count_extracted": 0,
                "status": "fetch_failed",
                "error": str(error)[:300]
            })

            report.append(
                f"{name}: FEHLER: {error}"
            )

        time.sleep(0.4)

    OUTPUT.write_text(
        json.dumps(
            catalogue,
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    REPORT.write_text(
        "MKWii HNS PACK-KATALOG\n"
        f"Quelle: {INDEX}\n"
        f"Gefundene Pack-Seiten: {len(pack_links)}\n\n"
        + "\n".join(report)
        + "\n",
        encoding="utf-8"
    )

    print("--------------------------------")
    print("FERTIG!")
    print("Gefundene Packs:", len(pack_links))
    print("Datenbank:", OUTPUT)
    print("Bericht:", REPORT)
    print("--------------------------------")


if __name__ == "__main__":
    main()
