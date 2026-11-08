import React, { useEffect, useState } from 'react';
import {
  ArrowDown, ArrowLeft, ArrowUpLeft, BedDouble, CalendarDays, Check,
  CircleHelp, Clock3, Filter, Globe2, MapPin, Route, Search, Sparkles,
} from 'lucide-react';
import { DestinationIntent } from './DestinationIntent.jsx';
import { TravelMapPanel } from './TravelMapPanel.jsx';

const fa = new Intl.NumberFormat('fa-IR');
const faDigits = (text) => text.replace(/\d/g, (digit) => '۰۱۲۳۴۵۶۷۸۹'[Number(digit)]);
const transportLabels = { flight: 'هواپیما', train: 'قطار', bus: 'اتوبوس' };
const initialFilters = {
  departure_city: '',
  destination_city: '',
  hotel_key: '',
  departure_date: '',
  hotel_checkin_date: '',
  service: '',
  sort: '',
};

function TourServices({ tour }) {
  const services = tour.services || [];
  const optional = tour.optional_services || [];
  return <div className="tour-services">
    <h4>خدمات اعلام‌شدهٔ تور</h4>
    {services.length > 0 ? <ul>{services.map((service) => <li key={service}><Check size={14} /> {faDigits(service)}</li>)}</ul>
      : <p>جزئیات خدمات را در صفحهٔ ارائه‌دهنده ببینید.</p>}
    {optional.length > 0 && <div className="tour-optional">
      <strong>خدمات اختیاری یا وابسته به نوع بسته</strong>
      <ul>{optional.map((service) => <li key={service}>{faDigits(service)}</li>)}</ul>
    </div>}
  </div>;
}

function TourCard({ tour, dateText }) {
  const origin = tour.departure_city_label || tour.departure_city;
  const destination = tour.destination_city_label || tour.destination_city;
  const transport = transportLabels[tour.transport] || tour.transport;
  const routeListing = tour.source_url && tour.source_url === tour.listing_url;
  return <article className="tour-card">
    <div className="tour-top">
      <div>
        <div className="tour-route"><MapPin size={15} /> <span>{origin || 'مبدأ اعلام نشده'}</span><ArrowLeft size={16} /><span>{destination || 'مقصد اعلام نشده'}</span></div>
        <h3>{tour.title}</h3>
        {tour.hotel_name && <p className="tour-hotel"><BedDouble size={15} /> {tour.hotel?.name || tour.hotel_name}</p>}
      </div>
      <div className="tour-rate">
        {Number.isFinite(tour.price_toman) && tour.price_basis === 'per_person'
          ? <><small>شروع از · هر نفر</small><strong>{fa.format(tour.price_toman)} <small>تومان</small></strong></>
          : <small>استعلام قیمت از ارائه‌دهنده</small>}
      </div>
    </div>
    <div className="tour-meta">
      {tour.departure_date && <span><CalendarDays size={15} /> حرکت {dateText(tour.departure_date)}{tour.return_date ? ' · برگشت ' + dateText(tour.return_date) : ''}</span>}
      {tour.hotel_checkin_date && <span><CalendarDays size={15} /> ورود به هتل {dateText(tour.hotel_checkin_date)}</span>}
      {tour.departure_time && <span><Clock3 size={15} /> ساعت حرکت {tour.departure_time}</span>}
      {tour.duration_nights > 0 && <span>{fa.format(tour.duration_nights)} شب</span>}
      {tour.travelers > 0 && <span>{fa.format(tour.travelers)} مسافر</span>}
      {transport && <span><Route size={15} /> {transport}</span>}
    </div>
    <TourServices tour={tour} />
    {origin && destination && <TravelMapPanel tour={tour} />}
    <div className="tour-bottom">
      <div><span><Globe2 size={14} /> {tour.provider_name || tour.provider}</span>
        {tour.observed_at && <small>ثبت {dateText(tour.observed_at)}</small>}
      </div>
      {tour.outbound_url && <a className="outline-button" href={tour.outbound_url} target="_blank" rel="noopener noreferrer nofollow">{tour.cta_label || (routeListing ? 'تورهای این مسیر در سایت' : 'جزئیات در سایت تور')} <ArrowUpLeft size={15} /></a>}
    </div>
    {tour.price_note && <p className="tour-price-note">{faDigits(tour.price_note)}</p>}
  </article>;
}

function FilterSelect({ title, value, onChange, empty, options }) {
  return <label><span>{title}</span>
    <select aria-label={title} value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">{empty}</option>
      {options.map(({ value: key, label }) => <option key={key} value={key}>{label}</option>)}
    </select>
  </label>;
}

const cityOptions = (items = []) => items.map(({ id, label }) => ({ value: id, label }));

export function Tours({ hotel, dateText }) {
  const [filters, setFilters] = useState(initialFilters);
  const [draft, setDraft] = useState('');
  const [query, setQuery] = useState('');
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [visible, setVisible] = useState(hotel ? 4 : 8);
  const hotelId = hotel?.id;

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ limit: '500' });
    if (hotelId) params.set('hotel_id', hotelId);
    if (query) params.set('q', query);
    for (const [key, value] of Object.entries(filters)) {
      if (value) params.set(key, value);
    }
    setBusy(true);
    setError(false);
    setVisible(hotelId ? 4 : 8);
    fetch('/api/tours?' + params, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('tour request failed');
        return response.json();
      })
      .then(setData)
      .catch((err) => { if (err.name !== 'AbortError') setError(true); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [hotelId, query, filters, retry]);

  function setFilter(key, value) {
    setFilters((current) => ({
      ...current, [key]: value, ...(key === 'destination_city' ? { hotel_key: '' } : {}),
    }));
  }

  function reset() {
    setDraft('');
    setQuery('');
    setFilters(initialFilters);
  }

  const options = data?.filters || {};
  const intent = data?.parsed_intent || {};
  const tours = data?.tours || [];
  const active = Boolean(query || Object.values(filters).some(Boolean));
  const departureCities = cityOptions(options.departure_cities);
  const departureDates = (options.departure_dates || []).map((date) => ({ value: date, label: dateText(date) }));
  const checkinDates = (options.hotel_checkin_dates || []).map((date) => ({ value: date, label: dateText(date) }));
  const hotelOptions = (options.hotels || [])
    .filter((item) => !filters.destination_city || item.city === filters.destination_city)
    .map(({ key, name, city_label: city }) => ({ value: key, label: city && !name.includes(city) ? name + ' · ' + city : name }));
  const serviceOptions = (options.services || []).map((service) => ({ value: service, label: faDigits(service) }));

  return <section className={hotel ? 'tour-section hotel-tours' : 'tour-section'} aria-label={hotel ? 'تورهای این هتل' : 'جست‌وجو و فیلتر تورها'}>
    {hotel
      ? <div className="hotel-tours-heading"><span className="provider-icon"><Route size={17} /></span><div><h3>تورهای این هتل</h3><p>بسته‌هایی که این هتل را در برنامهٔ اقامت دارند.</p></div></div>
      : <div className="tour-hero"><div>
          <span className="eyebrow"><Route size={15} /> تورهای داخلی ایران</span>
          <h1>از کجا، <em>به کجا؟</em></h1>
          <p>تور را با مبدأ، مقصد یا هتل پیدا کن و خدمات هر بسته را ببین.</p>
          <form className="hero-search" role="search" onSubmit={(event) => { event.preventDefault(); setQuery(draft.trim()); }}>
            <Search size={20} /><input aria-label="جست‌وجوی تور" placeholder="مثلاً تور کنار دریا از تهران" maxLength={200} value={draft} onChange={(event) => setDraft(event.target.value)} />
            <button type="submit">جست‌وجو <ArrowLeft size={15} /></button>
          </form>
          <div className="quick-search"><span>جست‌وجوی سریع</span>{['تور کیش', 'تور کنار دریا'].map((text) => <button key={text} onClick={() => { setDraft(text); setQuery(text); setFilters(initialFilters); }}>{text}</button>)}</div>
        </div><div className="route-art" aria-hidden="true"><MapPin size={32} /><span /><Route size={40} /><span /><BedDouble size={32} /></div></div>}

    {(!hotel || tours.length > 0 || active) && <div className="tour-filters">
      <div className="filter-title"><span><Filter size={16} /> فیلتر تور</span>{active && <button onClick={reset}>پاک کردن فیلتر تور</button>}</div>
      <div className="tour-filter-grid">
        <FilterSelect title="مبدأ حرکت" value={filters.departure_city} onChange={(value) => setFilter('departure_city', value)} empty="همهٔ مبدأها" options={departureCities} />
        {!hotel && <FilterSelect title="مقصد تور" value={filters.destination_city} onChange={(value) => setFilter('destination_city', value)} empty="همهٔ مقصدها" options={cityOptions(options.destination_cities)} />}
        {!hotel && <FilterSelect title="هتل محل اقامت" value={filters.hotel_key} onChange={(value) => setFilter('hotel_key', value)} empty="همهٔ هتل‌ها" options={hotelOptions} />}
        {departureDates.length > 0 && <FilterSelect title="تاریخ حرکت" value={filters.departure_date} onChange={(value) => setFilter('departure_date', value)} empty="همهٔ تاریخ‌ها" options={departureDates} />}
        {checkinDates.length > 0 && <FilterSelect title="تاریخ ورود به هتل" value={filters.hotel_checkin_date} onChange={(value) => setFilter('hotel_checkin_date', value)} empty="همهٔ تاریخ‌ها" options={checkinDates} />}
        {!hotel && <FilterSelect title="خدمات تور" value={filters.service} onChange={(value) => setFilter('service', value)} empty="همهٔ خدمات" options={serviceOptions} />}
      </div>
    </div>}
    {!busy && !error && (!hotel || tours.length > 0 || active) && <div className="tour-results-meta" aria-live="polite">
      <span>{fa.format(data?.total || 0)} تور {data?.data_as_of ? '· ثبت ' + dateText(data.data_as_of) : ''}</span>
      {!hotel && <label><span>مرتب‌سازی</span><select aria-label="مرتب‌سازی تورها" value={filters.sort || data?.sort || 'best'} onChange={(event) => setFilter('sort', event.target.value)}><option value="best">پیشنهادی</option><option value="price">کمترین نرخ</option>{(departureDates.length > 0 || data?.sort === 'departure') && <option value="departure">تاریخ حرکت</option>}<option value="hotel_stars">ستارهٔ هتل</option></select></label>}
    </div>}
    {!hotel && query && !busy && !error && <div className="intent">
      <Sparkles size={16} /><span>جست‌وجو: «{query}»</span>
      {data?.interpretation_source === 'openrouter' && <b className="intent-source">تفسیر هوشمند</b>}
      {intent.departure_city && <b>از {departureCities.find((city) => city.value === intent.departure_city)?.label || intent.departure_city}</b>}
      {intent.hotel_name && <b>{intent.hotel_name}</b>}
      {intent.max_price_toman && <b>تا {fa.format(intent.max_price_toman)} تومان</b>}
      {intent.transport && <b>{transportLabels[intent.transport] || intent.transport}</b>}
      {intent.service && <b>{intent.service}</b>}
      {intent.departure_date && <b>حرکت {dateText(intent.departure_date)}</b>}
      <DestinationIntent intent={intent} cities={options.destination_cities || []} onCity={(city) => setFilter('destination_city', city)} />
    </div>}
    {busy ? <p className="tour-message" role="status">در حال دریافت تورها…</p>
      : error ? <div className="tour-message"><CircleHelp size={18} /> دریافت تورها ممکن نشد. <button className="outline-button" onClick={() => setRetry((attempt) => attempt + 1)}>تلاش دوباره</button></div>
      : tours.length === 0 ? <div className="tour-message"><CircleHelp size={18} /> {hotel && !active ? 'برای این هتل در فهرست فعلی توری ثبت نشده است.' : 'توری با این فیلترها پیدا نشد.'}</div>
      : <><p className="tour-disclaimer">نرخ، تاریخ و خدمات از صفحهٔ تور ثبت شده‌اند. زمان حرکت و موجودی را با ارائه‌دهنده بررسی کنید.</p>
          <div className="tour-list">{tours.slice(0, visible).map((tour) => <TourCard key={tour.id} tour={tour} dateText={dateText} />)}</div>
          {tours.length > visible && <button className="outline-button tour-more" onClick={() => setVisible((count) => count + 8)}>نمایش تورهای بیشتر <ArrowDown size={16} /></button>}
        </>}
  </section>;
}
