import { useEffect, useState } from "react";
import {
  SIZE_LABELS,
  TYPE_LABELS,
  type CompanyDetail,
} from "../types";

interface Props {
  company: CompanyDetail | null;
  loading: boolean;
  onClose: () => void;
  onReview: (status: string, note: string) => void;
  onMerge?: (pairId: string, keepId: string) => void;
}

const DIMENSIONS: Array<[string, string]> = [
  ["product_fit", "产品契合"],
  ["buyer_intent", "采购意图"],
  ["scale", "规模"],
  ["reachability", "可触达"],
  ["geo_logistics", "地理物流"],
  ["strategic_fit", "战略匹配"],
];

export default function CompanyDrawer({ company, loading, onClose, onReview, onMerge }: Props) {
  const [note, setNote] = useState("");

  useEffect(() => {
    setNote("");
  }, [company?.id]);

  if (!company && !loading) return null;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(event) => event.stopPropagation()}>
        <button className="drawer-close" type="button" onClick={onClose} aria-label="关闭">
          ×
        </button>

        {loading || !company ? (
          <div className="drawer-loading">加载公司详情…</div>
        ) : (
          <>
            <header className="drawer-header">
              <div>
                <p className="eyebrow">Company evidence</p>
                <h2>{company.display_name}</h2>
                <p className="drawer-sub">
                  {company.website ? (
                    <a href={company.website} target="_blank" rel="noreferrer">
                      {company.website.replace(/^https?:\/\/(www\.)?/, "")}
                    </a>
                  ) : (
                    "无官网"
                  )}
                  <span>·</span>
                  <span>
                    {company.city || "未知城市"} / {company.state || "未知州"}
                  </span>
                  <span>·</span>
                  <span>{company.primary_type ? TYPE_LABELS[company.primary_type] ?? company.primary_type : "未分类"}</span>
                </p>
              </div>
              {company.score ? (
                <div className={`drawer-score tier-${company.score.tier}`}>
                  <strong>{company.score.total}</strong>
                  <span>{company.score.tier} 级</span>
                </div>
              ) : null}
            </header>

            <div className="drawer-section">
              <h3>联系与注册信息</h3>
              <div className="contact-grid">
                <div>
                  <span className="label">邮箱</span>
                  {company.emails.length ? (
                    company.emails.map((email) => (
                      <a className="contact-value" key={email.value} href={`mailto:${email.value}`}>
                        {email.value}
                        <small>{email.role ?? "unknown"}</small>
                      </a>
                    ))
                  ) : (
                    <span className="muted">未在公开页面发现</span>
                  )}
                </div>
                <div>
                  <span className="label">电话</span>
                  {company.phones.length ? (
                    company.phones.map((phone) => (
                      <a className="contact-value" key={phone.e164} href={`tel:${phone.e164}`}>
                        {phone.e164}
                      </a>
                    ))
                  ) : (
                    <span className="muted">未在公开页面发现</span>
                  )}
                </div>
                <div>
                  <span className="label">CNPJ</span>
                  <span className="contact-value">{company.cnpj || <span className="muted">未验证</span>}</span>
                </div>
                <div>
                  <span className="label">规模 / 注册状态</span>
                  <span className="contact-value">
                    {SIZE_LABELS[company.size_bucket ?? "unknown"] ?? company.size_bucket}
                    <small>{company.registry_status ?? "unverified"}</small>
                  </span>
                </div>
                <div className="wide">
                  <span className="label">地址</span>
                  <span className="contact-value">{company.address || <span className="muted">未发现</span>}</span>
                </div>
              </div>
            </div>

            {company.score ? (
              <div className="drawer-section">
                <h3>评分拆解</h3>
                <div className="dimension-list">
                  {DIMENSIONS.map(([key, label]) => {
                    const value = company.score?.[key as keyof typeof company.score] as number;
                    return (
                      <div className="dimension" key={key}>
                        <span>{label}</span>
                        <div className="dimension-bar">
                          <div style={{ width: `${value}%` }} />
                        </div>
                        <strong>{value}</strong>
                      </div>
                    );
                  })}
                </div>
                <ul className="reason-list">
                  {company.score.reasons.map((reason) => (
                    <li key={reason}>{reason}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="drawer-section">
              <h3>产品与行业</h3>
              <div className="tag-line">
                {company.products.map((product) => (
                  <span className="product-tag" key={product.form}>
                    {product.form}
                    {product.grades.length ? <small>{product.grades.join(" / ")}</small> : null}
                  </span>
                ))}
                {!company.products.length ? <span className="muted">未发现产品信息</span> : null}
              </div>
              <div className="tag-line">
                {company.applications.map((application) => (
                  <span className="mini-tag" key={application}>
                    {application}
                  </span>
                ))}
              </div>
              <div className="tag-line">
                {company.aliases
                  .filter((alias) => alias !== company.display_name)
                  .map((alias) => (
                    <span className="alias-tag" key={alias}>
                      {alias}
                    </span>
                  ))}
              </div>
            </div>

            <div className="drawer-section">
              <h3>证据链</h3>
              <div className="evidence-list">
                {company.sources.slice(0, 40).map((source, index) => (
                  <div className="evidence" key={`${source.field}-${source.value}-${index}`}>
                    <div className="evidence-head">
                      <span className="evidence-field">{source.field}</span>
                      <span className="evidence-conf">{Math.round(source.confidence * 100)}%</span>
                    </div>
                    <div className="evidence-value">{source.value}</div>
                    {source.quote ? <blockquote>{source.quote.slice(0, 320)}</blockquote> : null}
                    {source.source_url ? (
                      <a href={source.source_url} target="_blank" rel="noreferrer">
                        {source.source_url}
                      </a>
                    ) : null}
                  </div>
                ))}
                {!company.sources.length ? <span className="muted">暂无证据记录</span> : null}
              </div>
            </div>

            {company.dedup_pairs.length ? (
              <div className="drawer-section">
                <h3>去重关联</h3>
                {company.dedup_pairs.map((pair) => (
                  <div className="dedup-inline" key={pair.id}>
                    <span>
                      与 {pair.left_company_id === company.id ? pair.right_company_id : pair.left_company_id} 相似度{" "}
                      {Math.round(pair.score * 100)}%
                    </span>
                    <span className={`review-chip ${pair.status}`}>{pair.status}</span>
                    {onMerge && pair.status === "pending" ? (
                      <button className="ghost-button" type="button" onClick={() => onMerge(pair.id, company.id)}>
                        保留当前公司并合并
                      </button>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}

            <div className="drawer-section review-section">
              <h3>人工复核</h3>
              <textarea
                rows={3}
                placeholder="复核备注（可选）"
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
              <div className="review-actions">
                <button className="primary-button" type="button" onClick={() => onReview("approved", note)}>
                  标记合格
                </button>
                <button className="ghost-button" type="button" onClick={() => onReview("needs_info", note)}>
                  待补充
                </button>
                <button className="danger-button" type="button" onClick={() => onReview("rejected", note)}>
                  淘汰
                </button>
              </div>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
