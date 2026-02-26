import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "@/components/layout/AppShell";
import { Spinner } from "@/components/ui/Spinner";

const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Chat = lazy(() => import("@/pages/Chat"));
const Resources = lazy(() => import("@/pages/Resources"));
const Anomalies = lazy(() => import("@/pages/Anomalies"));
const AnomalyDetail = lazy(() => import("@/pages/AnomalyDetail"));
const FixPlans = lazy(() => import("@/pages/FixPlans"));
const FixPlanDetail = lazy(() => import("@/pages/FixPlanDetail"));
const Reports = lazy(() => import("@/pages/Reports"));
const ReportDetail = lazy(() => import("@/pages/ReportDetail"));
const Network = lazy(() => import("@/pages/Network"));
const Schedules = lazy(() => import("@/pages/Schedules"));
const ScheduleDetail = lazy(() => import("@/pages/ScheduleDetail"));
const Notifications = lazy(() => import("@/pages/Notifications"));
const NotificationLogs = lazy(() => import("@/pages/NotificationLogs"));
const Accounts = lazy(() => import("@/pages/Accounts"));
const AuditLog = lazy(() => import("@/pages/AuditLog"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/app" element={<AppShell />}>
            <Route
              index
              element={
                <Suspense fallback={<Spinner />}>
                  <Dashboard />
                </Suspense>
              }
            />
            <Route
              path="chat"
              element={
                <Suspense fallback={<Spinner />}>
                  <Chat />
                </Suspense>
              }
            />
            <Route
              path="resources"
              element={
                <Suspense fallback={<Spinner />}>
                  <Resources />
                </Suspense>
              }
            />
            <Route
              path="anomalies"
              element={
                <Suspense fallback={<Spinner />}>
                  <Anomalies />
                </Suspense>
              }
            />
            <Route
              path="anomalies/:id"
              element={
                <Suspense fallback={<Spinner />}>
                  <AnomalyDetail />
                </Suspense>
              }
            />
            <Route
              path="fix-plans"
              element={
                <Suspense fallback={<Spinner />}>
                  <FixPlans />
                </Suspense>
              }
            />
            <Route
              path="fix-plans/:id"
              element={
                <Suspense fallback={<Spinner />}>
                  <FixPlanDetail />
                </Suspense>
              }
            />
            <Route
              path="reports"
              element={
                <Suspense fallback={<Spinner />}>
                  <Reports />
                </Suspense>
              }
            />
            <Route
              path="reports/:id"
              element={
                <Suspense fallback={<Spinner />}>
                  <ReportDetail />
                </Suspense>
              }
            />
            <Route
              path="network"
              element={
                <Suspense fallback={<Spinner />}>
                  <Network />
                </Suspense>
              }
            />
            <Route
              path="schedules"
              element={
                <Suspense fallback={<Spinner />}>
                  <Schedules />
                </Suspense>
              }
            />
            <Route
              path="schedules/:id"
              element={
                <Suspense fallback={<Spinner />}>
                  <ScheduleDetail />
                </Suspense>
              }
            />
            <Route
              path="notifications"
              element={
                <Suspense fallback={<Spinner />}>
                  <Notifications />
                </Suspense>
              }
            />
            <Route
              path="notifications/logs"
              element={
                <Suspense fallback={<Spinner />}>
                  <NotificationLogs />
                </Suspense>
              }
            />
            <Route
              path="accounts"
              element={
                <Suspense fallback={<Spinner />}>
                  <Accounts />
                </Suspense>
              }
            />
            <Route
              path="audit"
              element={
                <Suspense fallback={<Spinner />}>
                  <AuditLog />
                </Suspense>
              }
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
