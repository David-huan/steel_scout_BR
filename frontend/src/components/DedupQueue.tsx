import type { DedupPair, Event } from "../types";

interface Props {
  pairs: DedupPair[];
  events: Event[];
  loading: boolean;
  onRefresh: () => void;
  onMerge: (pairId: string, keepId: string) => void;
  onDismiss: (pairId: string) => void;
}

export default function DedupQueue({ pairs, events, loading, onRefresh, onMerge, onDismiss }: Props) {
  const autoMerges = events.filter((event) => event.event_type === "auto_merge");

  return (
    <section className="panel dedup-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Entity resolution</p>
          <h2>去重复核队列</h2>
        </div>
        <div className="heading-actions">
          <span className="result-count">{pairs.length} 组</span>
          <button className="ghost-button" type="button" onClick={onRefresh}>
            刷新
          </button>
        </div>
      </div>

      <p className="section-help">
        CNPJ / 注册域 / 邮箱为强匹配，自动合并；名称相似但州或地址不一致的组合进入人工复核，不硬删除。
      </p>

      {loading ? <div className="table-loading">加载中…</div> : null}

      <div className="dedup-list">
        {pairs.map((pair) => (
          <article className="dedup-card" key={pair.id}>
            <div className="dedup-score">
              <strong>{Math.round(pair.score * 100)}%</strong>
              <span>similarity</span>
            </div>
            <div className="dedup-body">
              <div className="dedup-sides">
                {(["left", "right"] as const).map((side) => {
                  const company = pair[side];
                  if (!company) return null;
                  return (
                    <div className="dedup-side" key={side}>
                      <strong>{company.display_name}</strong>
                      <span>
                        {company.city || "—"} / {company.state || "—"}
                      </span>
                      <span>{company.cnpj || "CNPJ 未验证"}</span>
                      <span>{company.emails.join(", ") || "无邮箱"}</span>
                      <span>{company.phones.join(", ") || "无电话"}</span>
                      <button className="ghost-button" type="button" onClick={() => onMerge(pair.id, company.id)}>
                        保留这家并合并
                      </button>
                    </div>
                  );
                })}
              </div>
              <div className="dedup-reasons">
                {pair.reasons.map((reason) => (
                  <span className="mini-tag" key={reason}>
                    {reason}
                  </span>
                ))}
                <span className="mini-tag">
                  name {String(pair.features.name_sim ?? "—")}
                </span>
              </div>
            </div>
            <button className="link-button" type="button" onClick={() => onDismiss(pair.id)}>
              不是同一家
            </button>
          </article>
        ))}
        {!pairs.length && !loading ? (
          <div className="empty-state">暂无待人工复核的重复对。自动合并记录可在事件日志中查看。</div>
        ) : null}
      </div>
    </section>
  );
}
