# ShabSanj — Iranian hotel, tour, and ticket comparison

ShabSanj explores **"Torob for domestic hotel stays"**: identify the same hotel across booking sites, put observed listing prices beside one another, and explain what a traveller is actually comparing. It is an independent local prototype for Torob's [AI Product Engineer challenge](https://jobs.torob.com/ai-product-engineer), not a Torob service or a booking agent.

## Start with Docker

Install Docker with Compose, then run from the repository root.

```bash
docker compose up --build -d
```

Open [ShabSanj](http://localhost:8765). Hotel results appear on first load. The tours tab loads the included packages, and the tickets tab provides the included routes after you choose your departure city. All three datasets ship with the repository and image. Startup fills a fresh named volume with them, and later restarts preserve refreshed catalogs and click counts. Source timestamps identify the age of the observations. The first launch requires no provider crawl.

**OpenRouter is optional and unconfigured by default.** The app displays a Persian notice when its key is missing. Filters and local phrase parsing work immediately. To use AI search, copy `.env.example` to a local `.env`, supply your own key, and recreate the container. Model requests can spend your OpenRouter credits.

```bash
cp .env.example .env
# Edit .env locally, then apply the runtime configuration.
docker compose up -d
```

The key is read by the Python server at runtime. `.env`, private key files, analytics databases, and logs are excluded from Git and Docker build context. The public configuration endpoint returns only whether a key is configured. You can also mount a private file read-only and set `OPENROUTER_API_KEY_FILE` to its container path using your own Compose override.

The local port defaults to 8765. Set `PORT=8766` in `.env` if that port is occupied. View container status or refresh the persistent catalogs with these commands.

```bash
docker compose ps
docker compose logs --tail=50 app
docker compose exec app python -m backend.crawl
docker compose exec app python -m backend.crawl_tours
docker compose exec app python -m backend.crawl_tickets
docker compose down
```

`docker compose down` preserves the data volume. The macOS scheduled refresh documented below applies to the native launcher. Container refresh commands operate on the Docker volume.

## Why hotels

Torob already compares retail goods across millions of products and more than 100,000 online shops. Its current [home-page category menu](https://torob.com/) covers consumer goods, groceries, vehicle goods, health products, building equipment and industrial products, but does not show a hotel-booking category. This is a category-menu audit as of **5 November 2026**, not a claim that Torob has never indexed a travel-related item. [Torob's description of its catalog and shop model](https://torob.com/pages/about-us/).

Hotel search has multiple booking providers, changing rates, and offers that can look alike while having different room types or terms. Alibaba's own [1404 travel report](https://www.alibaba.ir/1404report) says its platform supplied **12,472,971 travel services** across all its travel categories, offered **4,771 domestic and international hotels**, and had **270,573,901 site/app visits** during that year. These are one company's disclosed operating figures, not the size of Iran's hotel market. [Original report PDF](https://cdn.alibaba.ir/ostorage/tour-statics/reports/AlibabaYearlyReport1404.pdf). Another booking provider, [Eghamat24](https://www.eghamat24.com/), lists domestic hotels and accommodation by city, including Tehran.

## What the comparison means

The useful comparison unit for a bookable product is a **hotel for a specified stay**, with a provider offer attached. Hotel identity can be matched from normalized names and locations; rate comparison also needs check-in and check-out dates, party size, room and bed type, meals, cancellation policy, taxes, and payment terms. The current prototype does **not** have enough information to establish equivalent bookable rates. A lower headline price is not necessarily the lower price for an equivalent stay.

The app shows published starting rates with their source and capture time. A Tournegar rate may average the nights in a stay package. Check the provider for dates, room details, availability, terms, and the final booking price.

The hotel catalog covers Tehran, Mashhad, Kish, Rasht, Bandar Anzali, Lahijan, Astara, Ramsar, Chalus, and Nowshahr. The crawler reads public listings from Tournegar, Tikhotel, IranHotelOnline, Snapptrip, and Asa Safar. Snapptrip observations include the room type when shown. Asa Safar observations are starting prices from the Kish listing. [Rasht on Tikhotel](https://tikhotel.com/hotels/iran/rasht) · [Kish on Snapptrip](https://www.snapptrip.com/رزرو-هتل/کیش) · [Kish on Asa Safar](https://www.asasafar.com/fa/رزرو_هتل_در/هرمزگان/کیش)

The bundled snapshot contains **520 rates across 331 hotel groups** from 33 public listings. A seaside search brings one recommended hotel from each matching city to the top. Sorting by price keeps the lowest published nightly prices first.

## What works in the demo

- Search Persian phrases such as `هتل‌های گیلان`, `می‌خوام برم کنار دریا`, or `هتل کنار دریا تا ۸ میلیون`. The results show the interpreted destination and budget. Coastal searches use destination cities and the provider confirms the hotel's distance from the water.
- Filter by city, minimum star rating, observed price ceiling, or **دارای تور** to see hotels linked to at least one cataloged tour. Sort by recommendation, lowest observed price, provider count or star rating.
- Open a hotel to see its source-specific observations, price notes, published photos where available, and outbound links. The browser loads photos from their published URLs. Select up to three hotels for a side-by-side property comparison.
- Open **نقشهٔ هتل** to see the property's published coordinates when available, or its approximate city center. **نقشهٔ مسیر** shows the origin and destination of a tour with a schematic line. The overview works offline and uses a public-domain [Natural Earth outline](https://www.naturalearthdata.com/about/terms-of-use/).
- View the catalog's last observation time and the explanation of how the result matched the search.
- Open the **تورها** tab and filter packages by departure city, destination, hotel, published dates, and included services. A hotel's detail view lists packages matched to that property, with the original provider link and published inclusions.

## Tour data

The tour crawler reads Tournegar's public routes and selected package details, plus Snapptrip's public Kish routes from Tehran, Mashhad, and Shiraz. It keeps the origin, destination, hotel, transport, published services, and price basis for each package. Hotel check-in and departure dates appear separately when available. Snapptrip cards preserve both the published per-person rate and the total for two travelers. Their booking buttons lead to the provider's route results. [Tournegar Rasht to Kish](https://tournegar.com/tours/kish-rasht) · [Snapptrip Tehran to Kish](https://www.snapptrip.com/tour/THR/KIH)

The bundled tour snapshot contains **250 options** across two providers, including 100 Kish flights and 30 Rasht packages. The coastal tour search currently returns Kish packages. The hotel search covers Kish and the included Caspian cities.

The API provides `GET /api/tours` for filtering the tour catalog and `GET /api/hotel-tours?hotel_id=…` for a particular property. The hotel and tour snapshots refresh independently.

## Semantic search

With an OpenRouter key on the server, the API sends the search phrase to OpenRouter and requires a function call that returns typed filters. Hotel queries can specify the hotel name, cities or region, coast, star rating, budget, whether the hotel has linked tours, and sort order. Tour queries also support origin, destination, explicit Jalali travel dates, transport, and included services. The API validates the result and applies it to the local catalog. A filter set explicitly in the UI takes precedence. If the model is unavailable or its response is invalid, the local parser interprets the request. [OpenRouter tool calling](https://openrouter.ai/blog/tutorials/tool-calling/).

## Outbound clicks

Open **آمار کلیک‌ها** in the header to see totals by hotel or tour, provider, and outbound link. The booking buttons use a tracked redirect that keeps the provider's original route and query parameters. The aggregate counter stores link details and counts in `data/analytics.sqlite3`. It survives app restarts and includes repeat clicks. The API exposes `GET /api/analytics/outbound`. Set `SHABSANJ_ANALYTICS_DB` to a path on a persistent volume for a container deployment.

## Ticket comparison

Choose a departure city in **بلیط‌ها** or the **بلیط سفر** section of a hotel. The same browser remembers that city for both views. Changing the departure city updates the saved preference.

Open **بلیط‌ها** and choose an origin, destination, and optionally a departure date or transport mode. From a hotel's details, **بلیط سفر** opens the same comparison with the hotel's city as the destination. The crawler reads dated bus fares and seats from Redbilit and Safar724, public flight calendars and departure listings from Rahig and TikoTrip, and dated train fares and published capacity from Fadak. Safar724 checks up to eight days per core route. Redbilit prioritizes dates on shared routes and stops requests to its host for the current refresh if it is rate-limited. Fadak serves fares across the dates its route pages publish. MrBilit, OrientTrips, and TikoTrip rail pages provide seller links for checking prices. [Safar724 buses](https://safar724.com/bus/tehran-mashhad) · [Redbilit buses](https://redbilit.com/bus) · [Rahig flights](https://rahig.com/flights/THR-KIH) · [TikoTrip flights](https://tikotrip.com/flights/tehran-kish) · [Fadak trains](https://www.fadaktrains.com/train/mashhad/tehran-mashhad)

Each group shows the lowest observed one-way adult fare per seller for the same route, day, and transport mode. Departures from different sellers can have different operators, times, and classes. Flexible-date starting prices appear separately. The date picker lists every collected date and labels the days with recent fares from multiple sellers. Expand **دیدن حرکت‌های ثبت‌شده** to see the recorded departures for that day, including times, terminals, class, duration, and seat counts where the source publishes them. Each row shows its observation time. Dated observations over 12 hours old or retained after a failed check stay labeled as older observations and are left out of the recent comparison and seat display. Public route links without a comparable fare appear under the seller links. Ticket links use the same click counter as hotels and tours.

For a city without its own passenger airport, flight searches use the provincial capital's airport. Bandar Anzali, Lahijan, and Astara use Rasht. Chalus uses Sari. The results show the airport and the ground leg separately. Cities with their own airports, including Kish, Ramsar, and Nowshahr, keep them. Bus and train searches use the selected cities. [Iran AIM aerodrome documents](https://oibk.ir/aip) · [Visit Iran on Gilan](https://visitiran.ir/fa/province/استان-گیلان) · [Visit Iran on Chalus](https://visitiran.ir/fa/destination/چالوس)

Refresh `data/tickets.json` with `./run.sh refresh-tickets`. Use `./run.sh refresh-tickets --mode bus --mode train` to refresh ground transport while keeping the flight snapshot. The API offers `GET /api/tickets/routes` and `GET /api/tickets?origin=tehran&destination=mashhad`, with optional `date` (ISO YYYY-MM-DD) and `mode` (`flight`, `bus`, or `train`).

On macOS, the local refresh runs at 00:00, 06:00, 12:00, and 18:00 in the Mac's timezone while signed in. It also runs when the scheduler is loaded and catches up once after sleep. The web app can be closed during refreshes. Manual and scheduled runs use the same lock and replace the ticket snapshot atomically. Logs are in `~/Library/Logs/ShabSanj/`.

```bash
./run.sh schedule-tickets install
./run.sh schedule-tickets status
./run.sh schedule-tickets remove
```

## Run locally

Use Python 3.12 or newer and Node.js 22 or newer. Start the prototype from this directory.

```bash
./run.sh
```

Open **http://127.0.0.1:8765**. The launcher builds the React app and serves it with the API. The included snapshot makes the first run independent of provider availability. Refresh it with the following command.

```bash
./run.sh refresh
./run.sh refresh-tours
./run.sh refresh-tickets
```

Refresh only the new hotel sources while preserving the other providers' observations.

```bash
./run.sh refresh --provider snapptrip --provider asasafar
```

To enable the model, set the server's `OPENROUTER_API_KEY` or point the launcher at a private key file outside the project.

```bash
OPENROUTER_API_KEY_FILE=/absolute/path/to/private-key-file ./run.sh
```

The default model is `google/gemini-3.1-flash-lite`. Set `OPENROUTER_MODEL` to select another model with named function calling. Configured model requests may use OpenRouter credits.

If a provider page fails during refresh, the crawler retains its last successful observations and their original timestamps. Use `PORT=9000 ./run.sh` to choose another port.

You can also build and start the image directly with a persistent data volume.

```bash
docker build -t shabsanj .
docker run --rm -p 127.0.0.1:8765:8765 -v shabsanj-data:/app/data shabsanj
```

Run the backend tests with `.venv/bin/python -m unittest discover` after starting the app once.

The frontend is React/Vite in `frontend/`; the Python API, public-page adapters and search logic live in `backend/`. The search accepts Persian hotel, city, star and budget phrases and offers explicit city, minimum-star and indicative-price filters. The refresh path uses the same collector that can be run as a Python module; see `python -m backend.crawl --help` for its supported flags once dependencies are installed.

The API exposes `GET /api/search`, `GET /api/catalog/summary`, and `GET /api/health`. The collector checks each provider's `robots.txt` before requesting its public city page and writes timestamped observations to `data/catalog.json`. Hotel grouping uses checked cross-provider identities and keeps uncertain matches separate.

The included `data/catalog.json` and `data/tours.json` snapshots record each source page, fetch outcome, and individual provider link.

## What to show in the application demo

The [challenge](https://jobs.torob.com/ai-product-engineer) asks for a market X, an AI-assisted product build, and a video of **at most five minutes** that explains the problem, product and key decisions. [DEMO.md](DEMO.md) is a timed walkthrough. The challenge asks applicants to submit their own project and video links; this repository does not submit an application.

## Limits and next steps

- Provider pages may block automated requests or change markup. A missing provider observation does not mean the provider has no offer.
- Public snippets may omit the exact date, room or cancellation terms. The interface must preserve an “unverified/indicative” state instead of presenting those snippets as bookable inventory.
- A production version would need provider agreements or reliable APIs for date-specific availability, total price and booking handoff, plus monitoring for stale and mismatched offers.
