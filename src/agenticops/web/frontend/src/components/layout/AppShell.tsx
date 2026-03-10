import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";

export function AppShell() {
  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <Sidebar />
      <div className="pl-56">
        <main className="p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
