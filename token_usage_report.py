#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hermes Token Plan 用量分析报告（【优化消耗token】触发时运行）。

数据源：D:/hermes/state.db —— Hermes 自己的精确用量记录。
注意：腾讯 TokenHub 个人版套餐无 API 可查用量（管控面 DescribeTokenPlan 仅企业版，
且该套餐账号下返回空），本机 state.db 是唯一权威源。

用法:
  python token_usage_report.py [--days 2] [--limit 12]
"""
import argparse, sqlite3, sys, time
from datetime import datetime, timezone, timedelta

DB = r"D:/hermes/state.db"

def ts_fmt(ts):
    if not ts: return "-"
    return datetime.fromtimestamp(ts, timezone(timedelta(hours=8))).strftime("%m-%d %H:%M")

def fmt_tok(n):
    if n is None: return "-"
    if n >= 1_000_000: return f"{n/1e6:.2f}M"
    if n >= 1000: return f"{n/1000:.1f}K"
    return str(n)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=2.0)
    ap.add_argument("--limit", type=int, default=15)
    a = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    since = time.time() - a.days * 86400

    # 会话级聚合
    rows = cur.execute("""
        SELECT id, display_name, title, source, started_at, last_activity_at,
               input_tokens, output_tokens, cache_read_tokens, reasoning_tokens,
               estimated_cost_usd, cost_status, api_call_count, model
        FROM sessions
        WHERE COALESCE(last_activity_at, started_at) >= ?
        ORDER BY COALESCE(last_activity_at, started_at) DESC
    """, (since,)).fetchall()

    if not rows:
        print("窗口内无会话。")
        return

    tot_in=tot_out=tot_cache=tot_reas=calls=0
    print(f"=== Token 用量报告（近 {a.days:.0f} 天，{ts_fmt(since)} 起）===")
    for r in rows:
        d = dict(r)
        i= d["input_tokens"] or 0; o=d["output_tokens"] or 0
        c=d["cache_read_tokens"] or 0; re=d["reasoning_tokens"] or 0
        n=d["api_call_count"] or 0
        tot_in+=i; tot_out+=o; tot_cache+=c; tot_reas+=re; calls+=n
        cache_ratio = (c+i+o) and c/(c+i+o) or 0
        out_per = o/n if n else 0
        reas_ratio = (re+o) and re/(re+o) or 0
        title = (d["title"] or d["display_name"] or d["id"])[:34]
        print(f"\n[{ts_fmt(d['started_at'])}] {title}")
        print(f"  源={d['source']} 调用={n} 输入={fmt_tok(i)} 输出={fmt_tok(o)} 缓存读={fmt_tok(c)} 推理={fmt_tok(re)}")
        print(f"  均输出/次={int(out_per)} 缓存占比={cache_ratio:.0%} 推理/输出={reas_ratio:.0%} 成本=${d['estimated_cost_usd'] or 0} status={d['cost_status']}")
        # 异常标记
        flags=[]
        if cache_ratio > 0.8: flags.append("⚠上下文缓存主导(超长历史每轮重读)")
        if out_per > 12000: flags.append("⚠单次输出偏大")
        if reas_ratio > 0.6 and re > 3000: flags.append("⚠推理链冗长")
        if flags:
            print("  " + " | ".join(flags))

    print("\n=== 总量 ===")
    print(f"输入={fmt_tok(tot_in)} 输出={fmt_tok(tot_out)} 缓存读={fmt_tok(tot_cache)} 推理={fmt_tok(tot_reas)} 调用数={calls}")
    print(f"缓存读 / (输入+输出) = {tot_cache/(tot_in+tot_out) if tot_in+tot_out else 0:.1f}x  ← 上下文重读是最大放大项")

    # 模型×任务级明细
    print("\n=== 模型×任务 明细 ===")
    smu = cur.execute("""
        SELECT model, task, billing_provider, api_call_count, input_tokens, output_tokens,
               cache_read_tokens, reasoning_tokens, estimated_cost_usd
        FROM session_model_usage WHERE last_seen >= ?
        ORDER BY (output_tokens+input_tokens+cache_read_tokens) DESC LIMIT ?
    """, (since, a.limit)).fetchall()
    for r in smu:
        d=dict(r)
        n=d["api_call_count"] or 0
        o=d["output_tokens"] or 0
        out_per = o/n if n else 0
        print(f"  {d['model']:<28} task={d['task'] or '-':<16} 调用={n:<3} 输出/次={int(out_per):<6} 输入={fmt_tok(d['input_tokens']):<7} 输出={fmt_tok(o):<7} 缓存={fmt_tok(d['cache_read_tokens'])} 推理={fmt_tok(d['reasoning_tokens'])}")

    print("\n提示: cost=0/unknown = Hermes 未给该模型配价格，仅 token 数可信。")

if __name__ == "__main__":
    main()
