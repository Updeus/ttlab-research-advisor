import { useEffect, useRef, useState } from "react";
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
import {
  Link,
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";

import {
  fetchPapers,
  fetchServiceStatus,
  fetchStats,
  hasReviewerToken,
  setReviewerToken,
} from "./api/client";
import { ListSkeleton, MetricSkeletonGrid, ToastStack } from "./components/UiPrimitives";
import type { ToastMessage, ToastTone } from "./components/UiPrimitives";
import { AdminReviewPage } from "./pages/AdminReviewPage";
import { AskPage } from "./pages/AskPage";
import { Dashboard } from "./pages/Dashboard";
import { EvaluationDashboardPage } from "./pages/EvaluationDashboardPage";
import { PaperBrowser } from "./pages/PaperBrowser";
import { PaperDetail } from "./pages/PaperDetail";
import { SearchPage } from "./pages/SearchPage";
import { ThesisExtensionFinder } from "./pages/ThesisExtensionFinder";
import { TopicAuthorExplorer } from "./pages/TopicAuthorExplorer";
import type { Paper, ServiceStatus, Stats } from "./types/paper";

type NavItem = {
  path: string;
  label: string;
  shortLabel: string;
  icon: typeof LayoutDashboard;
  count: (stats: Stats | null, paperCount: number) => string | null;
};

const NAV_ITEMS: NavItem[] = [
  { path: "/", label: "Dashboard", shortLabel: "Dashboard", icon: LayoutDashboard, count: () => null },
  { path: "/papers", label: "Papers", shortLabel: "Papers", icon: Library, count: (stats, papers) => String(stats?.papers ?? papers) },
  { path: "/search", label: "Search", shortLabel: "Search", icon: Search, count: (stats) => String(stats?.searchable_chunks ?? 0) },
  { path: "/ask", label: "Ask TTLAB", shortLabel: "Ask", icon: MessageCircleQuestion, count: (stats) => String(stats?.total_ask_answers ?? 0) },
  { path: "/extensions", label: "Thesis Extension Finder", shortLabel: "Extensions", icon: Lightbulb, count: (stats) => String(stats?.total_extension_recommendation_runs ?? 0) },
  { path: "/explorer", label: "Topic/Author Explorer", shortLabel: "Explorer", icon: Compass, count: (stats) => String(stats?.topic_count ?? 0) },
  { path: "/admin", label: "Admin Review", shortLabel: "Admin", icon: ShieldCheck, count: (stats) => String(stats?.admin_review_queue_count ?? 0) },
  { path: "/evaluation", label: "Evaluation", shortLabel: "Evaluation", icon: ClipboardCheck, count: (stats) => String(Object.values(stats?.evaluation_files_present ?? {}).filter(Boolean).length) },
];

export function App() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [serviceStatus, setServiceStatus] = useState<ServiceStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statsWarning, setStatsWarning] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const toastId = useRef(0);
  const mainRef = useRef<HTMLElement>(null);
  const location = useLocation();

  function loadData() {
    setLoading(true);
    setError(null);
    setStatsWarning(null);
    Promise.allSettled([fetchPapers(), fetchStats(), fetchServiceStatus()])
      .then(([paperResult, statsResult, serviceResult]) => {
        if (paperResult.status === "rejected") {
          throw paperResult.reason;
        }
        setPapers(paperResult.value);
        if (statsResult.status === "fulfilled") {
          setStats(statsResult.value);
        } else {
          setStats(null);
          setStatsWarning("Platform statistics are unavailable; publication records remain usable.");
        }
        setServiceStatus(serviceResult.status === "fulfilled" ? serviceResult.value : null);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Unable to load publication records.");
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadData();
  }, []);

  useEffect(() => {
    const title = titleForPath(location.pathname);
    document.title = `${title} | TTLAB Research Intelligence`;
    mainRef.current?.focus({ preventScroll: true });
  }, [location.pathname]);

  function notify(message: string, tone: ToastTone = "info") {
    const id = toastId.current + 1;
    toastId.current = id;
    setToasts((current) => [...current, { id, message, tone }].slice(-4));
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 5200);
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <header className="app-header">
        <div className="brand-block">
          <p className="eyebrow">TTLAB Research Intelligence</p>
          <h1>Research Intelligence Platform</h1>
          <p className="app-subtitle">Full-paper discovery, grounded answers, thesis ideas, and review-ready outputs.</p>
          <SecurityMode status={serviceStatus} />
        </div>
        <nav className="tabs" aria-label="Primary">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const count = item.count(stats, papers.length);
            return (
              <NavLink
                className={({ isActive }) => isActive ? "active" : undefined}
                end={item.path === "/"}
                key={item.path}
                to={item.path}
              >
                <Icon size={16} aria-hidden="true" />
                <span className="tabs__label">{item.label}</span>
                <span className="tabs__short-label">{item.shortLabel}</span>
                {count !== null ? <span className="tabs__count" aria-label={`${count} ${item.shortLabel.toLowerCase()}`}>{count}</span> : null}
              </NavLink>
            );
          })}
        </nav>
      </header>

      <p className="sr-only" role="status" aria-live="polite">{titleForPath(location.pathname)} view loaded</p>
      <main id="main-content" ref={mainRef} tabIndex={-1}>
        {loading ? <InitialAppSkeleton /> : null}
        {error ? (
          <section className="page-section" aria-labelledby="startup-error-title">
            <div className="notice notice--error" role="alert">
              <h2 id="startup-error-title">Publication service unavailable</h2>
              <p>{error}</p>
              <button className="action-button" onClick={loadData}>Retry</button>
            </div>
          </section>
        ) : null}
        {!loading && !error && statsWarning ? <p className="notice notice--warning" role="status">{statsWarning}</p> : null}
        {!loading && !error ? (
          <AppRoutes papers={papers} stats={stats} serviceStatus={serviceStatus} notify={notify} />
        ) : null}
      </main>
      <footer className="app-footer">
        <p>Generated answers and suggestions require source checking and human review. Public profile inputs are sent only for the current request.</p>
      </footer>
      <ToastStack messages={toasts} onDismiss={(id) => setToasts((current) => current.filter((toast) => toast.id !== id))} />
    </div>
  );
}

function AppRoutes({
  papers,
  stats,
  serviceStatus,
  notify,
}: {
  papers: Paper[];
  stats: Stats | null;
  serviceStatus: ServiceStatus | null;
  notify: (message: string, tone?: ToastTone) => void;
}) {
  const navigate = useNavigate();
  const openPaper = (paperId: string) => navigate(`/papers/${encodeURIComponent(paperId)}`);

  return (
    <Routes>
      <Route path="/" element={<Dashboard stats={stats} papers={papers} />} />
      <Route path="/papers" element={<PaperBrowser papers={papers} />} />
      <Route path="/papers/:paperId" element={<PaperRoute papers={papers} onSelectPaper={openPaper} onNotify={notify} />} />
      <Route path="/search" element={<SearchPage papers={papers} onSelectPaper={openPaper} onNotify={notify} />} />
      <Route path="/ask" element={<AskPage papers={papers} onSelectPaper={openPaper} onNotify={notify} />} />
      <Route path="/ask/:paperId" element={<AskRoute papers={papers} onSelectPaper={openPaper} onNotify={notify} />} />
      <Route path="/extensions" element={<ThesisExtensionFinder papers={papers} onSelectPaper={openPaper} onNotify={notify} />} />
      <Route path="/explorer" element={<TopicAuthorExplorer onSelectPaper={openPaper} />} />
      <Route path="/explorer/topics" element={<TopicAuthorExplorer initialTab="topics" onSelectPaper={openPaper} />} />
      <Route path="/explorer/topics/:topicId" element={<ExplorerTopicRoute onSelectPaper={openPaper} />} />
      <Route path="/explorer/authors" element={<TopicAuthorExplorer initialTab="authors" onSelectPaper={openPaper} />} />
      <Route path="/explorer/authors/:authorId" element={<ExplorerAuthorRoute onSelectPaper={openPaper} />} />
      <Route path="/evaluation" element={<EvaluationDashboardPage />} />
      <Route path="/admin" element={<AdminGate papers={papers} serviceStatus={serviceStatus} onSelectPaper={openPaper} onNotify={notify} />} />
      <Route path="/dashboard" element={<Navigate replace to="/" />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

function PaperRoute({ papers, onSelectPaper, onNotify }: { papers: Paper[]; onSelectPaper: (paperId: string) => void; onNotify: (message: string, tone?: ToastTone) => void }) {
  const { paperId = "" } = useParams();
  const navigate = useNavigate();
  const paper = papers.find((item) => item.paper_id === paperId);
  if (!paper) {
    return <NotFound title="Paper not found" body="This paper ID is not present in the public publication snapshot." />;
  }
  return (
    <PaperDetail
      paper={paper}
      onBack={() => navigate("/papers")}
      onSelectPaper={onSelectPaper}
      onAskPaper={(id) => navigate(`/ask/${encodeURIComponent(id)}`)}
      onNotify={onNotify}
      canGenerateArtifacts={hasReviewerToken()}
    />
  );
}

function AskRoute({ papers, onSelectPaper, onNotify }: { papers: Paper[]; onSelectPaper: (paperId: string) => void; onNotify: (message: string, tone?: ToastTone) => void }) {
  const { paperId } = useParams();
  return <AskPage papers={papers} onSelectPaper={onSelectPaper} initialPaperId={paperId} onNotify={onNotify} />;
}

function ExplorerTopicRoute({ onSelectPaper }: { onSelectPaper: (paperId: string) => void }) {
  const { topicId } = useParams();
  return <TopicAuthorExplorer initialTab="topics" initialTopicId={topicId} onSelectPaper={onSelectPaper} />;
}

function ExplorerAuthorRoute({ onSelectPaper }: { onSelectPaper: (paperId: string) => void }) {
  const { authorId } = useParams();
  const parsed = Number(authorId);
  return Number.isInteger(parsed) && parsed > 0
    ? <TopicAuthorExplorer initialTab="authors" initialAuthorId={parsed} onSelectPaper={onSelectPaper} />
    : <NotFound title="Author not found" body="Author identifiers must be positive integers." />;
}

function AdminGate({ papers, serviceStatus, onSelectPaper, onNotify }: { papers: Paper[]; serviceStatus: ServiceStatus | null; onSelectPaper: (paperId: string) => void; onNotify: (message: string, tone?: ToastTone) => void }) {
  const demoBypass = serviceStatus?.admin_authentication === "insecure_local_demo_bypass";
  const [credentialLoaded, setCredentialLoaded] = useState(hasReviewerToken());
  const [tokenInput, setTokenInput] = useState("");

  if (!demoBypass && !credentialLoaded) {
    return (
      <section className="page-section auth-gate" aria-labelledby="admin-auth-title">
        <p className="eyebrow">Protected reviewer surface</p>
        <h2 id="admin-auth-title">Reviewer authentication required</h2>
        <p>Enter an environment-provisioned reviewer or administrator bearer token. The token is held only in page memory, is never written to local or session storage, and is cleared on reload.</p>
        <form onSubmit={(event) => {
          event.preventDefault();
          setReviewerToken(tokenInput);
          setTokenInput("");
          setCredentialLoaded(true);
        }}>
          <label htmlFor="reviewer-token">Reviewer bearer token</label>
          <input id="reviewer-token" type="password" autoComplete="off" minLength={32} required value={tokenInput} onChange={(event) => setTokenInput(event.target.value)} />
          <button className="action-button" type="submit">Open protected review</button>
        </form>
      </section>
    );
  }

  return (
    <>
      <div className={`notice ${demoBypass ? "notice--warning" : "notice--success"}`} role="status">
        {demoBypass
          ? "Insecure local-demo bypass is active. Do not expose this configuration on a network."
          : "A reviewer credential is loaded in page memory for protected API requests."}
        {!demoBypass ? <button className="link-button" onClick={() => { setReviewerToken(""); setCredentialLoaded(false); }}>Clear credential</button> : null}
      </div>
      <AdminReviewPage papers={papers} onSelectPaper={onSelectPaper} onNotify={onNotify} />
    </>
  );
}

function SecurityMode({ status }: { status: ServiceStatus | null }) {
  if (!status) {
    return <span className="environment-badge environment-badge--unknown">Security mode unavailable</span>;
  }
  const insecure = status.admin_authentication === "insecure_local_demo_bypass";
  return (
    <span className={`environment-badge ${insecure ? "environment-badge--warning" : "environment-badge--secure"}`}>
      {insecure ? "Insecure local demo" : `${status.security_mode.replaceAll("_", " ")} · protected administration`}
    </span>
  );
}

function NotFound({ title = "Page not found", body = "The requested route is not part of this research-intelligence interface." }: { title?: string; body?: string }) {
  return (
    <section className="page-section" aria-labelledby="not-found-title">
      <h2 id="not-found-title">{title}</h2>
      <p>{body}</p>
      <Link className="action-link" to="/">Return to dashboard</Link>
    </section>
  );
}

function InitialAppSkeleton() {
  return (
    <section className="page-section" aria-label="Loading dashboard" aria-busy="true">
      <div className="section-heading section-heading--compact">
        <h2><BarChart3 size={20} aria-hidden="true" /> Loading research dashboard</h2>
        <BookOpen size={20} aria-hidden="true" />
      </div>
      <MetricSkeletonGrid count={8} />
      <div className="section-heading"><h2>Preparing recent papers</h2></div>
      <ListSkeleton count={4} lines={2} />
    </section>
  );
}

function titleForPath(pathname: string): string {
  if (pathname === "/") return "Dashboard";
  if (pathname.startsWith("/papers/")) return "Paper Detail";
  if (pathname === "/papers") return "Paper Browser";
  if (pathname.startsWith("/ask")) return "Ask TTLAB";
  if (pathname === "/search") return "Search";
  if (pathname === "/extensions") return "Thesis Extension Finder";
  if (pathname.startsWith("/explorer/topics")) return "Topic Explorer";
  if (pathname.startsWith("/explorer/authors")) return "Author Explorer";
  if (pathname === "/explorer") return "Topic and Author Explorer";
  if (pathname === "/evaluation") return "Evaluation Dashboard";
  if (pathname === "/admin") return "Admin Review";
  return "Page Not Found";
}
