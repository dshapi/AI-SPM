// src/index.jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import App                 from './App.jsx'
import { AppShell as DashboardLayout } from './admin/shell/AppShell.jsx'
import Overview      from './admin/pages/Overview.jsx'
import Dashboard     from './admin/pages/Dashboard.jsx'
import Posture       from './admin/pages/Posture.jsx'
import Alerts        from './admin/pages/Alerts.jsx'
import Inventory     from './admin/pages/Inventory.jsx'
import Runtime       from './admin/pages/Runtime.jsx'
import Policies      from './admin/pages/Policies.jsx'
import Lineage       from './admin/pages/Lineage.jsx'
import Simulation    from './admin/pages/Simulation.jsx'
import Cases         from './admin/pages/Cases.jsx'
import Automation    from './admin/pages/Automation.jsx'
import Integrations  from './admin/pages/Integrations.jsx'
import Identity      from './admin/pages/Identity.jsx'
import Data          from './admin/pages/Data.jsx'
import Placeholder   from './admin/pages/Placeholder.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
          {/* Chat UI */}
          <Route path="/" element={<App />} />

          {/* Admin UI */}
          <Route path="/admin" element={<DashboardLayout />}>

            <Route index element={<Overview />} />

            {/* ── Command center ── */}
            <Route path="overview"     element={<Overview />} />

            {/* ── Monitor ── */}
            <Route path="dashboard"    element={<Dashboard />} />
            <Route path="posture"      element={<Posture />} />
            <Route path="alerts"       element={<Alerts />} />
            <Route path="alerts/:alertId" element={<Alerts />} />

            {/* ── Discover ── */}
            <Route path="inventory"    element={<Inventory />} />
            <Route path="inventory/:assetId" element={<Inventory />} />
            <Route path="identity"     element={<Identity />} />
            <Route path="data"         element={<Data />} />

            {/* ── Protect ── */}
            <Route path="runtime"      element={<Runtime />} />
            <Route path="runtime/:sessionId" element={<Runtime />} />
            <Route path="policies"     element={<Policies />} />
            <Route path="policies/:policyId" element={<Policies />} />
            <Route path="lineage"      element={<Lineage />} />
            <Route path="lineage/:sessionId" element={<Lineage />} />

            {/* ── Validate ── */}
            <Route path="simulation"   element={<Simulation />} />
            <Route path="cases"        element={<Cases />} />
            <Route path="cases/:caseId" element={<Cases />} />
            <Route path="automation"   element={<Automation />} />

            {/* ── Platform ── */}
            <Route path="integrations" element={<Integrations />} />
            <Route path="settings"     element={<Placeholder title="Settings" description="Configuration, thresholds, and notifications." />} />
          </Route>

          {/* Any unknown path → Overview */}
          <Route path="*" element={<Navigate to="/admin/overview" replace />} />
        </Routes>
    </BrowserRouter>
  </React.StrictMode>
)

