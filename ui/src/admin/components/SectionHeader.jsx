/**
 * SectionHeader — page-level title row with optional subtitle and action slot.
 *
 * Design tokens:
 *   title    → text-xl font-semibold text-gray-900 tracking-tight
 *   subtitle → text-[13px] text-gray-400
 *   buttons  → h-9 px-4 text-[13px] font-medium rounded-lg
 */
export default function SectionHeader({ title, subtitle, actions }) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <h1 className="text-xl font-semibold text-gray-900 tracking-tight leading-tight">
          {title}
        </h1>
        {subtitle && (
          <p className="text-[13px] text-gray-400 mt-0.5 leading-snug">{subtitle}</p>
        )}
      </div>

      {actions && (
        <div className="flex items-center gap-2">{actions}</div>
      )}
    </div>
  )
}
