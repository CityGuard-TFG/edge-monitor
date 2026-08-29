import { useEffect, useRef, useState } from 'react';

/**
 * Polls `url` every `intervalMs`, keeping the last-known good `data` on the
 * screen (grayed out via `lastUpdatedAt` staleness, not hidden) whenever a
 * request fails -- diagnosing a flaky device is the whole point of this tool.
 */
export function usePolling(url, intervalMs) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState(null);

  useEffect(() => {
    let cancelled = false;
    let timer;
    const controller = new AbortController();

    async function poll() {
      try {
        const res = await fetch(url, { signal: controller.signal });
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const json = await res.json();
        if (!cancelled) {
          setData(json);
          setError(null);
          setLastUpdatedAt(Date.now());
        }
      } catch (err) {
        if (!cancelled && err.name !== 'AbortError') {
          setError(err.message || 'request failed');
        }
      } finally {
        if (!cancelled) {
          timer = setTimeout(poll, intervalMs);
        }
      }
    }

    poll();

    return () => {
      cancelled = true;
      controller.abort();
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, intervalMs]);

  return { data, error, lastUpdatedAt };
}
