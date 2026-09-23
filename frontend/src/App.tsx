import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "@/auth/AuthProvider";
import { AppShell } from "@/app/AppShell";
import { Login } from "@/routes/Login";
import { Register } from "@/routes/Register";
import { Dashboard } from "@/routes/Dashboard";
import { Vendors } from "@/routes/Vendors";
import { VendorDetail } from "@/routes/VendorDetail";
import { Alerts } from "@/routes/Alerts";
import { Reports } from "@/routes/Reports";
import { Settings } from "@/routes/Settings";

function FullPageSpinner() {
  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "100vh" }}>
      <span className="spinner" />
    </div>
  );
}

export function App() {
  const { user, loading } = useAuth();

  if (loading) return <FullPageSpinner />;

  return (
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
      <Route path="/register" element={user ? <Navigate to="/" replace /> : <Register />} />

      {user ? (
        <Route element={<AppShell />}>
          <Route index element={<Dashboard />} />
          <Route path="vendors" element={<Vendors />} />
          <Route path="vendors/:vendorId" element={<VendorDetail />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="reports" element={<Reports />} />
          <Route path="settings" element={<Settings />} />
        </Route>
      ) : (
        <Route path="*" element={<Navigate to="/login" replace />} />
      )}

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
