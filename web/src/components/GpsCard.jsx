import { useState } from 'react';

const FIX_BADGES = {
  none: { label: 'No Fix', className: 'bg-gray-200 text-gray-700' },
  '2d': { label: '2D Fix', className: 'bg-amber-100 text-amber-800' },
  '3d': { label: '3D Fix', className: 'bg-emerald-100 text-emerald-800' },
};

const GNSS_COLORS = {
  GPS: { badge: 'bg-blue-100 text-blue-800 border-blue-200', bar: 'bg-blue-500' },
  GLONASS: { badge: 'bg-purple-100 text-purple-800 border-purple-200', bar: 'bg-purple-500' },
  BeiDou: { badge: 'bg-amber-100 text-amber-800 border-amber-200', bar: 'bg-amber-500' },
  Galileo: { badge: 'bg-cyan-100 text-cyan-800 border-cyan-200', bar: 'bg-cyan-500' },
  QZSS: { badge: 'bg-pink-100 text-pink-800 border-pink-200', bar: 'bg-pink-500' },
  SBAS: { badge: 'bg-indigo-100 text-indigo-800 border-indigo-200', bar: 'bg-indigo-500' },
  GNSS: { badge: 'bg-gray-100 text-gray-800 border-gray-200', bar: 'bg-gray-500' },
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

function headingToCompass(deg) {
  if (deg === null || deg === undefined) return null;
  const directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  const index = Math.round(((deg % 360) / 45)) % 8;
  return `${Math.round(deg)}° ${directions[index]}`;
}

function snrBarColor(snr) {
  if (!snr) return 'bg-gray-300';
  if (snr >= 35) return 'bg-emerald-500';
  if (snr >= 25) return 'bg-amber-500';
  return 'bg-red-400';
}

export default function GpsCard({ gps }) {
  const [showSatDetails, setShowSatDetails] = useState(true);

  if (!gps || gps.gpsd_connected === false) {
    return (
      <div className="card p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-bold tracking-tight">GPS / GNSS</h2>
          <span className="rounded-full bg-gray-200 px-2.5 py-0.5 text-[0.65rem] font-bold text-gray-600">
            gpsd disconnected
          </span>
        </div>
        <p className="text-[0.75rem] text-[color:var(--muted)]">
          Waiting for local gpsd daemon on port 2947…
        </p>
      </div>
    );
  }

  const isLocked = gps.fix === '2d' || gps.fix === '3d';
  const visibleSats = gps.satellites_visible ?? (gps.satellites ? gps.satellites.length : 0);
  const usedSats = gps.satellites_used ?? (gps.satellites ? gps.satellites.filter(s => s.used).length : 0);

  let fixBadge;
  if (isLocked) {
    fixBadge = FIX_BADGES[gps.fix] || FIX_BADGES.none;
  } else if (visibleSats > 0) {
    fixBadge = {
      label: `Acquiring (${visibleSats} sats)`,
      className: 'bg-blue-100 text-blue-700 animate-pulse',
    };
  } else {
    fixBadge = FIX_BADGES.none;
  }

  const accuracy = gps.epx !== null && gps.epx !== undefined && gps.epy !== null && gps.epy !== undefined
    ? `±${Math.round(Math.max(gps.epx, gps.epy) * 10) / 10} m`
    : null;

  return (
    <div className="card p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-bold tracking-tight">GPS / GNSS</h2>
          {gps.driver && (
            <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[0.6rem] font-mono text-gray-500">
              {gps.driver}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {gps.avg_snr_db !== null && gps.avg_snr_db !== undefined && (
            <span
              className={`rounded-full border px-2 py-0.5 text-[0.65rem] font-semibold ${
                gps.signal_quality === 'good'
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                  : gps.signal_quality === 'moderate'
                  ? 'border-amber-200 bg-amber-50 text-amber-700'
                  : 'border-gray-200 bg-gray-50 text-gray-600'
              }`}
            >
              {gps.avg_snr_db} dB-Hz
            </span>
          )}
          <span className={`rounded-full px-2.5 py-0.5 text-[0.65rem] font-bold ${fixBadge.className}`}>
            {fixBadge.label}
          </span>
        </div>
      </div>

      {/* Constellation Summary Pills */}
      {gps.constellations && Object.keys(gps.constellations).length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
          {Object.entries(gps.constellations).map(([name, count]) => {
            const colors = GNSS_COLORS[name] || GNSS_COLORS.GNSS;
            return (
              <span
                key={name}
                className={`flex items-center gap-1 rounded-md border px-2 py-0.5 text-[0.65rem] font-medium ${colors.badge}`}
              >
                <span>{name}</span>
                <span className="font-bold">{count}</span>
              </span>
            );
          })}
        </div>
      )}

      {/* Acquisition / Lock Diagnostic Banner */}
      {!isLocked && (
        <div className="rounded-md border border-blue-100 bg-blue-50/70 p-2 text-[0.7rem] text-blue-900 leading-snug">
          {visibleSats >= 4 ? (
            <span>
              <strong>Locking:</strong> Tracking {visibleSats} satellites (avg {gps.avg_snr_db ?? '—'} dB-Hz). Downloading ephemeris almanac…
            </span>
          ) : (
            <span>
              <strong>Searching:</strong> {visibleSats} satellite{visibleSats === 1 ? '' : 's'} detected in sky (minimum 4 required for 3D fix).
            </span>
          )}
        </div>
      )}

      {/* Main Metrics Grid */}
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 text-[0.75rem]">
        <dt className="text-[color:var(--muted)]">Latitude</dt>
        <dd className="text-right font-semibold font-mono">{fmt(gps.latitude, 6)}</dd>
        
        <dt className="text-[color:var(--muted)]">Longitude</dt>
        <dd className="text-right font-semibold font-mono">{fmt(gps.longitude, 6)}</dd>
        
        <dt className="text-[color:var(--muted)]">Altitude</dt>
        <dd className="text-right font-semibold">{fmt(gps.altitude_m, 1, ' m')}</dd>
        
        <dt className="text-[color:var(--muted)]">Speed</dt>
        <dd className="text-right font-semibold">{fmt(gps.speed_kmh, 1, ' km/h')}</dd>

        <dt className="text-[color:var(--muted)]">Heading</dt>
        <dd className="text-right font-semibold">
          {headingToCompass(gps.track_deg) ?? '—'}
        </dd>

        <dt className="text-[color:var(--muted)]">Accuracy</dt>
        <dd className="text-right font-semibold">{accuracy ?? '—'}</dd>

        <dt className="text-[color:var(--muted)]">Satellites</dt>
        <dd className="text-right font-semibold">
          <span className={usedSats >= 4 ? 'text-emerald-700 font-bold' : ''}>{usedSats}</span>
          {' / '}
          <span>{visibleSats}</span>
        </dd>
        
        <dt className="text-[color:var(--muted)]">HDOP / PDOP</dt>
        <dd className="text-right font-semibold">
          {fmt(gps.hdop, 1)}
          {gps.pdop !== null && gps.pdop !== undefined ? ` / ${Number(gps.pdop).toFixed(1)}` : ''}
        </dd>
      </dl>

      {/* Live Tracked Satellites Bar Section */}
      {gps.satellites && gps.satellites.length > 0 && (
        <div className="border-t border-[color:var(--line)] pt-2">
          <div className="mb-2 flex items-center justify-between">
            <button
              type="button"
              onClick={() => setShowSatDetails(!showSatDetails)}
              className="text-[0.7rem] font-bold text-[color:var(--ink)] hover:underline flex items-center gap-1"
            >
              <span>Tracked Satellites ({gps.satellites.length})</span>
              <span className="text-[0.6rem] text-[color:var(--muted)]">
                {showSatDetails ? '▲' : '▼'}
              </span>
            </button>
            <span className="text-[0.65rem] text-[color:var(--muted)]">
              Signal (dB-Hz)
            </span>
          </div>

          {showSatDetails && (
            <div className="flex flex-col gap-1 max-h-44 overflow-y-auto pr-1">
              {gps.satellites.map((sat) => {
                const colors = GNSS_COLORS[sat.gnss] || GNSS_COLORS.GNSS;
                const snrPercent = sat.snr ? Math.min(100, Math.round((sat.snr / 50) * 100)) : 0;
                
                return (
                  <div
                    key={`${sat.gnss}-${sat.prn}`}
                    className={`flex items-center justify-between gap-2 rounded px-2 py-1 text-[0.68rem] ${
                      sat.used ? 'bg-emerald-50/70 border border-emerald-200' : 'bg-gray-50/80 border border-transparent'
                    }`}
                  >
                    <div className="flex items-center gap-1.5 min-w-[5.5rem]">
                      <span className={`rounded px-1 py-0.2 text-[0.6rem] font-semibold ${colors.badge}`}>
                        {sat.gnss.slice(0, 3).toUpperCase()}
                      </span>
                      <span className="font-mono font-bold">#{sat.prn}</span>
                      {sat.used && (
                        <span className="text-[0.6rem] text-emerald-600 font-bold" title="Used in navigation fix">
                          ✓
                        </span>
                      )}
                    </div>

                    <div className="flex flex-1 items-center gap-2">
                      <div className="h-1.5 flex-1 rounded-full bg-gray-200 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all duration-300 ${snrBarColor(sat.snr)}`}
                          style={{ width: `${snrPercent}%` }}
                        />
                      </div>
                      <span className="font-mono text-[0.65rem] text-right w-12 font-medium">
                        {sat.snr ? `${sat.snr.toFixed(0)} dB` : '—'}
                      </span>
                    </div>

                    {sat.elevation !== null && sat.elevation !== undefined && (
                      <span className="text-[0.6rem] text-[color:var(--muted)] font-mono w-10 text-right">
                        {sat.elevation}° el
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="flex items-center justify-between text-[0.65rem] text-[color:var(--muted)] pt-1 border-t border-[color:var(--line)]">
        <span>
          {gps.time ? `UTC ${new Date(gps.time).toLocaleTimeString()}` : 'No GPS time'}
        </span>
        <span>
          {gps.last_update ? `Updated ${relativeAge(gps.last_update)}` : ''}
        </span>
      </div>
    </div>
  );
}
