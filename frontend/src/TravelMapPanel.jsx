import React, { useId, useState } from 'react';
import { MapPin, Route } from 'lucide-react';
import { TravelMap } from './TravelMap.jsx';

export function TravelMapPanel({ hotel, tour }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return <div className="travel-map-panel">
    <button type="button" className="outline-button" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(!open)}>
      {tour ? <Route size={15} /> : <MapPin size={15} />}
      {open ? 'بستن نقشه' : tour ? 'نقشهٔ مسیر' : 'نقشهٔ هتل'}
    </button>
    <div id={panelId} hidden={!open}>{open && <TravelMap hotel={hotel} tour={tour} />}</div>
  </div>;
}
