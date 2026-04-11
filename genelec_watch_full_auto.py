#!/usr/bin/env python3
"""
Genelec watcher for local runs and GitHub Actions.

Highlights for GitHub Actions:
- Runs once per invocation (`--once`)
- Persists seen items to a JSON file that can be committed back to the repo
- Reads notifier credentials from environment variables / GitHub Secrets
- Can auto-enable WhatsApp, Discord, or email when secrets are present
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import smtplib
import sys
import time
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

try:
    from twilio.rest import Client as TwilioClient
except Exception:  # pragma: no cover
    TwilioClient = None

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 20
DEFAULT_KEYWORDS = [
    "genelec",
    "8030",
    "8040",
    "8050",
    "8010",
    "8020",
    "8330",
    "8340",
    "8350",
    "8361",
    "7350",
    "7360",
    "7370",
    "7380",
    "subwoofer",
]


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Listing:
    source: str
    title: str
    url: str
    price: Optional[str] = None
    location: Optional[str] = None

    @property
    def fingerprint(self) -> str:
        raw = f"{self.source}|{self.title}|{self.url}".strip().lower()
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SeenStore:
    def __init__(self, path: Path):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("seen"), dict):
                    return loaded
            except Exception:
                pass
        return {"seen": {}}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_new(self, listing: Listing) -> bool:
        return listing.fingerprint not in self.data["seen"]

    def mark(self, listing: Listing) -> None:
        self.data["seen"][listing.fingerprint] = {
            "source": listing.source,
            "title": listing.title,
            "url": listing.url,
            "price": listing.price,
            "location": listing.location,
            "seen_at": int(time.time()),
        }


class Fetcher:
    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.timeout = timeout

    def get(self, url: str, **kwargs) -> requests.Response:
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        response.raise_for_status()
        return response


class Notifier:
    def __init__(self, config: dict):
        self.config = config

    def notify(self, message: str) -> None:
        sent_any = False
        if self.config.get("whatsapp", {}).get("enabled"):
            self._notify_whatsapp(message)
            sent_any = True
        if self.config.get("discord", {}).get("enabled"):
            self._notify_discord(message)
            sent_any = True
        if self.config.get("email", {}).get("enabled"):
            self._notify_email(message)
            sent_any = True
        print(message)
        if not sent_any:
            logging.info("No outbound notifier enabled; printed to stdout only.")

    def _notify_whatsapp(self, message: str) -> None:
        cfg = self.config.get("whatsapp", {})
        if TwilioClient is None:
            logging.warning("Twilio SDK not installed; skipping WhatsApp notification.")
            return
        required = [cfg.get("account_sid"), cfg.get("auth_token"), cfg.get("from"), cfg.get("to")]
        if not all(required):
            logging.warning("WhatsApp config incomplete; skipping.")
            return
        try:
            client = TwilioClient(cfg["account_sid"], cfg["auth_token"])
            client.messages.create(body=message[:1500], from_=cfg["from"], to=cfg["to"])
        except Exception as exc:
            logging.exception("WhatsApp notification failed: %s", exc)

    def _notify_discord(self, message: str) -> None:
        cfg = self.config.get("discord", {})
        webhook_url = cfg.get("webhook_url")
        if not webhook_url:
            logging.warning("Discord webhook missing; skipping.")
            return
        try:
            requests.post(webhook_url, json={"content": message[:1900]}, timeout=15).raise_for_status()
        except Exception as exc:
            logging.exception("Discord notification failed: %s", exc)

    def _notify_email(self, message: str) -> None:
        cfg = self.config.get("email", {})
        required = [
            cfg.get("smtp_host"),
            cfg.get("smtp_port"),
            cfg.get("username"),
            cfg.get("password"),
            cfg.get("from"),
            cfg.get("to"),
        ]
        if not all(required):
            logging.warning("Email config incomplete; skipping.")
            return
        try:
            msg = EmailMessage()
            msg["Subject"] = "Uusi Genelec-osuma"
            msg["From"] = cfg["from"]
            msg["To"] = cfg["to"]
            msg.set_content(message)
            with smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"])) as server:
                server.starttls()
                server.login(cfg["username"], cfg["password"])
                server.send_message(msg)
        except Exception as exc:
            logging.exception("Email notification failed: %s", exc)


def contains_keyword(text: str, keywords: Iterable[str]) -> bool:
    lower = (text or "").lower()
    return any(k.lower() in lower for k in keywords)


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def scrape_huutokaupat(fetcher: Fetcher, keywords: list[str]) -> list[Listing]:
    url = f"https://huutokaupat.com/haku?term={quote_plus('Genelec')}"
    soup = BeautifulSoup(fetcher.get(url).text, "html.parser")
    items: list[Listing] = []
    seen_urls: set[str] = set()
    for a in soup.select("a[href]"):
        href = urljoin(url, a.get("href", ""))
        title = normalize_space(a.get_text(" "))
        if not href or "/kohde/" not in href or not contains_keyword(title + " " + href, keywords):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        items.append(Listing(source="Huutokaupat.com", title=title or "Genelec-kohde", url=href))
    return items


def scrape_huuto(fetcher: Fetcher, keywords: list[str]) -> list[Listing]:
    url = "https://www.huuto.net/haku/sell?words=genelec"
    soup = BeautifulSoup(fetcher.get(url).text, "html.parser")
    items: list[Listing] = []
    seen_urls: set[str] = set()
    for a in soup.select("a[href]"):
        href = urljoin(url, a.get("href", ""))
        title = normalize_space(a.get_text(" "))
        if not href or not re.search(r"/(kohteet|items?)/", href) or not contains_keyword(title + " " + href, keywords):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        items.append(Listing(source="Huuto.net", title=title or "Genelec-kohde", url=href))
    return items


def scrape_kiertonet(fetcher: Fetcher, keywords: list[str]) -> list[Listing]:
    candidate_urls = [
        "https://kiertonet.fi/?s=genelec",
        "https://kiertonet.fi/haku/?hakusana=genelec",
    ]
    items: list[Listing] = []
    for url in candidate_urls:
        try:
            soup = BeautifulSoup(fetcher.get(url).text, "html.parser")
        except Exception:
            continue
        seen_urls: set[str] = set(x.url for x in items)
        for a in soup.select("a[href]"):
            href = urljoin(url, a.get("href", ""))
            title = normalize_space(a.get_text(" "))
            if not href or not contains_keyword(title + " " + href, keywords):
                continue
            if "/huutokaupat/" not in href and "/kohde/" not in href and "genelec" not in href.lower():
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)
            items.append(Listing(source="Kiertonet", title=title or "Genelec-kohde", url=href))
        if items:
            break
    return items


def scrape_huutomylly(fetcher: Fetcher, keywords: list[str]) -> list[Listing]:
    candidate_urls = [
        "https://huutomylly.fi/huutokaupat?search=genelec",
        "https://huutomylly.fi/haku?term=genelec",
    ]
    items: list[Listing] = []
    for url in candidate_urls:
        try:
            soup = BeautifulSoup(fetcher.get(url).text, "html.parser")
        except Exception:
            continue
        seen_urls: set[str] = set(x.url for x in items)
        for a in soup.select("a[href]"):
            href = urljoin(url, a.get("href", ""))
            title = normalize_space(a.get_text(" "))
            if not href or not contains_keyword(title + " " + href, keywords):
                continue
            if "/huutokaupat/" not in href and "/kohde/" not in href and "genelec" not in href.lower():
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)
            items.append(Listing(source="Huutomylly", title=title or "Genelec-kohde", url=href))
        if items:
            break
    return items


def scrape_hifiharrastajat(fetcher: Fetcher, keywords: list[str]) -> list[Listing]:
    url = "https://foorumi.hifiharrastajat.org/index.php?search/search&keywords=genelec"
    soup = BeautifulSoup(fetcher.get(url).text, "html.parser")
    items: list[Listing] = []
    seen_urls: set[str] = set()
    for a in soup.select("a[href]"):
        href = urljoin(url, a.get("href", ""))
        title = normalize_space(a.get_text(" "))
        if not href or not contains_keyword(title + " " + href, keywords):
            continue
        if "/threads/" not in href and "/classifieds/" not in href and "/posts/" not in href:
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        items.append(Listing(source="Hifiharrastajat", title=title or "Genelec-osuma", url=href))
    return items


def scrape_muusikoiden(fetcher: Fetcher, keywords: list[str]) -> list[Listing]:
    candidate_urls = [
        "https://muusikoiden.net/tori/haku.php?keyword=genelec",
        "https://muusikoiden.net/tori/?keyword=genelec",
    ]
    items: list[Listing] = []
    for url in candidate_urls:
        try:
            soup = BeautifulSoup(fetcher.get(url).text, "html.parser")
        except Exception:
            continue
        seen_urls: set[str] = set(x.url for x in items)
        for a in soup.select("a[href]"):
            href = urljoin(url, a.get("href", ""))
            title = normalize_space(a.get_text(" "))
            if not href or not contains_keyword(title + " " + href, keywords):
                continue
            if "/tori/" not in href and "genelec" not in href.lower():
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)
            items.append(Listing(source="Muusikoiden.net", title=title or "Genelec-osuma", url=href))
        if items:
            break
    return items


def scrape_ebay(fetcher: Fetcher, keywords: list[str]) -> list[Listing]:
    url = "https://www.ebay.com/sch/i.html?_nkw=genelec"
    soup = BeautifulSoup(fetcher.get(url).text, "html.parser")
    items: list[Listing] = []
    seen_urls: set[str] = set()
    for card in soup.select("li.s-item"):
        link = card.select_one("a.s-item__link")
        title_el = card.select_one("div.s-item__title") or link
        price_el = card.select_one("span.s-item__price")
        if not link:
            continue
        href = urljoin(url, link.get("href", ""))
        title = normalize_space(title_el.get_text(" ")) if title_el else "Genelec-osuma"
        price = normalize_space(price_el.get_text(" ")) if price_el else None
        if not contains_keyword(title + " " + href, keywords):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        items.append(Listing(source="eBay", title=title, url=href, price=price))
    return items


def scrape_reverb(fetcher: Fetcher, keywords: list[str]) -> list[Listing]:
    url = "https://reverb.com/marketplace?query=genelec"
    soup = BeautifulSoup(fetcher.get(url).text, "html.parser")
    items: list[Listing] = []
    seen_urls: set[str] = set()
    for a in soup.select("a[href]"):
        href = urljoin(url, a.get("href", ""))
        title = normalize_space(a.get_text(" "))
        if not href or not contains_keyword(title + " " + href, keywords):
            continue
        if "/item/" not in href and "/p/" not in href:
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        items.append(Listing(source="Reverb", title=title or "Genelec-osuma", url=href))
    return items


def scrape_tori(fetcher: Fetcher, keywords: list[str]) -> list[Listing]:
    url = "https://www.tori.fi/recommerce/forsale/search?query=genelec"
    soup = BeautifulSoup(fetcher.get(url).text, "html.parser")
    items: list[Listing] = []
    seen_urls: set[str] = set()
    for a in soup.select("a[href]"):
        href = urljoin(url, a.get("href", ""))
        title = normalize_space(a.get_text(" "))
        if not href or not contains_keyword(title + " " + href, keywords):
            continue
        if "/item/" not in href and "/forsale/" not in href:
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        items.append(Listing(source="Tori.fi", title=title or "Genelec-osuma", url=href))
    return items


def default_config() -> dict:
    return {
        "keywords": DEFAULT_KEYWORDS,
        "state_file": "seen_genelec_items.json",
        "sources": {
            "huutokaupat": True,
            "huuto": True,
            "kiertonet": True,
            "huutomylly": True,
            "hifiharrastajat": True,
            "muusikoiden": True,
            "ebay": True,
            "reverb": True,
            "tori": False,
            "facebook_marketplace": False,
        },
        "whatsapp": {
            "enabled": False,
            "account_sid": "",
            "auth_token": "",
            "from": "",
            "to": "",
        },
        "discord": {
            "enabled": False,
            "webhook_url": "",
        },
        "email": {
            "enabled": False,
            "smtp_host": "",
            "smtp_port": "587",
            "username": "",
            "password": "",
            "from": "",
            "to": "",
        },
    }


def load_config(path: Path) -> dict:
    if not path.exists():
        cfg = default_config()
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return cfg
    return json.loads(path.read_text(encoding="utf-8"))


def merge_env_overrides(config: dict) -> dict:
    cfg = json.loads(json.dumps(config))

    cfg.setdefault("state_file", os.getenv("STATE_FILE", cfg.get("state_file", "seen_genelec_items.json")))
    cfg.setdefault("sources", {})
    if env_flag("ENABLE_TORI", False):
        cfg["sources"]["tori"] = True

    whatsapp = cfg.setdefault("whatsapp", {})
    whatsapp["account_sid"] = os.getenv("TWILIO_SID", whatsapp.get("account_sid", ""))
    whatsapp["auth_token"] = os.getenv("TWILIO_AUTH", whatsapp.get("auth_token", ""))
    whatsapp["from"] = os.getenv("WHATSAPP_FROM", whatsapp.get("from", ""))
    whatsapp["to"] = os.getenv("WHATSAPP_TO", whatsapp.get("to", ""))
    if env_flag("ENABLE_WHATSAPP", False) or all(
        [whatsapp.get("account_sid"), whatsapp.get("auth_token"), whatsapp.get("from"), whatsapp.get("to")]
    ):
        whatsapp["enabled"] = True

    discord = cfg.setdefault("discord", {})
    discord["webhook_url"] = os.getenv("DISCORD_WEBHOOK_URL", discord.get("webhook_url", ""))
    if env_flag("ENABLE_DISCORD", False) or discord.get("webhook_url"):
        discord["enabled"] = True

    email = cfg.setdefault("email", {})
    email["smtp_host"] = os.getenv("SMTP_HOST", email.get("smtp_host", ""))
    email["smtp_port"] = os.getenv("SMTP_PORT", email.get("smtp_port", "587"))
    email["username"] = os.getenv("SMTP_USERNAME", email.get("username", ""))
    email["password"] = os.getenv("SMTP_PASSWORD", email.get("password", ""))
    email["from"] = os.getenv("EMAIL_FROM", email.get("from", ""))
    email["to"] = os.getenv("EMAIL_TO", email.get("to", ""))
    if env_flag("ENABLE_EMAIL", False) or all(
        [
            email.get("smtp_host"),
            email.get("smtp_port"),
            email.get("username"),
            email.get("password"),
            email.get("from"),
            email.get("to"),
        ]
    ):
        email["enabled"] = True

    return cfg


def build_sources(config: dict) -> list[tuple[str, Callable[[Fetcher, list[str]], list[Listing]]]]:
    all_sources = [
        ("huutokaupat", scrape_huutokaupat),
        ("huuto", scrape_huuto),
        ("kiertonet", scrape_kiertonet),
        ("huutomylly", scrape_huutomylly),
        ("hifiharrastajat", scrape_hifiharrastajat),
        ("muusikoiden", scrape_muusikoiden),
        ("ebay", scrape_ebay),
        ("reverb", scrape_reverb),
        ("tori", scrape_tori),
    ]
    enabled = config.get("sources", {})
    return [(name, fn) for name, fn in all_sources if enabled.get(name, False)]


def format_listing_message(listing: Listing) -> str:
    lines = [f"UUSI GENELEC: {listing.title}", f"Lähde: {listing.source}"]
    if listing.price:
        lines.append(f"Hinta: {listing.price}")
    if listing.location:
        lines.append(f"Sijainti: {listing.location}")
    lines.append(listing.url)
    return "\n".join(lines)


def run_once(config: dict) -> int:
    fetcher = Fetcher()
    store = SeenStore(Path(config.get("state_file", "seen_genelec_items.json")))
    notifier = Notifier(config)
    keywords = config.get("keywords") or DEFAULT_KEYWORDS
    new_count = 0

    for source_name, scraper in build_sources(config):
        try:
            logging.info("Checking %s", source_name)
            listings = scraper(fetcher, keywords)
            logging.info("%s returned %d candidate(s)", source_name, len(listings))
            for listing in listings:
                if store.is_new(listing):
                    notifier.notify(format_listing_message(listing))
                    store.mark(listing)
                    new_count += 1
        except Exception as exc:
            logging.exception("Source %s failed: %s", source_name, exc)

    store.save()
    logging.info("Run complete; %d new item(s).", new_count)
    return new_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Genelec watcher for GitHub Actions or local runs")
    parser.add_argument("--config", default="config_genelec_watch.json", help="Path to config JSON")
    parser.add_argument("--once", action="store_true", help="Run one scan and exit")
    parser.add_argument("--interval", type=int, default=0, help="Repeat every N seconds")
    parser.add_argument("--enable-tori", action="store_true", help="Enable best-effort Tori monitoring")
    parser.add_argument("--log-level", default="INFO", help="DEBUG, INFO, WARNING, ERROR")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config_path = Path(args.config)
    config = merge_env_overrides(load_config(config_path))
    if args.enable_tori:
        config.setdefault("sources", {})["tori"] = True

    if args.once or args.interval <= 0:
        run_once(config)
        return 0

    while True:
        run_once(config)
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
print("TESTI: lähetetään WhatsApp viesti")

import os
from twilio.rest import Client

if os.getenv("ENABLE_WHATSAPP") == "true":
    client = Client(os.getenv("TWILIO_SID"), os.getenv("TWILIO_AUTH"))
    
    client.messages.create(
        body="TESTI OK ✅ Genelec vahti toimii!",
        from_=os.getenv("WHATSAPP_FROM"),
        to=os.getenv("WHATSAPP_TO")
    )
