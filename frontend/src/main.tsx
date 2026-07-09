import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BarChart3,
  BookOpen,
  ClipboardCheck,
  Compass,
  LayoutDashboard,
  Library,
  Lightbulb,
  MessageCircleQuestion,
  Search,
  ShieldCheck,
} from "lucide-react";

import { fetchPapers, fetchStats } from "./api/client";
import { AdminReviewPage } from "./pages/AdminReviewPage";
import { Dashboard } from "./pages/Dashboard";
import { EvaluationDashboardPage } from "./pages/EvaluationDashboardPage";
import { AskPage } from "./pages/AskPage";
import { PaperBrowser } from "./pages/PaperBrowser";
import { PaperDetail } from "./pages/PaperDetail";
import { SearchPage } from "./pages/SearchPage";
import { ThesisExtensionFinder } from "./pages/ThesisExtensionFinder";
import { TopicAuthorExplorer } from "./pages/TopicAuthorExplorer";
import { ListSkeleton, MetricSkeletonGrid, ToastStack } from "./components/UiPrimitives";
import type { ToastMessage, ToastTone } from "./components/UiPrimitives";
import type { Paper, Stats } from "./types/paper";
import "./styles/app.css";

type AppPage = "dashboard" | "papers" | "detail" | "search" | "ask" | "extensions" | "explorer" | "admin" | "evaluation";

const NAV_ITEMS: {
  page: Exclude<AppPage, "detail">;
  label: string;
  shortLabel: string;
  icon: typeof LayoutDashboard;
}[] = [
  { page: "dashboard", label: "Dashboard", shortLabel: "Dashboard", icon: LayoutDashboard },
  { page: "papers", label: "Papers", shortLabel: "Papers", icon: Library },
  { page: "search", label: "Search", shortLabel: "Search", icon: Search },
  { page: "ask", label: "Ask TTLAB", shortLabel: "Ask", icon: MessageCircleQuestion },
  { page: "extensions", label: "Thesis Extension Finder", shortLabel: "Extensions", icon: Lightbulb },
  { page: "explorer", label: "Topic/Author Explorer", shortLabel: "Explorer", icon: Compass },
  { page: "admin", label: "Admin Review", shortLabel: "Admin", icon: ShieldCheck },
  { page: "evaluation", label: "Evaluation", shortLabel: "Evaluation", icon: ClipboardCheck },
];

function App() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [activePage, setActivePage] = useState<AppPage>("dashboard");
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null);
  const [askPaperId, setAskPaperId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const toastId = useRef(0);

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

  function notify(message: string, tone: ToastTone = "info") {
    const id = toastId.current + 1;
    toastId.current = id;
    setToasts((current) => [...current, { id, message, tone }].slice(-4));
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 5200);
  }

  function openPaper(paperId: string) {
    const paper = papers.find((item) => item.paper_id === paperId);
    if (paper) {
      setSelectedPaper(paper);
      setActivePage("detail");
    }
  }

  function askAboutPaper(paperId: string) {
    setAskPaperId(paperId);
    setActivePage("ask");
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div className="brand-block">
          <p className="eyebrow">TTLAB Research Intelligence</p>
          <h1>Research Intelligence Platform</h1>
          <p className="app-subtitle">Full-paper discovery, grounded answers, thesis ideas, and review-ready outputs.</p>
        </div>
        <nav className="tabs" aria-label="Primary views">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = activePage === item.page || (item.page === "papers" && activePage === "detail");
            const count = navCount(item.page, stats, papers.length);
            return (
              <button className={isActive ? "active" : ""} onClick={() => setActivePage(item.page)} key={item.page}>
                <Icon size={16} aria-hidden="true" />
                <span className="tabs__label">{item.label}</span>
                <span className="tabs__short-label">{item.shortLabel}</span>
                {count !== null ? <span className="tabs__count">{count}</span> : null}
              </button>
            );
          })}
        </nav>
      </header>

      {loading ? <InitialAppSkeleton /> : null}
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
        <PaperDetail
          paper={selectedPaper}
          onBack={() => setActivePage("papers")}
          onSelectPaper={openPaper}
          onAskPaper={askAboutPaper}
          onNotify={notify}
        />
      ) : null}
      {!loading && !error && activePage === "search" ? (
        <SearchPage
          papers={papers}
          onSelectPaper={openPaper}
          onNotify={notify}
        />
      ) : null}
      {!loading && !error && activePage === "ask" ? (
        <AskPage
          papers={papers}
          onSelectPaper={openPaper}
          initialPaperId={askPaperId}
          onNotify={notify}
        />
      ) : null}
      {!loading && !error && activePage === "extensions" ? (
        <ThesisExtensionFinder
          papers={papers}
          onSelectPaper={openPaper}
          onNotify={notify}
        />
      ) : null}
      {!loading && !error && activePage === "explorer" ? (
        <TopicAuthorExplorer
          onSelectPaper={openPaper}
        />
      ) : null}
      {!loading && !error && activePage === "admin" ? (
        <AdminReviewPage
          papers={papers}
          onSelectPaper={openPaper}
          onNotify={notify}
        />
      ) : null}
      {!loading && !error && activePage === "evaluation" ? <EvaluationDashboardPage /> : null}
      <ToastStack messages={toasts} onDismiss={(id) => setToasts((current) => current.filter((toast) => toast.id !== id))} />
    </main>
  );
}

function navCount(page: Exclude<AppPage, "detail">, stats: Stats | null, paperCount: number): string | null {
  if (page === "papers") {
    return String(stats?.papers ?? paperCount);
  }
  if (page === "search") {
    return String(stats?.searchable_chunks ?? 0);
  }
  if (page === "ask") {
    return String(stats?.total_ask_answers ?? 0);
  }
  if (page === "extensions") {
    return String(stats?.total_extension_recommendation_runs ?? 0);
  }
  if (page === "explorer") {
    return String(stats?.topic_count ?? 0);
  }
  if (page === "admin") {
    return String(stats?.admin_review_queue_count ?? 0);
  }
  if (page === "evaluation") {
    return String(Object.values(stats?.evaluation_files_present ?? {}).filter(Boolean).length);
  }
  return null;
}

function InitialAppSkeleton() {
  return (
    <section className="page-section" aria-label="Loading dashboard" aria-busy="true">
      <div className="section-heading section-heading--compact">
        <h2>
          <BarChart3 size={20} aria-hidden="true" /> Loading research dashboard
        </h2>
        <BookOpen size={20} aria-hidden="true" />
      </div>
      <MetricSkeletonGrid count={8} />
      <div className="section-heading">
        <h2>Preparing recent papers</h2>
      </div>
      <ListSkeleton count={4} lines={2} />
    </section>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
