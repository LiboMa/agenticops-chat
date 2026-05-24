import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "@/components/layout/AppShell";
import { Spinner } from "@/components/ui/Spinner";
import { getAuthToken } from "@/api/client";

const Login = lazy(() => import("@/pages/Login"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Chat = lazy(() => import("@/pages/Chat"));
const IssuesAndPlans = lazy(() => import("@/pages/IssuesAndPlans"));
const IssueDetail = lazy(() => import("@/pages/IssueDetail"));
const Reports = lazy(() => import("@/pages/Reports"));
const ReportDetail = lazy(() => import("@/pages/ReportDetail"));
const Schedules = lazy(() => import("@/pages/Schedules"));
const ScheduleDetail = lazy(() => import("@/pages/ScheduleDetail"));
const Settings = lazy(() => import("@/pages/Settings"));
const ResourceDetail = lazy(() => import("@/pages/ResourceDetail"));
const AgentMetrics = lazy(() => import("@/pages/AgentMetrics"));
const Skills = lazy(() => import("@/pages/Skills"));
const SkillDetail = lazy(() => import("@/pages/SkillDetail"));

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = getAuthToken();
  if (!token) return <Navigate to="/app/login" replace />;
  return <>{children}</>;
}

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
          <Route
            path="/app/login"
            element={
              <Suspense fallback={<Spinner />}>
                <Login />
              </Suspense>
            }
          />
          <Route path="/app" element={<RequireAuth><AppShell /></RequireAuth>}>
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
              path="chat/:sessionId"
              element={
                <Suspense fallback={<Spinner />}>
                  <Chat />
                </Suspense>
              }
            />
            <Route
              path="issues"
              element={
                <Suspense fallback={<Spinner />}>
                  <IssuesAndPlans />
                </Suspense>
              }
            />
            <Route
              path="issues/:id"
              element={
                <Suspense fallback={<Spinner />}>
                  <IssueDetail />
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
              path="settings"
              element={
                <Suspense fallback={<Spinner />}>
                  <Settings />
                </Suspense>
              }
            />
            <Route
              path="resources/:id"
              element={
                <Suspense fallback={<Spinner />}>
                  <ResourceDetail />
                </Suspense>
              }
            />
            <Route
              path="agent-metrics"
              element={
                <Suspense fallback={<Spinner />}>
                  <AgentMetrics />
                </Suspense>
              }
            />
            <Route
              path="skills"
              element={
                <Suspense fallback={<Spinner />}>
                  <Skills />
                </Suspense>
              }
            />
            <Route
              path="skills/:name"
              element={
                <Suspense fallback={<Spinner />}>
                  <SkillDetail />
                </Suspense>
              }
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
