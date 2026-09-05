import { useState } from 'react';
import { usePolling } from '../hooks/usePolling.js';

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
  const { data: status, error } = usePolling('/api/collection/status', 2000);
  const [isBusy, setIsBusy] = useState(false);

  const handleStart = async () => {
    setIsBusy(true);
    try {
      await fetch('/api/collection/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ segment_ms: 60000 })
      });
    } finally {
      setIsBusy(false);
    }
  };

  const handleStop = async () => {
    setIsBusy(true);
    try {
      await fetch('/api/collection/stop', { method: 'POST' });
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <div className="card flex h-full flex-col p-4">
      <h2 className="text-sm font-bold tracking-tight">Data Collection</h2>
      {status?.recording && (
        <div className="flex-none rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-[0.75rem] font-semibold text-red-700 mt-2">
          Recording is active
        </div>
      )}
      <div className="mt-2 flex flex-col gap-2">
        <button
          onClick={status?.recording ? handleStop : handleStart}
          disabled={isBusy}
          className={`px-3 py-1.5 text-sm font-medium rounded-md ${status?.recording ? 'bg-red-500 hover:bg-red-600 text-white' : 'bg-blue-500 hover:bg-blue-600 text-white'} ${isBusy ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          {status?.recording ? 'Stop Recording' : 'Start Recording'}
        </button>
        {status?.collection_dir && (
          <a
            href="/api/collection/gpx"
            target="_blank"
            rel="noreferrer"
            className="text-[0.75rem] text-blue-500 hover:underline"
          >
            Download GPX track
          </a>
        )}
        {status?.error && (
          <p className="text-[0.7rem] font-semibold text-amber-600">
            {status.error}
          </p>
        )}
        {status?.recording && (
          <div className="mt-2 text-[0.75rem] text-[color:var(--muted)]">
            <p>Elapsed: {formatTime(status.elapsed_seconds)}</p>
            <p>Segments: {status.segment_count}</p>
            <p>Size: {formatBytes(status.total_bytes)}</p>
            <p>Storage remaining: {status.estimated_hours_remaining !== null ? `${status.estimated_hours_remaining.toFixed(1)} hours` : 'calculating…'}</p>
          </div>
        )}
      </div>
    </div>
  );
}
