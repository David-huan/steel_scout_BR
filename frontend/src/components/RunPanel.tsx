import { useState } from "react";

interface Props {
  onCreate: (product: string, country: string, targetCount: number) => void;
  busy: boolean;
}

const PRESETS = [
  "Stainless steel flat products and profiles",
  "Chapas e bobinas de aço inoxidável 304/316L",
  "Barras e perfis de aço inox",
];

export default function RunPanel({ onCreate, busy }: Props) {
  const [product, setProduct] = useState(PRESETS[0]);
  const [country, setCountry] = useState("Brazil");
  const [targetCount, setTargetCount] = useState(15);

  return (
    <section className="panel run-panel">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">New discovery run</p>
          <h2>发起客户发现</h2>
        </div>
        <span className="mode-pill">BR · inox</span>
      </div>

      <form
        className="run-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (!product.trim()) return;
          onCreate(product.trim(), country, targetCount);
        }}
      >
        <label>
          <span>产品 / Product</span>
          <textarea
            value={product}
            onChange={(event) => setProduct(event.target.value)}
            rows={3}
            placeholder="例如：Stainless steel flat products and profiles"
          />
        </label>

        <div className="form-row">
          <label>
            <span>目标国家</span>
            <select value={country} onChange={(event) => setCountry(event.target.value)}>
              <option value="Brazil">Brazil / 巴西</option>
            </select>
          </label>
          <label>
            <span>目标数量</span>
            <input
              type="number"
              min={1}
              max={200}
              value={targetCount}
              onChange={(event) =>
                setTargetCount(Math.max(1, Math.min(200, Number(event.target.value) || 1)))
              }
            />
          </label>
        </div>

        <div className="preset-row">
          {PRESETS.map((preset) => (
            <button
              type="button"
              className={`preset ${product === preset ? "active" : ""}`}
              key={preset}
              onClick={() => setProduct(preset)}
            >
              {preset}
            </button>
          ))}
        </div>

        <button className="primary-button" type="submit" disabled={busy || !product.trim()}>
          {busy ? "正在启动…" : "开始发现"}
        </button>
      </form>

      <p className="fine-print">
        仅采集公开页面与官方注册数据；不绕过登录、验证码或付费墙。邮箱/电话/CNPJ 均保留来源，不生成未知信息。
      </p>
    </section>
  );
}
