const ACCENTS = {
  red: '#d30418',
  gold: '#eca217',
  green: '#2f8f4e',
  gray: '#9a948d',
};

export default function MetricCard({ label, value, caption, accent = 'gray' }) {
  return (
    <div className="card relative overflow-hidden p-4">
      <span
        aria-hidden="true"
        className="absolute -right-5 -top-5 h-16 w-16 rounded-full opacity-10"
        style={{ background: ACCENTS[accent] || ACCENTS.gray }}
      />
      <span className="block text-[0.68rem] font-semibold uppercase tracking-wide text-[color:var(--muted)]">
        {label}
      </span>
      <b className="mt-1 block text-2xl font-extrabold tracking-tight text-[color:var(--ink)]">
        {value}
      </b>
      {caption && <small className="block text-[0.68rem] text-[color:var(--muted)]">{caption}</small>}
    </div>
  );
}
