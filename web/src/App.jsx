import { usePolling } from './hooks/usePolling.js';
import MetricCard from './components/MetricCard.jsx';
import HailoCard from './components/HailoCard.jsx';
import GpsCard from './components/GpsCard.jsx';
import CameraPanel from './components/CameraPanel.jsx';
import logoUrl from './assets/logo.png';

function tempAccent(tempC) {
  if (tempC === null || tempC === undefined) return 'gray';
  if (tempC >= 80) return 'red';
  if (tempC >= 65) return 'gold';
  return 'green';
}

function fmtPercent(value) {
  return value === null || value === undefined ? '—' : `${Math.round(value)}%`;
}

function fmtUptime(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function fmtFreq(mhz) {
  if (mhz === null || mhz === undefined) return '—';
  return mhz >= 1000 ? `${(mhz / 1000).toFixed(2)} GHz` : `${Math.round(mhz)} MHz`;
}

function wifiAccent(quality) {
  if (quality === null || quality === undefined) return 'gray';
  if (quality < 30) return 'red';
  if (quality < 60) return 'gold';
  return 'green';
}

export default function App() {
  const { data: statusData, lastUpdatedAt } = usePolling('/api/status', 2000);
  const { data: hailo } = usePolling('/api/hailo', 2000);
  const { data: gps } = usePolling('/api/gps', 2000);

  const isStale = !lastUpdatedAt || Date.now() - lastUpdatedAt > 10000;
  const secondsSinceUpdate = lastUpdatedAt ? Math.round((Date.now() - lastUpdatedAt) / 1000) : null;

  const primaryIp = statusData?.ip_addresses
    ? Object.values(statusData.ip_addresses)[0]
    : null;

  const throttleWarning =
    statusData?.throttled?.under_voltage || statusData?.throttled?.throttled;

  return (
    <div className="flex w-full flex-col gap-3 p-4 lg:h-dvh lg:overflow-hidden lg:p-5">
      <header className="flex flex-none flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <img
            src={logoUrl}
            alt="CityGuard Logo"
            className="h-10 w-10 object-contain rounded-lg border border-[color:var(--line)] bg-white p-1 shadow-sm"
          />
          <div>
            <h1 className="text-xl font-extrabold tracking-tight text-[color:var(--ink)]">
              CityGuard Edge Monitor
            </h1>
            <p className="text-[0.75rem] text-[color:var(--muted)]">
              {statusData?.hostname || 'connecting…'}
              {primaryIp ? ` · ${primaryIp}` : ''}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 text-[0.7rem] text-[color:var(--muted)]">
          <span className={`live-dot ${isStale ? 'live-dot--stale' : 'live-dot--live'}`} />
          {secondsSinceUpdate === null ? 'connecting…' : `updated ${secondsSinceUpdate}s ago`}
        </div>
      </header>

      {throttleWarning && (
        <div className="flex-none rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-[0.75rem] font-semibold text-red-700">
          {statusData.throttled.under_voltage && 'Under-voltage detected. '}
          {statusData.throttled.throttled && 'Pi is throttling.'}
        </div>
      )}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[15rem_1fr_20rem]">
        <section className="grid grid-cols-2 content-start gap-2 lg:overflow-y-auto">
          <MetricCard label="CPU" value={fmtPercent(statusData?.cpu_percent)} accent="gold" />
          <MetricCard
            label="RAM"
            value={fmtPercent(statusData?.ram?.percent)}
            caption={
              statusData?.ram
                ? `${Math.round(statusData.ram.used_mb)} / ${Math.round(statusData.ram.total_mb)} MB`
                : undefined
            }
            accent="red"
          />
          <MetricCard
            label="Disk"
            value={fmtPercent(statusData?.disk?.percent)}
            caption={
              statusData?.disk
                ? `${statusData.disk.used_gb} / ${statusData.disk.total_gb} GB`
                : undefined
            }
            accent="gray"
          />
          <MetricCard
            label="CPU Temp"
            value={statusData?.cpu_temp_c !== null && statusData?.cpu_temp_c !== undefined ? `${statusData.cpu_temp_c}°C` : '—'}
            accent={tempAccent(statusData?.cpu_temp_c)}
          />
          <MetricCard
            label="Power"
            value={statusData?.power_w !== null && statusData?.power_w !== undefined ? `${statusData.power_w} W` : '—'}
            caption="internal rails"
            accent="gold"
          />
          <MetricCard label="Uptime" value={fmtUptime(statusData?.uptime_seconds)} accent="gray" />
          <MetricCard
            label="Hailo Temp"
            value={hailo?.temperature_c !== null && hailo?.temperature_c !== undefined ? `${hailo.temperature_c}°C` : '—'}
            accent={tempAccent(hailo?.temperature_c)}
          />
          <MetricCard
            label="CPU Clock"
            value={fmtFreq(statusData?.cpu_freq_mhz)}
            accent="gray"
          />
          <MetricCard
            label="Load Avg"
            value={statusData?.load_avg_1m !== null && statusData?.load_avg_1m !== undefined ? statusData.load_avg_1m.toFixed(2) : '—'}
            caption="1 minute"
            accent="gray"
          />
          <MetricCard
            label="WiFi Signal"
            value={statusData?.wifi ? `${statusData.wifi.signal_dbm} dBm` : '—'}
            caption={statusData?.wifi ? `${statusData.wifi.quality_percent}% quality` : 'no link'}
            accent={statusData?.wifi ? wifiAccent(statusData.wifi.quality_percent) : 'gray'}
          />
        </section>

        <section className="min-h-[240px] lg:min-h-0">
          <CameraPanel />
        </section>

        <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-1 lg:overflow-y-auto">
          <HailoCard hailo={hailo} />
          <GpsCard gps={gps} />
        </section>
      </div>
    </div>
  );
}
