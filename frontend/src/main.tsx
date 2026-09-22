import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { queryClient } from "@/lib/queryClient";
import { ThemeProvider } from "@/theme/ThemeProvider";
import { AuthProvider } from "@/auth/AuthProvider";
import { OrgProvider } from "@/org/OrgProvider";
import { App } from "@/App";
import "@/styles/global.css";
import "@/styles/ui.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <OrgProvider>
            <BrowserRouter>
              <App />
            </BrowserRouter>
          </OrgProvider>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
);
