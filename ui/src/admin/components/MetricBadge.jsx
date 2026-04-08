/**
 * MetricBadge — severity / tenant pill.
 * variant: critical | high | medium | low | info | neutral
 */
const V = {
  critical: 'bg-red-50    text-red-600    border-red-200',
  high:     'bg-orange-50 text-orange-600 border-orange-200',
  medium:   'bg-yellow-50 text-yellow-700 border-yellow-200',
  low:      'bg-green-50  text-green-700  border-green-200',
  info:     'bg-blue-50   text-blue-600   border-blue-200',
  neutral:  'bg-gray-100  text-gray-500   border-gray-200',
}

export default function MetricBadge({ label, variant = 'neutral' }) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-semibold tracking-wide border whitespace-nowrap ${V[variant] ?? V.neutral}`}
    >
      {label}
    </span>
  )
}
