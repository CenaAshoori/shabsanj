"""Count visits through the provider CTAs without collecting visitor identifiers."""

from contextlib import closing
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit


PROVIDERS = {
    "tournegar": ("تورنگار", {"tournegar.com", "www.tournegar.com"}),
    "tikhotel": ("تیک‌هتل", {"tikhotel.com", "www.tikhotel.com"}),
    "iranhotelonline": ("ایران هتل آنلاین", {"iranhotelonline.com", "www.iranhotelonline.com"}),
    "snapptrip": ("اسنپ‌تریپ", {"www.snapptrip.com"}),
    "asasafar": ("آسا سفر", {"www.asasafar.com"}),
    "rahig": ("رهیگ", {"rahig.com"}),
    "tikotrip": ("تیکو تریپ", {"tikotrip.com"}),
    "redbilit": ("ردبلیط", {"redbilit.com"}),
    "safar724": ("سفر۷۲۴", {"safar724.com"}),
    "mrbilit": ("مستربلیط", {"mrbilit.com"}),
    "orienttrips": ("اورینت تریپس", {"orienttrips.com"}),
    "fadak": ("فدک", {"www.fadaktrains.com"}),
}


def destination(kind: str, row: dict) -> tuple[str, str, str, str, str] | None:
    provider = row.get("provider")
    url = row.get("source_url")
    if provider not in PROVIDERS or not isinstance(url, str):
        return None
    provider_name, hosts = PROVIDERS[provider]
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname not in hosts
                or parts.username or parts.password or parts.port not in (None, 443)
                or any(char in url for char in "\\\r\n\t")):
            return None
    except ValueError:
        return None
    if kind == "ticket":
        route = f"{row.get('origin', '')} → {row.get('destination', '')}"
        title = f"{row.get('mode', '')} · {route}"
        item = f"{title} · {row.get('departure_date') or ''}"
    elif kind == "tour":
        item, title = row.get("tour_id"), row.get("title")
    else:
        item, title = row.get("hotel_id"), row.get("hotel_name")
    key = sha256(f"{kind}\0{provider}\0{item or ''}\0{url}".encode()).hexdigest()[:32]
    return key, provider, provider_name, str(title or provider_name), url


def cta_url(kind: str, row: dict) -> str | None:
    target = destination(kind, row)
    return f"/go/{kind}/{target[0]}" if target else None


class ClickCounter:
    def __init__(self, path: Path):
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def record(self, kind: str, target: tuple[str, str, str, str, str]) -> None:
        key, provider, name, title, _ = target
        observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with closing(self._connect()) as connection, connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS outbound_clicks (
                    link_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    provider TEXT NOT NULL, provider_name TEXT NOT NULL,
                    title TEXT NOT NULL, clicks INTEGER NOT NULL,
                    last_clicked_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                INSERT INTO outbound_clicks VALUES (?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(link_id) DO UPDATE SET
                    clicks = clicks + 1, title = excluded.title,
                    last_clicked_at = excluded.last_clicked_at
            """, (key, kind, provider, name, title, observed_at))

    def summary(self) -> dict:
        links = []
        if self.path.is_file():
            with closing(self._connect()) as connection:
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='outbound_clicks'"
                ).fetchone()
                if exists:
                    links = [dict(row) for row in connection.execute("""
                        SELECT * FROM outbound_clicks ORDER BY clicks DESC, last_clicked_at DESC, link_id
                    """)]
        by_kind = {"hotel": 0, "tour": 0}
        by_provider: dict[str, dict] = {}
        for link in links:
            by_kind[link["kind"]] = by_kind.get(link["kind"], 0) + link["clicks"]
            provider = by_provider.setdefault(link["provider"], {
                "provider": link["provider"], "provider_name": link["provider_name"], "clicks": 0,
            })
            provider["clicks"] += link["clicks"]
        return {
            "total": sum(by_kind.values()),
            "by_kind": by_kind,
            "providers": sorted(by_provider.values(), key=lambda row: (-row["clicks"], row["provider"])),
            "links": links,
        }
