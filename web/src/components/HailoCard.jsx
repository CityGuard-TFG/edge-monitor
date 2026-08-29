export default function HailoCard({ hailo }) {
  const detected = hailo?.detected;
  return (
    <div className="card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-bold tracking-tight">Hailo-8L</h2>
        <span
          className={
            'rounded-full px-2.5 py-1 text-[0.65rem] font-bold ' +
            (detected ? 'bg-green-100 text-green-700' : 'bg-gray-200 text-gray-600')
          }
        >
          {detected ? 'Detected' : 'Not detected'}
        </span>
      </div>
      {detected ? (
        <dl className="grid grid-cols-2 gap-y-1 text-[0.75rem]">
          <dt className="text-[color:var(--muted)]">Board</dt>
          <dd className="text-right font-semibold">{hailo.board_name}</dd>
          <dt className="text-[color:var(--muted)]">Architecture</dt>
          <dd className="text-right font-semibold">{hailo.architecture}</dd>
          <dt className="text-[color:var(--muted)]">Firmware</dt>
          <dd className="text-right font-semibold">{hailo.firmware_version}</dd>
          <dt className="text-[color:var(--muted)]">Temperature</dt>
          <dd className="text-right font-semibold">
            {hailo.temperature_c !== null && hailo.temperature_c !== undefined
              ? `${hailo.temperature_c}°C`
              : '—'}
          </dd>
          <dt className="text-[color:var(--muted)]">Usage</dt>
          <dd className="text-right font-semibold text-[color:var(--muted)]">
            Idle · no model loaded
          </dd>
        </dl>
      ) : (
        <p className="text-[0.75rem] text-[color:var(--muted)]">
          {hailo?.error || 'Waiting for a status check…'}
        </p>
      )}
    </div>
  );
}
