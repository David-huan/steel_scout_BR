import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createRun,
  dismissPair,
  exportUrl,
  getCompany,
  getRun,
  getRunEvents,
  listCompanies,
  listDedupQueue,
  listRuns,
  mergePair,
  reviewCompany,
} from "./api";
import CompanyDrawer from "./components/CompanyDrawer";
import CompanyTable from "./components/CompanyTable";
import DedupQueue from "./components/DedupQueue";
import RunOverview from "./components/RunOverview";
import RunPanel from "./components/RunPanel";
import type { Company, CompanyDetail, DedupPair, Event, Filters, Run } from "./types";

interface Health {
  status: string;
  flags: { serper: boolean; places: boolean; llm: boolean; crawl_live: boolean };
}

const DEFAULT_FILTERS: Filters = {
  tier: "AB",
  state: "",
  type: "",
  q: "",
  minScore: 0,
  sort: "score_desc",
};

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [busy, setBusy] = useState(false);
  const [loadingCompanies, setLoadingCompanies] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"companies" | "dedup">("companies");
  const [pairs, setPairs] = useState<DedupPair[]>([]);
  const [events, setEvents] = useState<Event[]>([]);
  const [pairsLoading, setPairsLoading] = useState(false);
  const [selected, setSelected] = useState<CompanyDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const refreshPairs = useCallback(async () => {
    setPairsLoading(true);
    try {
      const data = await listDedupQueue();
      setPairs(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPairsLoading(false);
    }
  }, []);

  const refreshEvents = useCallback(async (runId: string) => {
    try {
      const data = await getRunEvents(runId);
      setEvents(data.items);
    } catch {
      setEvents([]);
    }
  }, []);

  const loadRun = useCallback(async (runId: string) => {
    try {
      setError("");
      setSelected(null);
      setCompanies([]);
      setTotal(0);
      const data = await getRun(runId);
      setRun(data);
      if (data.status === "completed") {
        refreshPairs();
        refreshEvents(data.id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [refreshPairs, refreshEvents]);

  useEffect(() => {
    fetch("/api/health")
      .then((resp) => (resp.ok ? resp.json() : null))
      .then((data) => setHealth(data))
      .catch(() => setHealth(null));
    listRuns()
      .then((data) => {
        setRuns(data.items);
        if (data.items[0]) loadRun(data.items[0].id);
      })
      .catch(() => undefined);
  }, [loadRun]);

  useEffect(() => {
    if (!run || (run.status !== "queued" && run.status !== "running")) return;
    const timer = window.setTimeout(async () => {
      try {
        const next = await getRun(run.id);
        setRun(next);
        if (next.status === "completed" || next.status === "failed") {
          listRuns().then((data) => setRuns(data.items)).catch(() => undefined);
          if (next.status === "completed") {
            refreshPairs();
            refreshEvents(next.id);
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      }
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [run, refreshPairs, refreshEvents]);

  useEffect(() => {
    if (!run || run.status !== "completed") return;
    const timer = window.setTimeout(async () => {
      setLoadingCompanies(true);
      try {
        const data = await listCompanies(run.id, filters);
        setCompanies(data.items);
        setTotal(data.total);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoadingCompanies(false);
      }
    }, 220);
    return () => window.clearTimeout(timer);
  }, [run, filters]);

  const handleCreate = async (product: string, country: string, targetCount: number) => {
    setBusy(true);
    setError("");
    try {
      const created = await createRun(product, country, targetCount);
      const next = await getRun(created.run_id);
      setRun(next);
      setTab("companies");
      setFilters(DEFAULT_FILTERS);
      const data = await listRuns();
      setRuns(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const handleSelect = async (company: Company) => {
    setDetailLoading(true);
    setSelected(null);
    try {
      const detail = await getCompany(company.id);
      setSelected(detail);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setDetailLoading(false);
    }
  };

  const refreshDetail = async (companyId: string) => {
    const detail = await getCompany(companyId);
    setSelected(detail);
  };

  const handleReview = async (status: string, note: string) => {
    if (!selected) return;
    try {
      await reviewCompany(selected.id, status, note);
      await refreshDetail(selected.id);
      if (run) {
        const data = await listCompanies(run.id, filters);
        setCompanies(data.items);
        setTotal(data.total);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleMerge = async (pairId: string, keepId: string) => {
    try {
      await mergePair(pairId, keepId);
      await refreshPairs();
      if (run) {
        const data = await listCompanies(run.id, filters);
        setCompanies(data.items);
        setTotal(data.total);
      }
      if (selected) await refreshDetail(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleDismiss = async (pairId: string) => {
    try {
      await dismissPair(pairId);
      await refreshPairs();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleExport = () => {
    if (!run) return;
    const tier = filters.tier === "AB" ? "A,B" : filters.tier;
    window.location.href = exportUrl(run.id, tier, filters.state);
  };

  const modeText = useMemo(() => {
    if (!health) return "API 连接中";
    return health.flags.crawl_live ? "实时抓取开启" : "仅 seed 数据";
  }, [health]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">SS</div>
          <div>
            <h1>Steel Scout BR</h1>
            <p>AI 辅助的不锈钢海外客户开发 · Brazil</p>
          </div>
        </div>
        <div className="topbar-right">
          <span className={`health-dot ${health ? "ok" : ""}`} />
          <span className="mode-text">{modeText}</span>
          {health?.flags.serper ? <span className="mode-pill">Serper</span> : null}
          {runs.length ? (
            <select
              className="run-select"
              value={run?.id ?? ""}
              onChange={(event) => loadRun(event.target.value)}
            >
              {runs.map((item) => (
                <option value={item.id} key={item.id}>
                  {item.status} · {new Date(item.created_at).toLocaleString()} · {item.stats?.companies ?? 0} 家
                </option>
              ))}
            </select>
          ) : null}
        </div>
      </header>

      {error ? (
        <div className="alert error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => setError("")}>
            关闭
          </button>
        </div>
      ) : null}

      <main className="layout">
        <aside className="sidebar">
          <RunPanel onCreate={handleCreate} busy={busy} />
          <div className="sidebar-note">
            <strong>数据边界</strong>
            <p>
              评分中的贸易数据、注册状态与联系人仅来自公开 API/网页。未知字段保持为空，不使用 LLM
              生成邮箱或电话。
            </p>
          </div>
        </aside>

        <div className="content">
          {!run ? (
            <section className="panel empty-hero">
              <p className="eyebrow">Start here</p>
              <h2>输入产品与国家，生成一份可复核的客户名单。</h2>
              <p>
                系统会生成葡语查询、发现候选、抓取公开页面、判定客户类型、评分并去重。Demo
                预置 19 家巴西不锈钢客户样本，无搜索 API Key 时仍可运行。
              </p>
            </section>
          ) : (
            <>
              <RunOverview run={run} />

              <div className="tabs">
                <button
                  type="button"
                  className={tab === "companies" ? "active" : ""}
                  onClick={() => setTab("companies")}
                >
                  客户清单
                  <span>{total}</span>
                </button>
                <button
                  type="button"
                  className={tab === "dedup" ? "active" : ""}
                  onClick={() => {
                    setTab("dedup");
                    refreshPairs();
                    if (run) refreshEvents(run.id);
                  }}
                >
                  去重复核
                  <span>{pairs.length}</span>
                </button>
              </div>

              {tab === "companies" ? (
                <CompanyTable
                  companies={companies}
                  total={total}
                  filters={filters}
                  loading={loadingCompanies}
                  onFilters={(next) => setFilters((current) => ({ ...current, ...next }))}
                  onSelect={handleSelect}
                  onExport={handleExport}
                />
              ) : (
                <DedupQueue
                  pairs={pairs}
                  events={events}
                  loading={pairsLoading}
                  onRefresh={refreshPairs}
                  onMerge={handleMerge}
                  onDismiss={handleDismiss}
                />
              )}
            </>
          )}
        </div>
      </main>

      <CompanyDrawer
        company={selected}
        loading={detailLoading}
        onClose={() => setSelected(null)}
        onReview={handleReview}
        onMerge={handleMerge}
      />
    </div>
  );
}
