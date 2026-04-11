#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
import ssl
import sys
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SEEN_FILE = Path("seen_genelec_items.json")
DEFAULT_KEYWORDS = ["genelec"]
DEFAULT_TIMEOUT = 25


@dataclass
class Item:
    source: str
    title: str
    url: str
    price: Optional[str] = None

    @property
    def key(self) -> str:
        return f"{self.source}|{self.url}".strip().lower()


def load_seen() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        return set(data.get("seen", []))
    except Exception:
        return set()


def save_seen(seen: set[str]) -> None:
    SEEN_FILE.write_text(
        json.dumps({"seen": sorted(seen)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def http_get(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.text


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def match_keywords(text: str, keywords: Iterable[str]) -> bool:
    low = (text or "").lower()
    return any(k.lower() in low for k in keywords)


def dedupe(items: List[Item]) -> List[Item]:
    out: List[Item] = []
    seen: set[str] = set()
    for item in items:
        if item.key not in seen:
            seen.add(item.key)
            out.append(item)
    return out


def parse_huutokaupat(keywords: List[str]) -> List[Item]:
    url = "https://huutokaupat.com/haku?term=genelec"
    items: List[Item] = []
    try:
        soup = BeautifulSoup(http_get(url), "html.parser")
        for a in soup.select("a[href*='/kohde/']"):
            title = clean_text(a.get_text(" ", strip=True))
            href = a.get("href", "")
            full = urljoin("https://huutokaupat.com", href)
            if title and match_keywords(title, keywords):
                items.append(Item("huutokaupat.com", title, full))
    except Exception as exc:
        print(f"[WARN] huutokaupat.com failed: {exc}")
    return dedupe(items)


def parse_huuto(keywords: List[str]) -> List[Item]:
    url = "https://www.huuto.net/haku/sana/genelec"
    items: List[Item] = []
    try:
        soup = BeautifulSoup(http_get(url), "html.parser")
        for a in soup.select("a[href*='/kohteet/'], a[href*='/tuote/'], a[href*='/kohde/']"):
            title = clean_text(a.get_text(" ", strip=True))
            href = a.get("href", "")
            full = urljoin("https://www.huuto.net", href)
            if title and match_keywords(title, keywords):
                items.append(Item("huuto.net", title, full))
    except Exception as exc:
        print(f"[WARN] huuto.net failed: {exc}")
    return dedupe(items)


def parse_hifiharrastajat(keywords: List[str]) -> List[Item]:
    url = "https://foorumi.hifiharrastajat.org/index.php?search/search&keywords=genelec"
    items: List[Item] = []
    try:
        soup = BeautifulSoup(http_get(url), "html.parser")
        for a in soup.select("a[href*='/threads/'], a[href*='/posts/']"):
            title = clean_text(a.get_text(" ", strip=True))
            href = a.get("href", "")
            full = urljoin("https://foorumi.hifiharrastajat.org", href)
            if title and match_keywords(title, keywords):
                items.append(Item("foorumi.hifiharrastajat.org", title, full))
    except Exception as exc:
        print(f"[WARN] hifiharrastajat failed: {exc}")
    return dedupe(items)


def parse_muusikoiden(keywords: List[str]) -> List[Item]:
    url = "https://muusikoiden.net/tori/?keyword=genelec"
    items: List[Item] = []
    try:
        soup = BeautifulSoup(http_get(url), "html.parser")
        for a in soup.select("a[href*='tori/ilmoitus/'], a[href*='/tori/']"):
            title = clean_text(a.get_text(" ", strip=True))
            href = a.get("href", "")
            full = urljoin("https://muusikoiden.net", href)
            if title and match_keywords(title, keywords):
                items.append(Item("muusikoiden.net", title, full))
    except Exception as exc:
        print(f"[WARN] muusikoiden.net failed: {exc}")
    return dedupe(items)


def parse_ebay(keywords: List[str]) -> List[Item]:
    url = "https://www.ebay.com/sch/i.html?_nkw=genelec"
    items: List[Item] = []
    try:
        soup = BeautifulSoup(http_get(url), "html.parser")
        for a in soup.select("a.s-item__link"):
            title_el = a.select_one(".s-item__title")
            title = clean_text(title_el.get_text(" ", strip=True) if title_el else a.get_text(" ", strip=True))
            href = a.get("href", "")
            if title and href and match_keywords(title, keywords):
                items.append(Item("ebay.com", title, href))
    except Exception as exc:
        print(f"[WARN] ebay.com failed: {exc}")
    return dedupe(items)


def parse_reverb(keywords: List[str]) -> List[Item]:
    url = "https://reverb.com/marketplace?query=genelec"
    items: List[Item] = []
    try:
        soup = BeautifulSoup(http_get(url), "html.parser")
        for a in soup.select("a[href*='/item/']"):
            title = clean_text(a.get_text(" ", strip=True))
            href = a.get("href", "")
            full = urljoin("https://reverb.com", href)
            if title and match_keywords(title, keywords):
                items.append(Item("reverb.com", title, full))
    except Exception as exc:
        print(f"[WARN] reverb.com failed: {exc}")
    return dedupe(items)


def collect_items(keywords: List[str]) -> List[Item]:
    all_items: List[Item] = []
    for fn in [
        parse_huutokaupat,
        parse_huuto,
        parse_hifiharrastajat,
        parse_muusikoiden,
        parse_ebay,
        parse_reverb,
    ]:
        all_items.extend(fn(keywords))
    return dedupe(all_items)


def send_email(subject: str, body: str) -> None:
    if os.getenv("ENABLE_EMAIL", "false").lower() != "true":
        print("[INFO] Email notifications disabled.")
        return

    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_username = os.getenv("SMTP_USERNAME")
    smtp_password = os.getenv("SMTP_PASSWORD")
    email_from = os.getenv("EMAIL_FROM")
    email_to = os.getenv("EMAIL_TO")

    missing = [
        name for name, value in {
            "SMTP_HOST": smtp_host,
            "SMTP_USERNAME": smtp_username,
            "SMTP_PASSWORD": smtp_password,
            "EMAIL_FROM": email_from,
            "EMAIL_TO": email_to,
        }.items() if not value
    ]
    if missing:
        print(f"[WARN] Missing email settings: {', '.join(missing)}")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls(context=context)
        server.login(smtp_username, smtp_password)
        server.send_message(msg)

    print("[INFO] Email sent successfully.")


def format_email(items: List[Item]) -> str:
    lines = ["Uusia Genelec-osumia löytyi:", ""]
    for idx, item in enumerate(items, 1):
        lines.append(f"{idx}. [{item.source}] {item.title}")
        lines.append(f"   {item.url}")
        if item.price:
            lines.append(f"   Hinta: {item.price}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keywords", nargs="*", default=DEFAULT_KEYWORDS)
    parser.add_argument("--send-test-email", action="store_true")
    args = parser.parse_args()

    if args.send_test_email:
        send_email(
            subject="TESTI OK - Genelec vahti toimii",
            body="Tämä on testiviesti. Jos näet tämän, sähköposti-ilmoitukset toimivat.",
        )
        return 0

    seen = load_seen()
    items = collect_items(args.keywords)

    print(f"[INFO] Found {len(items)} total matching items.")
    for item in items[:20]:
        print(f"- {item.source}: {item.title} -> {item.url}")

    new_items = [item for item in items if item.key not in seen]
    print(f"[INFO] New items: {len(new_items)}")

    if new_items:
        send_email(
            subject=f"Genelec-vahti: {len(new_items)} uutta osumaa",
            body=format_email(new_items),
        )
        for item in new_items:
            seen.add(item.key)
        save_seen(seen)
    else:
        print("[INFO] No new items, no email sent.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
