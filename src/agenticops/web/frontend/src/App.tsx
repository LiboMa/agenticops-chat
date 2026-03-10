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

// Legacy pages (still accessible)
const Chat = lazy(() => import("@/pages/Chat"));
const IssueDetail = lazy(() => import("@/pages/AnomalyDetail"));
const FixPlanDetail = lazy(() => import("@/pages/FixPlanDetail"));
const Network = lazy(() => import("@/pages/Network"));
const Resources = lazy(() => import("@/pages/Resources"));
const Reports = lazy(() => import("@/pages/Reports"));
const ReportDetail = lazy(() => import("@/pages/ReportDetail"));

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
            {/* 5 main views */}
            <Route index element={<S><OpsHub /></S>} />
            <Route path="diagnose" element={<S><Diagnose /></S>} />
            <Route path="ai" element={<S><AICenter /></S>} />
            <Route path="knowledge" element={<S><Knowledge /></S>} />
            <Route path="system" element={<S><System /></S>} />

            {/* Detail/legacy routes */}
            <Route path="chat" element={<S><Chat /></S>} />
            <Route path="issues/:id" element={<S><IssueDetail /></S>} />
            <Route path="fix-plans/:id" element={<S><FixPlanDetail /></S>} />
            <Route path="network" element={<S><Network /></S>} />
            <Route path="resources" element={<S><Resources /></S>} />
            <Route path="reports" element={<S><Reports /></S>} />
            <Route path="reports/:id" element={<S><ReportDetail /></S>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
