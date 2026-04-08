import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import App from './App.jsx'
import { AppShell as DashboardLayout } from './admin/shell/AppShell.jsx'
import Dashboard from './admin/pages/Dashboard.jsx'
import Alerts      from './admin/pages/Alerts.jsx'
import Inventory   from './admin/pages/Inventory.jsx'
import Placeholder from './admin/pages/Placeholder.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        {/* Chat UI */}
        <Route path="/" element={<App />} />

        {/* Admin UI */}
        <Route path="/admin" element={<DashboardLayout />}>
          <Route index element={<Dashboard />} />
          <Route path="posture"      element={<Placeholder title="Posture"          description="Real-time posture score breakdown per tenant and model." />} />
          <Route path="alerts"       element={<Alerts />} />
          <Route path="inventory"    element={<Inventory />} />
          <Route path="data"         element={<Placeholder title="Data & Knowledge" description="Knowledge bases, retrieval sources, and data lineage." />} />
          <Route path="identity"     element={<Placeholder title="Identity & Trust" description="User identities, roles, and trust scores." />} />
          <Route path="runtime"      element={<Placeholder title="Runtime"          description="Live request monitoring and CEP event stream." />} />
          <Route path="policies"     element={<Placeholder title="Policies"         description="OPA policy management and version history." />} />
          <Route path="lineage"      element={<Placeholder title="Lineage"          description="Model and data lineage graph." />} />
          <Route path="simulation"   element={<Placeholder title="Simulation"       description="Policy simulator — dry-run rules against sample events." />} />
          <Route path="cases"        element={<Placeholder title="Cases"            description="Investigation cases and audit trail." />} />
          <Route path="automation"   element={<Placeholder title="Automation"       description="Automated response playbooks and triggers." />} />
          <Route path="integrations" element={<Placeholder title="Integrations"     description="Connected data sources, SIEMs, and ticketing systems." />} />
          <Route path="settings"     element={<Placeholder title="Settings"         description="Tenant configuration, thresholds, and notifications." />} />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>
)
