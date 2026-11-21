---
name: skill-info
description: Due-diligence report for an agent skill listed on skills.sh, looked up by name. Shows the trust score, security audits (Gen Agent Trust Hub, Socket, Snyk, Runlayer, ZeroLeaks), installs, GitHub stars, publisher and author profile, repo health, git history, a static scan of the skill's files for risky patterns, same-name and impersonation checks, and a best-guess author country inferred from public signals (GitHub location, commit timezone and DST pattern, commit and README language, email and website TLDs). Use when the user runs /skill-info <name>, asks "is this skill safe/trustworthy", "who made skill X", "where is the author of X from", "should I install X", or wants to compare skills before running `npx skills add`.
argument-hint: <skill-name | owner/repo/skill | skills.sh URL>
---

# skill-info

Check a skill from the skills.sh ecosystem **before** installing it: who published it, how trustworthy it looks, what it can do to the machine, and where the author is probably based.

## Input

`$ARGUMENTS` holds the query. Any of these forms works:

- `find-skills`: bare name. Resolved through skills.sh search. When several sources publish the same name, the one with the most installs is chosen and the others are listed as collisions.
- `vercel-labs/skills/find-skills` or `vercel-labs/skills@find-skills`: exact id
- `https://skills.sh/vercel-labs/skills/find-skills`
- `https://github.com/owner/repo --skill <name>`

If no query was given, ask for one. If the script reports "No exact match", show the closest candidates it printed and ask which one the user meant.

## Step 1: Run the collector

Run the bundled script from this skill's directory (the folder that contains this SKILL.md):

```bash
python3 scripts/skill_info.py "<query>"            # markdown report
python3 scripts/skill_info.py "<query>" --json     # full raw data, when you need details
```

- It needs Python 3.9+ and `git`, and uses only the standard library.
- It takes about 10–40 s. It makes a blobless bare clone into a temp dir, deletes the clone afterwards, and never executes anything from the cloned repo.
- If `GITHUB_TOKEN` or `GH_TOKEN` is set, the script uses it. Without a token GitHub allows 60 requests/hour, which covers roughly 10 lookups.
- `--no-clone` skips the git history, timezone analysis and static scan. Use it only for huge repos or when the clone times out.

To compare several skills, run the script once per skill.

## Step 2: Write the answer

Answer in the user's language. Lead with the verdict and keep the answer short:

1. **Verdict line**: trust score, grade, and one sentence on whether to install (OK / install with care / avoid), plus the main reason.
2. **Key facts table**: id, installs, GitHub stars, official publisher yes/no, publisher (login, type, account age, followers), license, first seen, last activity, install command.
3. **Security**: each audit provider's status. Include every static-scan finding of `high` or `medium` severity with its file:line. Say whether those findings look legitimate in context (for example, a Yandex API skill that POSTs to yandex.net is expected) or suspicious. Read the snippet before you judge it. If unsure, open the file on GitHub (`https://github.com/<source>/blob/HEAD/<path>`).
4. **Author and probable country**: weigh the origin signals using [references/origin-inference.md](references/origin-inference.md). Give the guess, a confidence level (high / medium / low), and the 2–4 signals it rests on. If the signals conflict, say so. Present the country as an inference, never as a fact.
5. **Red flags**: the script's ⚠ flags, plus anything you noticed. Examples: a name that shadows a far more popular skill, a brand-new account, a single-commit repo, an archived repo, `allowed-tools: Bash(*)`, or instructions that hide actions from the user.

Don't dump the whole raw report. Pick out what matters. Include the full breakdown only if the user asks for it.

## How the trust score works (0–100)

| Component | Max | Basis |
|---|---|---|
| Security audits | 25 | all pass = 25, any warn = less, any fail = 0, none = 5 |
| Installs | 12 | log scale, full at 50k |
| GitHub stars | 12 | log scale, full at 5k |
| Publisher | 20 | official on skills.sh (+10), GitHub org (+3), verified domain (+3), account age, followers |
| Repo health | 12 | age > 3 mo, pushed within 6 mo, license, not archived or forked, more than 1 contributor |
| Static scan | 19 | minus 10 per high, 3 per medium, 1 per low finding |
| Impersonation | −10 | another source has the same name and ≥10× the installs |

Grades: ≥75 HIGH, 50–74 MEDIUM, 25–49 LOW, <25 VERY LOW. The score is a heuristic. A high score doesn't prove a skill is safe, and static scan hits can be false positives.

## Privacy and ethics

- Use only what is public: the skills.sh pages and API, the GitHub profile, and git metadata. Don't search other sites to find out more about the author.
- Report email **domains**, never full email addresses.
- Infer country only from the technical and self-declared signals listed in the reference. Never infer it from a person's name, appearance or presumed ethnicity.
