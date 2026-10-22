import { STAGE_LABELS, type Run } from "../types";

interface Props {
  run: Run;
}

const STATUS_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
};

export default function RunOverview({ run }: Props) {
  const stats = run.stats ?? {};
  const stages = run.stages ?? [];
  const done = stages.filter((stage) => stage.status === "done").length;
  const progress = stages.length ? Math.round((done / stages.length) * 100) : 0;

  return (
    <section className="panel run-overview">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Run overview</p>
          <h2>{run.product}</h2>
        </div>
        <span className={`status-pill ${run.status}`}>{STATUS_LABELS[run.status] ?? run.status}</span>
      </div>

      <div className="run-meta">
        <span>Run {run.id}</span>
        <span>{run.country}</span>
        <span>{new Date(run.created_at).toLocaleString()}</span>
        {run.brief?.needs_review ? <span className="warn">brief 需复核</span> : null}
      </div>

      <div className="progress-track" aria-label="pipeline progress">
        <div className="progress-fill" style={{ width: `${progress}%` }} />
      </div>

      <div className="stage-row">
        {stages.map((stage) => (
          <div className={`stage ${stage.status}`} key={stage.stage}>
            <div className="stage-dot" />
            <div>
              <strong>{STAGE_LABELS[stage.stage] ?? stage.stage}</strong>
              <span>{stage.status === "done" ? "完成" : stage.status === "running" ? "进行中" : stage.status === "failed" ? "失败" : "等待"}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="stat-grid">
        <div className="stat">
          <span>客户公司</span>
          <strong>{stats.companies ?? 0}</strong>
        </div>
        <div className="stat">
          <span>合格 A/B</span>
          <strong>{stats.qualified ?? 0}</strong>
        </div>
        <div className="stat">
          <span>A 级</span>
          <strong>{stats.tier_a ?? 0}</strong>
        </div>
        <div className="stat">
          <span>有邮箱公司</span>
          <strong>{stats.emails ?? 0}</strong>
        </div>
        <div className="stat">
          <span>实时抓取</span>
          <strong>{stats.live_ok ?? 0}</strong>
        </div>
        <div className="stat">
          <span>自动合并</span>
          <strong>{stats.auto_merged ?? 0}</strong>
        </div>
        <div className="stat">
          <span>待去重复核</span>
          <strong>{stats.review_pairs ?? 0}</strong>
        </div>
        <div className="stat">
          <span>候选总数</span>
          <strong>{stats.candidates ?? 0}</strong>
        </div>
      </div>

      {run.error ? <div className="alert error">{run.error}</div> : null}
    </section>
  );
}
