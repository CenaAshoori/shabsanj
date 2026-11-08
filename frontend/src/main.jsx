import React, { useEffect, useId, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ArrowDown, ArrowDownUp, ArrowLeft, ArrowUpLeft, BedDouble, Building2,
  Check, ChevronLeft, CircleHelp, Database, Filter, Globe2, Layers3, MapPin,
  MousePointer2, RefreshCw, Route, Search, ShieldCheck, Sparkles, Star, Ticket, X,
} from 'lucide-react';
import '@fontsource-variable/vazirmatn';
import { Tours } from './Tours.jsx';
import { Tickets } from './Tickets.jsx';
import { DestinationIntent } from './DestinationIntent.jsx';
import { TravelMapPanel } from './TravelMapPanel.jsx';
import './style.css';

const number = new Intl.NumberFormat('fa-IR');
const money = (value) => Number.isFinite(value) ? number.format(value) : '—';
const dateText = (value) => {
  if (typeof value === 'string' && /^1[34]\d\d\/\d\d\/\d\d$/.test(value)) {
    return value.replace(/\d/g, (digit) => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]);
  }
  const date = new Date(value);
  return value && !Number.isNaN(+date)
    ? new Intl.DateTimeFormat('fa-IR', { dateStyle: 'medium', timeZone: 'Asia/Tehran' }).format(date)
    : '—';
};
const defaults = { city: '', min_stars: '', max_price: '', has_tours: '', sort: '' };
const starters = ['هتل کیش', 'هتل‌های گیلان', 'می‌خوام برم کنار دریا'];
const pageSize = 12;
const currentView = () => ({ '#tours': 'tours', '#tickets': 'tickets' })[window.location.hash] || 'hotels';
const departureCityKey = 'shabsanj.departure-city.v1';
const clickKindLabels = { hotel: 'هتل', tour: 'تور', ticket: 'بلیط' };
const providerNames = {
  tournegar: 'تورنگار', tikhotel: 'تیک‌هتل', iranhotelonline: 'ایران هتل آنلاین',
  snapptrip: 'اسنپ‌تریپ', asasafar: 'آسا سفر',
};
const providerName = (offer) => offer.provider_name || providerNames[offer.provider] || offer.provider;
const sourceUrl = (offer) => offer.source_url || offer.url;
const nightlyPrice = (offer) => offer?.price_per_night_toman ?? offer?.price_toman;
const priceLabel = (offer) => {
  if (offer.stay_nights > 1) return 'میانگین هر شبِ بسته';
  if (['nightly', 'per_night'].includes(offer.price_basis)) return 'نرخ اعلام‌شدهٔ یک شب';
  return 'قیمت شروع اعلام‌شده';
};

function hotelSearchParams(query, filters, offset = 0) {
  const params = new URLSearchParams({ q: query, limit: String(pageSize), offset: String(offset) });
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  return params;
}

function Brand() {
  return <a className="brand" href="#" aria-label="شب‌سنج، صفحه اول">
    <span className="brand-mark"><BedDouble size={23} strokeWidth={2.2} /></span>
    <span>شب‌<b>سنج</b><small>مقایسهٔ هتل، تور و بلیط</small></span>
  </a>;
}

function Skyline() {
  return <svg className="skyline" viewBox="0 0 590 295" fill="none" aria-hidden="true">
    <defs>
      <linearGradient id="horizon" x1="0" x2="0" y1="0" y2="1">
        <stop stopColor="#f37572" stopOpacity=".46" /><stop offset="1" stopColor="#9a373c" stopOpacity="0" />
      </linearGradient>
      <linearGradient id="buildings" x1="0" x2="0" y1="0" y2="1">
        <stop stopColor="#a85053" stopOpacity=".82" /><stop offset="1" stopColor="#391e2c" />
      </linearGradient>
      <pattern id="windows" width="12" height="15" patternUnits="userSpaceOnUse">
        <path d="M4 5h3v5H4z" fill="#ffc1a2" opacity=".45"/>
      </pattern>
    </defs>
    <circle cx="339" cy="129" r="97" fill="url(#horizon)" />
    <path d="M363 51a43 43 0 1 0 41 58c-29 9-56-18-41-58Z" fill="#ffd5ae" />
    <g fill="#ffe6ca">
      <circle cx="280" cy="43" r="2"/><circle cx="432" cy="61" r="2"/><circle cx="512" cy="87" r="2"/>
      <circle cx="105" cy="109" r="1.5"/><circle cx="209" cy="87" r="1.5"/><circle cx="468" cy="127" r="1.5"/>
      <path d="M196 39v16m-8-8h16M467 34v12m-6-6h12" stroke="#ffd5ae" strokeWidth="1.5" />
    </g>
    <path d="M10 232 111 154l65 43 82-91 79 88 56-43 151 81Z" fill="#875061" opacity=".26"/>
    <path d="M12 257 136 184l77 42 67-63 62 49 56-34 154 79Z" fill="#be6471" opacity=".18"/>
    <path d="M44 276v-62h37v-24h45v86m9 0v-39h46v-36h28v75m16 0v-64h46v-16h44v80m23 0v-30h26v-41h27v-25h55v96m9 0v-50h40v-27h42v77" fill="url(#buildings)" />
    <path d="M44 276v-62h37v-24h45v86m9 0v-39h46v-36h28v75m16 0v-64h46v-16h44v80m23 0v-30h26v-41h27v-25h55v96m9 0v-50h40v-27h42v77" fill="url(#windows)" />
    <path d="M319 276l7-120h8l6 120zm5-126-7-10 6-11h13l6 11-6 10zm4-22V95h3v33z" fill="#d2918c" />
    <path d="M22 276h526" stroke="#d5928d" opacity=".25" />
  </svg>;
}

function PublishedPhoto({ src, fallback }) {
  const [failedSrc, setFailedSrc] = useState(null);
  if (!src || failedSrc === src) return fallback;
  return <span className="published-photo">
    <img src={src} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer"
      onError={() => setFailedSrc(src)} />
  </span>;
}

function HotelTile({ hotel }) {
  const seed = [...hotel.name].reduce((sum, char) => sum + char.codePointAt(0), 0) % 4;
  return <div className={'hotel-art shade-' + seed} aria-hidden="true">
    <PublishedPhoto src={hotel.image_url} fallback={<>
      <div className="art-orb" /><div className="art-building"><Building2 size={45} strokeWidth={1.25} /></div>
    </>} />
  </div>;
}

function Modal({ title, onClose, children }) {
  const ref = useRef(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return <dialog ref={ref} className="modal" aria-labelledby={titleId} onCancel={onClose} onClick={(event) => {
    if (event.target === event.currentTarget) onClose();
  }}>
    <section className="modal-body">
      <header className="modal-head"><h2 id={titleId}>{title}</h2><button className="icon-button" aria-label="بستن" onClick={onClose}><X size={21} /></button></header>
      {children}
    </section>
  </dialog>;
}

function OfferRows({ hotel }) {
  return <div className="offer-list">
    {hotel.offers.map((offer, index) => <div className="offer-row" key={offer.id || sourceUrl(offer) + index}>
      <div className="offer-provider"><span className="provider-icon" aria-hidden="true">
        <PublishedPhoto src={offer.image_url} fallback={<Globe2 size={17} />} />
      </span>
        <div><strong>{providerName(offer)}</strong><small>{dateText(offer.observed_at)} · {priceLabel(offer)}</small>{offer.room_type && <small>{offer.room_type}</small>}</div>
      </div>
      <div className="offer-cost"><strong>{money(nightlyPrice(offer))} <small>تومان / شب</small></strong>
        {offer.checkin && offer.checkout && <small>{dateText(offer.checkin)} تا {dateText(offer.checkout)}</small>}
      </div>
      {offer.outbound_url && <a className="outline-button" href={offer.outbound_url} target="_blank" rel="noopener noreferrer nofollow">سایت رزرو <ArrowUpLeft size={15} /></a>}
      {offer.price_note && <p className="offer-note">{offer.price_note}</p>}
    </div>)}
  </div>;
}

function HotelCard({ hotel, selected, onCompare, onOpen }) {
  const offer = hotel.best_offer || hotel.offers[0];
  return <article className="hotel-card">
    <HotelTile hotel={hotel} />
    <div className="hotel-info">
      <div className="location"><MapPin size={14} /> {hotel.city}</div>
      <h3><button onClick={onOpen}>{hotel.name}</button></h3>
      <div className="hotel-meta">
        {hotel.stars ? <span className="stars"><Star size={14} fill="currentColor" /> {number.format(hotel.stars)} ستاره</span> : null}
        <span><Layers3 size={14} /> {number.format(hotel.provider_count)} سایت رزرو</span>
        {hotel.tour_count > 0 && <span><Route size={14} /> {number.format(hotel.tour_count)} تور</span>}
      </div>
      <button className={'compare-toggle' + (selected ? ' checked' : '')} onClick={onCompare} aria-pressed={selected}>
        <span>{selected && <Check size={13} />}</span> مقایسهٔ هتل
      </button>
    </div>
    <div className="hotel-price">
      <small>{offer?.stay_nights > 1 ? 'شروع از · میانگین بسته' : 'شروع از · نرخ اعلام‌شده'}</small>
      <strong>{money(nightlyPrice(offer))} <small>تومان / شب</small></strong>
      <button className="primary-button" onClick={onOpen}>مشاهدهٔ نرخ‌ها <ChevronLeft size={16} /></button>
    </div>
  </article>;
}

function ClickStats() {
  const [stats, setStats] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setError(false);
    fetch('/api/analytics/outbound', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('statistics unavailable');
        return response.json();
      })
      .then(setStats)
      .catch((failure) => { if (failure.name !== 'AbortError') setError(true); });
    return () => controller.abort();
  }, [attempt]);

  return <div className="click-stats">
    <div className="stats-intro"><p>تعداد کلیک روی دکمه‌هایی که به سایت رزرو می‌روند.</p>
      <button className="outline-button" onClick={() => setAttempt((current) => current + 1)}><RefreshCw size={14} /> تازه‌سازی</button>
    </div>
    {error && <p className="callout" role="alert">دریافت آمار ممکن نشد.</p>}
    {!stats && !error && <p role="status">در حال دریافت آمار…</p>}
    {stats && <>
      <div className="stats-metrics" aria-live="polite">
        <div><strong>{number.format(stats.total)}</strong><span>کل کلیک‌ها</span></div>
        <div><strong>{number.format(stats.by_kind.hotel)}</strong><span>رزرو هتل</span></div>
        <div><strong>{number.format(stats.by_kind.tour)}</strong><span>رزرو تور</span></div>
        <div><strong>{number.format(stats.by_kind.ticket || 0)}</strong><span>خرید بلیط</span></div>
      </div>
      {stats.total > 0 ? <>
        <h3>به تفکیک ارائه‌دهنده</h3>
        <ul className="stats-list">{stats.providers.map((row) => <li key={row.provider}><span>{row.provider_name}</span><b>{number.format(row.clicks)}</b></li>)}</ul>
        <h3>به تفکیک لینک</h3>
        <ul className="stats-list">{stats.links.map((row) => <li key={row.link_id}><span>{row.title}<small>{row.provider_name} · {clickKindLabels[row.kind]}</small></span><b>{number.format(row.clicks)}</b></li>)}</ul>
      </> : <p className="callout">هنوز کلیکی روی لینک‌های رزرو ثبت نشده است.</p>}
    </>}
  </div>;
}

function App() {
  const [view, setView] = useState(currentView);
  const [departureCity, setDepartureCity] = useState(() => {
    try {
      return window.localStorage.getItem(departureCityKey) || '';
    } catch {
      return '';
    }
  });
  const [draft, setDraft] = useState('');
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState(defaults);
  const [summary, setSummary] = useState(null);
  const [serverConfig, setServerConfig] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [openHotel, setOpenHotel] = useState(null);
  const [compared, setCompared] = useState([]);
  const [showCompare, setShowCompare] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const [showStats, setShowStats] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [notice, setNotice] = useState('');
  const [loadingMore, setLoadingMore] = useState(false);
  const resultsRef = useRef(null);
  const hotelToursRef = useRef(null);
  const hotelTicketsRef = useRef(null);
  const pageRequest = useRef(null);

  useEffect(() => {
    const syncView = () => {
      const next = currentView();
      setView(next);
      if (next !== 'hotels') window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', syncView);
    return () => window.removeEventListener('hashchange', syncView);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/config', { signal: controller.signal })
      .then((response) => response.ok ? response.json() : null)
      .then(setServerConfig).catch(() => {});
    fetch('/api/catalog/summary', { signal: controller.signal })
      .then((response) => response.ok ? response.json() : null)
      .then(setSummary).catch(() => {});
    return () => controller.abort();
  }, [retry]);

  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setError('');
    setLoadingMore(false);
    fetch('/api/search?' + hotelSearchParams(query, filters), { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('دریافت نتیجه‌ها ممکن نشد.');
        return response.json();
      })
      .then(setResult)
      .catch((failure) => { if (failure.name !== 'AbortError') setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => {
      controller.abort();
      pageRequest.current?.abort();
      pageRequest.current = null;
    };
  }, [query, filters, retry]);

  async function loadMoreHotels() {
    if (pageRequest.current || !result) return;
    const controller = new AbortController();
    pageRequest.current = controller;
    setLoadingMore(true);
    try {
      const params = hotelSearchParams(query, filters, result.hotels.length);
      const response = await fetch('/api/search?' + params, { signal: controller.signal });
      if (!response.ok) throw new Error('page unavailable');
      const next = await response.json();
      if (!controller.signal.aborted) setResult((current) => ({ ...next, hotels: [...current.hotels, ...next.hotels] }));
    } catch (failure) {
      if (failure.name !== 'AbortError') setNotice('دریافت هتل‌های بیشتر ممکن نشد.');
    } finally {
      if (pageRequest.current === controller) {
        pageRequest.current = null;
        setLoadingMore(false);
      }
    }
  }

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(''), 2800);
    return () => clearTimeout(timer);
  }, [notice]);

  function search(value) {
    setDraft(value);
    setQuery(value.trim());
    setFilters({ ...defaults });
    resultsRef.current?.scrollIntoView({ behavior: 'smooth' });
  }

  function toggleCompare(hotel) {
    if (compared.some((item) => item.id === hotel.id)) {
      setCompared(compared.filter((item) => item.id !== hotel.id));
    } else if (compared.length < 3) {
      setCompared([...compared, hotel]);
    } else {
      setNotice('برای افزودن هتل جدید، یکی از سه هتل را حذف کنید.');
    }
  }

  const change = (key, value) => setFilters((prev) => ({ ...prev, [key]: value }));
  function changeDepartureCity(city) {
    setDepartureCity(city);
    try {
      if (city) window.localStorage.setItem(departureCityKey, city);
      else window.localStorage.removeItem(departureCityKey);
    } catch {
      // The selected city still works in this session if storage is disabled.
    }
  }
  const hotels = result?.hotels || [];
  const cityList = summary?.cities || [];
  const parsed = result?.parsed_intent || {};
  const budget = parsed.max_price ?? parsed.budget_toman ?? parsed.max_price_toman;
  const stars = parsed.min_stars ?? parsed.stars;
  const snapshotDate = result?.data_as_of || summary?.last_updated;
  const providerCount = summary?.provider_count ?? (Array.isArray(summary?.providers) ? summary.providers.length : undefined);
  const hotelCount = summary?.hotel_count ?? summary?.hotels ?? undefined;

  return <>
    <header className="site-header">
      <div className="container header-inner">
        <Brand />
        <nav aria-label="ناوبری">
          <a href="#" aria-current={view === 'hotels' ? 'page' : undefined}>هتل‌ها</a>
          <a href="#tours" aria-current={view === 'tours' ? 'page' : undefined}>تورها</a>
          <a href="#tickets" aria-current={view === 'tickets' ? 'page' : undefined}>بلیط‌ها</a>
          <button className="nav-stats" onClick={() => setShowStats(true)}><MousePointer2 size={14} /> آمار کلیک‌ها</button>
          <button className="nav-guide" onClick={() => setShowGuide(true)}>راهنمای قیمت</button>
        </nav>
        <span className="prototype"><span /> نمونهٔ تعاملی</span>
      </div>
    </header>

    {serverConfig?.openrouter_configured === false && <div className="container ai-config-notice" role="status">
      <CircleHelp size={17} />
      <span>کلید OpenRouter تنظیم نشده است. جست‌وجو با فیلترها و پردازش محلی فعال است.</span>
    </div>}

    {view === 'tours' ? <main className="container tours-page" id="tours"><Tours dateText={dateText} /></main>
      : view === 'tickets' ? <main className="container tickets-page" id="tickets">
        <Tickets dateText={dateText} departureCity={departureCity} onDepartureChange={changeDepartureCity} />
      </main> : <main className="container">
      <section className="hero" aria-labelledby="page-title">
        <Skyline />
        <div className="hero-content">
          <span className="eyebrow"><MapPin size={14} /> هتل‌های ایران</span>
          <h1 id="page-title">برای یک هتل،<br /> <em>چند قیمت ببین.</em></h1>
          <p>نام هتل، مقصد یا بودجه‌ات را بنویس و نرخ‌های اعلام‌شده در سایت‌های رزرو را کنار هم ببین.</p>
          <form className="hero-search" role="search" onSubmit={(event) => { event.preventDefault(); search(draft); }}>
            <Search size={21} />
            <input aria-label="جست‌وجوی هتل" placeholder="مثلاً می‌خوام برم کنار دریا تا ۸ میلیون" maxLength={200} value={draft} onChange={(event) => setDraft(event.target.value)} />
            <button type="submit">جست‌وجو <ArrowLeft size={16} /></button>
          </form>
          <div className="quick-search"><span>جست‌وجوی سریع</span>{starters.map((item) => <button key={item} onClick={() => search(item)}>{item}</button>)}
            <a className="tour-jump" href="#tours"><Route size={13} /> دیدن تورها</a>
          </div>
        </div>
      </section>

      <div className="status-bar">
        <div><Database size={17} /><span>{Number.isFinite(hotelCount) ? number.format(hotelCount) + ' هتل' : 'دادهٔ هتل‌ها'}</span></div>
        <div><Globe2 size={17} /><span>{Number.isFinite(providerCount) ? number.format(providerCount) + ' سایت رزرو' : 'چند سایت رزرو'}</span></div>
        <div><ShieldCheck size={17} /><span>آخرین برداشت: {dateText(snapshotDate)}</span></div>
        <button onClick={() => setShowGuide(true)}><CircleHelp size={16} /> دربارهٔ نرخ‌ها</button>
      </div>

      <section id="results" ref={resultsRef} className="results">
        <div className="section-title">
          <div><div className="section-kicker"><span /> جست‌وجو و مقایسه</div><h2>{query ? 'نتیجهٔ جست‌وجو' : 'هتل‌های قابل مقایسه'}</h2></div>
          <button className="mobile-filters outline-button" onClick={() => setShowFilters(!showFilters)} aria-expanded={showFilters}><Filter size={16} /> فیلترها</button>
        </div>
        <div className="results-layout">
          <aside className={'filters' + (showFilters ? ' mobile-open' : '')} aria-label="فیلترهای جست‌وجو">
            <div className="filter-title"><span><Filter size={17} /> فیلترها</span><button onClick={() => search('')}>پاک کردن</button></div>
            <label>شهر<select aria-label="شهر هتل" value={filters.city} onChange={(e) => change('city', e.target.value)}><option value="">همهٔ شهرها</option>{cityList.map((city) => <option key={city.id} value={city.id}>{city.label}</option>)}</select></label>
            <label>درجهٔ هتل<select value={filters.min_stars} onChange={(e) => change('min_stars', e.target.value)}>
              <option value="">همهٔ درجه‌ها</option>{[3, 4, 5].map((n) => <option key={n} value={n}>{number.format(n)} ستاره یا بیشتر</option>)}
            </select></label>
            <label>سقف قیمت اعلام‌شده<select value={filters.max_price} onChange={(e) => change('max_price', e.target.value)}>
              <option value="">بدون محدودیت</option>{[3, 5, 6, 8, 10, 15].map((n) => <option key={n} value={n * 1000000}>تا {number.format(n)} میلیون تومان</option>)}
            </select></label>
            <label className="hotel-tour-filter">
              <input type="checkbox" checked={filters.has_tours ? filters.has_tours === 'true' : Boolean(parsed.has_tours)}
                onChange={(event) => change('has_tours', String(event.target.checked))} />
              <span>دارای تور<small>هتل‌هایی که دست‌کم یک تور ثبت‌شده دارند</small></span>
            </label>
            <div className="filter-note"><CircleHelp size={16} /> مبلغ و ظرفیت را برای تاریخ سفر در سایت رزرو بررسی کنید.</div>
          </aside>

          <div className="results-main">
            <div className="result-toolbar">
              <span>{busy ? 'در حال جست‌وجو…' : error ? 'خطا در دریافت نتیجه' : number.format(result?.total ?? hotels.length) + ' هتل'}</span>
              <label><ArrowDownUp size={16} /><select aria-label="مرتب‌سازی" value={filters.sort || result?.sort || 'best'} onChange={(e) => change('sort', e.target.value)}>
                <option value="best">پیشنهادی</option><option value="price">کمترین قیمت</option>
                <option value="provider_count">بیشترین سایت رزرو</option><option value="stars">بیشترین ستاره</option>
              </select></label>
            </div>

            {query && !busy && !error && <div className="intent">
              <Sparkles size={16} /><span>جست‌وجو: «{query}»</span>
              {result.interpretation_source === 'openrouter' && <b className="intent-source">تفسیر هوشمند</b>}
              {parsed.city && <b>{parsed.city_label || parsed.city}</b>}{stars && <b>{number.format(stars)} ستاره</b>}
              {parsed.hotel_name && <b>{parsed.hotel_name}</b>}
              {budget && <b>تا {money(budget)} تومان</b>}
              {parsed.has_tours && <b>دارای تور</b>}
              <DestinationIntent intent={parsed} cities={cityList} onCity={(city) => change('city', city)} />
              {parsed.destination_theme && <span className="intent-note">ساحلی بودن به شهر مقصد اشاره دارد. فاصلهٔ هتل تا ساحل را در سایت رزرو بررسی کنید.</span>}
            </div>}

            {error ? <div className="state-panel"><CircleHelp /><h3>نتایج دریافت نشد</h3><p>{error}</p><button className="outline-button" onClick={() => setRetry(retry + 1)}>تلاش دوباره</button></div>
              : busy ? <div className="loading" role="status">{[0, 1, 2].map((n) => <div key={n} />)}</div>
              : hotels.length === 0 ? <div className="state-panel"><Search /><h3>هتلی با این شرایط پیدا نشد</h3><p>فیلترها را تغییر بده و دوباره جست‌وجو کن.</p><button className="outline-button" onClick={() => search('')}>دیدن همهٔ هتل‌ها</button></div>
              : <div className="hotel-list">{hotels.map((hotel) => <HotelCard key={hotel.id} hotel={hotel} onOpen={() => setOpenHotel(hotel)} selected={compared.some((item) => item.id === hotel.id)} onCompare={() => toggleCompare(hotel)} />)}
                {result.total > hotels.length && <button className="outline-button load-more" disabled={loadingMore} onClick={loadMoreHotels}>{loadingMore ? 'در حال دریافت…' : 'نمایش هتل‌های بیشتر'} <ArrowDown size={15} /></button>}
              </div>}
          </div>
        </div>
      </section>
    </main>}

    <footer><div className="container footer-inner"><Brand /><span>پروتوتایپ مستقل برای چالش مهندس محصول هوش مصنوعی ترب</span><button onClick={() => setShowGuide(true)}>منابع و روش مقایسه</button></div></footer>

    {view === 'hotels' && compared.length > 0 && <div className="compare-bar">
      <span><Layers3 size={17} /> {number.format(compared.length)} هتل برای مقایسه</span>
      <button className="primary-button" disabled={compared.length < 2} onClick={() => setShowCompare(true)}>مقایسه <ArrowLeft size={15} /></button>
      <button className="icon-button" aria-label="پاک کردن هتل‌های منتخب" onClick={() => setCompared([])}><X size={18} /></button>
    </div>}
    {notice && <div className="notice" role="status">{notice}</div>}

    {showStats && <Modal title="آمار کلیک‌های خروجی" onClose={() => setShowStats(false)}><ClickStats /></Modal>}
    {openHotel && <Modal title={openHotel.name} onClose={() => setOpenHotel(null)}>
      <div className="hotel-modal-tools">
        <div className="modal-intro"><MapPin size={16} /> {openHotel.city} <span>·</span> {number.format(openHotel.provider_count)} سایت رزرو</div>
        <div className="hotel-modal-jumps">
          <button className="outline-button" onClick={() => hotelTicketsRef.current?.scrollIntoView({ block: 'start' })}><Ticket size={15} /> بلیط سفر <ArrowDown size={15} /></button>
          <button className="outline-button" onClick={() => hotelToursRef.current?.scrollIntoView({ block: 'start' })}><Route size={15} /> تورهای این هتل <ArrowDown size={15} /></button>
        </div>
      </div>
      <p className="callout">نرخ‌ها برای یک هتل جمع شده‌اند. نوع اتاق، تاریخ، ظرفیت و شرایط رزرو را در سایت ارائه‌دهنده بررسی کنید.</p>
      {query && openHotel.match_explanation && <p className="match-reason"><Sparkles size={14} /> {openHotel.match_explanation}</p>}
      <TravelMapPanel key={openHotel.id} hotel={openHotel} />
      <OfferRows hotel={openHotel} />
      <div ref={hotelTicketsRef}><Tickets key={openHotel.id} hotel={openHotel} dateText={dateText}
        departureCity={departureCity} onDepartureChange={changeDepartureCity} /></div>
      <div ref={hotelToursRef}><Tours key={openHotel.id} hotel={openHotel} dateText={dateText} /></div>
    </Modal>}
    {showCompare && <Modal title="مقایسهٔ هتل‌های منتخب" onClose={() => setShowCompare(false)}>
      <div className="compare-grid">{compared.map((hotel) => <article key={hotel.id}>
        <HotelTile hotel={hotel} /><h3>{hotel.name}</h3><p>{hotel.city} {hotel.stars ? '· ' + number.format(hotel.stars) + ' ستاره' : ''}</p>
        <small>{(hotel.best_offer || hotel.offers[0])?.stay_nights > 1 ? 'میانگین هر شبِ بسته' : 'شروع از هر شب'}</small><strong>{money(nightlyPrice(hotel.best_offer || hotel.offers[0]))} تومان</strong>
        <span>{number.format(hotel.provider_count)} سایت رزرو</span>
        <button className="outline-button" onClick={() => { setShowCompare(false); setOpenHotel(hotel); }}>نرخ‌های این هتل <ChevronLeft size={15} /></button>
      </article>)}</div>
    </Modal>}
    {showGuide && <Modal title="نرخ‌ها چطور مقایسه می‌شوند؟" onClose={() => setShowGuide(false)}>
      <div className="guide">
        <p>شب‌سنج نرخ‌های عمومی نمایش داده‌شده در صفحات سایت‌های رزرو را با واحد تومان ثبت می‌کند. کمترین نرخ نمایش داده‌شده برای هر هتل در فهرست می‌آید.</p>
        <p>نرخ‌ها نشان‌دهندهٔ موجودی لحظه‌ای یا قیمت قطعی اتاق نیستند. برای انتخاب تاریخ، شرایط لغو و رزرو به سایت ارائه‌دهنده بروید.</p>
        <p>جست‌وجو نام هتل، مقصد، ستاره، بودجه و فیلترهای تور را از متن برداشت می‌کند. وقتی تفسیر هوشمند فعال است، متن جست‌وجو برای تفسیر به OpenRouter فرستاده می‌شود.</p>
        {Array.isArray(summary?.providers) && <div className="guide-sources">{summary.providers.map((provider) => {
          const name = typeof provider === 'string' ? providerNames[provider] || provider : provider.name || provider.provider;
          return <span key={name}><Globe2 size={16} /> {name}</span>;
        })}</div>}
      </div>
    </Modal>}
  </>;
}

createRoot(document.getElementById('root')).render(<App />);
