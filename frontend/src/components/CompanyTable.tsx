import { TYPE_LABELS, type Company, type Filters } from "../types";

interface Props {
  companies: Company[];
  total: number;
  filters: Filters;
  loading: boolean;
  onFilters: (next: Partial<Filters>) => void;
  onSelect: (company: Company) => void;
  onExport: () => void;
}

const TIERS = ["AB", "A", "B", "C", "D", ""];
const STATES = ["SP", "PR", "SC", "MG", "RS", "DF"];
const TYPES = Object.keys(TYPE_LABELS);

export default function CompanyTable({
  companies,
  total,
  filters,
  loading,
  onFilters,
  onSelect,
  onExport,
}: Props) {
  return (
    <section className="panel company-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Qualified accounts</p>
          <h2>客户清单</h2>
        </div>
        <div className="heading-actions">
          <span className="result-count">{total} 家</span>
          <button className="ghost-button" type="button" onClick={onExport}>
            导出 CSV
          </button>
        </div>
      </div>

      <div className="filter-bar">
        <div className="tier-filter" role="group" aria-label="tier filter">
          {TIERS.map((tier) => (
            <button
              type="button"
              key={tier || "all"}
              className={filters.tier === tier ? "active" : ""}
              onClick={() => onFilters({ tier })}
            >
              {tier === "" ? "全部等级" : tier === "AB" ? "A + B" : tier}
            </button>
          ))}
        </div>

        <input
          className="search-input"
          type="search"
          placeholder="搜索公司名称、备注…"
          value={filters.q}
          onChange={(event) => onFilters({ q: event.target.value })}
        />

        <select value={filters.state} onChange={(event) => onFilters({ state: event.target.value })}>
          <option value="">全部州</option>
          {STATES.map((state) => (
            <option key={state} value={state}>
              {state}
            </option>
          ))}
        </select>

        <select value={filters.type} onChange={(event) => onFilters({ type: event.target.value })}>
          <option value="">全部类型</option>
          {TYPES.map((type) => (
            <option key={type} value={type}>
              {TYPE_LABELS[type]}
            </option>
          ))}
        </select>

        <select value={filters.sort} onChange={(event) => onFilters({ sort: event.target.value })}>
          <option value="score_desc">分数从高到低</option>
          <option value="score_asc">分数从低到高</option>
          <option value="name">公司名称</option>
          <option value="recent">最近更新</option>
        </select>

        <label className="score-filter">
          <span>最低分 {filters.minScore}</span>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={filters.minScore}
            onChange={(event) => onFilters({ minScore: Number(event.target.value) })}
          />
        </label>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>公司</th>
              <th>州 / 城市</th>
              <th>类型</th>
              <th>产品形态</th>
              <th>可触达</th>
              <th>评分</th>
              <th>复核</th>
            </tr>
          </thead>
          <tbody>
            {companies.map((company) => {
              const score = company.score;
              return (
                <tr key={company.id} onClick={() => onSelect(company)} tabIndex={0}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") onSelect(company);
                  }}
                >
                  <td>
                    <div className="company-name">{company.display_name}</div>
                    <div className="company-sub">
                      {company.website ? company.website.replace(/^https?:\/\/(www\.)?/, "") : "无官网"}
                      {company.dedup_status === "merged" ? " · 已合并" : ""}
                    </div>
                  </td>
                  <td>
                    <div className="state-code">{company.state || "—"}</div>
                    <div className="company-sub">{company.city || "—"}</div>
                  </td>
                  <td>
                    <span className="type-tag">
                      {company.primary_type ? TYPE_LABELS[company.primary_type] ?? company.primary_type : "未分类"}
                    </span>
                  </td>
                  <td>
                    <div className="tag-line">
                      {company.products.slice(0, 4).map((product) => (
                        <span className="mini-tag" key={product.form}>
                          {product.form}
                        </span>
                      ))}
                      {company.products.length === 0 ? <span className="muted">—</span> : null}
                    </div>
                  </td>
                  <td>
                    <div className="contact-line">
                      <span className={company.emails.length ? "contact-ok" : "contact-no"}>
                        邮箱 {company.emails.length}
                      </span>
                      <span className={company.phones.length ? "contact-ok" : "contact-no"}>
                        电话 {company.phones.length}
                      </span>
                    </div>
                  </td>
                  <td>
                    {score ? (
                      <div className="score-cell">
                        <span className={`tier tier-${score.tier}`}>{score.tier}</span>
                        <div>
                          <strong>{score.total}</strong>
                          <div className="score-bar">
                            <div style={{ width: `${score.total}%` }} />
                          </div>
                        </div>
                      </div>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>
                    <span className={`review-chip ${company.review_status}`}>
                      {company.review_status === "approved"
                        ? "已确认"
                        : company.review_status === "rejected"
                          ? "已淘汰"
                          : company.review_status === "needs_info"
                            ? "待补充"
                            : "待复核"}
                    </span>
                  </td>
                </tr>
              );
            })}
            {!companies.length && !loading ? (
              <tr>
                <td colSpan={7}>
                  <div className="empty-state">没有符合筛选条件的公司。</div>
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
        {loading ? <div className="table-loading">加载中…</div> : null}
      </div>
    </section>
  );
}
