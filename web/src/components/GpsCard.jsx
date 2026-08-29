const FIX_BADGES = {
  none: { label: 'No Fix', className: 'bg-gray-200 text-gray-600' },
  '2d': { label: '2D Fix', className: 'bg-amber-100 text-amber-700' },
  '3d': { label: '3D Fix', className: 'bg-green-100 text-green-700' },
};

function relativeAge(isoString) {
  if (!isoString) return null;
  const seconds = Math.max(0, Math.round((Date.now() - new Date(isoString).getTime()) / 1000));
  return `${seconds}s ago`;
}

function fmt(value, digits = 5, suffix = '') {
  if (value === null || value === undefined) return '—';
  return `${Number(value).toFixed(digits)}${suffix}`;
}

export default function GpsCard({ gps }) {
  if (!gps || gps.gpsd_connected === false) {
    return (
      <div className="card p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-bold tracking-tight">GPS</h2>
          <span className="rounded-full bg-gray-200 px-2.5 py-1 text-[0.65rem] font-bold text-gray-600">
            gpsd not connected
          </span>
        </div>
        <p className="text-[0.75rem] text-[color:var(--muted)]">
          Waiting for gpsd to report a position…
        </p>
      </div>
    );
  }

  const badge = FIX_BADGES[gps.fix] || FIX_BADGES.none;

  return (
    <div className="card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-bold tracking-tight">GPS</h2>
        <span className={`rounded-full px-2.5 py-1 text-[0.65rem] font-bold ${badge.className}`}>
          {badge.label}
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-y-1 text-[0.75rem]">
        <dt className="text-[color:var(--muted)]">Latitude</dt>
        <dd className="text-right font-semibold">{fmt(gps.latitude)}</dd>
        <dt className="text-[color:var(--muted)]">Longitude</dt>
        <dd className="text-right font-semibold">{fmt(gps.longitude)}</dd>
        <dt className="text-[color:var(--muted)]">Altitude</dt>
        <dd className="text-right font-semibold">{fmt(gps.altitude_m, 1, ' m')}</dd>
        <dt className="text-[color:var(--muted)]">Speed</dt>
        <dd className="text-right font-semibold">{fmt(gps.speed_kmh, 1, ' km/h')}</dd>
        <dt className="text-[color:var(--muted)]">Satellites</dt>
        <dd className="text-right font-semibold">
          {gps.satellites_used ?? '—'} / {gps.satellites_visible ?? '—'}
        </dd>
        <dt className="text-[color:var(--muted)]">HDOP</dt>
        <dd className="text-right font-semibold">{fmt(gps.hdop, 1)}</dd>
      </dl>
      {gps.last_update && (
        <small className="mt-2 block text-[0.65rem] text-[color:var(--muted)]">
          Last update {relativeAge(gps.last_update)}
        </small>
      )}
    </div>
  );
}
