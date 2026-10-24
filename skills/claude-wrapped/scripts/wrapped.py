#!/usr/bin/env python3
"""Claude Wrapped — turn your local Claude Code history into a shareable stats page.

Reads ~/.claude/projects/*/*.jsonl (your own on-disk session logs), computes a
year-in-review, and writes a single self-contained HTML file you can open and
screenshot. Nothing is uploaded anywhere; everything runs locally.

Usage:
    python3 wrapped.py [--projects DIR] [--out FILE] [--open]
"""
import argparse
import datetime as dt
import glob
import html
import json
import os
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

MODEL_NAMES = {
    "opus": "Opus",
    "sonnet": "Sonnet",
    "haiku": "Haiku",
    "fable": "Fable",
}


def pretty_model(model_id: str) -> str:
    """claude-opus-5-5 -> Opus 5.5 ; fall back to the raw id."""
    if not model_id or model_id.startswith("<"):
        return model_id or "unknown"
    parts = model_id.replace("claude-", "").split("-")
    family = next((MODEL_NAMES[p] for p in parts if p in MODEL_NAMES), None)
    nums = [p for p in parts if p.isdigit()]
    if family and nums:
        return f"{family} {'.'.join(nums)}"
    return family or model_id


def pretty_project(dirname: str, home: str) -> str:
    """Turn the mangled project dir name back into a readable path."""
    name = dirname
    # Claude Code encodes the cwd by replacing '/' with '-'.
    tag = home.replace("/", "-")
    if name.startswith(tag):
        name = "~" + name[len(tag):]
    name = name.replace("-", "/")
    return name or "~"


def collect(projects_dir: str):
    files = sorted(glob.glob(os.path.join(projects_dir, "*", "*.jsonl")))
    home = os.path.expanduser("~")

    data = {
        "sessions": set(),
        "user_msgs": 0,
        "asst_msgs": 0,
        "models": Counter(),
        "tools": Counter(),
        "projects": Counter(),
        "out_tok": 0,
        "cache_r": 0,
        "think_ms": 0,
        "by_hour": Counter(),
        "by_dow": Counter(),
        "by_day": Counter(),
        "sess_msgs": Counter(),
        "first": None,
        "last": None,
        "user_chars": 0,
    }

    for fp in files:
        proj = pretty_project(os.path.basename(os.path.dirname(fp)), home)
        try:
            fh = open(fp, errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except (ValueError, TypeError):
                    continue
                t = o.get("type")
                sid = o.get("sessionId")
                if sid:
                    data["sessions"].add(sid)

                ts = o.get("timestamp")
                when = None
                if ts:
                    try:
                        when = dt.datetime.fromisoformat(
                            ts.replace("Z", "+00:00")
                        ).astimezone()  # convert to the viewer's local time
                    except (ValueError, TypeError):
                        when = None

                if when and t in ("user", "assistant"):
                    if data["first"] is None or when < data["first"]:
                        data["first"] = when
                    if data["last"] is None or when > data["last"]:
                        data["last"] = when
                    data["by_hour"][when.hour] += 1
                    data["by_dow"][when.strftime("%A")] += 1
                    data["by_day"][when.date().isoformat()] += 1

                msg = o.get("message")
                if t == "user" and isinstance(msg, dict):
                    content = msg.get("content")
                    only_tool_results = (
                        isinstance(content, list)
                        and content
                        and all(
                            isinstance(b, dict) and b.get("type") == "tool_result"
                            for b in content
                        )
                    )
                    if not only_tool_results:
                        data["user_msgs"] += 1
                        data["projects"][proj] += 1
                        if sid:
                            data["sess_msgs"][sid] += 1
                        if isinstance(content, str):
                            data["user_chars"] += len(content)
                        elif isinstance(content, list):
                            for b in content:
                                if isinstance(b, dict) and b.get("type") == "text":
                                    data["user_chars"] += len(b.get("text", ""))
                elif t == "assistant" and isinstance(msg, dict):
                    data["asst_msgs"] += 1
                    if msg.get("model"):
                        data["models"][msg["model"]] += 1
                    usage = msg.get("usage") or {}
                    data["out_tok"] += usage.get("output_tokens", 0) or 0
                    data["cache_r"] += usage.get("cache_read_input_tokens", 0) or 0
                    data["think_ms"] += o.get("thinkingDurationMs", 0) or 0
                    content = msg.get("content")
                    if isinstance(content, list):
                        for b in content:
                            if isinstance(b, dict) and b.get("type") == "tool_use":
                                data["tools"][b.get("name", "?")] += 1
    return data


# ---------------------------------------------------------------------------
# Persona — a fun label derived from the numbers
# ---------------------------------------------------------------------------

def choose_persona(d):
    top_tool = d["tools"].most_common(1)
    top_tool = top_tool[0][0] if top_tool else ""
    hours = d["by_hour"]
    night = sum(hours.get(h, 0) for h in list(range(22, 24)) + list(range(0, 5)))
    total_h = sum(hours.values()) or 1
    night_share = night / total_h

    if night_share > 0.33:
        return ("The Night Owl", "You and Claude do your best work after dark.")
    if top_tool == "Bash":
        return ("The Terminal Wizard", "The command line is your natural habitat.")
    if top_tool in ("Write", "Edit"):
        return ("The Builder", "You ship. Files appear wherever you go.")
    if top_tool == "WebSearch":
        return ("The Researcher", "No question left ungoogled.")
    if top_tool.startswith("mcp__"):
        return ("The Power User", "You wire Claude into everything.")
    return ("The Explorer", "A bit of everything, always curious.")


# ---------------------------------------------------------------------------
# Build the stats payload the page renders
# ---------------------------------------------------------------------------

def human(n):
    for unit, size in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if abs(n) >= size:
            v = n / size
            return (f"{v:.1f}".rstrip("0").rstrip(".")) + unit
    return str(int(n))


def build_payload(d):
    first, last = d["first"], d["last"]
    span_days = ((last - first).days + 1) if first and last else 0
    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday"]

    top_hour = d["by_hour"].most_common(1)
    busiest_day = d["by_day"].most_common(1)
    top_model = d["models"].most_common(1)
    longest = d["sess_msgs"].most_common(1)
    persona_title, persona_sub = choose_persona(d)

    def fmt_hour(h):
        ampm = "AM" if h < 12 else "PM"
        h12 = h % 12 or 12
        return f"{h12} {ampm}"

    return {
        "generated": dt.datetime.now().strftime("%b %d, %Y"),
        "range": (
            f"{first.strftime('%b %d')} – {last.strftime('%b %d, %Y')}"
            if first and last else "your sessions"
        ),
        "persona_title": persona_title,
        "persona_sub": persona_sub,
        "sessions": len(d["sessions"]),
        "prompts": d["user_msgs"],
        "prompts_h": human(d["user_msgs"]),
        "replies": d["asst_msgs"],
        "replies_h": human(d["asst_msgs"]),
        "tool_calls": sum(d["tools"].values()),
        "tool_calls_h": human(sum(d["tools"].values())),
        "out_tok_h": human(d["out_tok"]),
        "cache_r_h": human(d["cache_r"]),
        "think_min": round(d["think_ms"] / 60000),
        "think_hours": round(d["think_ms"] / 3_600_000, 1),
        "active_days": len([1 for v in d["by_day"].values() if v]),
        "span_days": span_days,
        "words_written": human(int(d["out_tok"] * 0.75)),  # ~0.75 words/token
        "top_tools": [
            {"name": n, "count": c, "count_h": human(c)}
            for n, c in d["tools"].most_common(5)
        ],
        "top_projects": [
            {"name": n, "count": c} for n, c in d["projects"].most_common(5)
        ],
        "models": [
            {"name": pretty_model(m), "count": c}
            for m, c in d["models"].most_common(6)
            if not m.startswith("<")
        ],
        "top_model": pretty_model(top_model[0][0]) if top_model else "—",
        "top_hour": fmt_hour(top_hour[0][0]) if top_hour else "—",
        "top_dow": d["by_dow"].most_common(1)[0][0] if d["by_dow"] else "—",
        "busiest_day": busiest_day[0][0] if busiest_day else "—",
        "busiest_day_n": busiest_day[0][1] if busiest_day else 0,
        "longest_session": longest[0][1] if longest else 0,
        "hours": [d["by_hour"].get(h, 0) for h in range(24)],
        "dow": [d["by_dow"].get(x, 0) for x in dow_order],
    }


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Wrapped</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{
  --ink:#F6F3EE; --muted:#B9B2C7;
  --c1:#D97757; --c2:#7B5EA7; --c3:#2F6F6B; --c4:#C9A227; --c5:#B5485D;
  --display:"Space Grotesk",system-ui,sans-serif;
  --body:"Inter",system-ui,sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-snap-type:y mandatory;scroll-behavior:smooth}
body{font-family:var(--body);color:var(--ink);background:#15121B}
.card{min-height:100svh;scroll-snap-align:start;display:flex;flex-direction:column;
  justify-content:center;align-items:center;text-align:center;
  padding:max(28px,env(safe-area-inset-top)) 22px max(28px,env(safe-area-inset-bottom));
  position:relative;overflow:hidden}
.inner{width:100%;max-width:720px;position:relative;z-index:2;
  opacity:0;transform:translateY(26px);transition:opacity .7s ease,transform .7s ease}
.card.in .inner{opacity:1;transform:none}
.eyebrow{font-family:var(--display);font-weight:500;letter-spacing:.22em;
  text-transform:uppercase;font-size:.8rem;opacity:.85;margin-bottom:18px}
.big{font-family:var(--display);font-weight:700;line-height:.95;
  font-size:clamp(3.6rem,20vw,9rem);letter-spacing:-.02em;text-wrap:balance}
.sub{font-family:var(--display);font-weight:500;font-size:clamp(1.3rem,5vw,2rem);margin-top:6px}
.note{font-size:clamp(1rem,3.4vw,1.2rem);color:var(--muted);margin-top:20px;
  max-width:34ch;margin-left:auto;margin-right:auto;line-height:1.5}
.bg{position:absolute;inset:0;z-index:1;opacity:.95}
.list{display:flex;flex-direction:column;gap:12px;margin-top:30px;text-align:left}
.row{display:flex;align-items:center;gap:14px;background:rgba(255,255,255,.08);
  border:1px solid rgba(255,255,255,.12);border-radius:16px;padding:14px 18px;
  font-family:var(--display);backdrop-filter:blur(6px)}
.rank{font-weight:700;font-size:1.3rem;opacity:.55;min-width:1.4ch}
.rname{font-weight:500;font-size:clamp(1rem,4vw,1.25rem);flex:1;min-width:0;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rval{font-weight:700;font-size:1.05rem;font-variant-numeric:tabular-nums;opacity:.9}
.bars{display:flex;align-items:flex-end;gap:3px;height:160px;margin-top:34px;
  width:100%;max-width:560px;margin-left:auto;margin-right:auto}
.bar{flex:1;background:linear-gradient(180deg,var(--ink),rgba(255,255,255,.35));
  border-radius:4px 4px 0 0;min-height:3px;transition:height .9s cubic-bezier(.2,.8,.2,1)}
.axis{display:flex;justify-content:space-between;max-width:560px;margin:8px auto 0;
  width:100%;font-size:.72rem;color:var(--muted);font-family:var(--display)}
.stat-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:30px}
.tile{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.12);
  border-radius:18px;padding:20px 16px}
.tile .n{font-family:var(--display);font-weight:700;font-size:clamp(1.6rem,7vw,2.4rem);
  font-variant-numeric:tabular-nums}
.tile .l{font-size:.82rem;color:var(--muted);margin-top:6px;letter-spacing:.04em}
.scrollcue{position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:9;
  font-family:var(--display);font-size:.72rem;letter-spacing:.2em;text-transform:uppercase;
  color:rgba(255,255,255,.7);animation:bob 1.8s infinite;pointer-events:none}
@keyframes bob{0%,100%{transform:translate(-50%,0)}50%{transform:translate(-50%,6px)}}
.foot{font-size:.85rem;color:var(--muted);margin-top:26px;line-height:1.6}
.tag{display:inline-block;font-family:var(--display);font-weight:500;font-size:.82rem;
  letter-spacing:.14em;text-transform:uppercase;padding:7px 14px;border-radius:999px;
  background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.2);margin-top:22px}
@media (prefers-reduced-motion:reduce){
  html{scroll-behavior:auto}
  .inner{opacity:1;transform:none;transition:none}
}
</style>
</head>
<body>
<div id="app"></div>
<div class="scrollcue" id="cue">scroll ↓</div>
<script>
const DATA = __DATA__;

function grad(a,b){return `radial-gradient(120% 120% at 30% 10%, ${a} 0%, ${b} 70%, #120F18 120%)`;}

const cards = [];

// 1. Cover
cards.push({bg:grad('#D97757','#7B5EA7'), html:`
  <div class="eyebrow">Claude Wrapped</div>
  <div class="big">Your<br>Wrapped</div>
  <div class="note">${DATA.range}. Everything below was built from the session logs on your own machine.</div>
  <div class="tag">${DATA.active_days} active days</div>`});

// 2. Persona
cards.push({bg:grad('#7B5EA7','#2F6F6B'), html:`
  <div class="eyebrow">Your type this year</div>
  <div class="sub" style="opacity:.8">You were</div>
  <div class="big" style="font-size:clamp(2.6rem,12vw,5.5rem)">${DATA.persona_title}</div>
  <div class="note">${DATA.persona_sub}</div>`});

// 3. Prompts
cards.push({bg:grad('#2F6F6B','#15303A'), html:`
  <div class="eyebrow">You asked</div>
  <div class="big">${DATA.prompts_h}</div>
  <div class="sub">prompts</div>
  <div class="note">and Claude sent back ${DATA.replies_h} replies across ${DATA.sessions} sessions.</div>`});

// 4. Tool calls
cards.push({bg:grad('#C9A227','#8A5A1E'), html:`
  <div class="eyebrow">Behind the scenes</div>
  <div class="big">${DATA.tool_calls_h}</div>
  <div class="sub">tool calls</div>
  <div class="list">${DATA.top_tools.map((t,i)=>`
    <div class="row"><span class="rank">${i+1}</span>
      <span class="rname">${t.name}</span>
      <span class="rval">${t.count_h}</span></div>`).join('')}</div>`});

// 5. Words
cards.push({bg:grad('#B5485D','#5A1E33'), html:`
  <div class="eyebrow">Claude wrote you</div>
  <div class="big">${DATA.out_tok_h}</div>
  <div class="sub">tokens</div>
  <div class="note">roughly ${DATA.words_written} words — and read back ${DATA.cache_r_h} cached tokens to keep up with you.</div>`});

// 6. When — hour bars
cards.push({bg:grad('#3A4CC9','#171F57'), html:`
  <div class="eyebrow">When you work</div>
  <div class="sub">Peak hour: <b>${DATA.top_hour}</b></div>
  <div class="bars" id="hourbars">${DATA.hours.map(v=>`<div class="bar" data-v="${v}"></div>`).join('')}</div>
  <div class="axis"><span>12a</span><span>6a</span><span>12p</span><span>6p</span><span>11p</span></div>
  <div class="note">Your busiest single day was ${DATA.busiest_day} with ${DATA.busiest_day_n} events. Favourite day: ${DATA.top_dow}.</div>`});

// 7. Thinking
cards.push({bg:grad('#D97757','#8A2E1E'), html:`
  <div class="eyebrow">Claude spent</div>
  <div class="big">${DATA.think_hours}</div>
  <div class="sub">hours thinking</div>
  <div class="note">just reasoning through your problems before replying — about ${DATA.think_min} minutes in total.</div>`});

// 8. Projects
cards.push({bg:grad('#2F6F6B','#123'), html:`
  <div class="eyebrow">Where you spent it</div>
  <div class="sub">Top projects</div>
  <div class="list">${DATA.top_projects.map((p,i)=>`
    <div class="row"><span class="rank">${i+1}</span>
      <span class="rname">${p.name}</span>
      <span class="rval">${p.count}</span></div>`).join('')}</div>`});

// 9. Summary / share
cards.push({bg:grad('#D97757','#7B5EA7'), html:`
  <div class="eyebrow">${DATA.generated} · Claude Wrapped</div>
  <div class="sub" style="margin-bottom:6px">${DATA.persona_title}</div>
  <div class="stat-grid">
    <div class="tile"><div class="n">${DATA.prompts_h}</div><div class="l">prompts</div></div>
    <div class="tile"><div class="n">${DATA.tool_calls_h}</div><div class="l">tool calls</div></div>
    <div class="tile"><div class="n">${DATA.top_model}</div><div class="l">top model</div></div>
    <div class="tile"><div class="n">${DATA.think_hours}h</div><div class="l">thinking</div></div>
  </div>
  <div class="foot">Screenshot this card and share it.<br>Make your own: <b>claude-wrapped</b></div>`});

const app = document.getElementById('app');
app.innerHTML = cards.map(c=>`<section class="card" style="--bgi:0">
  <div class="bg" style="background:${c.bg}"></div>
  <div class="inner">${c.html}</div></section>`).join('');

const secs = [...document.querySelectorAll('.card')];
const io = new IntersectionObserver((es)=>{
  es.forEach(e=>{
    if(e.isIntersecting){
      e.target.classList.add('in');
      const bars = e.target.querySelectorAll('#hourbars .bar');
      if(bars.length){
        const max = Math.max(...[...bars].map(b=>+b.dataset.v))||1;
        bars.forEach(b=>{b.style.height=(8+ (+b.dataset.v/max)*152)+'px';});
      }
    }
  });
},{threshold:.5});
secs.forEach(s=>io.observe(s));

addEventListener('scroll',()=>{const c=document.getElementById('cue');if(c)c.style.opacity=scrollY>80?0:1;},{passive:true});
</script>
</body>
</html>
"""


def render(payload) -> str:
    return TEMPLATE.replace("__DATA__", json.dumps(payload))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate your Claude Wrapped page.")
    ap.add_argument("--projects", default=os.path.expanduser("~/.claude/projects"),
                    help="Path to ~/.claude/projects")
    ap.add_argument("--out", default="claude-wrapped.html",
                    help="Output HTML file")
    ap.add_argument("--open", action="store_true",
                    help="Open the result in your browser when done")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.projects):
        sys.exit(
            f"No Claude Code history found at {args.projects}\n"
            "Use --projects to point at your ~/.claude/projects directory."
        )

    data = collect(args.projects)
    if data["asst_msgs"] == 0:
        sys.exit("No sessions found yet — chat with Claude Code first, then try again.")

    payload = build_payload(data)
    out = os.path.abspath(args.out)
    with open(out, "w") as fh:
        fh.write(render(payload))

    print("\n  Claude Wrapped\n  " + "-" * 32)
    print(f"  {payload['persona_title']}")
    print(f"  {payload['prompts']} prompts · {payload['tool_calls']} tool calls "
          f"· {payload['think_hours']}h thinking")
    print(f"  Top model: {payload['top_model']}  ·  Peak hour: {payload['top_hour']}")
    print(f"\n  Saved: {out}")
    print("  Open it in a browser and screenshot the last card to share.\n")

    if args.open:
        import webbrowser
        webbrowser.open("file://" + out)


if __name__ == "__main__":
    main()
