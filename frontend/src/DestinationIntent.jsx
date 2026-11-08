import React from 'react';

export function DestinationIntent({ intent, cities, onCity }) {
  const labels = new Map(cities.map((city) => [city.id, city.label || city.name || city.city]));
  const matched = (intent.matched_city_ids || []).filter((id) => labels.has(id));
  const theme = intent.destination_theme_label;
  if (!theme && !matched.length) return null;

  return <>
    {theme && <b>{theme}</b>}
    {matched.length > 0 && <span className="intent-cities">{matched.map((id) => onCity
      ? <button key={id} onClick={() => onCity(id)}>{labels.get(id)}</button>
      : <span key={id}>{labels.get(id)}</span>)}</span>}
  </>;
}
