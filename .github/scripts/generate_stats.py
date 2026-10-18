"""Generate Allen-style GitHub stats cards (dark + light SVG) from the GitHub GraphQL API."""
import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

USER = os.environ.get("GH_USER", "Vampire0011")
DISPLAY_NAME = os.environ.get("DISPLAY_NAME", "Vampire")
TOKEN = os.environ.get("GH_TOKEN", "")
OUT_DIR = os.environ.get("OUT_DIR", "assets")

API = "https://api.github.com/graphql"


def gql(query, variables):
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        data = json.load(r)
    if "errors" in data:
        sys.exit(f"GraphQL error: {data['errors']}")
    return data["data"]


CAL_Q = """
query($login:String!,$from:DateTime!,$to:DateTime!){
  user(login:$login){
    contributionsCollection(from:$from,to:$to){
      contributionCalendar{ totalContributions weeks{ contributionDays{ date contributionCount } } }
    }
  }
}"""

INFO_Q = """
query($login:String!,$after:String){
  user(login:$login){
    createdAt
    pullRequests{ totalCount }
    repositories(ownerAffiliations:OWNER, privacy:PUBLIC, first:100, after:$after){
      totalCount
      pageInfo{ hasNextPage endCursor }
      nodes{ stargazerCount isFork }
    }
  }
}"""


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def calendar(start, end):
    d = gql(CAL_Q, {"login": USER, "from": iso(start), "to": iso(end)})
    cal = d["user"]["contributionsCollection"]["contributionCalendar"]
    days = [(x["date"], x["contributionCount"]) for w in cal["weeks"] for x in w["contributionDays"]]
    return cal["totalContributions"], days


def collect():
    now = datetime.now(timezone.utc)

    # repos, stars, PRs
    stars, repos, after, created, prs = 0, 0, None, None, 0
    while True:
        u = gql(INFO_Q, {"login": USER, "after": after})["user"]
        created = datetime.fromisoformat(u["createdAt"].replace("Z", "+00:00"))
        prs = u["pullRequests"]["totalCount"]
        repos = u["repositories"]["totalCount"]
        stars += sum(n["stargazerCount"] for n in u["repositories"]["nodes"] if not n["isFork"])
        pi = u["repositories"]["pageInfo"]
        if not pi["hasNextPage"]:
            break
        after = pi["endCursor"]

    # contributions in the last year
    total_1y, _ = calendar(now - timedelta(days=365), now)

    # all-time daily counts for streaks (API allows 1 year per request)
    counts = {}
    for year in range(created.year, now.year + 1):
        s = datetime(year, 1, 1, tzinfo=timezone.utc)
        e = min(datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc), now)
        _, days = calendar(s, e)
        for d, c in days:
            counts[d] = c

    return {"contribs": total_1y, "stars": stars, "repos": repos, "prs": prs, "counts": counts}


def streaks(counts):
    days = sorted(counts)
    longest = run = 0
    for d in days:
        run = run + 1 if counts[d] > 0 else 0
        longest = max(longest, run)
    # current streak: walk back from today (or yesterday if today has no contributions yet)
    today = date.today()
    cur, d = 0, today
    if counts.get(d.isoformat(), 0) == 0:
        d -= timedelta(days=1)
    while counts.get(d.isoformat(), 0) > 0:
        cur += 1
        d -= timedelta(days=1)
    return cur, longest


THEMES = {
    "dark": {"bg": "#0d1117", "title": "#ffffff", "num": "#58a6ff", "label": "#9da7b3", "border": "#30363d"},
    "light": {"bg": "#ffffff", "title": "#1f2328", "num": "#0969da", "label": "#59636e", "border": "#d1d9e0"},
}


def svg(theme, items):
    t = THEMES[theme]
    w, h = 826, 145
    col_w = (w - 30) / len(items)
    font = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{DISPLAY_NAME} GitHub stats">',
        f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="6" fill="{t["bg"]}" stroke="{t["border"]}"/>',
        f'<text x="15" y="33" font-family="{font}" font-size="18" font-weight="600" fill="{t["title"]}">{DISPLAY_NAME}\'s GitHub Stats</text>',
    ]
    for i, (value, label) in enumerate(items):
        cx = 15 + col_w * i + col_w / 2
        out.append(f'<text x="{cx:.1f}" y="86" text-anchor="middle" font-family="{font}" font-size="30" font-weight="700" fill="{t["num"]}">{value}</text>')
        out.append(f'<text x="{cx:.1f}" y="110" text-anchor="middle" font-family="{font}" font-size="12" fill="{t["label"]}">{label}</text>')
    out.append("</svg>")
    return "\n".join(out)


def main():
    if not TOKEN:
        sys.exit("GH_TOKEN is not set")
    s = collect()
    cur, longest = streaks(s["counts"])
    items = [
        (s["contribs"], "Contributions (1y)"),
        (f"{cur}d", "Current streak"),
        (f"{longest}d", "Longest streak"),
        (s["stars"], "Stars earned"),
        (s["repos"], "Repositories"),
        (s["prs"], "Pull requests"),
    ]
    os.makedirs(OUT_DIR, exist_ok=True)
    for theme in THEMES:
        with open(os.path.join(OUT_DIR, f"stats-{theme}.svg"), "w", encoding="utf-8") as f:
            f.write(svg(theme, items))
    print("Generated:", items)


if __name__ == "__main__":
    main()
