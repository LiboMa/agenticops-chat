import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation, useSearchParams } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { AppShell } from "@/components/layout/AppShell";
import { HomeResolver } from "@/components/layout/HomeResolver";
import { loginPath } from "@/lib/home";
import { queryClient } from "@/queryClient";
import { Spinner } from "@/components/ui/Spinner";
import { getAuthToken } from "@/api/client";
import { legacyPlansRedirect } from "@/lib/plans";

const Login = lazy(() => import("@/pages/Login"));
const Dashboard = lazy(() => import("@/pages/Dashboard"));
const Chat = lazy(() => import("@/pages/Chat"));
const IssuesAndPlans = lazy(() => import("@/pages/IssuesAndPlans"));
const IssueDetail = lazy(() => import("@/pages/IssueDetail"));
const Changes = lazy(() => import("@/pages/Changes"));
const Audit = lazy(() => import("@/pages/Audit"));
const ChangeDetail = lazy(() => import("@/pages/ChangeDetail"));
const Reports = lazy(() => import("@/pages/Reports"));
const ReportDetail = lazy(() => import("@/pages/ReportDetail"));
const Schedules = lazy(() => import("@/pages/Schedules"));
const ScheduleDetail = lazy(() => import("@/pages/ScheduleDetail"));
const Settings = lazy(() => import("@/pages/Settings"));
const Resources = lazy(() => import("@/pages/Resources"));
const ResourceDetail = lazy(() => import("@/pages/ResourceDetail"));
const Signals = lazy(() => import("@/pages/Signals"));
const AgentMetrics = lazy(() => import("@/pages/AgentMetrics"));
const Skills = lazy(() => import("@/pages/Skills"));
const SkillDetail = lazy(() => import("@/pages/SkillDetail"));
const Galaxy = lazy(() => import("@/pages/Galaxy"));
const Security = lazy(() => import("@/pages/Security"));
const NotFound = lazy(() => import("@/pages/NotFound"));

function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const token = getAuthToken();
  // signed out: log in, then come back exactly here (path, query and hash)
  if (!token) return <Navigate to={loginPath(location)} replace />;
  return <>{children}</>;
}

/** `/app/plans` was split into Changes + Audit (MVP-2.6.1); an old bookmark lands on the page that replaced its tab. */
function LegacyPlansRedirect() {
  const [params] = useSearchParams();
  return <Navigate to={legacyPlansRedirect(params.get("tab"))} replace />;
}

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
            {/* /app: a pinned home, the last place, or Chat (MVP-2.7.0); the dashboard lives at /app/overview */}
            <Route index element={<HomeResolver />} />
            <Route
              path="overview"
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
            <Route path="plans" element={<LegacyPlansRedirect />} />
            <Route
              path="changes"
              element={
                <Suspense fallback={<Spinner />}>
                  <Changes />
                </Suspense>
              }
            />
            <Route
              path="changes/:id"
              element={
                <Suspense fallback={<Spinner />}>
                  <ChangeDetail />
                </Suspense>
              }
            />
            <Route
              path="audit"
              element={
                <Suspense fallback={<Spinner />}>
                  <Audit />
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
              path="resources"
              element={
                <Suspense fallback={<Spinner />}>
                  <Resources />
                </Suspense>
              }
            />
            <Route
              path="signals"
              element={
                <Suspense fallback={<Spinner />}>
                  <Signals />
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
            <Route
              path="galaxy"
              element={
                <Suspense fallback={<Spinner />}>
                  <Galaxy />
                </Suspense>
              }
            />
            <Route
              path="security"
              element={
                <Suspense fallback={<Spinner />}>
                  <Security />
                </Suspense>
              }
            />
            <Route
              path="*"
              element={
                <Suspense fallback={<Spinner />}>
                  <NotFound />
                </Suspense>
              }
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
