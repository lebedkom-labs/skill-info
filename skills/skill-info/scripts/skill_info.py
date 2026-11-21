#!/usr/bin/env python3
"""skill-info: trust & provenance report for a skill listed on skills.sh.

Usage:
    skill_info.py <query> [--json] [--no-clone] [--max-commits N]

<query> may be:
    find-skills                              bare skill name (resolved via skills.sh search)
    vercel-labs/skills/find-skills           full skills.sh id
    vercel-labs/skills@find-skills           owner/repo@skill
    https://skills.sh/vercel-labs/skills/find-skills
    https://github.com/vercel-labs/skills    (whole repo; picks the matching skill if --skill given)

Stdlib only. Network: skills.sh, api.github.com, github.com (blobless clone).
Set GITHUB_TOKEN / GH_TOKEN to raise the GitHub API limit from 60 to 5000 req/h.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

UA = "skill-info/1.0 (+https://skills.sh)"
SKILLS = "https://skills.sh"
GH_API = "https://api.github.com"
TIMEOUT = 20

# --------------------------------------------------------------------------- http


def http_get(url: str, headers: dict | None = None, timeout: int = TIMEOUT):
    """Return (status, body_text). Never raises on HTTP errors."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, body
    except Exception as e:  # network / timeout
        return 0, str(e)


def get_json(url: str, headers: dict | None = None):
    status, body = http_get(url, headers)
    if status != 200:
        return None, status, body[:300]
    try:
        return json.loads(body), status, None
    except ValueError:
        return None, status, "invalid json"


def gh_headers():
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h


def gh(path: str):
    data, status, err = get_json(GH_API + path, gh_headers())
    if status == 403 and err and "rate limit" in err.lower():
        WARNINGS.append("GitHub API rate limit hit (set GITHUB_TOKEN for 5000 req/h)")
    return data


WARNINGS: list[str] = []

# --------------------------------------------------------------------------- resolve


def parse_query(q: str):
    """Return (source, slug) if q is fully qualified, else (None, name)."""
    q = q.strip().rstrip("/")
    m = re.match(r"^https?://(www\.)?skills\.sh/(.+)$", q)
    if m:
        q = m.group(2)
    m = re.match(r"^https?://(www\.)?github\.com/([^/]+)/([^/@#]+)", q)
    if m:
        return f"{m.group(2)}/{m.group(3)}", None
    if "@" in q and "/" in q:
        src, slug = q.split("@", 1)
        return src, slug
    parts = q.split("/")
    if len(parts) >= 3:
        return "/".join(parts[:-1]), parts[-1]
    if len(parts) == 2 and "." in parts[0]:  # well-known source e.g. mintlify.com/mintlify
        return parts[0], parts[1]
    return None, q


def search(name: str):
    url = f"{SKILLS}/api/search?q={urllib.parse.quote(name)}&limit=100"
    data, status, err = get_json(url)
    if not data:
        WARNINGS.append(f"skills.sh search failed ({status}): {err}")
        return []
    return data.get("skills", [])


def resolve(query: str, prefer_skill: str | None = None):
    source, slug = parse_query(query)
    if prefer_skill:
        slug = prefer_skill
    if source and slug:
        hits = search(slug)
        same = [h for h in hits if h.get("skillId", "").lower() == slug.lower() or h.get("name", "").lower() == slug.lower()]
        chosen = next((h for h in same if h["source"].lower() == source.lower()), None)
        if not chosen:
            chosen = {"id": f"{source}/{slug}", "source": source, "skillId": slug, "name": slug, "installs": None}
        return chosen, same
    if source and not slug:
        raise SystemExit(f"Repo given ({source}); pass --skill <name> to pick a skill from it.")
    hits = search(slug)
    same = [h for h in hits if h.get("skillId", "").lower() == slug.lower() or h.get("name", "").lower() == slug.lower()]
    if not same:
        alts = ", ".join(f"{h['id']} ({h.get('installs')})" for h in hits[:8])
        raise SystemExit(f"No exact match for '{slug}' on skills.sh. Closest: {alts or 'none'}")
    same.sort(key=lambda h: h.get("installs") or 0, reverse=True)
    return same[0], same


# --------------------------------------------------------------------------- skills.sh page + audits


def page_text(url: str):
    status, body = http_get(url)
    if status != 200:
        return None
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", body, flags=re.S)
    t = re.sub(r"<[^>]+>", "\n", t)
    return [html.unescape(x).strip() for x in t.split("\n") if x.strip()]


def after(lines, label, n=1):
    try:
        i = lines.index(label)
        return lines[i + 1] if n == 1 else lines[i + 1 : i + 1 + n]
    except ValueError:
        return None


def scrape_skill_page(skill_id: str, slug: str):
    lines = page_text(f"{SKILLS}/{skill_id}")
    if not lines:
        return {}
    out = {
        "installs_text": after(lines, "Installs"),
        "github_stars_text": after(lines, "GitHub Stars"),
        "first_seen": after(lines, "First Seen"),
        "repository": after(lines, "Repository"),
    }
    # category: line right after the skill title, before "Installation"
    try:
        i = lines.index("Installation")
        if i >= 2 and lines[i - 2].lower() == slug.lower() and lines[i - 1].lower() != slug.lower():
            out["category"] = lines[i - 1]
    except ValueError:
        pass
    # install command
    for l in lines:
        if l.startswith("npx skills add"):
            out["install_cmd"] = l
            break
    # summary block
    try:
        i, j = lines.index("Summary"), lines.index("SKILL.md")
        if i < j:
            out["summary"] = " ".join(lines[i + 1 : j])[:1200]
    except ValueError:
        pass
    return out


def fetch_audits(skill_id: str):
    data, status, err = get_json(f"{SKILLS}/api/v1/skills/audit/{skill_id}")
    if not data:
        return None
    return data.get("audits", [])


_NAV = {"about", "agent", "agents", "audits", "contact", "docs", "hot", "official", "packs",
        "privacy", "terms", "topic", "topics", "trending", "api"}


def official_owners():
    status, body = http_get(f"{SKILLS}/official")
    if status != 200:
        return set()
    owners = set(re.findall(r'href="/([A-Za-z0-9_.-]+)"', body))
    return {o.lower() for o in owners} - _NAV


# --------------------------------------------------------------------------- git (blobless clone)


def git(repo_dir, *args, timeout=60):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true"}
    r = subprocess.run(["git", "--git-dir", repo_dir, *args], capture_output=True, timeout=timeout, env=env)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def clone(source: str, dest: str):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true"}
    try:
        r = subprocess.run(
            ["git", "clone", "--bare", "--filter=blob:none", "--quiet",
             f"https://github.com/{source}.git", dest],
            capture_output=True, timeout=120, env=env)
        if r.returncode != 0:
            WARNINGS.append("git clone failed: " + r.stderr.decode()[:200])
            return False
        return True
    except subprocess.TimeoutExpired:
        WARNINGS.append("git clone timed out (repo too large); commit analysis skipped")
        return False


def find_skill_dir(repo, slug):
    files = git(repo, "ls-tree", "-r", "--name-only", "HEAD") or ""
    skill_mds = [f for f in files.splitlines() if f.endswith("SKILL.md")]
    for f in skill_mds:
        d = f.rsplit("/", 1)[0] if "/" in f else ""
        if d.rsplit("/", 1)[-1].lower() == slug.lower():
            return d, f, len(skill_mds)
    for f in skill_mds[:80]:  # fall back to frontmatter name
        body = git(repo, "cat-file", "-p", f"HEAD:{f}") or ""
        m = re.search(r"^name:\s*['\"]?([^'\"\n]+)", body, re.M)
        if m and m.group(1).strip().lower() == slug.lower():
            return (f.rsplit("/", 1)[0] if "/" in f else ""), f, len(skill_mds)
    if len(skill_mds) == 1:
        f = skill_mds[0]
        return (f.rsplit("/", 1)[0] if "/" in f else ""), f, 1
    return None, None, len(skill_mds)


BOT_RE = re.compile(r"\[bot\]|dependabot|github-actions|renovate|semantic-release|actions-user", re.I)
SEP_F, SEP_R = "\x1f", "\x1e"


def git_log(repo, path=None, max_commits=2000):
    fmt = SEP_F.join(["%H", "%an", "%ae", "%aI", "%cn", "%ce", "%s", "%b"]) + SEP_R
    args = ["log", f"--max-count={max_commits}", f"--format={fmt}", "HEAD"]
    if path is not None:
        args += ["--", path or "."]
    out = git(repo, *args, timeout=120) or ""
    commits = []
    for rec in out.split(SEP_R):
        rec = rec.strip("\n")
        if not rec:
            continue
        p = rec.split(SEP_F)
        if len(p) < 8:
            continue
        sha, an, ae, ad, cn, ce, subj, body = p[:8]
        try:
            when = dt.datetime.fromisoformat(ad.replace("Z", "+00:00"))
        except ValueError:
            continue
        commits.append({
            "sha": sha, "author": an, "email": ae.lower(), "date": when,
            "committer_email": ce.lower(), "subject": subj, "body": body,
            "bot": bool(BOT_RE.search(an) or BOT_RE.search(ae)),
            "web": ce.lower() == "noreply@github.com",
        })
    return commits


# --------------------------------------------------------------------------- origin inference

TZ_REGIONS = {
    -600: "Hawaii", -540: "Alaska", -480: "US/Canada Pacific (winter)",
    -420: "US Pacific (summer) / US Mountain", -360: "US Central / Mexico / Central America",
    -300: "US Eastern (winter) / Colombia / Peru / US Central (summer)",
    -240: "US Eastern (summer) / Venezuela / Bolivia / Chile", -180: "Brazil / Argentina / Uruguay",
    -60: "Azores / Cape Verde",
    0: "UTC (often CI or web UI) / UK / Ireland / Portugal (winter) / West Africa",
    60: "Central Europe (winter: DE, FR, PL, IT, ES, NL...) / UK (summer) / Nigeria",
    120: "Central Europe (summer) / Eastern Europe (winter: UA, RO, FI, BG, GR, Baltics) / Israel / Egypt / South Africa",
    180: "Russia (Moscow) / Belarus / Turkey / Saudi Arabia / East Africa / Eastern Europe (summer)",
    210: "Iran", 240: "UAE / Georgia / Armenia / Azerbaijan / Russia (Samara)", 270: "Afghanistan",
    300: "Pakistan / Uzbekistan / Kazakhstan / Russia (Yekaterinburg)", 330: "India / Sri Lanka",
    345: "Nepal", 360: "Bangladesh / Kyrgyzstan / Russia (Omsk)",
    420: "Vietnam / Thailand / Indonesia (West) / Russia (Novosibirsk)",
    480: "China / Taiwan / Hong Kong / Singapore / Malaysia / Philippines / Western Australia",
    540: "Japan / South Korea", 570: "South Australia", 600: "Eastern Australia (winter) / Russia (Vladivostok)",
    660: "Eastern Australia (summer)", 720: "New Zealand (winter)", 780: "New Zealand (summer)",
}

# (winter_offset, summer_offset) in minutes -> region (northern-hemisphere DST pattern)
DST_PATTERNS = {
    (0, 60): "UK / Ireland / Portugal",
    (60, 120): "Central Europe (DE, FR, PL, NL, IT, ES, CZ, AT, CH, SE, NO...)",
    (120, 180): "Eastern Europe (UA, RO, BG, FI, GR, Baltics, MD) / Israel / Lebanon",
    (-300, -240): "US / Canada Eastern",
    (-360, -300): "US / Canada Central",
    (-420, -360): "US / Canada Mountain",
    (-480, -420): "US / Canada Pacific",
}

EMAIL_PROVIDERS = {
    "yandex.ru": "RU", "ya.ru": "RU", "mail.ru": "RU", "bk.ru": "RU", "list.ru": "RU", "inbox.ru": "RU",
    "rambler.ru": "RU", "yandex.com": "RU", "ukr.net": "UA", "i.ua": "UA", "meta.ua": "UA", "tut.by": "BY",
    "qq.com": "CN", "163.com": "CN", "126.com": "CN", "foxmail.com": "CN", "sina.com": "CN",
    "sina.cn": "CN", "aliyun.com": "CN", "yeah.net": "CN", "139.com": "CN", "sohu.com": "CN",
    "naver.com": "KR", "daum.net": "KR", "hanmail.net": "KR", "kakao.com": "KR",
    "yahoo.co.jp": "JP", "docomo.ne.jp": "JP", "gmx.de": "DE", "web.de": "DE", "t-online.de": "DE",
    "gmx.at": "AT", "gmx.ch": "CH", "seznam.cz": "CZ", "wp.pl": "PL", "onet.pl": "PL", "interia.pl": "PL",
    "o2.pl": "PL", "libero.it": "IT", "orange.fr": "FR", "free.fr": "FR", "laposte.net": "FR",
    "rediffmail.com": "IN", "uol.com.br": "BR", "bol.com.br": "BR", "terra.com.br": "BR",
}

CC_TLDS = {
    "ru": "RU", "su": "RU", "ua": "UA", "by": "BY", "kz": "KZ", "uz": "UZ", "cn": "CN", "tw": "TW",
    "hk": "HK", "jp": "JP", "kr": "KR", "de": "DE", "fr": "FR", "it": "IT", "es": "ES", "pl": "PL",
    "nl": "NL", "be": "BE", "br": "BR", "in": "IN", "uk": "GB", "ca": "CA", "au": "AU", "nz": "NZ",
    "tr": "TR", "ir": "IR", "vn": "VN", "id": "ID", "sg": "SG", "my": "MY", "th": "TH", "ph": "PH",
    "ch": "CH", "at": "AT", "se": "SE", "no": "NO", "fi": "FI", "dk": "DK", "cz": "CZ", "sk": "SK",
    "il": "IL", "pt": "PT", "ro": "RO", "hu": "HU", "gr": "GR", "ar": "AR", "mx": "MX", "cl": "CL",
    "co": None, "io": None, "ai": None, "me": None, "dev": None, "app": None,  # generic-ish
    "ee": "EE", "lv": "LV", "lt": "LT", "bg": "BG", "rs": "RS", "hr": "HR", "si": "SI", "ge": "GE",
    "am": "AM", "az": "AZ", "md": "MD", "ie": "IE", "za": "ZA", "eg": "EG", "sa": "SA", "ae": "AE",
    "pk": "PK", "bd": "BD", "lk": "LK", "np": "NP",
}

SCRIPTS = [
    ("Cyrillic", 0x0400, 0x04FF), ("CJK", 0x4E00, 0x9FFF), ("Hiragana/Katakana", 0x3040, 0x30FF),
    ("Hangul", 0xAC00, 0xD7AF), ("Arabic", 0x0600, 0x06FF), ("Hebrew", 0x0590, 0x05FF),
    ("Devanagari", 0x0900, 0x097F), ("Thai", 0x0E00, 0x0E7F), ("Greek", 0x0370, 0x03FF),
    ("Georgian", 0x10A0, 0x10FF), ("Armenian", 0x0530, 0x058F),
]
LATIN_HINTS = {  # characters that point at a specific language
    "pt": "ãõç", "es": "ñ¿¡", "de": "äöüß", "fr": "œàâèêëîïôùûç", "pl": "ąćęłńśźż",
    "cs": "čďěňřšťůž", "tr": "ğışİ", "ro": "ăâîșțşţ", "hu": "őű", "vi": "ăđơưạảấầẩẫậắằẳẵặẹẻẽếềểễệ",
    "nordic": "åøæ",
}
SIMPLIFIED = set("们这个说时为国来对发会过还没后么开关实现计数据库请图标务")
TRADITIONAL = set("們這個說時為國來對發會過還沒後麼開關實現計數據庫請圖標務")
SIMPLIFIED -= TRADITIONAL  # keep only discriminating chars
TRADITIONAL -= set("们这个说时为国来对发会过还没后么开关实现计数据库请图标务")


def script_profile(text: str):
    counts = collections.Counter()
    letters = 0
    for ch in text:
        o = ord(ch)
        if ch.isalpha():
            letters += 1
        for name, lo, hi in SCRIPTS:
            if lo <= o <= hi:
                counts[name] += 1
                break
    res = {"letters": letters, "scripts": {k: round(v / max(letters, 1), 3) for k, v in counts.most_common()}}
    low = text.lower()
    latin = {lang: sum(low.count(c) for c in chars) for lang, chars in LATIN_HINTS.items()}
    res["latin_diacritics"] = {k: v for k, v in sorted(latin.items(), key=lambda x: -x[1]) if v >= 3}
    if counts.get("Cyrillic"):
        ua = sum(low.count(c) for c in "іїєґ")
        ru = sum(low.count(c) for c in "ыэъё")
        be = low.count("ў")
        res["cyrillic_variant"] = {"uk": ua, "ru": ru, "be": be}
    if counts.get("CJK"):
        s = sum(1 for c in text if c in SIMPLIFIED)
        t = sum(1 for c in text if c in TRADITIONAL)
        res["cjk_variant"] = {"simplified": s, "traditional": t}
    return res


def fmt_off(m: int):
    sign = "+" if m >= 0 else "-"
    m = abs(m)
    return f"{sign}{m // 60:02d}{m % 60:02d}"


def tz_analysis(commits):
    usable = [c for c in commits if not c["bot"] and not c["web"]]
    offs = collections.Counter(int(c["date"].utcoffset().total_seconds() // 60) for c in usable)
    winter = collections.Counter(int(c["date"].utcoffset().total_seconds() // 60)
                                 for c in usable if c["date"].month in (11, 12, 1, 2, 3))
    summer = collections.Counter(int(c["date"].utcoffset().total_seconds() // 60)
                                 for c in usable if c["date"].month in (4, 5, 6, 7, 8, 9, 10))
    hours = collections.Counter(c["date"].hour for c in usable)
    weekdays = collections.Counter(c["date"].weekday() for c in usable)
    res = {
        "commits_analyzed": len(usable),
        "excluded_bot_or_web": len(commits) - len(usable),
        "offsets": [{"offset": fmt_off(k), "count": v, "regions": TZ_REGIONS.get(k, "?")} for k, v in offs.most_common(6)],
    }
    if winter and summer:
        w, s = winter.most_common(1)[0][0], summer.most_common(1)[0][0]
        res["winter_offset"], res["summer_offset"] = fmt_off(w), fmt_off(s)
        if (w, s) in DST_PATTERNS:
            res["dst_pattern"] = DST_PATTERNS[(w, s)]
        elif w == s and w != 0:
            regions = " / ".join(x for x in TZ_REGIONS.get(w, "?").split(" / ") if "(summer" not in x and "(winter" not in x)
            res["dst_pattern"] = f"no DST shift at {fmt_off(w)} -> {regions}"
    if hours:
        busiest = [h for h, _ in hours.most_common(6)]
        res["peak_local_hours"] = sorted(busiest)
        night = sum(v for h, v in hours.items() if 2 <= h <= 6)
        res["share_02_06_local"] = round(night / max(sum(hours.values()), 1), 2)
    if weekdays:
        res["weekend_share"] = round((weekdays[5] + weekdays[6]) / max(sum(weekdays.values()), 1), 2)
    return res


def email_domains(commits):
    doms = collections.Counter()
    for c in commits:
        if c["bot"]:
            continue
        d = c["email"].rsplit("@", 1)[-1]
        if d.endswith("users.noreply.github.com") or not d:
            d = "users.noreply.github.com"
        doms[d] += 1
    out = []
    for d, n in doms.most_common(8):
        hint = EMAIL_PROVIDERS.get(d)
        if not hint and d != "users.noreply.github.com":
            hint = CC_TLDS.get(d.rsplit(".", 1)[-1])
        out.append({"domain": d, "count": n, "country_hint": hint})
    return out


def blog_tld_hint(url: str | None):
    if not url:
        return None
    host = urllib.parse.urlparse(url if "://" in url else "http://" + url).hostname or ""
    return CC_TLDS.get(host.rsplit(".", 1)[-1]) if host else None


# --------------------------------------------------------------------------- static scan

RISK_PATTERNS = [
    ("pipe-to-shell", "high", r"(curl|wget)[^\n|]{0,200}\|\s*(sudo\s+)?(ba|z|da)?sh\b"),
    ("powershell-remote-exec", "high", r"\biex\s*\(|Invoke-Expression|DownloadString\("),
    ("prompt-injection-phrasing", "high",
     r"ignore (all |any )?(previous|prior|above) (instructions|rules)|disregard (all |the )?(previous|prior|system)"
     r"|do not (tell|inform|notify) the user|without (asking|telling|informing) the user|hide (this|it) from the user"),
    ("destructive-rm", "high", r"rm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(/|~|\$HOME)(\s|$|/\*)"),
    ("base64-decode", "medium", r"base64\s+(-d|--decode)|b64decode\(|atob\(|FromBase64String"),
    ("dynamic-eval", "medium", r"\beval\s*\(|\bexec\s*\(|new Function\("),
    ("credential-paths", "medium",
     r"~/\.ssh|id_rsa|id_ed25519|\.aws/credentials|\.netrc|\.npmrc|\.pypirc|\.docker/config\.json|keychain|"
     r"\.git-credentials|\.kube/config"),
    ("secret-env-vars", "low", r"\b(ANTHROPIC_API_KEY|OPENAI_API_KEY|GITHUB_TOKEN|GH_TOKEN|AWS_SECRET_ACCESS_KEY|NPM_TOKEN)\b"),
    ("exfil-endpoints", "high",
     r"discord(app)?\.com/api/webhooks|api\.telegram\.org/bot|pastebin\.com|ngrok\.(io|app)|requestbin|webhook\.site|"
     r"interact\.sh|burpcollaborator"),
    ("outbound-post", "low", r"requests\.post\(|curl\s[^\n]*(-X\s*POST|--data|-d\s)|method:\s*['\"]POST"),
    ("permission-bypass", "medium", r"--dangerously-skip-permissions|bypassPermissions|--yolo\b|Bash\(\*\)"),
    ("persistence", "medium", r"crontab\s|>>\s*~/\.(bash|zsh)rc|\.profile\b|launchctl\s|systemctl\s+enable|LaunchAgents"),
    ("sudo", "low", r"\bsudo\s"),
    ("global-install", "low", r"npm\s+i(nstall)?\s+-g|pip\s+install\s(?!-r)|curl[^\n]*-o\s*/usr/"),
]
HIDDEN_UNICODE = re.compile("[\\u200b-\\u200f\\u202a-\\u202e\\u2060-\\u2064\\u2066-\\u2069\\U000e0000-\\U000e007f]")
BINARY_EXT = (".exe", ".dll", ".so", ".dylib", ".bin", ".jar", ".pyc", ".wasm", ".node", ".class")
URL_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")


def static_scan(repo, skill_dir, skill_md_path=None):
    listing = git(repo, "ls-tree", "-r", "-l", "HEAD", "--", skill_dir or ".") or ""
    files = []
    for line in listing.splitlines():
        m = re.match(r"\d+ (\w+) [0-9a-f]+\s+(-|\d+)\t(.+)$", line)
        if m and m.group(1) == "blob":
            files.append((m.group(3), int(m.group(2)) if m.group(2) != "-" else 0))
    findings, domains, total = [], collections.Counter(), 0
    skill_md_text, frontmatter = None, {}
    exts = collections.Counter()
    for path, size in files[:120]:
        total += size
        exts[os.path.splitext(path)[1].lower() or "(none)"] += 1
        if path.lower().endswith(BINARY_EXT):
            findings.append({"rule": "binary-file", "severity": "medium", "file": path, "line": 0, "snippet": ""})
            continue
        if size > 512_000:
            continue
        raw = subprocess.run(["git", "--git-dir", repo, "cat-file", "-p", f"HEAD:{path}"],
                             capture_output=True, timeout=60).stdout
        if b"\x00" in raw[:8000]:
            findings.append({"rule": "binary-file", "severity": "medium", "file": path, "line": 0, "snippet": ""})
            continue
        text = raw.decode("utf-8", "replace")
        if path == skill_md_path:
            skill_md_text = text
            fm = re.match(r"^---\n(.*?)\n---", text, re.S)
            if fm:
                for l in fm.group(1).splitlines():
                    if ":" in l and not l.startswith(" "):
                        k, v = l.split(":", 1)
                        frontmatter[k.strip()] = v.strip()[:300]
        for d in URL_RE.findall(text):
            domains[d.lower()] += 1
        body = text.lstrip("\ufeff")
        for hm in HIDDEN_UNICODE.finditer(body):
            ln = body.count("\n", 0, hm.start()) + 1
            findings.append({"rule": "hidden-unicode", "severity": "high", "file": path, "line": ln,
                             "snippet": f"U+{ord(hm.group()):04X}"})
            break
        for rule, sev, pat in RISK_PATTERNS:
            for m in re.finditer(pat, body, re.I):
                ln = body.count("\n", 0, m.start()) + 1
                line = body.splitlines()[ln - 1] if body.splitlines() else ""
                findings.append({"rule": rule, "severity": sev, "file": path, "line": ln, "snippet": line.strip()[:160]})
                break  # one hit per rule per file is enough
    return {
        "files": len(files), "total_bytes": total, "extensions": dict(exts.most_common(10)),
        "frontmatter": frontmatter, "findings": findings,
        "external_domains": [d for d, _ in domains.most_common(25)],
        "skill_md_text": skill_md_text,
    }


# --------------------------------------------------------------------------- trust score


def log_score(x, full_at, pts):
    if not x or x <= 0:
        return 0.0
    return round(min(pts, pts * math.log10(x + 1) / math.log10(full_at + 1)), 1)


def trust_score(r):
    parts, flags = [], []
    audits = r.get("audits") or []
    st = [a.get("status", "").lower() for a in audits]
    if not audits:
        parts.append(("security audits", 5, 25, "no audits published"))
    elif any(s in ("fail", "critical", "high") for s in st):
        parts.append(("security audits", 0, 25, "at least one FAIL"))
        flags.append("security audit FAIL")
    elif any(s == "warn" for s in st):
        n = st.count("warn")
        parts.append(("security audits", max(8, 20 - 5 * n), 25, f"{n} warn / {len(st)}"))
    else:
        parts.append(("security audits", 25, 25, f"all {len(st)} pass"))

    parts.append(("installs", log_score(r.get("installs"), 50_000, 12), 12, f"{r.get('installs')}"))
    repo = r.get("github", {}).get("repo") or {}
    parts.append(("github stars", log_score(repo.get("stargazers_count"), 5_000, 12), 12, f"{repo.get('stargazers_count')}"))

    owner = r.get("github", {}).get("owner") or {}
    pub, why = 0, []
    if r.get("official"):
        pub += 10; why.append("official publisher on skills.sh")
    if owner.get("type") == "Organization":
        pub += 3; why.append("organization")
        if owner.get("is_verified"):
            pub += 3; why.append("verified domain")
    age_y = years_since(owner.get("created_at"))
    if age_y is not None:
        pub += min(4, age_y); why.append(f"account {age_y:.1f}y old")
        if age_y < 0.25:
            flags.append("publisher account younger than 3 months")
    pub += log_score(owner.get("followers"), 1_000, 4)
    parts.append(("publisher", round(min(pub, 20), 1), 20, ", ".join(why) or "unknown"))

    if not repo:
        parts.append(("repo health", 0, 12, "no GitHub repo data"))
        return finish_score(parts, flags, r)
    h, why = 0, []
    ra = years_since(repo.get("created_at"))
    if ra is not None:
        h += 3 if ra > 0.25 else 0; why.append(f"repo {ra:.1f}y old")
    pa = years_since(repo.get("pushed_at"))
    if pa is not None and pa < 0.5:
        h += 3; why.append("active <6 mo")
    if (repo.get("license") or {}).get("spdx_id") not in (None, "NOASSERTION"):
        h += 2; why.append(repo["license"]["spdx_id"])
    else:
        why.append("no license")
    if repo.get("archived"):
        flags.append("repository archived"); why.append("archived")
    else:
        h += 1
    if repo.get("fork"):
        flags.append("repository is a fork"); why.append("fork")
    else:
        h += 1
    contrib = len(r.get("github", {}).get("contributors") or [])
    if contrib > 1:
        h += 2; why.append(f"{contrib}+ contributors")
    parts.append(("repo health", h, 12, ", ".join(why)))
    return finish_score(parts, flags, r)


def finish_score(parts, flags, r):

    scan = r.get("scan") or {}
    sev = collections.Counter(f["severity"] for f in scan.get("findings", []))
    pen = 10 * sev["high"] + 3 * sev["medium"] + 1 * sev["low"]
    s = max(0, 19 - pen) if scan else 5
    parts.append(("static scan", s, 19, f"high={sev['high']} med={sev['medium']} low={sev['low']}" if scan else "not run"))
    if sev["high"]:
        flags.append(f"{sev['high']} high-severity static finding(s)")

    total = sum(p[1] for p in parts)
    for c in r.get("name_collisions", []):
        if c.get("typosquat_risk"):
            total -= 10
            flags.append(f"name shadows more popular {c['id']} ({c['installs']} installs)")
            break
    total = max(0, min(100, round(total)))
    grade = "HIGH" if total >= 75 else "MEDIUM" if total >= 50 else "LOW" if total >= 25 else "VERY LOW"
    return {"score": total, "grade": grade, "flags": flags,
            "breakdown": [{"component": a, "points": b, "max": c, "detail": d} for a, b, c, d in parts]}


def years_since(iso):
    if not iso:
        return None
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round((dt.datetime.now(dt.timezone.utc) - t).days / 365.25, 2)


# --------------------------------------------------------------------------- main pipeline


def build(query, skill=None, do_clone=True, max_commits=2000):
    chosen, same = resolve(query, skill)
    skill_id, source = chosen["id"], chosen["source"]
    slug = chosen.get("skillId") or chosen.get("name")
    r = {"query": query, "id": skill_id, "source": source, "slug": slug,
         "url": f"{SKILLS}/{skill_id}", "installs": chosen.get("installs")}

    off = official_owners()
    owner_login = source.split("/")[0] if "/" in source else source
    r["official"] = owner_login.lower() in off

    r["name_collisions"] = []
    for h in same:
        if h["id"] == skill_id:
            continue
        mine, theirs = r["installs"] or 0, h.get("installs") or 0
        r["name_collisions"].append({
            "id": h["id"], "installs": theirs,
            "typosquat_risk": theirs >= 10 * max(mine, 1) and not r["official"],
        })

    r["page"] = scrape_skill_page(skill_id, slug)
    r["audits"] = fetch_audits(skill_id)

    is_github = "/" in source and "." not in source.split("/")[0]
    r["github"] = {}
    if is_github:
        owner = gh(f"/users/{owner_login}") or {}
        if owner.get("type") == "Organization":
            owner = {**owner, **(gh(f"/orgs/{owner_login}") or {})}
        r["github"]["owner"] = pick(owner, "login", "type", "name", "company", "blog", "location", "email",
                                    "bio", "twitter_username", "followers", "public_repos", "created_at",
                                    "is_verified", "description", "hireable")
        repo = gh(f"/repos/{source}") or {}
        r["github"]["repo"] = pick(repo, "full_name", "description", "stargazers_count", "forks_count",
                                   "open_issues_count", "subscribers_count", "created_at", "pushed_at",
                                   "archived", "fork", "license", "topics", "language", "default_branch", "homepage")
        r["github"]["contributors"] = [
            {"login": c.get("login"), "contributions": c.get("contributions")}
            for c in (gh(f"/repos/{source}/contributors?per_page=10") or [])
            if isinstance(c, dict)
        ]

    if not is_github:
        WARNINGS.append("non-GitHub (well-known/registry) source: no repo, owner or commit provenance available")
    r["name_collisions"].sort(key=lambda c: c["installs"] or 0, reverse=True)

    if is_github and do_clone and shutil.which("git"):
        tmp = tempfile.mkdtemp(prefix="skill-info-")
        try:
            repo_dir = os.path.join(tmp, "repo.git")
            if clone(source, repo_dir):
                sdir, smd, n_skills = find_skill_dir(repo_dir, slug)
                r["repo_skill_count"] = n_skills
                r["skill_path"] = smd
                all_commits = git_log(repo_dir, None, max_commits)
                skill_commits = git_log(repo_dir, sdir, max_commits) if sdir is not None else []
                r["git"] = summarize_git(all_commits, skill_commits)
                total = (git(repo_dir, "rev-list", "--count", "HEAD") or "").strip()
                roots = (git(repo_dir, "log", "--max-parents=0", "--format=%aI", "HEAD") or "").split()
                if total.isdigit():
                    r["git"]["repo_commits"] = int(total)
                if roots:
                    r["git"]["repo_first_commit"] = min(roots)
                # map skill authors to GitHub logins via API (1 call)
                if smd:
                    api = gh(f"/repos/{source}/commits?path={urllib.parse.quote(sdir or smd)}&per_page=100") or []
                    logins = collections.Counter(
                        (c.get("author") or {}).get("login") for c in api if isinstance(c, dict))
                    logins.pop(None, None)
                    r["git"]["skill_author_logins"] = dict(logins.most_common(5))
                    top = logins.most_common(1)[0][0] if logins else None
                    if top and top.lower() != owner_login.lower():
                        u = gh(f"/users/{top}") or {}
                        r["github"]["skill_author"] = pick(u, "login", "name", "company", "blog", "location",
                                                           "bio", "twitter_username", "followers", "created_at")
                    r["scan"] = static_scan(repo_dir, sdir, smd)
                    text = "\n".join(c["subject"] + "\n" + c["body"] for c in skill_commits or all_commits)
                    r["language"] = {
                        "commit_messages": script_profile(text),
                        "skill_md": script_profile(r["scan"].get("skill_md_text") or ""),
                    }
                    readme = git(repo_dir, "cat-file", "-p", "HEAD:README.md")
                    if readme:
                        r["language"]["readme"] = script_profile(readme)
                else:
                    WARNINGS.append(f"SKILL.md for '{slug}' not found in repo HEAD")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    r["origin_signals"] = origin_signals(r)
    r["trust"] = trust_score(r)
    r["warnings"] = WARNINGS
    if r.get("scan"):
        r["scan"].pop("skill_md_text", None)
    return r


def pick(d, *keys):
    out = {k: d.get(k) for k in keys if d.get(k) not in (None, "", [])}
    if isinstance(out.get("license"), dict):
        out["license"] = {"spdx_id": out["license"].get("spdx_id")}
    return out


def summarize_git(all_commits, skill_commits):
    def authors(cs):
        c = collections.Counter((x["author"], x["email"].rsplit("@", 1)[-1]) for x in cs if not x["bot"])
        return [{"name": a, "email_domain": d, "commits": n} for (a, d), n in c.most_common(6)]

    out = {
        "repo_commits": len(all_commits),
        "repo_first_commit": all_commits[-1]["date"].isoformat() if all_commits else None,
        "repo_last_commit": all_commits[0]["date"].isoformat() if all_commits else None,
        "repo_authors": authors(all_commits),
        "skill_commits": len(skill_commits),
        "skill_first_commit": skill_commits[-1]["date"].isoformat() if skill_commits else None,
        "skill_last_commit": skill_commits[0]["date"].isoformat() if skill_commits else None,
        "skill_authors": authors(skill_commits),
    }
    # tz analysis on the main human author of the skill (fallback: whole repo)
    base = skill_commits or all_commits
    humans = collections.Counter(c["email"] for c in base if not c["bot"])
    main_email = humans.most_common(1)[0][0] if humans else None
    main_all = [c for c in all_commits if c["email"] == main_email] if main_email else []
    out["main_author"] = next((c["author"] for c in base if c["email"] == main_email), None)
    out["timezone"] = tz_analysis(main_all or base)
    out["email_domains"] = email_domains(base)
    return out


def origin_signals(r):
    sig = []
    gh_ = r.get("github", {})
    for who in ("owner", "skill_author"):
        p = gh_.get(who) or {}
        if p.get("location"):
            sig.append({"signal": f"{who} GitHub location", "value": p["location"], "strength": "strong"})
        if p.get("blog") and blog_tld_hint(p["blog"]):
            sig.append({"signal": f"{who} website TLD", "value": f"{p['blog']} -> {blog_tld_hint(p['blog'])}", "strength": "medium"})
        if p.get("company"):
            sig.append({"signal": f"{who} company", "value": p["company"], "strength": "weak"})
    g = r.get("git") or {}
    for d in g.get("email_domains", []):
        if d.get("country_hint"):
            sig.append({"signal": "commit email domain", "value": f"{d['domain']} -> {d['country_hint']} ({d['count']} commits)", "strength": "medium"})
    tz = g.get("timezone") or {}
    if tz.get("dst_pattern"):
        sig.append({"signal": "commit timezone DST pattern", "value": f"{tz.get('winter_offset')}/{tz.get('summer_offset')}: {tz['dst_pattern']}", "strength": "medium"})
    elif tz.get("offsets"):
        o = tz["offsets"][0]
        sig.append({"signal": "dominant commit timezone", "value": f"{o['offset']} ({o['count']}x): {o['regions']}", "strength": "medium" if o["offset"] != "+0000" else "weak"})
    for k, prof in (r.get("language") or {}).items():
        scripts = prof.get("scripts") or {}
        for s, share in scripts.items():
            if share >= 0.05:
                extra = ""
                if s == "Cyrillic" and prof.get("cyrillic_variant"):
                    v = prof["cyrillic_variant"]; extra = f" (uk-markers={v['uk']}, ru-markers={v['ru']}, be={v['be']})"
                if s == "CJK" and prof.get("cjk_variant"):
                    v = prof["cjk_variant"]; extra = f" (simplified={v['simplified']}, traditional={v['traditional']})"
                sig.append({"signal": f"{k} script", "value": f"{s} {share:.0%}{extra}", "strength": "medium"})
        if prof.get("latin_diacritics"):
            sig.append({"signal": f"{k} diacritics", "value": str(prof["latin_diacritics"]), "strength": "weak"})
    return sig


# --------------------------------------------------------------------------- markdown


def md(r):
    L = []
    t = r["trust"]
    pg, ghr, gho = r.get("page", {}), r.get("github", {}).get("repo", {}), r.get("github", {}).get("owner", {})
    L.append(f"# {r['slug']}  —  `{r['id']}`")
    L.append(f"{r['url']}\n")
    L.append(f"**Trust: {t['score']}/100 ({t['grade']})**" + (f"  ·  ⚠ {'; '.join(t['flags'])}" if t["flags"] else ""))
    L.append("")
    L.append("| Field | Value |\n|---|---|")
    rows = [
        ("Installs", f"{r.get('installs')} ({pg.get('installs_text', '?')})"),
        ("GitHub stars", ghr.get("stargazers_count", pg.get("github_stars_text"))),
        ("Forks / open issues", f"{ghr.get('forks_count')} / {ghr.get('open_issues_count')}" if ghr else None),
        ("Category", pg.get("category")),
        ("Official publisher", "yes" if r.get("official") else "no"),
        ("First seen on skills.sh", pg.get("first_seen")),
        ("Repo created / last push", f"{(ghr.get('created_at') or '')[:10]} / {(ghr.get('pushed_at') or '')[:10]}" if ghr else None),
        ("License", (ghr.get("license") or {}).get("spdx_id") if ghr else None),
        ("Skills in repo", r.get("repo_skill_count")),
        ("SKILL.md path", r.get("skill_path")),
        ("Install", f"`{pg.get('install_cmd')}`" if pg.get("install_cmd") else None),
    ]
    for k, v in rows:
        if v not in (None, "", "None / None"):
            L.append(f"| {k} | {v} |")
    if pg.get("summary"):
        L.append(f"\n**Summary (skills.sh):** {pg['summary']}")

    L.append("\n## Publisher")
    for k in ("login", "type", "name", "is_verified", "company", "location", "blog", "twitter_username",
              "followers", "public_repos", "created_at", "bio", "description"):
        if gho.get(k) not in (None, ""):
            L.append(f"- **{k}**: {gho[k]}")
    sa = r.get("github", {}).get("skill_author")
    if sa:
        L.append(f"\nMain committer of this skill differs from the owner: **{sa.get('login')}**"
                 + (f" ({sa['name']})" if sa.get("name") else "")
                 + f", location: {sa.get('location', '—')}, company: {sa.get('company', '—')}"
                 + (f", followers: {sa['followers']}" if sa.get("followers") is not None else ""))

    L.append("\n## Security audits (skills.sh partners)")
    if r.get("audits"):
        for a in r["audits"]:
            L.append(f"- **{a.get('provider')}**: {a.get('status', '?').upper()}"
                     + (f" · risk {a['riskLevel']}" if a.get("riskLevel") else "")
                     + f" — {(a.get('summary') or '')[:300]}")
    else:
        L.append("- none published")

    sc = r.get("scan")
    if sc:
        L.append(f"\n## Static scan ({sc['files']} files, {sc['total_bytes']} bytes)")
        fm = sc.get("frontmatter") or {}
        if fm.get("allowed-tools"):
            L.append(f"- allowed-tools: `{fm['allowed-tools']}`")
        if not sc["findings"]:
            L.append("- no risky patterns matched")
        for f in sc["findings"][:25]:
            L.append(f"- [{f['severity']}] {f['rule']} — `{f['file']}:{f['line']}` {('`' + f['snippet'] + '`') if f['snippet'] else ''}")
        if sc["external_domains"]:
            L.append(f"- external domains referenced: {', '.join(sc['external_domains'][:15])}")

    g = r.get("git")
    if g:
        L.append("\n## Git history")
        L.append(f"- repo: {g['repo_commits']} commits, {(g['repo_first_commit'] or '')[:10]} → {(g['repo_last_commit'] or '')[:10]}")
        L.append(f"- this skill: {g['skill_commits']} commits, {(g['skill_first_commit'] or '')[:10]} → {(g['skill_last_commit'] or '')[:10]}")
        if g.get("skill_authors"):
            L.append("- skill authors: " + ", ".join(f"{a['name']} @{a['email_domain']} ({a['commits']})" for a in g["skill_authors"]))
        if g.get("skill_author_logins"):
            L.append(f"- GitHub logins on skill commits: {g['skill_author_logins']}")
        tz = g.get("timezone") or {}
        if tz.get("offsets"):
            L.append(f"- main author **{g.get('main_author')}** — commit TZ offsets: "
                     + ", ".join(f"{o['offset']}×{o['count']}" for o in tz["offsets"])
                     + (f"; winter {tz.get('winter_offset')} / summer {tz.get('summer_offset')}" if tz.get("winter_offset") else "")
                     + (f"; peak local hours {tz.get('peak_local_hours')}" if tz.get("peak_local_hours") else "")
                     + (f"; weekend share {tz.get('weekend_share')}" if "weekend_share" in tz else ""))

    L.append("\n## Origin signals (author country is an inference, not a fact)")
    if r["origin_signals"]:
        for s in r["origin_signals"]:
            L.append(f"- [{s['strength']}] {s['signal']}: {s['value']}")
    else:
        L.append("- no usable signals")

    if r.get("name_collisions"):
        L.append("\n## Other skills with the same name")
        for c in r["name_collisions"][:10]:
            L.append(f"- `{c['id']}` — {c['installs']} installs" + ("  ⚠ much more popular: possible impersonation" if c["typosquat_risk"] else ""))

    L.append("\n## Trust breakdown")
    L.append("| Component | Points | Detail |\n|---|---|---|")
    for b in t["breakdown"]:
        L.append(f"| {b['component']} | {b['points']}/{b['max']} | {b['detail']} |")
    if r.get("warnings"):
        L.append("\n_Warnings: " + "; ".join(r["warnings"]) + "_")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Trust & provenance report for a skills.sh skill")
    ap.add_argument("query", help="skill name, owner/repo/skill, owner/repo@skill, or skills.sh / GitHub URL")
    ap.add_argument("--skill", help="skill name when query is a repo URL")
    ap.add_argument("--json", action="store_true", help="emit raw JSON instead of markdown")
    ap.add_argument("--no-clone", action="store_true", help="skip git clone (no commit/TZ/static analysis)")
    ap.add_argument("--max-commits", type=int, default=2000)
    a = ap.parse_args()
    r = build(a.query, a.skill, not a.no_clone, a.max_commits)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        print(md(r))


if __name__ == "__main__":
    main()
