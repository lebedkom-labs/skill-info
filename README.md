# skill-info

`/skill-info <skill-name>` produces a due-diligence report for any skill on [skills.sh](https://skills.sh) **before** you install it.

- **Trust score (0–100).** Built from the partner security audits (Gen Agent Trust Hub, Socket, Snyk, Runlayer, ZeroLeaks), installs, GitHub stars, publisher reputation, repo health and a static scan.
- **Publisher and author.** The GitHub profile, org verification, account age and followers, plus the skill's actual main committer.
- **Static scan of the skill's files.** Looks for pipe-to-shell, prompt-injection phrasing, credential paths, exfiltration endpoints, hidden Unicode, permission bypass, persistence and binaries.
- **Impersonation check.** Lists other skills with the same name and flags yours when another one has ≥10× the installs.
- **Probable author country.** Inferred from public signals: GitHub location, the commit timezone and its DST pattern, the language of commits/README/SKILL.md (including UK vs RU Cyrillic and simplified vs traditional CJK), and email/website TLDs. It is reported as an inference with a confidence level.

## Install

```bash
npx skills add lebedkom-labs/skill-info
```

## Use

In Claude Code:

```
/skill-info find-skills
/skill-info vercel-labs/skills/find-skills
/skill-info https://skills.sh/openakita/openakita/get-skill-info
```

From any other agent, just ask: "check the skill `yandex-wordstat` before I install it".

You can also run the script standalone (Python 3.9+, standard library only; `git` only for `--clone`):

```bash
python3 skills/skill-info/scripts/skill_info.py find-skills           # markdown, fast mode
python3 skills/skill-info/scripts/skill_info.py find-skills --json    # raw data
python3 skills/skill-info/scripts/skill_info.py find-skills --clone   # deep mode: full git history
```

### Modes

| | fast (default) | `--clone` |
|---|---|---|
| Typical time | 5–8 s | 30 s to several minutes, depending on repo size |
| Commit history | skill folder (up to 100 commits) + the main author's commits | the whole repo |
| Commit timezone | read from the headers of up to 30 sampled `<sha>.patch` files | every commit |
| Squash-merge repos | timezone taken from the original PR commits (`pull/<n>.patch`) | same |
| Skill files for the static scan | raw.githubusercontent.com | git objects |

Both modes reach the same conclusions about the author's timezone. For example, `yandex-wordstat` gives `+0300` with no DST shift either way. Fast mode took 4.6 s on it, `--clone` took 42.6 s.

### GitHub auth

The script picks up a token automatically, from `$GITHUB_TOKEN`, `$GH_TOKEN` or a logged-in `gh` CLI. Without one it falls back to the anonymous API: 60 requests/hour, which is enough for about 8 lookups, and the report shows a warning. The fast mode needs about 5–8 API calls per lookup. Patches and raw files are downloaded from github.com and raw.githubusercontent.com directly, so they don't count against the API limit.

The list of official publishers is cached for a day in `~/.cache/skill-info/`. If fast mode can't find the skill's files (for example, because GitHub truncates the file tree of a huge repo), the script falls back to `--clone` automatically and says so in the report.

### What the report contains

- **About**: what the skill says it does, from its SKILL.md `description`, the skills.sh summary (when skills.sh has one) and the SKILL.md section headings.
- **Static scan**: findings sorted by severity. Each high and medium finding includes ±2 lines of context, so you can judge it without opening the file.
  - Executables and archives are flagged.
  - Media assets (images, audio, fonts) are not. Only their first bytes are checked, for an executable disguised under a media extension.

## Data sources

| Source | What it provides |
|---|---|
| `skills.sh/api/search` | resolves the name to an id, installs, same-name collisions |
| `skills.sh/api/v1/skills/audit/{id}` | security audit results |
| `skills.sh/{id}` page | GitHub stars, first-seen date, summary, install command |
| `skills.sh/official` | list of official publishers |
| GitHub REST API | repo, owner/org, contributors, git tree, the skill's commits and their logins |
| raw.githubusercontent.com | the skill's files for the static scan, README |
| `github.com/<repo>/commit/<sha>.patch` (first 1.5 KB) | the author's real local UTC offset (the REST API only returns UTC) |
| blobless `git clone --bare` (only with `--clone`) | full commit history |

Nothing downloaded is ever executed. The temporary clone is deleted after the run.

## Security notes

By design, this skill reads text written by third parties (the skill being inspected, GitHub profiles, skills.sh pages). Snyk flags this as W011, "third-party content exposure", the same finding it reports for other discovery skills such as `find-skills`. The exposure can't be removed without removing the feature, so skill-info limits it instead:

- Third-party strings are sanitised before the agent sees them. Hidden, bidi and control characters are stripped. Newlines are collapsed, so the text can't fake headings or code fences. Backticks are neutralised and the text is truncated.
- In the report, third-party strings are wrapped in `⟦…⟧`, under a notice that they are data, not instructions.
- Commit messages are never shown to the agent, only aggregate language statistics.
- The install command is built by the script itself, not scraped from the page.
- SKILL.md tells the agent not to fetch, open or run anything from the inspected skill. It also tells the agent to report any embedded instructions as a prompt-injection red flag.

If you run skill-info on itself, the static scan reports hits in `skill_info.py`. They come from the scanner's own pattern table, which contains strings like `webhook.site` and `Invoke-Expression`. These hits are expected. The patterns are left readable on purpose: hiding them would itself be obfuscation.

## Privacy

The tool uses only public data. It prints email domains, never full addresses. Country inference never uses names or ethnicity.

## License

MIT
