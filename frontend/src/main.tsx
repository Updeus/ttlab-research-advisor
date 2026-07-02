import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import { fetchPapers, fetchStats } from "./api/client";
import { Dashboard } from "./pages/Dashboard";
import { PaperBrowser } from "./pages/PaperBrowser";
import { PaperDetail } from "./pages/PaperDetail";
import type { Paper, Stats } from "./types/paper";
import "./styles/app.css";

function App() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [activePage, setActivePage] = useState<"dashboard" | "papers" | "detail">("dashboard");
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([fetchPapers(), fetchStats()])
      .then(([paperRows, statRows]) => {
        setPapers(paperRows);
        setStats(statRows);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Unable to load backend data.");
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <p className="eyebrow">TTLAB Research Intelligence</p>
          <h1>Publication Discovery Console</h1>
        </div>
        <nav className="tabs" aria-label="Primary views">
          <button className={activePage === "dashboard" ? "active" : ""} onClick={() => setActivePage("dashboard")}>
            Dashboard
          </button>
          <button className={activePage === "papers" || activePage === "detail" ? "active" : ""} onClick={() => setActivePage("papers")}>
            Papers
          </button>
        </nav>
      </header>

      {loading ? <p className="notice">Loading paper records...</p> : null}
      {error ? <p className="notice notice--error">Backend unavailable: {error}</p> : null}
      {!loading && !error && activePage === "dashboard" ? <Dashboard stats={stats} papers={papers} /> : null}
      {!loading && !error && activePage === "papers" ? (
        <PaperBrowser
          papers={papers}
          onSelectPaper={(paper) => {
            setSelectedPaper(paper);
            setActivePage("detail");
          }}
        />
      ) : null}
      {!loading && !error && activePage === "detail" && selectedPaper ? (
        <PaperDetail paper={selectedPaper} onBack={() => setActivePage("papers")} />
      ) : null}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
