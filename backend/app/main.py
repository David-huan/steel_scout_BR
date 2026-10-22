import csv
import io
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND_DIST, flags
from .db import add_event, dumps, get_conn, init_db, loads, new_id, utcnow
from .pipeline.brief import build_brief
from .pipeline.orchestrator import STAGES, run_pipeline
from .schemas import MergeRequest, ReviewUpdate, RunCreate

REVIEW_STATUSES = {"new", "approved", "rejected", "needs_info"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Steel Customer Discovery", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _run_payload(row) -> dict:
    d = dict(row)
    d["options"] = loads(d.pop("options_json", "{}"), {})
    d["brief"] = loads(d.pop("brief_json", None), None)
    d["stats"] = loads(d.pop("stats_json", "{}"), {})
    return d


def _company_base(row) -> dict:
    d = dict(row)
    d["secondary_types"] = loads(d.pop("secondary_types_json", "[]"), [])
    d.pop("breakdown_json", None)
    return d


def _score_from_row(row) -> dict | None:
    if row["total"] is None:
        return None
    return {
        "total": row["total"],
        "tier": row["tier"],
        "product_fit": row["product_fit"],
        "buyer_intent": row["buyer_intent"],
        "scale": row["scale"],
        "reachability": row["reachability"],
        "geo_logistics": row["geo_logistics"],
        "strategic_fit": row["strategic_fit"],
        "breakdown": loads(row["breakdown_json"], {}),
        "reasons": loads(row["reasons_json"], []),
        "score_version": row["score_version"],
    }


def _relations(conn, company_id: str) -> dict:
    emails = [
        dict(r)
        for r in conn.execute(
            "SELECT email AS value, role, mx_ok, source, source_url, first_seen_at FROM company_emails WHERE company_id=? ORDER BY id",
            (company_id,),
        )
    ]
    phones = [
        dict(r)
        for r in conn.execute(
            "SELECT e164, type, source FROM company_phones WHERE company_id=? ORDER BY id",
            (company_id,),
        )
    ]
    domains = [
        dict(r)
        for r in conn.execute(
            "SELECT domain, kind, is_primary FROM company_domains WHERE company_id=? ORDER BY is_primary DESC, id",
            (company_id,),
        )
    ]
    aliases = [
        r[0]
        for r in conn.execute(
            "SELECT alias FROM company_aliases WHERE company_id=? ORDER BY id", (company_id,)
        )
    ]
    products = []
    product_index: dict[str, dict] = {}
    for r in conn.execute(
        "SELECT form, grades_json, quote, source_url, confidence FROM company_products WHERE company_id=? ORDER BY id",
        (company_id,),
    ):
        item = dict(r)
        item["grades"] = loads(item.pop("grades_json"), [])
        form = item.get("form") or "unknown"
        if form in product_index:
            product_index[form]["grades"] = list(
                dict.fromkeys(product_index[form]["grades"] + item["grades"])
            )
            continue
        product_index[form] = item
        products.append(item)
    applications = []
    for r in conn.execute(
        "SELECT value FROM company_sources WHERE company_id=? AND field='applications' ORDER BY id",
        (company_id,),
    ):
        applications.extend(x.strip() for x in (r[0] or "").split(";") if x.strip())
    return {
        "emails": emails,
        "phones": phones,
        "domains": domains,
        "aliases": aliases,
        "products": products,
        "applications": list(dict.fromkeys(applications)),
    }


def _company_summary(conn, row) -> dict:
    base = _company_base(row)
    base.update(_relations(conn, base["id"]))
    base["score"] = _score_from_row(row)
    base["source_count"] = conn.execute(
        "SELECT COUNT(*) FROM company_sources WHERE company_id=?", (base["id"],)
    ).fetchone()[0]
    return base


@app.get("/api/health")
def health():
    return {"status": "ok", "flags": flags(), "time": utcnow()}


@app.post("/api/runs", status_code=202)
def create_run(body: RunCreate, background: BackgroundTasks):
    try:
        brief = build_brief(body.product, body.country, body.target_count)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    run_id = new_id("run")
    now = utcnow()
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO runs (id, product, country, target_count, options_json, brief_json, status,
              current_stage, stats_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                body.product,
                brief.country,
                body.target_count,
                dumps(body.options),
                dumps(brief.to_dict()),
                "queued",
                "queued",
                "{}",
                now,
            ),
        )
        for stage in STAGES:
            conn.execute(
                "INSERT OR IGNORE INTO run_stages (run_id, stage, status, stats_json, warnings_json) VALUES (?,?,?,?,?)",
                (run_id, stage, "pending", "{}", "[]"),
            )
        conn.commit()
    finally:
        conn.close()

    background.add_task(run_pipeline, run_id)
    return {"run_id": run_id, "status": "queued", "brief": brief.to_dict()}


@app.get("/api/runs")
def list_runs(limit: int = Query(20, ge=1, le=100)):
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return {"items": [_run_payload(r) for r in rows]}
    finally:
        conn.close()


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")
        stages = [dict(r) for r in conn.execute("SELECT * FROM run_stages WHERE run_id=? ORDER BY rowid", (run_id,))]
        for stage in stages:
            stage["stats"] = loads(stage.pop("stats_json", "{}"), {})
            stage["warnings"] = loads(stage.pop("warnings_json", "[]"), [])
        data = _run_payload(row)
        data["stages"] = stages
        data["company_count"] = conn.execute(
            "SELECT COUNT(*) FROM run_companies rc JOIN companies c ON c.id=rc.company_id WHERE rc.run_id=? AND c.status='active'",
            (run_id,),
        ).fetchone()[0]
        return data
    finally:
        conn.close()


@app.get("/api/runs/{run_id}/companies")
def run_companies(
    run_id: str,
    tier: str | None = None,
    state: str | None = None,
    type: str | None = None,
    q: str | None = None,
    min_score: int | None = Query(None, ge=0, le=100),
    review_status: str | None = None,
    sort: str = Query("score_desc"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    conn = get_conn()
    try:
        run = conn.execute("SELECT id FROM runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")

        where = ["rc.run_id=?", "c.status='active'"]
        params: list = [run_id]
        if tier:
            tiers = [t.strip().upper() for t in tier.split(",") if t.strip()]
            if tiers:
                where.append(f"s.tier IN ({','.join('?' for _ in tiers)})")
                params.extend(tiers)
        if state:
            where.append("c.state=?")
            params.append(state.upper())
        if type:
            where.append("c.primary_type=?")
            params.append(type)
        if q:
            where.append("(c.display_name LIKE ? OR c.legal_name LIKE ? OR c.notes LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like])
        if min_score is not None:
            where.append("s.total>=?")
            params.append(min_score)
        if review_status:
            where.append("c.review_status=?")
            params.append(review_status)

        sort_sql = {
            "score_desc": "s.total DESC, c.display_name",
            "score_asc": "s.total ASC, c.display_name",
            "name": "c.display_name ASC",
            "recent": "c.last_seen_at DESC",
        }.get(sort, "s.total DESC, c.display_name")

        where_sql = " AND ".join(where)
        total = conn.execute(
            f"SELECT COUNT(*) FROM run_companies rc JOIN companies c ON c.id=rc.company_id "
            f"LEFT JOIN scores s ON s.id=rc.score_id WHERE {where_sql}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT c.*, s.total, s.tier, s.product_fit, s.buyer_intent, s.scale, s.reachability,
              s.geo_logistics, s.strategic_fit, s.breakdown_json, s.reasons_json, s.score_version
            FROM run_companies rc
            JOIN companies c ON c.id=rc.company_id
            LEFT JOIN scores s ON s.id=rc.score_id
            WHERE {where_sql}
            ORDER BY {sort_sql}
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()
        return {
            "run_id": run_id,
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [_company_summary(conn, r) for r in rows],
        }
    finally:
        conn.close()


@app.get("/api/companies/{company_id}")
def get_company(company_id: str):
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM companies WHERE id=?", (company_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="COMPANY_NOT_FOUND")
        data = _company_base(row)
        data.update(_relations(conn, company_id))
        data["sources"] = [
            dict(r)
            for r in conn.execute(
                "SELECT field, value, quote, source_url, extractor, confidence, fetched_at FROM company_sources WHERE company_id=? ORDER BY id",
                (company_id,),
            )
        ]
        data["scores"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM scores WHERE company_id=? ORDER BY created_at DESC, id DESC",
                (company_id,),
            )
        ]
        for score in data["scores"]:
            score["breakdown"] = loads(score.pop("breakdown_json", "{}"), {})
            score["reasons"] = loads(score.pop("reasons_json", "[]"), [])
        data["events"] = [
            {
                **dict(r),
                "payload": loads(r["payload_json"], {}),
            }
            for r in conn.execute(
                "SELECT event_type, actor, payload_json, created_at FROM events WHERE company_id=? ORDER BY id DESC LIMIT 50",
                (company_id,),
            )
        ]
        data["dedup_pairs"] = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM dedup_pairs WHERE left_company_id=? OR right_company_id=? ORDER BY created_at DESC",
                (company_id, company_id),
            )
        ]
        for pair in data["dedup_pairs"]:
            pair["features"] = loads(pair.pop("features_json", "{}"), {})
            pair["reasons"] = loads(pair.pop("reasons_json", "[]"), [])
        return data
    finally:
        conn.close()


@app.post("/api/companies/{company_id}/review")
def review_company(company_id: str, body: ReviewUpdate):
    if body.status not in REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail="INVALID_REVIEW_STATUS")
    conn = get_conn()
    try:
        row = conn.execute("SELECT id FROM companies WHERE id=?", (company_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="COMPANY_NOT_FOUND")
        status = "rejected" if body.status == "rejected" else "active"
        conn.execute(
            "UPDATE companies SET review_status=?, review_note=?, status=?, updated_at=? WHERE id=?",
            (body.status, body.note, status, utcnow(), company_id),
        )
        add_event(
            conn,
            "review_updated",
            company_id=company_id,
            actor="user",
            payload={"status": body.status, "note": body.note},
        )
        conn.commit()
        return {"company_id": company_id, "review_status": body.status, "status": status}
    finally:
        conn.close()


@app.get("/api/dedup/queue")
def dedup_queue(limit: int = Query(50, ge=1, le=200)):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM dedup_pairs WHERE status='pending' ORDER BY score DESC LIMIT ?", (limit,)
        ).fetchall()
        items = []
        for row in rows:
            pair = dict(row)
            for side in ("left", "right"):
                cid = pair[f"{side}_company_id"]
                c = conn.execute("SELECT * FROM companies WHERE id=?", (cid,)).fetchone()
                pair[side] = {
                    "id": c["id"],
                    "display_name": c["display_name"],
                    "website": c["website"],
                    "state": c["state"],
                    "city": c["city"],
                    "cnpj": c["cnpj"],
                    "emails": [e[0] for e in conn.execute("SELECT email FROM company_emails WHERE company_id=?", (cid,))],
                    "phones": [p[0] for p in conn.execute("SELECT e164 FROM company_phones WHERE company_id=?", (cid,))],
                }
            pair["features"] = loads(pair.pop("features_json", "{}"), {})
            pair["reasons"] = loads(pair.pop("reasons_json", "[]"), [])
            items.append(pair)
        return {"items": items, "total": len(items)}
    finally:
        conn.close()


def _move_children(conn, keep_id: str, lost_id: str) -> None:
    for table, columns in [
        ("company_aliases", "alias, alias_norm, source, created_at"),
        (
            "company_domains",
            "domain, kind, is_primary, source, first_seen_at",
        ),
        (
            "company_emails",
            "email, role, mx_ok, source, source_url, first_seen_at",
        ),
        ("company_phones", "e164, type, source"),
        (
            "company_sources",
            "field, value, quote, source_url, extractor, confidence, fetched_at",
        ),
        (
            "company_products",
            "form, grades_json, quote, source_url, confidence",
        ),
    ]:
        conn.execute(
            f"INSERT OR IGNORE INTO {table} (company_id, {columns}) "
            f"SELECT ?, {columns} FROM {table} WHERE company_id=?",
            (keep_id, lost_id),
        )
    conn.execute(
        "INSERT OR IGNORE INTO run_companies (run_id, company_id, score_id, candidate_id, dedup_status) "
        "SELECT run_id, ?, score_id, candidate_id, dedup_status FROM run_companies WHERE company_id=?",
        (keep_id, lost_id),
    )


@app.post("/api/dedup/{pair_id}/merge")
def merge_pair(pair_id: str, body: MergeRequest):
    conn = get_conn()
    try:
        pair = conn.execute("SELECT * FROM dedup_pairs WHERE id=?", (pair_id,)).fetchone()
        if not pair:
            raise HTTPException(status_code=404, detail="PAIR_NOT_FOUND")
        left, right = pair["left_company_id"], pair["right_company_id"]
        keep = body.keep_id or left
        if keep not in {left, right}:
            raise HTTPException(status_code=400, detail="KEEP_ID_NOT_IN_PAIR")
        lost = right if keep == left else left
        _move_children(conn, keep, lost)
        conn.execute(
            "UPDATE companies SET status='merged', merged_into=?, dedup_status='merged', updated_at=? WHERE id=?",
            (keep, utcnow(), lost),
        )
        conn.execute(
            "UPDATE companies SET dedup_status='unique', updated_at=? WHERE id=?",
            (utcnow(), keep),
        )
        conn.execute(
            "UPDATE dedup_pairs SET status='merged', reviewed_at=?, review_note=? WHERE id=?",
            (utcnow(), body.note, pair_id),
        )
        conn.execute(
            "UPDATE run_companies SET dedup_status='merged' WHERE company_id=?", (lost,)
        )
        add_event(
            conn,
            "dedup_merged",
            company_id=keep,
            pair_id=pair_id,
            actor="user",
            payload={"keep_id": keep, "lost_id": lost, "note": body.note},
        )
        conn.commit()
        return {"pair_id": pair_id, "status": "merged", "keep_id": keep, "lost_id": lost}
    finally:
        conn.close()


@app.post("/api/dedup/{pair_id}/dismiss")
def dismiss_pair(pair_id: str, body: MergeRequest):
    conn = get_conn()
    try:
        pair = conn.execute("SELECT * FROM dedup_pairs WHERE id=?", (pair_id,)).fetchone()
        if not pair:
            raise HTTPException(status_code=404, detail="PAIR_NOT_FOUND")
        conn.execute(
            "UPDATE dedup_pairs SET status='dismissed', reviewed_at=?, review_note=? WHERE id=?",
            (utcnow(), body.note, pair_id),
        )
        for cid in (pair["left_company_id"], pair["right_company_id"]):
            conn.execute("UPDATE companies SET dedup_status='unique' WHERE id=?", (cid,))
            conn.execute(
                "UPDATE run_companies SET dedup_status='unique' WHERE company_id=?", (cid,)
            )
        add_event(
            conn,
            "dedup_dismissed",
            pair_id=pair_id,
            actor="user",
            payload={"note": body.note},
        )
        conn.commit()
        return {"pair_id": pair_id, "status": "dismissed"}
    finally:
        conn.close()


@app.get("/api/export")
def export_csv(
    run_id: str | None = None,
    tier: str | None = None,
    state: str | None = None,
    include_rejected: bool = False,
):
    conn = get_conn()
    try:
        if not run_id:
            row = conn.execute(
                "SELECT id FROM runs WHERE status='completed' ORDER BY finished_at DESC LIMIT 1"
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="NO_COMPLETED_RUN")
            run_id = row[0]
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not run:
            raise HTTPException(status_code=404, detail="RUN_NOT_FOUND")

        where = ["rc.run_id=?", "c.status='active'"]
        params: list = [run_id]
        if not include_rejected:
            where.append("c.review_status != 'rejected'")
        if tier:
            tiers = [t.strip().upper() for t in tier.split(",") if t.strip()]
            if tiers:
                where.append(f"s.tier IN ({','.join('?' for _ in tiers)})")
                params.extend(tiers)
        if state:
            where.append("c.state=?")
            params.append(state.upper())
        rows = conn.execute(
            f"""
            SELECT c.*, s.total, s.tier, s.product_fit, s.buyer_intent, s.scale, s.reachability,
              s.geo_logistics, s.strategic_fit, s.reasons_json
            FROM run_companies rc
            JOIN companies c ON c.id=rc.company_id
            JOIN scores s ON s.id=rc.score_id
            WHERE {' AND '.join(where)}
            ORDER BY s.total DESC, c.display_name
            """,
            params,
        ).fetchall()

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "公司名称",
                "CNPJ",
                "官网",
                "州",
                "城市",
                "客户类型",
                "总分",
                "等级",
                "产品契合",
                "采购意图",
                "规模",
                "可触达",
                "地理物流",
                "战略匹配",
                "邮箱",
                "电话",
                "产品形态",
                "牌号",
                "应用行业",
                "评分理由",
                "证据来源",
                "复核状态",
            ]
        )
        for r in rows:
            cid = r["id"]
            emails = [x[0] for x in conn.execute("SELECT email FROM company_emails WHERE company_id=? ORDER BY id", (cid,))]
            phones = [x[0] for x in conn.execute("SELECT e164 FROM company_phones WHERE company_id=? ORDER BY id", (cid,))]
            forms = [x[0] for x in conn.execute("SELECT form FROM company_products WHERE company_id=? ORDER BY id", (cid,))]
            applications = [
                x[0]
                for x in conn.execute(
                    "SELECT value FROM company_sources WHERE company_id=? AND field='applications' ORDER BY id",
                    (cid,),
                )
            ]
            sources = [x[0] for x in conn.execute("SELECT DISTINCT source_url FROM company_sources WHERE company_id=? AND source_url IS NOT NULL AND source_url != ''", (cid,))]
            writer.writerow(
                [
                    r["display_name"],
                    r["cnpj"] or "",
                    r["website"] or "",
                    r["state"] or "",
                    r["city"] or "",
                    r["primary_type"] or "",
                    r["total"],
                    r["tier"],
                    r["product_fit"],
                    r["buyer_intent"],
                    r["scale"],
                    r["reachability"],
                    r["geo_logistics"],
                    r["strategic_fit"],
                    "; ".join(emails),
                    "; ".join(phones),
                    "; ".join(forms),
                    "; ".join(sorted({g for x in conn.execute("SELECT grades_json FROM company_products WHERE company_id=?", (cid,)) for g in loads(x[0], [])})),
                    "; ".join(applications),
                    " | ".join(loads(r["reasons_json"], [])),
                    "; ".join(sources),
                    r["review_status"],
                ]
            )
        data = "\ufeff" + buf.getvalue()
        filename = f"steel_customers_{run_id}.csv"
        return Response(
            content=data.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    finally:
        conn.close()


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str, limit: int = Query(100, ge=1, le=500)):
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM events WHERE run_id=? ORDER BY id DESC LIMIT ?", (run_id, limit)
        ).fetchall()
        return {
            "items": [{**dict(r), "payload": loads(r["payload_json"], {})} for r in rows]
        }
    finally:
        conn.close()


if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
else:

    @app.get("/")
    def root():
        return JSONResponse(
            {
                "message": "API is running. Build the frontend with: cd frontend && npm.cmd install && npm.cmd run build",
                "docs": "/docs",
            }
        )
