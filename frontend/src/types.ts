export type Tier = "A" | "B" | "C" | "D";

export interface Score {
  total: number;
  tier: Tier;
  product_fit: number;
  buyer_intent: number;
  scale: number;
  reachability: number;
  geo_logistics: number;
  strategic_fit: number;
  breakdown: Record<string, number>;
  reasons: string[];
  score_version: string;
}

export interface Email {
  value: string;
  role: string | null;
  source: string | null;
  source_url: string | null;
  first_seen_at?: string;
}

export interface Phone {
  e164: string;
  type: string | null;
  source: string | null;
}

export interface Product {
  form: string;
  grades: string[];
  quote: string | null;
  source_url: string | null;
  confidence: number;
}

export interface Domain {
  domain: string;
  kind: string;
  is_primary: number;
}

export interface Company {
  id: string;
  display_name: string;
  legal_name: string | null;
  website: string | null;
  cnpj: string | null;
  registry_status?: string | null;
  state: string | null;
  city: string | null;
  address: string | null;
  postal_code: string | null;
  country: string;
  size_bucket: string | null;
  primary_type: string | null;
  secondary_types: string[];
  type_confidence: number | null;
  status: string;
  review_status: string;
  review_note?: string | null;
  dedup_status: string;
  notes: string | null;
  emails: Email[];
  phones: Phone[];
  products: Product[];
  applications: string[];
  domains: Domain[];
  aliases: string[];
  source_count: number;
  score: Score | null;
}

export interface Source {
  field: string;
  value: string;
  quote: string | null;
  source_url: string | null;
  extractor: string;
  confidence: number;
  fetched_at: string;
}

export interface Event {
  event_type: string;
  actor: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface DedupPair {
  id: string;
  run_id: string;
  left_company_id: string;
  right_company_id: string;
  score: number;
  decision: string;
  status: string;
  features: Record<string, unknown>;
  reasons: string[];
  reviewed_at: string | null;
  review_note: string | null;
  created_at: string;
  left?: DedupSide;
  right?: DedupSide;
}

export interface DedupSide {
  id: string;
  display_name: string;
  website: string | null;
  state: string | null;
  city: string | null;
  cnpj: string | null;
  emails: string[];
  phones: string[];
}

export interface CompanyDetail extends Company {
  sources: Source[];
  scores: Array<Score & { id: number; run_id: string; created_at: string }>;
  events: Event[];
  dedup_pairs: DedupPair[];
}

export interface Stage {
  stage: string;
  status: string;
  stats: Record<string, unknown>;
  warnings: string[];
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface RunStats {
  candidates?: number;
  companies?: number;
  qualified?: number;
  tier_a?: number;
  tier_b?: number;
  emails?: number;
  auto_merged?: number;
  review_pairs?: number;
  live_ok?: number;
  seed_fallback?: number;
  serper_queries?: number;
  type_counts?: Record<string, number>;
}

export interface Brief {
  product: string;
  country: string;
  category: string;
  ncm: string[];
  grades: string[];
  forms: string[];
  search_hints: string[];
  negative_keywords: string[];
  regions: string[];
  target_count: number;
  needs_review: boolean;
  confidence: number;
}

export interface Run {
  id: string;
  product: string;
  country: string;
  target_count: number;
  status: string;
  current_stage: string;
  stats: RunStats;
  brief: Brief | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  stages?: Stage[];
  company_count?: number;
}

export interface CompanyList {
  run_id: string;
  total: number;
  limit: number;
  offset: number;
  items: Company[];
}

export interface Filters {
  tier: string;
  state: string;
  type: string;
  q: string;
  minScore: number;
  sort: string;
}

export const TYPE_LABELS: Record<string, string> = {
  importer_distributor: "进口商 / 分销商",
  service_center: "加工服务中心",
  fabricator: "制造商",
  end_user: "终端用户",
  trader: "贸易商",
  mill_producer: "钢厂 / 生产者",
  recycler: "回收 / 废料",
  other: "其他",
};

export const STAGE_LABELS: Record<string, string> = {
  brief: "需求解析",
  queries: "查询生成",
  discovery: "候选发现",
  crawl: "公开信息抓取",
  enrich: "信息补全",
  classify: "类型判定",
  dedup: "去重合并",
};

export const SIZE_LABELS: Record<string, string> = {
  large: "大型",
  medium: "中型",
  small: "小型",
  micro: "微型",
  unknown: "未知",
};
