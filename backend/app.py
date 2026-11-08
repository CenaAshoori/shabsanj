"""FastAPI application for comparing observed Iranian travel offers.

Run from the torob-hotel directory with:
    uvicorn backend.app:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
import json
import logging
import os
from pathlib import Path
import sqlite3
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .search import catalog_summary, search_catalog
from .config import openrouter_key
from .tickets import CITIES as TICKET_CITIES, search_tickets, ticket_routes
from .tours import linked_tour_counts, search_tours
from .outbound import ClickCounter, cta_url, destination


ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "data" / "catalog.json"
TOURS_PATH = ROOT / "data" / "tours.json"
TICKETS_PATH = ROOT / "data" / "tickets.json"
DIST_DIR = ROOT / "frontend" / "dist"
CLICK_COUNTER = ClickCounter(Path(os.environ.get("SHABSANJ_ANALYTICS_DB") or ROOT / "data" / "analytics.sqlite3"))
LOGGER = logging.getLogger(__name__)

app = FastAPI(
    title="ShabSanj Travel Comparison",
    description="Compare observed hotel, tour, and ticket prices with links to the sellers.",
    version="0.1.0",
)

# The demo UI normally shares this origin. This also permits local Vite dev
# servers, which only use public read-only GET endpoints.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@lru_cache(maxsize=4)
def _read_catalog_for_revision(revision: int) -> dict[str, Any]:
    with CATALOG_PATH.open("r", encoding="utf-8") as file:
        catalog = json.load(file)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("offers"), list):
        raise ValueError("catalog.json must contain an offers array")
    return catalog


def load_catalog() -> dict[str, Any]:
    try:
        return _read_catalog_for_revision(CATALOG_PATH.stat().st_mtime_ns)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Hotel catalog has not been crawled yet") from exc
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Hotel catalog is unavailable: {exc}") from exc


@lru_cache(maxsize=4)
def _read_tours_for_revision(revision: int) -> dict[str, Any]:
    with TOURS_PATH.open("r", encoding="utf-8") as file:
        catalog = json.load(file)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("tours"), list):
        raise ValueError("tours.json must contain a tours array")
    return catalog


def load_tours_catalog() -> dict[str, Any]:
    try:
        return _read_tours_for_revision(TOURS_PATH.stat().st_mtime_ns)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Tour catalog has not been crawled yet") from exc
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=f"Tour catalog is unavailable: {exc}") from exc


@lru_cache(maxsize=4)
def _read_tickets_for_revision(revision: int) -> dict[str, Any]:
    with TICKETS_PATH.open("r", encoding="utf-8") as file:
        catalog = json.load(file)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("offers"), list):
        raise ValueError("tickets.json must contain an offers array")
    return catalog


def load_ticket_catalog() -> dict[str, Any]:
    try:
        return _read_tickets_for_revision(TICKETS_PATH.stat().st_mtime_ns)
    except FileNotFoundError:
        return {"offers": [], "generated_at": None}
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Ticket catalog is unavailable") from exc


@app.get("/api/tickets/routes")
def available_ticket_routes() -> dict:
    return ticket_routes(load_ticket_catalog())


@app.get("/api/tickets")
def tickets(
    origin: str = Query(max_length=32),
    destination: str = Query(max_length=32),
    departure_date: date | None = Query(default=None, alias="date"),
    mode: Literal["flight", "bus", "train"] | None = None,
) -> dict:
    if origin not in TICKET_CITIES or destination not in TICKET_CITIES or origin == destination:
        raise HTTPException(status_code=422, detail="Choose distinct origin and destination cities")
    return search_tickets(load_ticket_catalog(), origin, destination, departure_date, mode)


def _query_plan(query: str, mode: Literal["hotels", "tours"]) -> tuple[dict[str, Any] | None, str]:
    """Interpret free text separately from the trusted catalog filter engine."""
    if not query.strip():
        return None, "deterministic"
    try:
        from .semantic import plan_query
        plan, source = plan_query(query, mode)
        return (plan, source) if plan else (None, "fallback")
    except Exception:
        # Network, provider, or planner failures must not break catalog search.
        LOGGER.warning("Semantic query planning unavailable; using local parser")
        return None, "fallback"


@app.get("/api/config")
def public_config(response: Response) -> dict[str, bool]:
    response.headers["Cache-Control"] = "no-store"
    return {"openrouter_configured": bool(openrouter_key())}


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        catalog = load_catalog()
    except HTTPException as exc:
        return {"status": "degraded", "catalog_ready": False, "message": exc.detail}
    summary = catalog_summary(catalog)
    try:
        tours = load_tours_catalog()
        tour_count = len(tours["tours"])
    except HTTPException:
        tours = None
        tour_count = 0
    tickets = load_ticket_catalog()
    return {
        "status": "ok" if summary["offer_count"] and tour_count else "degraded",
        "catalog_ready": bool(summary["offer_count"]),
        "tour_catalog_ready": bool(tour_count),
        "generated_at": summary["generated_at"],
        "offer_count": summary["offer_count"],
        "tour_count": tour_count,
        "tours_generated_at": tours.get("generated_at") if tours else None,
        "ticket_count": len(tickets["offers"]),
        "ticket_catalog_ready": bool(tickets["offers"]),
    }


@app.get("/api/catalog/summary")
def summary() -> dict[str, Any]:
    return catalog_summary(load_catalog())


@app.get("/api/analytics/outbound")
def outbound_stats(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return CLICK_COUNTER.summary()


@app.get("/go/{kind}/{link_id}", include_in_schema=False)
def outbound_redirect(kind: Literal["hotel", "tour", "ticket"], link_id: str, request: Request):
    headers = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}
    purpose = request.headers.get("sec-purpose", "") + " " + request.headers.get("purpose", "")
    if "prefetch" in purpose.lower() or "prerender" in purpose.lower():
        return Response(status_code=204, headers=headers)
    if kind == "hotel":
        rows = load_catalog()["offers"]
    elif kind == "tour":
        rows = load_tours_catalog()["tours"]
    else:
        rows = load_ticket_catalog()["offers"]
    for row in rows:
        target = destination(kind, row)
        if target and target[0] == link_id:
            try:
                CLICK_COUNTER.record(kind, target)
            except (OSError, sqlite3.Error):
                LOGGER.exception("Unable to record outbound click")
            return RedirectResponse(target[-1], status_code=302, headers=headers)
    raise HTTPException(status_code=404, detail="This provider link is no longer in the catalog.")


@app.get("/api/search")
def search(
    request: Request,
    q: str = Query(default="", max_length=200, description="Persian or English search, e.g. هتل پنج ستاره مشهد زیر ۳ میلیون"),
    city: str | None = Query(default=None, max_length=60),
    stars: int | None = Query(default=None, ge=1, le=5),
    min_stars: int | None = Query(default=None, ge=1, le=5),
    max_price_toman: int | None = Query(default=None, gt=0),
    max_price: int | None = Query(default=None, gt=0, description="Alias of max_price_toman"),
    has_tours: bool | None = Query(default=None, description="Show only hotels with a verified linked tour"),
    sort: Literal["best", "recommended", "best_price", "price", "price_asc", "stars", "stars_desc", "provider_count", "providers", "providers_desc"] = "best",
    limit: int = Query(default=200, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    catalog = load_catalog()
    try:
        tour_counts = linked_tour_counts(load_tours_catalog()["tours"], catalog["offers"])
    except HTTPException:
        tour_counts = None
    plan, interpretation_source = _query_plan(q, "hotels")
    effective_sort = sort if "sort" in request.query_params or plan is None else plan.get("sort") or sort
    result = search_catalog(
        catalog["offers"], q,
        city=city,
        stars=stars,
        min_stars=min_stars,
        max_price_toman=max_price_toman if max_price_toman is not None else max_price,
        has_tours=has_tours,
        tour_counts=tour_counts,
        sort=effective_sort,
        limit=limit,
        offset=offset,
        plan=plan,
    )
    if result["parsed_intent"]["has_tours"] and tour_counts is None:
        raise HTTPException(status_code=503, detail="Tour catalog is unavailable for this hotel filter")
    result["interpretation_source"] = interpretation_source
    result["data_as_of"] = catalog.get("generated_at")
    result["source_type"] = "public_provider_pages"
    for hotel in result["hotels"]:
        for offer in hotel["offers"]:
            offer["outbound_url"] = cta_url("hotel", offer)
    return result


def _tour_response(
    *,
    q: str = "",
    departure_city: str | None = None,
    destination_city: str | None = None,
    hotel_id: str | None = None,
    hotel_name: str | None = None,
    hotel_key: str | None = None,
    departure_date: str | None = None,
    departure_from: str | None = None,
    hotel_checkin_date: str | None = None,
    service: str | None = None,
    transport: str | None = None,
    max_price_toman: int | None = None,
    sort: str = "best",
    limit: int = 200,
    plan: dict[str, Any] | None = None,
    interpretation_source: str = "deterministic",
) -> dict[str, Any]:
    tours = load_tours_catalog()
    hotels = load_catalog()
    result = search_tours(
        tours["tours"], hotels["offers"], q,
        departure_city=departure_city,
        destination_city=destination_city,
        hotel_id=hotel_id,
        hotel_name=hotel_name,
        hotel_key=hotel_key,
        departure_date=departure_date,
        departure_from=departure_from,
        hotel_checkin_date=hotel_checkin_date,
        service=service,
        transport=transport,
        max_price_toman=max_price_toman,
        sort=sort,
        limit=limit,
        plan=plan,
    )
    result["interpretation_source"] = interpretation_source
    result["data_as_of"] = tours.get("generated_at")
    result["source_type"] = "public_provider_pages"
    for tour in result["tours"]:
        tour["outbound_url"] = cta_url("tour", tour)
    return result


@app.get("/api/tours")
def tours_search(
    request: Request,
    q: str = Query(default="", max_length=200),
    departure_city: str | None = Query(default=None, max_length=60),
    destination_city: str | None = Query(default=None, max_length=60),
    hotel_id: str | None = Query(default=None, max_length=180),
    hotel_name: str | None = Query(default=None, max_length=180),
    hotel_key: str | None = Query(default=None, max_length=240),
    departure_date: str | None = Query(default=None, max_length=20, description="Exact Jalali departure date"),
    departure_from: str | None = Query(default=None, max_length=20, description="Earliest Jalali departure date"),
    hotel_checkin_date: str | None = Query(default=None, max_length=20, description="Exact Jalali hotel arrival date"),
    service: str | None = Query(default=None, max_length=100),
    transport: Literal["flight", "train", "bus", "unknown"] | None = None,
    max_price_toman: int | None = Query(default=None, gt=0),
    max_price: int | None = Query(default=None, gt=0),
    sort: Literal["best", "recommended", "price", "best_price", "price_asc", "departure", "departure_asc", "hotel_stars", "stars"] = "best",
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    plan, interpretation_source = _query_plan(q, "tours")
    effective_sort = sort if "sort" in request.query_params or plan is None else plan.get("sort") or sort
    return _tour_response(
        q=q, departure_city=departure_city, destination_city=destination_city,
        hotel_id=hotel_id, hotel_name=hotel_name, hotel_key=hotel_key,
        departure_date=departure_date, departure_from=departure_from,
        hotel_checkin_date=hotel_checkin_date, service=service, transport=transport,
        max_price_toman=max_price_toman if max_price_toman is not None else max_price,
        sort=effective_sort, limit=limit,
        plan=plan, interpretation_source=interpretation_source,
    )


@app.get("/api/hotel-tours")
def hotel_tours(
    hotel_id: str = Query(min_length=1, max_length=180),
    limit: int = Query(default=200, ge=1, le=500),
) -> dict[str, Any]:
    return _tour_response(hotel_id=hotel_id, limit=limit)


if DIST_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def frontend(full_path: str):
        file_path = DIST_DIR / full_path
        if full_path and file_path.is_file() and file_path.resolve().is_relative_to(DIST_DIR.resolve()):
            return FileResponse(file_path)
        return FileResponse(DIST_DIR / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def index() -> dict[str, str]:
        return {"message": "Frontend has not been built yet. API documentation: /docs"}
