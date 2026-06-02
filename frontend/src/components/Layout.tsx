import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Navbar } from "./Navbar";

export function Layout() {
  return (
    <div className="flex h-screen bg-bb-dark">
      <Sidebar />
      <div className="flex flex-1 flex-col lg:ml-56">
        <Navbar />
        <main className="flex-1 overflow-auto p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
