import React, { useEffect, useId, useState } from 'react';
import { ArrowLeft, ArrowUpLeft, Bus, CircleHelp, Plane, Ticket, TrainFront } from 'lucide-react';

const modes = {
  flight: { label: 'هواپیما', Icon: Plane },
  bus: { label: 'اتوبوس', Icon: Bus },
  train: { label: 'قطار', Icon: TrainFront },
};
const number = new Intl.NumberFormat('fa-IR');
const amount = (value) => number.format(value);
const citiesInOrder = new Intl.Collator('fa');
const checkedTime = new Intl.DateTimeFormat('fa-IR', {
  hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tehran',
});

function travelDuration(minutes) {
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return [hours && `${amount(hours)} ساعت`, remainder && `${amount(remainder)} دقیقه`]
    .filter(Boolean).join(' و ');
}

function airportNotice(airportRoute, route) {
  if (!airportRoute || !route) return null;
  if (airportRoute.origin === airportRoute.destination) {
    return {
      unavailable: true,
      summary: 'پرواز بین‌شهری برای این جفت فرودگاه وجود ندارد',
      details: [`مبدأ و مقصد هوایی هر دو فرودگاه ${airportRoute.origin_label} هستند. این مسیر زمینی است.`],
    };
  }
  const originChanged = airportRoute.origin !== route.origin;
  const destinationChanged = airportRoute.destination !== route.destination;
  if (!originChanged && !destinationChanged) return null;
  const details = [];
  const summary = [];
  if (originChanged) {
    details.push(`جست‌وجوی پرواز از فرودگاه ${airportRoute.origin_label} است. مسیر ${route.origin_label} تا فرودگاه زمینی است.`);
    summary.push(`فرودگاه مبدأ ${airportRoute.origin_label}`);
  }
  if (destinationChanged) {
    details.push(`جست‌وجوی پرواز تا فرودگاه ${airportRoute.destination_label} است. ادامهٔ مسیر تا ${route.destination_label} زمینی است.`);
    summary.push(`فرودگاه مقصد ${airportRoute.destination_label}`);
  }
  return { summary: `${summary.join(' · ')} · اتصال زمینی`, details };
}

function SellerLink({ offer, label }) {
  return <a className="outline-button ticket-seller-link" href={offer.outbound_url}
    target="_blank" rel="noopener noreferrer">{label} <ArrowUpLeft size={14} /></a>;
}

function TicketLine({ offer, dateText, showNote = false }) {
  const service = [offer.operator, offer.service_number, offer.service_class,
    offer.departure_time && `حرکت ${offer.departure_time}`,
    offer.arrival_time && `ورود ${offer.arrival_time}`].filter(Boolean).join(' · ');
  const details = [
    offer.departure_terminal && `مبدأ ${offer.departure_terminal}`,
    offer.arrival_terminal && `مقصد ${offer.arrival_terminal}`,
    offer.duration_minutes > 0 && `مدت ${travelDuration(offer.duration_minutes)}`,
    !offer.stale && offer.seats_remaining > 0 && (offer.mode === 'flight'
      ? `${amount(offer.seats_remaining)} صندلی با این نرخ هنگام ثبت`
      : `${amount(offer.seats_remaining)} صندلی هنگام ثبت`),
    !offer.stale && offer.seats_remaining > 0 && offer.availability === 'unknown' && 'ظرفیت در انتظار تأیید فروشنده',
    !offer.stale && offer.seats_remaining == null && offer.seats_lower_bound > 0 && `دست‌کم ${amount(offer.seats_lower_bound)} صندلی هنگام ثبت`,
    !offer.stale && offer.seats_remaining == null && offer.seats_lower_bound == null && offer.departure_date && 'تعداد صندلی اعلام نشده',
  ].filter(Boolean).join(' · ');
  return <li>
    <div className="ticket-offer">
      <div><strong>{offer.provider_name}</strong>
        {service && <small>{service}</small>}
        {details && <small>{details}</small>}
        <small>{offer.stale ? 'ثبت قدیمی · ' : 'زمان ثبت · '}{dateText(offer.observed_at)}، {checkedTime.format(new Date(offer.observed_at))}</small>
      </div>
      <div className="ticket-price"><strong>{amount(offer.price_toman)}</strong><small>تومان / نفر</small></div>
      <SellerLink offer={offer} label="سایت فروشنده" />
    </div>
    {showNote && offer.price_note && <p className="ticket-price-note">{offer.price_note}</p>}
  </li>;
}

function TicketOffers({ group, dateText }) {
  const { basis, departure_date: day, offers, fresh_seller_count: sellers, departures = [] } = group;
  const dated = basis === 'dated';
  const lowest = offers[0].price_toman;
  const tied = offers.filter((offer) => !offer.stale && offer.price_toman === lowest).length > 1;
  return <div className="ticket-offers">
    <h4>{dated ? `نرخ‌های ثبت‌شده برای ${dateText(day)}` : 'نرخ شروع مسیر · تاریخ منعطف'}</h4>
    {dated && sellers > 1 && <p className="ticket-rank-reason">
      {tied ? 'کمترین نرخ این روز در چند فروشنده برابر است.' : `${offers[0].provider_name} کمترین نرخ این روز را بین ${amount(sellers)} فروشنده دارد.`}
    </p>}
    {dated && offers.some((offer) => offer.stale) && <p className="ticket-price-note">
      نرخ‌های قدیمی برای مقایسهٔ نرخ تازه و اعلام ظرفیت استفاده نمی‌شوند.
    </p>}
    <ul>{offers.map((offer) => <TicketLine key={offer.provider} offer={offer} dateText={dateText} showNote />)}</ul>
    {departures.length > offers.length && <details className="ticket-departures">
      <summary>دیدن {amount(departures.length)} حرکت ثبت‌شده</summary>
      <ul>{departures.map((offer) => <TicketLine key={offer.offer_id || `${offer.outbound_url}:${offer.departure_time}:${offer.service_class}:${offer.price_toman}`}
        offer={offer} dateText={dateText} />)}</ul>
    </details>}
  </div>;
}

function ModeResults({ id, result, route, dateText }) {
  const { Icon, label } = modes[result.mode];
  const notice = result.mode === 'flight' ? airportNotice(result.airport_route, route) : null;
  return <article id={id} className="ticket-mode">
    <h3><Icon size={17} /> {label}</h3>
    {notice && <div className="ticket-airport-notice"><CircleHelp size={15} />
      <div>{notice.details.map((detail) => <p key={detail}>{detail}</p>)}</div>
    </div>}
    {result.groups.length ? result.groups.map((group) => <TicketOffers key={group.basis} group={group} dateText={dateText} />)
      : !notice?.unavailable && <p className="ticket-empty">برای این مسیر نرخ قابل مقایسه ثبت نشده است.</p>}
    {result.links.length > 0 && <div className="ticket-source-links">
      <small>استعلام تاریخ و نرخ در سایت فروشنده</small>
      <div>{result.links.map((offer) => <SellerLink key={offer.provider} offer={offer} label={offer.provider_name} />)}</div>
    </div>}
  </article>;
}

function ModeSummary({ results, route, targetPrefix }) {
  return <div className="ticket-mode-summary" aria-label="خلاصهٔ گزینه‌های بلیط">
    {results.map(({ mode, groups, links, airport_route: airportRoute }) => {
      const { Icon, label } = modes[mode];
      const offer = groups.flatMap((group) => group.offers).find((row) => !row.stale);
      const flexible = offer && !offer.departure_date;
      const notice = mode === 'flight' ? airportNotice(airportRoute, route) : null;
      const target = `${targetPrefix}-${mode}`;
      return <button key={mode} type="button" aria-controls={target}
        onClick={() => document.getElementById(target)?.scrollIntoView({ block: 'start' })}>
        <strong><Icon size={14} /> {label}</strong>
        <small>{notice?.unavailable ? notice.summary : offer ? `${offer.provider_name} · ${flexible ? 'از ' : ''}${amount(offer.price_toman)} تومان${flexible ? ' · تاریخ منعطف' : ''}`
          : links.length ? `${amount(links.length)} فروشنده برای استعلام` : 'بدون نرخ ثبت‌شده'}</small>
        {notice && !notice.unavailable && <small className="ticket-airport-summary">{notice.summary}</small>}
      </button>;
    })}
  </div>;
}

export function Tickets({ hotel, dateText, departureCity, onDepartureChange }) {
  const titleId = useId();
  const [catalog, setCatalog] = useState(null);
  const [selection, setSelection] = useState({ destination: '', date: '', mode: '' });
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [catalogError, setCatalogError] = useState(false);
  const [resultError, setResultError] = useState(false);
  const [retry, setRetry] = useState(0);
  const routes = catalog?.routes || [];
  const cities = (catalog?.cities || []).slice().sort((a, b) => citiesInOrder.compare(a.label, b.label));
  const originCity = cities.find((city) => city.id === departureCity);
  const origin = originCity?.id || '';
  const outgoing = routes.filter((route) => route.destination !== origin
    && (!selection.mode || route.modes.includes(selection.mode)) && (
    route.origin === origin
    || ((!selection.mode || selection.mode === 'flight')
      && route.origin === originCity?.airport_city && route.modes.includes('flight'))
  ));
  const suggested = outgoing.find((route) => route.destination === 'mashhad') || outgoing[0];
  const chosenDestination = selection.destination === origin ? '' : selection.destination;
  const destination = hotel?.city_id || chosenDestination || suggested?.destination || '';
  const canSearch = Boolean(origin && destination && origin !== destination);
  const cityLabel = cities.find((city) => city.id === destination)?.label || hotel?.city;
  const comparisonDays = new Set(result?.compared_dates);

  useEffect(() => {
    const controller = new AbortController();
    setCatalogError(false);
    fetch('/api/tickets/routes', { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('Ticket routes unavailable');
        return response.json();
      })
      .then(setCatalog)
      .catch((error) => { if (error.name !== 'AbortError') setCatalogError(true); });
    return () => controller.abort();
  }, [retry]);

  useEffect(() => {
    if (!catalog || !canSearch) {
      setResult(null);
      setLoading(false);
      setResultError(false);
      return;
    }
    const controller = new AbortController();
    const params = new URLSearchParams({ origin, destination });
    if (selection.date) params.set('date', selection.date);
    if (selection.mode) params.set('mode', selection.mode);
    setLoading(true);
    setResultError(false);
    fetch('/api/tickets?' + params, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error('Ticket results unavailable');
        return response.json();
      })
      .then(setResult)
      .catch((error) => { if (error.name !== 'AbortError') setResultError(true); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [catalog, canSearch, origin, destination, selection.date, selection.mode]);

  function change(key, value) {
    setSelection((previous) => ({
      ...previous, [key]: value,
      ...(key === 'destination' && { date: '' }),
    }));
  }

  function changeOrigin(city) {
    onDepartureChange(city);
    setSelection((previous) => ({
      ...previous, date: '',
      destination: previous.destination === city ? '' : previous.destination,
    }));
  }

  const citiesFor = (excluded) => cities.filter((city) => city.id !== excluded)
    .map((city) => <option key={city.id} value={city.id}>{city.label}</option>);

  return <section className={hotel ? 'tickets hotel-tickets' : 'tickets'} aria-labelledby={titleId}>
    <header className="ticket-header">
      <div className="ticket-icon"><Ticket size={22} /></div>
      <div>
        {hotel ? <h3 id={titleId}>بلیط سفر به {cityLabel}</h3> : <h1 id={titleId}>مقایسهٔ بلیط سفر</h1>}
        <p>نرخ هواپیما، اتوبوس و قطار را برای یک مسیر از فروشنده‌های مختلف ببین.</p>
      </div>
    </header>
    {(catalogError || resultError) && <p className="ticket-message" role="alert"><CircleHelp size={17} />
      دریافت بلیط‌ها ممکن نشد.
      <button type="button" className="outline-button" onClick={() => setRetry((count) => count + 1)}>تلاش دوباره</button>
    </p>}
    {catalog && <div className="ticket-filters">
      <label>مبدأ حرکت<select value={origin} onChange={(event) => changeOrigin(event.target.value)}>
        <option value="">انتخاب مبدأ حرکت</option>{citiesFor('')}
      </select></label>
      {hotel ? <div className="ticket-fixed-city"><span>مقصد</span><strong>{cityLabel}</strong></div>
        : <label>مقصد<select value={destination} onChange={(event) => change('destination', event.target.value)}>
          <option value="" disabled>انتخاب مقصد</option>{citiesFor(origin)}
        </select></label>}
      <label>تاریخ حرکت (اختیاری)<input type="date" value={selection.date} onChange={(event) => change('date', event.target.value)} /></label>
      {!hotel && <label>نوع بلیط<select value={selection.mode} onChange={(event) => change('mode', event.target.value)}>
        <option value="">همهٔ بلیط‌ها</option>
        {Object.entries(modes).map(([key, { label }]) => <option key={key} value={key}>{label}</option>)}
      </select></label>}
    </div>}
    {catalog && !canSearch && <p className="ticket-message" role="status">
      {!origin ? 'مبدأ حرکت را انتخاب کنید. این انتخاب برای جست‌وجوهای بعدی ذخیره می‌شود.'
        : origin === destination ? 'مبدأ و مقصد یکسان‌اند. برای دیدن بلیط، مبدأ دیگری را انتخاب کنید.'
          : 'مقصد سفر را انتخاب کنید.'}
    </p>}
    {(!catalog && !catalogError || canSearch && loading) && <p className="ticket-message" role="status">در حال دریافت بلیط‌ها…</p>}
    {canSearch && !loading && !catalogError && !resultError && result
      && result.origin === origin && result.destination === destination && <>
      <div className="ticket-route">
        <strong>{result.origin_label} <ArrowLeft size={16} /> {result.destination_label}</strong>
        {selection.date && <button type="button" className="outline-button" onClick={() => change('date', '')}>حذف تاریخ</button>}
      </div>
      <p className="ticket-disclaimer">مبلغ‌ها برای یک مسافر بزرگسال و یک‌طرفه‌اند. مقایسه بر اساس ارزان‌ترین حرکت هر فروشنده در همان مسیر و روز است. مبلغ و ظرفیت ممکن است تا زمان خرید تغییر کنند.</p>
      {hotel && <ModeSummary results={result.modes} route={result} targetPrefix={titleId} />}
      {selection.date && result.modes.every(({ groups }) => groups.every(({ basis }) => basis !== 'dated')) &&
        <p className="ticket-message">برای {dateText(selection.date)} نرخ تاریخ‌دار ثبت نشده است. نرخ‌های شروع، تاریخ منعطف دارند.</p>}
      {result.available_dates.length > 0 && <div className="ticket-dates"><small>تاریخ‌های ثبت‌شده</small>
        {result.available_dates.slice(0, 5).map((day) => <button type="button" key={day} className="outline-button"
          aria-pressed={selection.date === day} onClick={() => change('date', day)}>{dateText(day)}</button>)}
        {result.available_dates.length > 5 && <select className="outline-button" aria-label="همهٔ تاریخ‌های ثبت‌شده"
          value={result.available_dates.includes(selection.date) ? selection.date : ''}
          onChange={(event) => change('date', event.target.value)}>
          <option value="">همهٔ تاریخ‌ها ({amount(result.available_dates.length)})</option>
          {result.available_dates.map((day) => <option key={day} value={day}>
            {dateText(day)}{comparisonDays.has(day) ? ' · قابل مقایسه' : ''}
          </option>)}
        </select>}
      </div>}
      <div className="ticket-modes">{result.modes.map((item) => <ModeResults
        key={item.mode} id={`${titleId}-${item.mode}`} result={item} route={result} dateText={dateText} />)}</div>
    </>}
  </section>;
}
