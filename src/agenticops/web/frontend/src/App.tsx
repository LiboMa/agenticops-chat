import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "@/components/layout/AppShell";
import { Spinner } from "@/components/ui/Spinner";

// New 5-view pages
const OpsHub = lazy(() => import("@/pages/OpsHub"));
const Diagnose = lazy(() => import("@/pages/Diagnose"));
const AICenter = lazy(() => import("@/pages/AICenter"));
const Knowledge = lazy(() => import("@/pages/Knowledge"));
const System = lazy(() => import("@/pages/System"));

// Original pages (ALL restored)
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Chat = lazy(() => import("@/pages/Chat"));
const Resources = lazy(() => import("@/pages/Resources"));
const Issues = lazy(() => import("@/pages/Anomalies"));
const IssueDetail = lazy(() => import("@/pages/AnomalyDetail"));
const FixPlans = lazy(() => import("@/pages/FixPlans"));
const FixPlanDetail = lazy(() => import("@/pages/FixPlanDetail"));
const Reports = lazy(() => import("@/pages/Reports"));
const ReportDetail = lazy(() => import("@/pages/ReportDetail"));
const Network = lazy(() => import("@/pages/Network"));
const Schedules = lazy(() => import("@/pages/Schedules"));
const ScheduleDetail = lazy(() => import("@/pages/ScheduleDetail"));
const Notifications = lazy(() => import("@/pages/Notifications"));
const NotificationLogs = lazy(() => import("@/pages/NotificationLogs"));
const Settings = lazy(() => import("@/pages/Settings"));
const AuditLog = lazy(() => import("@/pages/AuditLog"));
const KnowledgeBase = lazy(() => import("@/pages/KnowledgeBase"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function S({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<Spinner />}>{children}</Suspense>;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/app" element={<AppShell />}>
            {/* New aggregated views */}
            <Route index element={<S><OpsHub /></S>} />
            <Route path="diagnose" element={<S><Diagnose /></S>} />
            <Route path="ai" element={<S><AICenter /></S>} />
            <Route path="knowledge" element={<S><Knowledge /></S>} />
            <Route path="system" element={<S><System /></S>} />

            {/* ALL original pages restored */}
            <Route path="dashboard" element={<S><Dashboard /></S>} />
            <Route path="chat" element={<S><Chat /></S>} />
            <Route path="issues" element={<S><Issues /></S>} />
            <Route path="issues/:id" element={<S><IssueDetail /></S>} />
            <Route path="fix-plans" element={<S><FixPlans /></S>} />
            <Route path="fix-plans/:id" element={<S><FixPlanDetail /></S>} />
            <Route path="network" element={<S><Network /></S>} />
            <Route path="resources" element={<S><Resources /></S>} />
            <Route path="reports" element={<S><Reports /></S>} />
            <Route path="reports/:id" element={<S><ReportDetail /></S>} />
            <Route path="schedules" element={<S><Schedules /></S>} />
            <Route path="schedules/:id" element={<S><ScheduleDetail /></S>} />
            <Route path="notifications" element={<S><Notifications /></S>} />
            <Route path="notification-logs" element={<S><NotificationLogs /></S>} />
            <Route path="settings" element={<S><Settings /></S>} />
            <Route path="audit-log" element={<S><AuditLog /></S>} />
            <Route path="knowledge-base" element={<S><KnowledgeBase /></S>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
