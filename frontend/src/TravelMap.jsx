import React, { useId, useMemo, useRef, useState } from 'react';
import { ArrowUpLeft, BedDouble, LocateFixed, MapPin, Minus, Plus, Route } from 'lucide-react';
import './map.css';

const WIDTH = 800;
const HEIGHT = 580;
const INITIAL_VIEW = { x: 0, y: 0, w: WIDTH, h: HEIGHT };

// Approximate centers for tour endpoints and hotels without published pins.
const CITIES = {
  tehran: { label: 'تهران', lat: 35.689, lon: 51.389 },
  mashhad: { label: 'مشهد', lat: 36.261, lon: 59.617 },
  isfahan: { label: 'اصفهان', lat: 32.655, lon: 51.668 },
  shiraz: { label: 'شیراز', lat: 29.592, lon: 52.584 },
  kish: { label: 'کیش', lat: 26.532, lon: 53.972 },
  rasht: { label: 'رشت', lat: 37.281, lon: 49.583 },
  bandar_anzali: { label: 'بندر انزلی', lat: 37.473, lon: 49.462 },
  lahijan: { label: 'لاهیجان', lat: 37.207, lon: 50.003 },
  astara: { label: 'آستارا', lat: 38.430, lon: 48.872 },
  ramsar: { label: 'رامسر', lat: 36.902, lon: 50.679 },
  chalus: { label: 'چالوس', lat: 36.655, lon: 51.420 },
  nowshahr: { label: 'نوشهر', lat: 36.649, lon: 51.497 },
};

const CITY_LOOKUP = Object.fromEntries(
  Object.entries(CITIES).flatMap(([id, city]) => [
    [id, id], [id.replaceAll('_', ' '), id],
    [city.label, id], [city.label.replaceAll(' ', ''), id],
  ]),
);

// Natural Earth Admin 0 countries, 1:110m, Iran polygon. Public domain.
// https://www.naturalearthdata.com/about/terms-of-use/
// https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_admin_0_countries.geojson
const IRAN_OUTLINE = [
  [48.568, 29.927], [48.015, 30.452], [48.005, 30.985], [47.685, 30.985],
  [47.849, 31.709], [47.335, 32.469], [46.109, 33.017], [45.417, 33.968],
  [45.648, 34.748], [46.152, 35.093], [46.076, 35.677], [45.421, 35.978],
  [44.773, 37.170], [44.226, 37.972], [44.421, 38.281], [44.109, 39.428],
  [44.794, 39.713], [44.953, 39.336], [45.458, 38.874], [46.144, 38.741],
  [46.506, 38.771], [47.685, 39.508], [48.060, 39.582], [48.356, 39.289],
  [48.011, 38.794], [48.634, 38.270], [48.883, 38.320], [49.200, 37.583],
  [50.148, 37.375], [50.842, 36.873], [52.264, 36.700], [53.826, 36.965],
  [53.922, 37.199], [54.800, 37.392], [55.512, 37.964], [56.180, 37.935],
  [56.619, 38.121], [57.330, 38.029], [58.436, 37.522], [59.235, 37.413],
  [60.378, 36.527], [61.123, 36.492], [61.211, 35.650], [60.803, 34.404],
  [60.528, 33.676], [60.964, 33.529], [60.536, 32.981], [60.864, 32.183],
  [60.942, 31.548], [61.699, 31.380], [61.781, 30.736], [60.874, 29.829],
  [61.369, 29.303], [61.772, 28.699], [62.728, 28.260], [62.755, 27.379],
  [63.234, 27.217], [63.317, 26.757], [61.874, 26.240], [61.497, 25.078],
  [59.616, 25.380], [58.526, 25.610], [57.397, 25.740], [56.971, 26.966],
  [56.492, 27.143], [55.724, 26.965], [54.715, 26.481], [53.493, 26.812],
  [52.484, 27.581], [51.521, 27.866], [50.853, 28.815], [50.115, 30.148],
  [49.577, 29.986], [48.941, 30.317], [48.568, 29.927],
];

function project({ lon, lat }) {
  return { x: 50 + (lon - 43) * 34, y: 35 + (40.5 - lat) * 30 };
}

const OUTLINE_PATH = IRAN_OUTLINE.map(([lon, lat], index) => {
  const { x, y } = project({ lon, lat });
  return `${index ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`;
}).join(' ') + ' Z';

function cityId(value) {
  if (typeof value !== 'string') return null;
  const normalized = value.trim().replace(/\s+/g, ' ');
  return CITY_LOOKUP[normalized] || CITY_LOOKUP[normalized.replaceAll(' ', '')] || null;
}

function clampView(next) {
  const w = Math.max(250, Math.min(WIDTH, next.w));
  const h = w * HEIGHT / WIDTH;
  return {
    x: Math.max(0, Math.min(WIDTH - w, next.x)),
    y: Math.max(0, Math.min(HEIGHT - h, next.y)),
    w, h,
  };
}

function routePath(origin, destination) {
  const start = project(origin);
  const end = project(destination);
  const distance = Math.hypot(end.x - start.x, end.y - start.y);
  const lift = Math.min(80, Math.max(28, distance * 0.23));
  return `M ${start.x} ${start.y} Q ${(start.x + end.x) / 2} ${(start.y + end.y) / 2 - lift} ${end.x} ${end.y}`;
}

/**
 * Offline vector map for a hotel city or a tour's origin/destination.
 *
 * Usage: <TravelMap hotel={hotel} /> or <TravelMap tour={tour} />.
 * A provider's property pin takes precedence over the approximate city center.
 */
export function TravelMap({ hotel = null, tour = null, className = '' }) {
  const reactId = useId().replace(/:/g, '');
  const [view, setView] = useState(INITIAL_VIEW);
  const [focusedCity, setFocusedCity] = useState(null);
  const pointer = useRef(null);
  const originId = cityId(tour?.departure_city || tour?.departure_city_label);
  const destinationId = cityId(tour?.destination_city || tour?.destination_city_label || hotel?.city_id || hotel?.city);
  const activeId = focusedCity || destinationId || originId;
  const isTour = Boolean(tour);
  const hotelName = hotel?.name || tour?.hotel?.name || tour?.hotel_name || null;
  const location = hotel?.location || tour?.hotel?.location;
  const property = destinationId && location?.accuracy === 'property'
    && Number.isFinite(location.latitude) && Number.isFinite(location.longitude)
    ? { lat: location.latitude, lon: location.longitude }
    : null;
  const selectedProperty = property && activeId === destinationId;
  const propertyMapUrl = property
    ? `https://www.openstreetmap.org/?mlat=${property.lat}&mlon=${property.lon}#map=17/${property.lat}/${property.lon}`
    : null;
  const origin = originId ? CITIES[originId] : null;
  const destination = destinationId ? CITIES[destinationId] : null;
  const selected = activeId ? CITIES[activeId] : null;
  const route = isTour && origin && destination && originId !== destinationId
    ? routePath(origin, property || destination)
    : null;
  const gradientId = `travel-map-land-${reactId}`;
  const arrowId = `travel-map-arrow-${reactId}`;
  const mapLabel = isTour
    ? `نقشهٔ شماتیک مسیر ${origin?.label || 'مبدأ نامشخص'} به ${destination?.label || 'مقصد نامشخص'}`
    : property ? `موقعیت ${hotelName || 'هتل'} روی نقشه` : `نقشهٔ موقعیت شهری ${destination?.label || 'هتل'}`;

  const markers = useMemo(() => Object.entries(CITIES).map(([id, city]) => {
    const point = id === destinationId && property ? property : city;
    return { id, ...city, ...project(point) };
  }), [destinationId, property?.lat, property?.lon]);

  function zoom(factor) {
    setView((current) => {
      const w = Math.max(250, Math.min(WIDTH, current.w * factor));
      const h = w * HEIGHT / WIDTH;
      const focus = current.w === WIDTH && factor < 1 ? markers.find((marker) => marker.id === activeId) : null;
      return clampView({
        x: focus ? focus.x - w / 2 : current.x + (current.w - w) / 2,
        y: focus ? focus.y - h / 2 : current.y + (current.h - h) / 2,
        w, h,
      });
    });
  }

  function pointerDown(event) {
    if (event.button !== 0 || event.target.closest('[data-city-marker]')) return;
    pointer.current = { id: event.pointerId, x: event.clientX, y: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function pointerMove(event) {
    if (!pointer.current || pointer.current.id !== event.pointerId) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const dx = event.clientX - pointer.current.x;
    const dy = event.clientY - pointer.current.y;
    pointer.current = { ...pointer.current, x: event.clientX, y: event.clientY };
    setView((current) => clampView({
      ...current,
      x: current.x - dx * current.w / rect.width,
      y: current.y - dy * current.h / rect.height,
    }));
  }

  function pointerUp(event) {
    if (pointer.current?.id !== event.pointerId) return;
    pointer.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  return <section className={`travel-map ${className}`.trim()} dir="rtl" aria-label={mapLabel}>
    <div className="travel-map-head">
      <div className="travel-map-heading">
        <span className="travel-map-heading-icon">{isTour ? <Route size={19} /> : <MapPin size={19} />}</span>
        <div>
          <h3>{isTour ? 'مسیر تور روی نقشه' : 'موقعیت هتل روی نقشه'}</h3>
          <p>{isTour && origin && destination ? `${origin.label} ← ${destination.label}` : destination ? destination.label : 'موقعیت شهری در دسترس نیست'}</p>
        </div>
      </div>
      <div className="travel-map-controls" aria-label="کنترل نقشه">
        <button type="button" onClick={() => zoom(0.75)} disabled={view.w <= 251} aria-label="بزرگ‌نمایی نقشه"><Plus size={16} /></button>
        <button type="button" onClick={() => zoom(1.34)} disabled={view.w >= WIDTH - 1} aria-label="کوچک‌نمایی نقشه"><Minus size={16} /></button>
        <button type="button" onClick={() => setView(INITIAL_VIEW)} disabled={view.w >= WIDTH - 1} aria-label="بازنشانی نقشه"><LocateFixed size={16} /></button>
      </div>
    </div>

    <div className="travel-map-frame">
      <svg
        className="travel-map-svg"
        viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
        role="img"
        aria-label={mapLabel}
        onPointerDown={pointerDown}
        onPointerMove={pointerMove}
        onPointerUp={pointerUp}
        onPointerCancel={pointerUp}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            <stop stopColor="#f1e9d8" />
            <stop offset="1" stopColor="#dce9d9" />
          </linearGradient>
          <marker id={arrowId} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse">
            <path d="M1 1 L7 4 L1 7" fill="none" stroke="#a51b39" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </marker>
        </defs>
        <rect width={WIDTH} height={HEIGHT} fill="#eaf2f3" />
        <g className="travel-map-grid" aria-hidden="true">
          {[120, 240, 360, 480, 600, 720].map((x) => <path key={x} d={`M${x} 0V${HEIGHT}`} />)}
          {[110, 220, 330, 440, 550].map((y) => <path key={y} d={`M0 ${y}H${WIDTH}`} />)}
        </g>
        <path className="travel-map-land-shadow" d={OUTLINE_PATH} />
        <path className="travel-map-land" d={OUTLINE_PATH} fill={`url(#${gradientId})`} />
        <ellipse className="travel-map-island" cx={project(CITIES.kish).x} cy={project(CITIES.kish).y} rx="8" ry="4" />
        <text className="travel-map-water-label" x="329" y="533">خلیج فارس</text>
        <text className="travel-map-water-label" x="305" y="113">دریای خزر</text>
        {route && <>
          <path className="travel-map-route-glow" d={route} />
          <path className="travel-map-route" d={route} markerEnd={`url(#${arrowId})`} />
        </>}
        {markers.map((marker) => {
          const highlighted = marker.id === originId || marker.id === destinationId;
          const isSelected = marker.id === activeId;
          return <g
            key={marker.id}
            data-city-marker
            className={`travel-map-marker${highlighted ? ' is-highlighted' : ''}${isSelected ? ' is-selected' : ''}`}
            transform={`translate(${marker.x} ${marker.y})`}
            role="button"
            tabIndex={0}
            aria-label={`نمایش ${marker.id === destinationId && property ? hotelName : marker.label}`}
            onClick={() => setFocusedCity(marker.id)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                setFocusedCity(marker.id);
              }
            }}
          >
            <title>{marker.label}{marker.id === destinationId && hotelName ? `، ${hotelName}` : ''}</title>
            <circle className="travel-map-marker-halo" r={highlighted ? 14 : 9} />
            <circle className="travel-map-marker-core" r={highlighted ? 6 : 3.5} />
            {highlighted && <text y="-18" textAnchor="middle">{marker.label}</text>}
          </g>;
        })}
      </svg>
      <span className="travel-map-compass" aria-hidden="true">شمال ↑</span>
    </div>

    <div className="travel-map-details">
      <div className="travel-map-place">
        <span className="travel-map-place-dot" />
        <div><strong>{selectedProperty ? hotelName : selected?.label || 'شهر نامشخص'}</strong>
          <small>{selected
            ? selectedProperty ? `${destination.label} · مختصات منتشرشده در اسنپ‌تریپ`
              : selected === destination && hotelName ? `${hotelName} · نشان در مرکز شهر`
              : selected === origin && isTour ? 'شهر مبدأ تور'
                : selected === destination && isTour ? 'شهر مقصد تور'
                  : 'مرکز تقریبی شهر'
            : 'برای این شهر مختصات ثبت نشده است.'}</small></div>
      </div>
      {selectedProperty ? <a className="travel-map-street" href={propertyMapUrl} target="_blank" rel="noopener noreferrer">نقشهٔ خیابان‌ها <ArrowUpLeft size={14} /></a>
        : hotelName && activeId === destinationId && <BedDouble size={18} aria-hidden="true" />}
    </div>
    <p className="travel-map-note">
      {isTour ? 'خط شماتیک، مبدأ و مقصد را به هم وصل می‌کند. ' : ''}
      {property ? 'موقعیت هتل از مختصات منتشرشدهٔ ارائه‌دهنده گرفته شده است.' : 'نشان هتل مرکز تقریبی شهر را نشان می‌دهد.'}
      {' '}طرح مرزها از <a href="https://www.naturalearthdata.com/about/terms-of-use/" target="_blank" rel="noopener noreferrer">Natural Earth</a>.
    </p>
  </section>;
}

export default TravelMap;
