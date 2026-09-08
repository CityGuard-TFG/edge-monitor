import { useState } from 'react';
import { usePolling } from '../hooks/usePolling.js';

const modes = [
  {
    id: 'fixed-still',
    label: 'Fixed focus stills',
    detail: 'Legacy baseline · full-resolution JPEGs',
  },
  {
    id: 'continuous-af-still',
    label: 'Continuous autofocus',
    detail: 'AF adjusts during the route · full-resolution JPEGs',
  },
  {
    id: 'locked-af-still',
    label: 'Autofocus then lock',
    detail: 'Waits up to 5 s for focus, then locks the lens',
  },
  {
    id: 'mjpeg-video-baseline',
    label: 'MJPEG video baseline',
    detail: 'Experimental · high storage · no per-frame AF manifest',
    experimental: true,
  },
];

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(2)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(2)} KB`;
  return `${bytes} B`;
}

function formatTime(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  return `${hours}h ${minutes}m ${secs}s`;
}

export default function CollectionPanel() {
  const { data: status, error: pollError } = usePolling('/api/collection/status', 2000);
  const [isBusy, setIsBusy] = useState(false);
  const [actionError, setActionError] = useState(null);

  const handleStart = async (mode) => {
    setIsBusy(true);
    setActionError(null);
    try {
      const response = await fetch(`/api/collection/start?mode=${encodeURIComponent(mode)}`, { method: 'POST' });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Could not start collection.');
    } catch (error) {
      setActionError(error.message);
    } finally {
      setIsBusy(false);
    }
  };

  const handleStop = async () => {
    setIsBusy(true);
    setActionError(null);
    try {
      const response = await fetch('/api/collection/stop', { method: 'POST' });
      if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || 'Could not stop collection.');
    } catch (error) {
      setActionError(error.message);
    } finally {
      setIsBusy(false);
    }
  };

  const activeMode = modes.find((mode) => mode.id === status?.mode);

  return (
    <div className="card flex h-full flex-col p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-bold tracking-tight">Capture test</h2>
        <span className="text-[0.65rem] font-semibold uppercase tracking-wide text-[color:var(--muted)]">local only</span>
      </div>
      {status?.recording ? (
        <>
          <div className="mt-2 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-[0.75rem] font-semibold text-red-700">
            Recording: {activeMode?.label || status.mode}
          </div>
          <button
            onClick={handleStop}
            disabled={isBusy}
            className={`mt-2 rounded-md bg-red-500 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-600 ${isBusy ? 'cursor-not-allowed opacity-50' : ''}`}
          >
            Stop and finalise session
          </button>
        </>
      ) : (
        <div className="mt-2 grid gap-2">
          {modes.map((mode) => (
            <button
              key={mode.id}
              onClick={() => handleStart(mode.id)}
              disabled={isBusy}
              className={`rounded-md border px-3 py-2 text-left transition-colors ${mode.experimental ? 'border-amber-300 bg-amber-50 hover:bg-amber-100' : 'border-blue-200 bg-blue-50 hover:bg-blue-100'} ${isBusy ? 'cursor-not-allowed opacity-50' : ''}`}
            >
              <span className="block text-sm font-semibold text-[color:var(--ink)]">{mode.label}</span>
              <span className="block text-[0.68rem] text-[color:var(--muted)]">{mode.detail}</span>
            </button>
          ))}
        </div>
      )}
      <p className="mt-2 text-[0.68rem] leading-snug text-[color:var(--muted)]">
        Run one mode per loop under the same route, mount, and light. Still sessions save a session description, GPX, and one camera-metadata row per JPEG.
      </p>
      {(actionError || pollError || status?.error) && (
        <p className="mt-2 text-[0.7rem] font-semibold text-amber-700">{actionError || status?.error || 'Status polling failed.'}</p>
      )}
      {status?.collection_dir && (
        <a href="/api/collection/gpx" target="_blank" rel="noreferrer" className="mt-2 text-[0.75rem] text-blue-600 hover:underline">
          Download current session GPX
        </a>
      )}
      {status?.recording && (
        <div className="mt-2 text-[0.75rem] text-[color:var(--muted)]">
          <p>Elapsed: {formatTime(status.elapsed_seconds)}</p>
          <p>{status.mode === 'mjpeg-video-baseline' ? 'Video size' : 'Shots'}: {status.mode === 'mjpeg-video-baseline' ? formatBytes(status.total_bytes) : status.shot_count}</p>
          <p>Storage remaining: {status.estimated_hours_remaining !== null ? `${status.estimated_hours_remaining.toFixed(1)} hours` : 'calculating…'}</p>
          {status.focus_configuration?.lens_position !== undefined && <p>Locked lens: {Number(status.focus_configuration.lens_position).toFixed(3)}</p>}
          <p>GPS: {status.current_speed_kmh !== null ? `${status.current_speed_kmh.toFixed(0)} km/h` : 'no fix'} · {status.capturing ? 'capturing' : 'stationary (paused)'}</p>
        </div>
      )}
    </div>
  );
}
