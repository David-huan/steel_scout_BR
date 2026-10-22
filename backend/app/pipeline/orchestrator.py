import traceback

from ..db import add_event, dumps, get_conn, new_id, utcnow
from .brief import build_brief
from .classify import classify
from .crawl import crawl_run
from .dedup import dedup_run
from .discovery import discover
from .enrich import enrich_run
from .queries import generate_queries
from .score import score_company

STAGES = ["brief", "queries", "discovery", "crawl", "enrich", "classify", "dedup"]


def _stage(conn, run_id: str, stage: str, status: str, stats: dict | None = None, error: str | None = None) -> None:
    now = utcnow()
    conn.execute(
        "INSERT OR IGNORE INTO run_stages (run_id, stage, status, stats_json, warnings_json, started_at) VALUES (?,?,?,?,?,?)",
        (run_id, stage, "pending", "{}", "[]", now),
    )
    if status == "running":
        conn.execute(
            "UPDATE run_stages SET status=?, started_at=COALESCE(started_at, ?) WHERE run_id=? AND stage=?",
            (status, now, run_id, stage),
        )
    else:
        conn.execute(
            "UPDATE run_stages SET status=?, finished_at=?, stats_json=?, error=? WHERE run_id=? AND stage=?",
            (status, now, dumps(stats or {}), error, run_id, stage),
        )
    conn.execute("UPDATE runs SET current_stage=? WHERE id=?", (stage, run_id))
    conn.commit()


def _fail(conn, run_id: str, stage: str, exc: Exception) -> None:
    tb = traceback.format_exc()[-3000:]
    now = utcnow()
    conn.execute(
        "UPDATE runs SET status='failed', error=?, finished_at=? WHERE id=?",
        (f"{type(exc).__name__}: {exc}", now, run_id),
    )
    _stage(conn, run_id, stage, "failed", error=str(exc))
    add_event(
        conn,
        "run_failed",
        run_id=run_id,
        payload={"stage": stage, "error": str(exc), "traceback": tb},
    )
    conn.commit()


def run_pipeline(run_id: str) -> None:
    conn = get_conn()
    current = "brief"
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return
        conn.execute(
            "UPDATE runs SET status='running', started_at=?, current_stage='brief' WHERE id=?",
            (utcnow(), run_id),
        )
        for stage in STAGES:
            conn.execute(
                "INSERT OR IGNORE INTO run_stages (run_id, stage, status, stats_json, warnings_json) VALUES (?,?,?,?,?)",
                (run_id, stage, "pending", "{}", "[]"),
            )
        conn.commit()

        _stage(conn, run_id, "brief", "running")
        brief = build_brief(row["product"], row["country"], row["target_count"])
        conn.execute("UPDATE runs SET brief_json=? WHERE id=?", (dumps(brief.to_dict()), run_id))
        conn.commit()
        _stage(conn, run_id, "brief", "done", brief.to_dict())

        _stage(conn, run_id, "queries", "running")
        queries = generate_queries(brief)
        for q in queries:
            q["id"] = new_id("q")
            conn.execute(
                """
                INSERT OR IGNORE INTO queries (id, run_id, text, lang, source, dimensions_json,
                  expected_types_json, priority, query_hash, status, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    q["id"],
                    run_id,
                    q["text"],
                    q["lang"],
                    q["source"],
                    dumps(q["dimensions"]),
                    dumps(q["expected_types"]),
                    q["priority"],
                    q["query_hash"],
                    "pending",
                    utcnow(),
                ),
            )
        conn.commit()
        _stage(conn, run_id, "queries", "done", {"queries": len(queries)})

        _stage(conn, run_id, "discovery", "running")
        discovery_stats = discover(run_id, brief, queries, conn)
        _stage(conn, run_id, "discovery", "done", discovery_stats)

        _stage(conn, run_id, "crawl", "running")
        crawl_stats = crawl_run(run_id, conn)
        _stage(
            conn,
            run_id,
            "crawl",
            "done",
            {k: v for k, v in crawl_stats.items() if k != "companies"},
        )

        _stage(conn, run_id, "enrich", "running")
        enriched = enrich_run(run_id, crawl_stats["companies"], conn)
        companies = enriched["companies"]
        _stage(conn, run_id, "enrich", "done", {"enriched": enriched["enriched"]})

        _stage(conn, run_id, "classify", "running")
        type_counts: dict[str, int] = {}
        for company in companies:
            cls = classify(company)
            company.update(
                {
                    "primary_type": cls["primary_type"],
                    "secondary_types": cls["secondary_types"],
                    "type_confidence": cls["type_confidence"],
                    "status": cls["status"],
                }
            )
            company["sources"] = (company.get("sources") or []) + cls["evidence"]
            company["score"] = score_company(company)
            type_counts[cls["primary_type"]] = type_counts.get(cls["primary_type"], 0) + 1
        _stage(
            conn,
            run_id,
            "classify",
            "done",
            {"classified": len(companies), "type_counts": type_counts},
        )

        _stage(conn, run_id, "dedup", "running")
        dedup_stats = dedup_run(run_id, companies, conn)
        _stage(
            conn,
            run_id,
            "dedup",
            "done",
            {k: v for k, v in dedup_stats.items() if k != "canonical"},
        )

        stats = {
            "candidates": discovery_stats.get("candidates", 0),
            "companies": dedup_stats.get("companies", 0),
            "qualified": conn.execute(
                "SELECT COUNT(*) FROM run_companies rc JOIN scores s ON s.id=rc.score_id "
                "JOIN companies c ON c.id=rc.company_id WHERE rc.run_id=? AND s.total>=55 AND c.status='active'",
                (run_id,),
            ).fetchone()[0],
            "tier_a": dedup_stats.get("tier_a", 0),
            "tier_b": dedup_stats.get("tier_b", 0),
            "emails": dedup_stats.get("emails", 0),
            "auto_merged": dedup_stats.get("auto_merged", 0),
            "review_pairs": dedup_stats.get("review_pairs", 0),
            "live_ok": crawl_stats.get("live_ok", 0),
            "seed_fallback": crawl_stats.get("seed_fallback", 0),
            "serper_queries": discovery_stats.get("serper_queries", 0),
            "type_counts": type_counts,
        }
        conn.execute(
            "UPDATE runs SET status='completed', stats_json=?, current_stage='done', finished_at=? WHERE id=?",
            (dumps(stats), utcnow(), run_id),
        )
        add_event(conn, "run_completed", run_id=run_id, payload=stats)
        conn.commit()
    except Exception as exc:
        row = conn.execute("SELECT current_stage FROM runs WHERE id=?", (run_id,)).fetchone()
        _fail(conn, run_id, row[0] if row and row[0] else current, exc)
    finally:
        conn.close()

