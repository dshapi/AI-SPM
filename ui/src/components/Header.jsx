export default function Header({ model, models, onModelChange, onNewChat }) {
  return (
    <header style={{
      height: 54,
      borderBottom: '1px solid var(--border)',
      display: 'flex',
      alignItems: 'center',
      padding: '0 20px',
      gap: 12,
      background: 'rgba(255,255,255,0.92)',
      backdropFilter: 'blur(12px)',
      position: 'sticky',
      top: 0,
      zIndex: 100,
    }}>
      {/* Wordmark */}
      <div style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
        <span style={{ fontWeight: 700, fontSize: 16, letterSpacing: '-0.02em', color: 'var(--text)' }}>
          Orbyx
        </span>
      </div>

      {/* Model selector */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        background: 'var(--bg-2)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        padding: '4px 10px',
        fontSize: 13,
      }}>
        <span style={{ color: 'var(--text-3)', fontSize: 11 }}>Model</span>
        <select
          value={model}
          onChange={e => onModelChange(e.target.value)}
          style={{
            border: 'none', background: 'transparent',
            fontSize: 13, color: 'var(--text)',
            cursor: 'pointer', outline: 'none', fontWeight: 500,
          }}
        >
          {models.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select>
      </div>

      {/* New chat */}
      <button
        onClick={onNewChat}
        style={{
          display: 'flex', alignItems: 'center', gap: 5,
          background: 'var(--bg-2)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: '5px 12px',
          fontSize: 13, fontWeight: 500,
          color: 'var(--text-2)',
          transition: 'background var(--transition), color var(--transition)',
        }}
        onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-3)'; e.currentTarget.style.color = 'var(--text)' }}
        onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-2)'; e.currentTarget.style.color = 'var(--text-2)' }}
      >
        <span style={{ fontSize: 15, lineHeight: 1 }}>+</span>
        New chat
      </button>
    </header>
  )
}
