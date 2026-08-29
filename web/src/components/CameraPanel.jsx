import { useEffect, useState } from 'react';
import { usePolling } from '../hooks/usePolling.js';

function relativeAge(isoString) {
  if (!isoString) return null;
  const seconds = Math.max(0, Math.round((Date.now() - new Date(isoString).getTime()) / 1000));
  return seconds;
}

export default function CameraPanel() {
  const { data: status } = usePolling('/api/camera/status', 3000);
  const [src, setSrc] = useState(`/api/camera/snapshot.jpg?t=${Date.now()}`);
  const [imgError, setImgError] = useState(false);

  useEffect(() => {
    const timer = setInterval(() => {
      setSrc(`/api/camera/snapshot.jpg?t=${Date.now()}`);
    }, 3000);
    return () => clearInterval(timer);
  }, []);

  const unavailable = status && status.available === false;
  const age = status ? relativeAge(status.last_capture_at) : null;

  return (
    <div className="card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-bold tracking-tight">Camera preview</h2>
        {status && age !== null && age > 4 && !unavailable && (
          <small className="text-[0.65rem] text-[color:var(--muted)]">
            showing a {age}s old frame
          </small>
        )}
      </div>
      <div className="relative aspect-video w-full max-w-xs overflow-hidden rounded-lg bg-black sm:max-w-sm">
        {unavailable || imgError ? (
          <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-[0.75rem] text-gray-300">
            <span>Camera unavailable</span>
            {status?.error && <span className="text-gray-400">{status.error}</span>}
          </div>
        ) : (
          <img
            src={src}
            alt="Live camera preview"
            className="h-full w-full object-cover"
            onError={() => setImgError(true)}
            onLoad={() => setImgError(false)}
          />
        )}
      </div>
    </div>
  );
}
