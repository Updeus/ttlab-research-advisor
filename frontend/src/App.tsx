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
  ApiError,
  fetchPaper,
  fetchPapers,
  fetchAdminIdentity,
  fetchFeatures,
  fetchServiceStatus,
  fetchStats,
  hasReviewerToken,
  isAbortError,
  loginAdmin,
  changeAdminPassword,
  logoutAdmin,
  setReviewerToken,
} from "./api/client";
import type { FeatureStatus } from "./api/client";
import { ListSkeleton, MetricSkeletonGrid, ToastStack } from "./components/UiPrimitives";
import type { ToastMessage, ToastTone } from "./components/UiPrimitives";
import { AdminReviewPage } from "./pages/AdminReviewPage";
import { AskPage } from "./pages/AskPage";
import { Dashboard } from "./pages/Dashboard";
import { EvaluationDashboardPage } from "./pages/EvaluationDashboardPage";
import { IdeaGeneratorPage } from "./pages/IdeaGeneratorPage";
import { PaperBrowser } from "./pages/PaperBrowser";
import { PaperDetail } from "./pages/PaperDetail";
import { SearchPage } from "./pages/SearchPage";
import { TopicAuthorExplorer } from "./pages/TopicAuthorExplorer";
import type { Paper, ServiceStatus, Stats } from "./types/paper";

type NavItem = {
  path: string;
  label: string;
  shortLabel: string;
  icon: typeof LayoutDashboard;
  count: (stats: Stats | null, paperCount: number) => string | null;
  feature?: string;
  adminOnly?: boolean;
};

const NAV_ITEMS: NavItem[] = [
  { path: "/", label: "Dashboard", shortLabel: "Dashboard", icon: LayoutDashboard, count: () => null },
  { path: "/papers", label: "Papers", shortLabel: "Papers", icon: Library, feature: "papers", count: (stats, papers) => String(stats?.papers ?? papers) },
  { path: "/search", label: "Search", shortLabel: "Search", icon: Search, feature: "search", count: (stats) => String(stats?.searchable_chunks ?? 0) },
  { path: "/ask", label: "Ask TTLAB", shortLabel: "Ask", icon: MessageCircleQuestion, feature: "ask", count: () => null },
  { path: "/extensions", label: "Idea Generator", shortLabel: "Ideas", icon: Lightbulb, feature: "finder", count: () => null },
  { path: "/explorer", label: "Topic/Author Explorer", shortLabel: "Explorer", icon: Compass, feature: "explorer", count: (stats) => String(stats?.topic_count ?? 0) },
  { path: "/admin", label: "Admin Control", shortLabel: "Admin", icon: ShieldCheck, adminOnly: true, count: () => null },
  { path: "/evaluation", label: "Evaluation", shortLabel: "Evaluation", icon: ClipboardCheck, feature: "evaluation", count: (stats) => String(Object.values(stats?.evaluation_files_present ?? {}).filter(Boolean).length) },
];

export function App() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [serviceStatus, setServiceStatus] = useState<ServiceStatus | null>(null);
  const [features, setFeatures] = useState<FeatureStatus[]>([]);
  const [adminAuthenticated, setAdminAuthenticated] = useState(false);
  const [paperError, setPaperError] = useState<string | null>(null);
  const [statsWarning, setStatsWarning] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const toastId = useRef(0);
  const mainRef = useRef<HTMLElement>(null);
  const location = useLocation();

  function loadData(showInitialLoading = true) {
    if (showInitialLoading) setLoading(true);
    setPaperError(null);
    setStatsWarning(null);
    Promise.allSettled([fetchPapers(), fetchStats(), fetchServiceStatus()])
      .then(([paperResult, statsResult, serviceResult]) => {
        if (paperResult.status === "fulfilled") {
          setPapers(paperResult.value);
        } else {
          setPapers([]);
          setPaperError(
            paperResult.reason instanceof Error
              ? paperResult.reason.message
              : "Unable to load publication records.",
          );
        }
        if (statsResult.status === "fulfilled") {
          setStats(statsResult.value);
        } else {
          setStats(null);
          setStatsWarning("Platform statistics are unavailable; publication records remain usable.");
        }
        setServiceStatus(serviceResult.status === "fulfilled" ? serviceResult.value : null);
      })
      .finally(() => {
        if (showInitialLoading) setLoading(false);
      });
  }

  useEffect(() => {
    loadData();
    Promise.allSettled([fetchFeatures(), fetchAdminIdentity()]).then(([featureResult, authResult]) => {
      if (featureResult.status === "fulfilled") setFeatures(featureResult.value.features);
      setAdminAuthenticated(authResult.status === "fulfilled" && authResult.value.authenticated);
    });
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
          <p className="app-subtitle">Full-paper discovery, source-cited answers, thesis ideas, and review-ready outputs.</p>
          <SecurityMode status={serviceStatus} />
        </div>
        <nav className="tabs" aria-label="Primary">
          {NAV_ITEMS.filter((item) => {
            if (item.adminOnly) return adminAuthenticated || serviceStatus?.admin_authentication === "insecure_local_demo_bypass";
            if (!item.feature) return true;
            return features.find((feature) => feature.key === item.feature)?.enabled !== false;
          }).map((item) => {
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
        {serviceStatus?.corpus_access_mode === "unreviewed_local_demo_preview" ? (
          <p className="notice notice--warning" role="status">
            Local demonstration preview: catalogue and Ask use technically eligible records that may still require metadata, extraction, publication, or rights review.
          </p>
        ) : null}
        {loading ? <InitialAppSkeleton /> : null}
        {!loading && paperError ? (
          <section className="page-section" aria-labelledby="startup-error-title">
            <div className="notice notice--error" role="alert">
              <h2 id="startup-error-title">Publication catalogue unavailable</h2>
              <p>{paperError}</p>
              <p>Independent routes remain available while the catalogue is retried.</p>
              <button className="action-button" onClick={() => loadData()}>Retry publication catalogue</button>
            </div>
          </section>
        ) : null}
        {!loading && statsWarning ? <p className="notice notice--warning" role="status">{statsWarning}</p> : null}
        {!loading ? (
          <AppRoutes papers={papers} stats={stats} serviceStatus={serviceStatus} adminAuthenticated={adminAuthenticated} onAdminAuthenticated={setAdminAuthenticated} notify={notify} onSharedDataChanged={() => { loadData(false); fetchFeatures().then((result) => setFeatures(result.features)).catch(() => undefined); }} />
        ) : null}
      </main>
      <footer className="app-footer">
        <p>Generated answers and suggestions require source checking and human review. Idea Generator conversations are sent only for the current request and are not saved by the public endpoint.</p>
      </footer>
      <ToastStack messages={toasts} onDismiss={(id) => setToasts((current) => current.filter((toast) => toast.id !== id))} />
    </div>
  );
}

function AppRoutes({
  papers,
  stats,
  serviceStatus,
  adminAuthenticated,
  onAdminAuthenticated,
  notify,
  onSharedDataChanged,
}: {
  papers: Paper[];
  stats: Stats | null;
  serviceStatus: ServiceStatus | null;
  adminAuthenticated: boolean;
  onAdminAuthenticated: (authenticated: boolean) => void;
  notify: (message: string, tone?: ToastTone) => void;
  onSharedDataChanged: () => void;
}) {
  const navigate = useNavigate();
  const openPaper = (paperId: string) => navigate(`/papers/${encodeURIComponent(paperId)}`);

  return (
    <Routes>
      <Route path="/" element={<Dashboard stats={stats} papers={papers} />} />
      <Route path="/papers" element={<PaperBrowser papers={papers} />} />
      <Route path="/papers/:paperId" element={<PaperRoute papers={papers} serviceStatus={serviceStatus} adminAuthenticated={adminAuthenticated} onSelectPaper={openPaper} onNotify={notify} />} />
      <Route path="/search" element={<SearchPage papers={papers} onSelectPaper={openPaper} onNotify={notify} />} />
      <Route path="/ask" element={<AskPage papers={papers} onSelectPaper={openPaper} onNotify={notify} />} />
      <Route path="/ask/:paperId" element={<AskRoute papers={papers} onSelectPaper={openPaper} onNotify={notify} />} />
      <Route path="/extensions" element={<IdeaGeneratorPage papers={papers} onSelectPaper={openPaper} onNotify={notify} />} />
      <Route path="/explorer" element={<TopicAuthorExplorer onSelectPaper={openPaper} />} />
      <Route path="/explorer/topics" element={<TopicAuthorExplorer initialTab="topics" onSelectPaper={openPaper} />} />
      <Route path="/explorer/topics/:topicId" element={<ExplorerTopicRoute onSelectPaper={openPaper} />} />
      <Route path="/explorer/authors" element={<TopicAuthorExplorer initialTab="authors" onSelectPaper={openPaper} />} />
      <Route path="/explorer/authors/:authorId" element={<ExplorerAuthorRoute onSelectPaper={openPaper} />} />
      <Route path="/evaluation" element={<EvaluationDashboardPage />} />
      <Route path="/admin" element={<AdminGate papers={papers} serviceStatus={serviceStatus} initiallyAuthenticated={adminAuthenticated} onAuthenticated={onAdminAuthenticated} onSelectPaper={openPaper} onNotify={notify} onDataChanged={onSharedDataChanged} />} />
      <Route path="/dashboard" element={<Navigate replace to="/" />} />
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

function PaperRoute({ papers, serviceStatus, adminAuthenticated, onSelectPaper, onNotify }: { papers: Paper[]; serviceStatus: ServiceStatus | null; adminAuthenticated: boolean; onSelectPaper: (paperId: string) => void; onNotify: (message: string, tone?: ToastTone) => void }) {
  const { paperId = "" } = useParams();
  const navigate = useNavigate();
  const cataloguePaper = papers.find((item) => item.paper_id === paperId) ?? null;
  const [directPaper, setDirectPaper] = useState<Paper | null>(null);
  const [directError, setDirectError] = useState<Error | null>(null);
  const [directLoading, setDirectLoading] = useState(!cataloguePaper);
  const [directRequestId, setDirectRequestId] = useState(paperId);
  const requestController = useRef<AbortController | null>(null);
  const paper = cataloguePaper ?? (directPaper?.paper_id === paperId ? directPaper : null);
  const directStateMatchesRoute = directRequestId === paperId;

  function loadDirectPaper() {
    if (!paperId || cataloguePaper) return;
    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    setDirectRequestId(paperId);
    setDirectLoading(true);
    setDirectError(null);
    setDirectPaper(null);
    fetchPaper(paperId, controller.signal)
      .then(setDirectPaper)
      .catch((error: unknown) => {
        if (!isAbortError(error)) {
          setDirectError(error instanceof Error ? error : new Error("Unable to load this paper record."));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setDirectLoading(false);
      });
  }

  useEffect(() => {
    if (cataloguePaper) {
      requestController.current?.abort();
      setDirectPaper(null);
      setDirectError(null);
      setDirectLoading(false);
      return;
    }
    loadDirectPaper();
    return () => requestController.current?.abort();
    // The direct request is keyed only by the route ID and catalogue resolution.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cataloguePaper, paperId]);

  if (!paper && (!directStateMatchesRoute || directLoading)) {
    return (
      <section className="page-section" aria-labelledby="paper-detail-loading" aria-busy="true">
        <h2 id="paper-detail-loading">Loading paper detail</h2>
        <ListSkeleton count={2} lines={3} />
      </section>
    );
  }
  if (!paper && directStateMatchesRoute && directError instanceof ApiError && directError.status === 404) {
    return <NotFound title="Paper not found" body="This paper ID is not present in the public publication snapshot." />;
  }
  if (!paper && directStateMatchesRoute && directError) {
    return (
      <section className="page-section" aria-labelledby="paper-detail-error-title">
        <div className="notice notice--error" role="alert">
          <h2 id="paper-detail-error-title">Paper detail unavailable</h2>
          <p>{directError.message}</p>
          <button className="action-button" onClick={loadDirectPaper}>Retry paper detail</button>
        </div>
      </section>
    );
  }
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
      canGenerateArtifacts={adminAuthenticated || hasReviewerToken() || serviceStatus?.admin_authentication === "insecure_local_demo_bypass"}
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

function AdminGate({
  papers,
  serviceStatus,
  onSelectPaper,
  onNotify,
  onDataChanged,
  initiallyAuthenticated,
  onAuthenticated,
}: {
  papers: Paper[];
  serviceStatus: ServiceStatus | null;
  onSelectPaper: (paperId: string) => void;
  onNotify: (message: string, tone?: ToastTone) => void;
  onDataChanged: () => void;
  initiallyAuthenticated: boolean;
  onAuthenticated: (authenticated: boolean) => void;
}) {
  const demoBypass = serviceStatus?.admin_authentication === "insecure_local_demo_bypass";
  const [credentialLoaded, setCredentialLoaded] = useState(initiallyAuthenticated || hasReviewerToken());
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loggingIn, setLoggingIn] = useState(false);
  const [mustChangePassword, setMustChangePassword] = useState(false);
  const [newPassword, setNewPassword] = useState("");

  useEffect(() => {
    if (initiallyAuthenticated && !demoBypass) {
      fetchAdminIdentity().then((result) => setMustChangePassword(result.user.must_change_password)).catch(() => undefined);
    }
  }, [initiallyAuthenticated, demoBypass]);

  if (!demoBypass && !credentialLoaded) {
    return (
      <section className="page-section auth-gate" aria-labelledby="admin-auth-title">
        <p className="eyebrow">Protected administrator surface</p>
        <h2 id="admin-auth-title">Administrator sign in</h2>
        <p>Use a local administrator account. The session is stored in a secure HttpOnly cookie and expires automatically.</p>
        <form onSubmit={(event) => {
          event.preventDefault();
          setLoggingIn(true);
          setLoginError(null);
          loginAdmin(username, password)
            .then((result) => { setMustChangePassword(result.user.must_change_password); if (!result.user.must_change_password) setPassword(""); setCredentialLoaded(true); onAuthenticated(true); })
            .catch((error: unknown) => setLoginError(error instanceof Error ? error.message : "Sign in failed."))
            .finally(() => setLoggingIn(false));
        }}>
          <label htmlFor="admin-username">Username</label>
          <input id="admin-username" autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} />
          <label htmlFor="admin-password">Password</label>
          <input id="admin-password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
          {loginError ? <p className="notice notice--error" role="alert">{loginError}</p> : null}
          <button className="action-button" type="submit" disabled={loggingIn}>{loggingIn ? "Signing in…" : "Sign in"}</button>
        </form>
      </section>
    );
  }

  if (!demoBypass && credentialLoaded && mustChangePassword) {
    return (
      <section className="page-section auth-gate" aria-labelledby="password-change-title">
        <h2 id="password-change-title">Choose a permanent password</h2>
        <p>Your temporary password must be changed before administrative actions are available.</p>
        <form onSubmit={(event) => {
          event.preventDefault();
          setLoggingIn(true);
          setLoginError(null);
          changeAdminPassword(password, newPassword)
            .then(() => { setPassword(""); setNewPassword(""); setMustChangePassword(false); })
            .catch((error: unknown) => setLoginError(error instanceof Error ? error.message : "Password change failed."))
            .finally(() => setLoggingIn(false));
        }}>
          <label htmlFor="temporary-password">Temporary password</label>
          <input id="temporary-password" type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
          <label htmlFor="new-password">New password</label>
          <input id="new-password" type="password" autoComplete="new-password" minLength={12} required value={newPassword} onChange={(event) => setNewPassword(event.target.value)} />
          {loginError ? <p className="notice notice--error" role="alert">{loginError}</p> : null}
          <button className="action-button" disabled={loggingIn} type="submit">Change password</button>
        </form>
      </section>
    );
  }

  return (
    <>
      <div className={`notice ${demoBypass ? "notice--warning" : "notice--success"}`} role="status">
        {demoBypass
          ? "Insecure local-demo bypass is active. Do not expose this configuration on a network."
          : "Signed in as an administrator. Changes are attributed and audited."}
        {!demoBypass ? <button className="link-button" onClick={() => { logoutAdmin().finally(() => { setReviewerToken(""); setCredentialLoaded(false); onAuthenticated(false); }); }}>Sign out</button> : null}
      </div>
      <AdminReviewPage papers={papers} onSelectPaper={onSelectPaper} onNotify={onNotify} onDataChanged={onDataChanged} />
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
  if (pathname === "/extensions") return "Idea Generator";
  if (pathname.startsWith("/explorer/topics")) return "Topic Explorer";
  if (pathname.startsWith("/explorer/authors")) return "Author Explorer";
  if (pathname === "/explorer") return "Topic and Author Explorer";
  if (pathname === "/evaluation") return "Evaluation Dashboard";
  if (pathname === "/admin") return "Admin Review";
  return "Page Not Found";
}
