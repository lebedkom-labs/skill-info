# Inferring the author's country

All signals are probabilistic. Combine them, and state a confidence level.

## Signal strength (strongest first)

1. **Self-declared GitHub `location`** of the owner or the skill's main committer. This is strong, but people do write jokes ("Earth", "localhost") and some list a past location.
2. **Commit timezone with a DST pattern**. Git stores the author's local UTC offset on every commit. The winter offset (Nov–Mar) and summer offset (Apr–Oct) identify the region:
   - `+0100 / +0200`: Central Europe
   - `+0200 / +0300`: Eastern Europe (UA, RO, BG, FI, Baltics, GR) or Israel
   - `+0300 / +0300` with no DST shift: Russia (Moscow), Belarus, Turkey, Gulf states, East Africa
   - `+0000 / +0100`: UK, Ireland, Portugal
   - `-0500 / -0400`: US/Canada East. `-0800 / -0700`: US/Canada Pacific
   - `+0800` all year: China, Taiwan, HK, Singapore, Malaysia, Philippines. `+0900`: Japan or Korea. `+0530`: India
   - Ignore `+0000` when it comes from CI or bots, or when it shows up as a minority next to another offset. The script already drops bot commits and GitHub web-UI commits.
   - A VPN does not change the git offset. A laptop clock set to UTC does.
3. **Language of commit messages, README and SKILL.md**:
   - Cyrillic with `і ї є ґ` points to Ukrainian. `ы э ъ ё` points to Russian. `ў` points to Belarusian.
   - CJK in simplified characters points to mainland China or Singapore. Traditional characters point to Taiwan or Hong Kong.
   - Hiragana or Katakana means Japanese. Hangul means Korean.
   - Latin diacritics give a weak hint: `ã õ` Portuguese (usually Brazil), `ñ` Spanish, `ß ä ö ü` German, `ł ś ż ą` Polish, `ğ ş ı` Turkish.
   - English-only text carries no information.
4. **Email and website domains**:
   - Country TLDs (`.ru`, `.de`, `.cn`, …) and regional providers (`yandex.ru`, `mail.ru` → RU; `qq.com`, `163.com` → CN; `naver.com` → KR; `web.de`, `gmx.de` → DE) are medium signals.
   - `gmail.com` and `users.noreply.github.com` are neutral.
5. **Activity hours**:
   - Peak local hours between 9 and 23 are consistent with the offset being the author's real local time.
   - A cluster at 02–06 local time suggests the offset is not their real timezone.
6. **Company or organization**: weak, because many companies are remote and international.

## Confidence

- **High**: the declared location agrees with at least one independent technical signal (timezone, language or TLD).
- **Medium**: no declared location, but two or more technical signals agree. Also use medium when there is a declared location and nothing to corroborate it.
- **Low**: a single signal, or signals that conflict. Report the plausible region, such as "UTC+3 region: RU/BY/TR/…", rather than one country.

## Orgs and multi-author repos

- For an Organization, report the org's declared location or domain, and separately where the skill's main committer appears to be.
- When the skill's main committer differs from the repo owner, the committer is the one who actually wrote the skill. Say so.

## Do not

- Infer nationality from personal names, transliteration style or photos.
- Look up the person on other sites, or combine sources to identify them.
- Print full email addresses.
