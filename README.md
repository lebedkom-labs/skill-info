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

You can also run the script standalone (Python 3.9+, `git`, standard library only):

```bash
python3 skills/skill-info/scripts/skill_info.py find-skills          # markdown
python3 skills/skill-info/scripts/skill_info.py find-skills --json   # raw data
```

Set `GITHUB_TOKEN` to raise the GitHub API limit from 60 to 5000 requests/hour.

## Data sources

| Source | What it provides |
|---|---|
| `skills.sh/api/search` | resolves the name to an id, installs, same-name collisions |
| `skills.sh/api/v1/skills/audit/{id}` | security audit results |
| `skills.sh/{id}` page | GitHub stars, first-seen date, summary, install command |
| `skills.sh/official` | list of official publishers |
| GitHub REST API | repo, owner/org, contributors, mapping of commits to logins |
| blobless `git clone --bare` | full commit history with local UTC offsets, plus the skill files for the static scan |

Nothing from the cloned repository is executed. The temporary clone is deleted after the run.

## Privacy

The tool uses only public data. It prints email domains, never full addresses. Country inference never uses names or ethnicity.

## License

MIT
