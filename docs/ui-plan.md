# UI plan

This plan improves the fshy wiki for humans and for agents. It comes from a study of fmhy.net and five other
wikis, and from a measurement of our own build. A future agent can follow it without any other context.

The study date is 2026-10-28. Every figure about our site comes from `python publish/build.py --site site/dist`
on the data of the first publish, whose `data/meta.json` names `source_commit` `4eabfce`. The commit of this
repository that held it was rewritten later; an export of that source commit gives the same data. Every figure
about another site comes from a fetch on the same day. The site is not
deployed yet, so no figure comes from a live fshy URL.

## 0. How to use this plan

1. Read [`../AGENTS.md`](../AGENTS.md) and [`conventions.md`](conventions.md) first. They bind this plan.
2. Read section 4, the list of recommendations. Each one stands alone.
3. Do the recommendations in the order of section 10. Do not start a P2 item before the P1 items pass.
4. After each recommendation, run the three checks in `AGENTS.md` section 4. Then run its own acceptance check.
5. Write the measured byte cost in the pull request. Compare it with the cost stated here.

Three limits hold for every recommendation.

- No framework, no web font, no icon set, no image file, no request to another host.
- The shared CSS and JS cost 9,622 bytes gzip today. The budget in section 9 caps them at 12,000 bytes.
- Text follows ASD-STE100. The catalogue gives no legal advice.

## 1. Summary of the recommendations

| id | change | priority | shared bytes, gzip |
| --- | --- | --- | --- |
| R1 | A "pick" mark that the record fields compute | P1 | +133 |
| R2 | A key for every symbol, on topic pages and on the about page | P1 | +35 |
| R3 | Report links, and a contribute page | P1 | +184 |
| R4 | New issue forms, labels and a triage workflow | P1 | 0 |
| R5 | Move paid offers off each topic page | P1 | 0 |
| R6 | A "picks only" chip, filters kept in the URL, picks on the home page | P1 | +137 |
| R7 | An added date, and a page of new and removed offers | P1 | +67 |
| R8 | Requirement and evidence icons, and a verdict stripe | P2 | +79 |
| R9 | Aligned fact columns on wide screens | P2 | +36 |
| R10 | A clean one-line headline for each offer | P2 | 0 |
| R11 | Search that knows picks and topics | P2 | +34 |
| R12 | State the binding limit once on a record page | P2 | 0 |
| R13 | A monthly digest page | P2 | 0 |
| R14 | A weight budget test and a pull request template | P2 | 0 |
| R15 | Copies and permalinks on the about page | P2 | 0 |
| R16 | The same signals for agents: files, API and MCP | P2 | 0 |
| R17 | The colour theme: tokens and forced colours | P2 | +25 |
| R18 | A one-line topic bar on mid-width screens | P3 | 0 |
| R19 | Sort by price on a topic page | P3 | +88 |

The cost of the pull request for R1 to R7 is about +556 bytes gzip. The shared total becomes about 10,180
bytes. See section 9 for how the byte costs were measured.

## 2. What fmhy and the other sites do

### 2.1 fmhy.net: the reader's view

Source: [fmhy.net](https://fmhy.net), fetched 2026-10-28. The site is a VitePress build of Markdown files.

- **Structure.** The home page has a hero and 13 category cards. Each card opens one page. A page has H2 and H3
  sections, a left sidebar of pages, and a right "On this page" outline.
- **Header.** The top bar has a search button with a keyboard hint, a Beginners Guide, a Changelog and a menu of
  tools. The footer shows the build's revision hash.
- **One entry.** An entry is one Markdown bullet. Its shape is a bold name, a short description, then plain
  attributes separated by slashes, then extra links. Example attributes on the AI page are "Sign-Up", "No Sign-Up",
  "Unlimited" and a daily cap. There is no badge and no icon image in the entry.
- **Order.** The contribution guide says each section runs from best to worst.
- **Stars.** A star emoji at the start of a bullet marks a community recommendation. The README legend gives three
  marks: a star for a recommendation, a globe for a third-party index, and an arrow for a link to another section.
  On a line with several links, only the bold ones count as stars. Source: the contributing guide at
  [fmhy.net/other/contributing](https://fmhy.net/other/contributing) and the README of
  [github.com/fmhy/edit](https://github.com/fmhy/edit).
- **How scarce a star is.** The count is of bullet lines in the raw pages on 2026-10-28. The star share is 54 of 330
  bullets on `ai.md`, 32 of 176 on `storage.md` and 97 of 967 on `developer-tools.md`. That is 10 to 18 percent.
- **Toggle.** A switch in the page menu hides every list item that is not starred. The page script adds the class
  `starred-only` to the `html` element, and one CSS rule hides the other items. A second switch shows the index
  entries only. The marker comes from a Markdown plugin, `docs/.vitepress/markdown/toggleStarred.ts`. The plugin adds
  `class="starred"` to a list item that contains a star emoji.
- **Search.** A local search box opens with a keyboard key. The build writes a MiniSearch index. The index keeps a
  separate list of starred links, and the ranking code boosts starred and exact matches. A fuzzy-match switch is
  kept in local storage. Source: `docs/.vitepress/constants.ts` and `theme/components/VPLocalSearchBox.vue`.
- **Colour theme.** The appearance panel offers Light, Dark and AMOLED, and named colour schemes. The theme code has
  its own README in `docs/.vitepress/theme/themes/`. AMOLED is a pure black variant of dark.
- **Changelog.** There are two views. The first is a monthly post at [fmhy.net/posts](https://fmhy.net/posts). The
  post template has three sections: wiki updates, stars added and things removed. The second is
  [fmhy.net/recently-removed](https://fmhy.net/recently-removed). It lists removals of the last 30 days. Each item
  links to the commit that removed it. It shows no date and no reason. `scripts/generate-removed.js` builds it from
  git history.
- **Weight.** The figures come from `curl` and gzip. The AI page is 29.0 KB of HTML. The shared files are 140 KB for the
  theme script, 46 KB for the framework script and 203 KB for the stylesheet. The shared total is about 390 KB.
  Ours is 9.6 KB. This gap is the reason section 0 forbids a framework.

### 2.2 fmhy on GitHub

Sources: [fmhy/edit](https://github.com/fmhy/edit) and [fmhy/FMHY](https://github.com/fmhy/FMHY).

- **Where the wiki lives.** `fmhy/edit` holds the Markdown in `docs/`, the VitePress theme in `docs/.vitepress/`,
  small scripts in `scripts/` and an API in `api/`. `fmhy/FMHY` holds a README and the older wiki copy. The edit
  repository had 4,101 commits and 12,600 stars at the fetch.
- **Build and deploy.** A manual workflow builds with VitePress and publishes to GitHub Pages. It fetches the full
  git history, because the removed page reads it. A second workflow deploys the API.
- **One page for search.** `scripts/generate-single-page.js` joins all pages into `docs/public/single-page.md`. The
  guide tells a submitter to search this file with the browser's find command before a submission.
- **Linter.** `scripts/lint-markdown.js` checks the Markdown. The checks are: a starred, index or redirect
  line must have a bold link; no space between a bracket and a parenthesis; unclosed brackets, parentheses and bold
  marks; double spaces; spacing around slashes; and a duplicate primary URL inside one section.
- **Pull requests.** A workflow labels each pull request `core` or `docs` by the files it changes. A code owners
  file names the owner of the theme and the API. The repository has no other label.
- **Issue form.** There is one form, `wiki.yml`. It has a dropdown with four types: bad sites, grammar or Markdown,
  site suggestion and wiki section suggestion. It has one free text box. It tells the submitter to search the single
  page first.
- **Feedback form.** The site's feedback page posts to `api/routes/feedback.post.ts`. That code sanitises the text,
  translates non-English text with a small model, and posts an embed to a chat channel. Contact details are optional
  and only trusted staff can see them.
- **Backups.** [github.com/fmhy/FMHY/wiki/Backups](https://github.com/fmhy/FMHY/wiki/Backups) lists official
  domains, verified third-party mirrors, a GitHub copy, a Reddit copy, a paste-site copy, a zip of the Markdown and
  API mirrors that serve the whole text on one page. The page lists no JSON feed.

### 2.3 How fmhy handles volume, and what is not public

Source: [`.github/CONTRIBUTING.md`](https://github.com/fmhy/edit/blob/main/.github/CONTRIBUTING.md) and
[fmhy.net/other/FAQ](https://fmhy.net/other/FAQ).

- **Less input.** The guide lists what not to submit: paid and trial offers, emulators, most browsers, leech sites
  that are already listed, Linux distributions, most non-English software, coding libraries, betting and mining
  sites, multiplayer cheats and custom Windows images.
- **One at a time.** The guide says not to send many untested links at once. It says an issue is easier than a pull
  request, because staff test each site themselves.
- **A search first.** A submitter must search the single page for a duplicate.
- **A test gate.** Every addition goes through link testing in the project's chat server. Some kinds need more
  vetting.
- **A reason for removal.** A request to remove a site or to change a star must say why.
- **Big changes first.** A restructure needs a discussion before the pull request.
- **Staff only approve.** Trusted staff review and approve. The contact form hides contact details from everyone else.
- **Low GitHub backlog.** At the fetch the edit repository had 18 open items. The real queue is in the chat server.

Not verified. The chat server rules, the staff roster, the number of reviewers and the rubric for
earning a star are not published in any page that the study could read. The subreddit wiki page `find-new-sites` answered the
page reader with a bot challenge, so it was not read. `fmhy/edit` has no link-checking workflow. The
linter finds syntax faults and duplicate URLs. The recently removed page is the only public trace of dead links.

### 2.4 Five other sites that fmhy lists

These come from the pages `developer-tools.md`, `privacy.md` and `misc.md` of fmhy. Each one teaches
something about presentation or intake.

**free-for.dev.** [free-for.dev](https://free-for.dev/) and
[github.com/ripienaar/free-for-dev](https://github.com/ripienaar/free-for-dev). The scope is close to ours. The site
page is JavaScript only, so the study read the README. It is one Markdown file of about 272 KB with a table of contents.
The top of the file states the rules for entry: a free tier, not a trial, and a time-boxed tier must last a year.
The contribution guide lists services it does not accept. A new entry must use the pull request template and tick
every box, or the pull request is closed. Lesson for us: say the entry rules at the top of the page, and make
the intake form check them.

**Privacy Guides.** [privacyguides.org](https://www.privacyguides.org/en/about/criteria/) and
[github.com/privacyguides/privacyguides.org](https://github.com/privacyguides/privacyguides.org). The criteria page
states six general priorities and adds requirements for each category. It says no recommendation is sold. A
developer who submits their own tool must disclose the link. Each category page shows a comparison table with short
text cells and footnotes. The issue forms split cases: "Content Correction" is for verifiable errors, and the form
tells the reader to use the forum for a difference of opinion. The labels are `status:approved`, `status:rejected`,
`status:duplicate`, `status:research required`, `status:wontfix`, `t:correction` and one `c:` label for each
category. The pull request template asks for a conflict-of-interest disclosure. Lesson: split facts from opinions,
publish criteria, and use a short label set with a status prefix.

**awesome.** [github.com/sindresorhus/awesome](https://github.com/sindresorhus/awesome). The pull request template
is a long checklist. It requires the submitter to review four other open pull requests, and it requires a list to be
30 days old. A linter, `awesome-lint`, checks the list before review. An entry has a strict title and description
format. Lesson: a mechanical check before a human reads, and a check on the shape of the entry.

**FilterLists.** [filterlists.com](https://filterlists.com/) and
[github.com/collinbarrett/FilterLists](https://github.com/collinbarrett/FilterLists). The site page is JavaScript only,
so its layout was not readable. The repository keeps the directory as JSON files in `services/Directory/data/`, one
file per kind: lists, tags, licences, maintainers, languages and forks. It has a `lint.sh` and a `directory.yml`
workflow. The labels include `directory-data`, `url-validation`, `duplicate`, `archival` and `needs work`. Lesson:
labels that name the check that failed, and a label for a dead entry.

**Wotaku.** [wotaku.wiki](https://wotaku.wiki/) and [github.com/wotakumoe/wotaku](https://github.com/wotakumoe/wotaku).
The subject is not ours. The presentation is. Entries sit in tables with fixed columns, and yes and no cells use
icons. A sentence says when a section is sorted best first and when it is alphabetical. A `<more>` marker
sits after the first five rows, and the source suggests it folds the long tail. A tooltip file exists for each entry. The site is a VitePress build, so it has the same
weight problem as fmhy. Lesson: fixed columns make a table scannable, state the sort rule, and fold the tail.

### 2.5 What we do not copy

- Intake in a chat server. It leaves no public record, and an agent cannot read it.
- An emoji as the only carrier of meaning. A reader without the emoji font loses it. We always print the word.
- A star set by hand. A hand-set star is an opinion. Our star comes from fields (R1).
- A 390 KB shared bundle.
- Closing a pull request without discussion. It conflicts with our register in `conventions.md`.

## 3. What we do today

### 3.1 Measured sizes

| item | raw bytes | gzip bytes |
| --- | --- | --- |
| `assets/style.css` | 16,921 | 4,810 |
| `assets/app.js` | 14,041 | 4,812 |
| shared CSS and JS | 30,962 | 9,622 |
| page shell (header, topic bar, footer) | 1,988 | 971 |
| `assets/minisearch.js`, loaded on first focus of the search box | 86,455 | 18,690 |
| `api/v1/names.json`, loaded with it | 305,208 | 88,180 |
| home page | 9,066 | 3,113 |
| `t/compute/` | 684,756 | 99,037 |
| `t/storage/` | 297,109 | 52,836 |
| `t/debrid/` | 186,707 | 30,836 |
| `t/inference/` | 33,245 | 6,543 |
| `t/email/` | 16,131 | 3,215 |
| `changes/` | 360,408 | 85,774 |
| `graveyard/` | 172,958 | 29,698 |
| `llms.txt` and `index.md` | 10,737 | 3,513 |
| `t/compute.md` | 298,468 | 82,814 |
| one provider page, median of 2,936 | 7,953 | about 2,975 |
| largest provider page, `p/google/` | 436,771 | not measured |
| the whole `site/dist/` | 140 MB | not measured |

The compute page lists 1,119 offers, so one row costs about 610 bytes. The compute page has three groups. The
usable group is 308,729 bytes raw and 45,193 gzip. The trial group is 76,310 raw and 13,128 gzip. The paid group is
294,629 raw and 40,541 gzip.

### 3.2 What a human sees

- **Pages.** Home, 13 topic pages, a rejected page for each topic, about 2,936 provider pages, best-per-need
  pages, a graveyard, a changes page, a compare page, a search page and an about page.
- **A row.** A row shows a verdict pill, the name, a parsed price, a clipped summary and a facts line. The facts
  line shows the topic, identity, card, phone, binding limit, evidence rung and freshness.
- **The star today.** The pill text `★ qualifies` is the only star. It marks the verdict `qualifies`. That is 218
  of 4,188 records.
- **Navigation.** A sticky header has a search box with a `/` key hint. A topic bar lists 13 topics. A jump line
  lists the categories of a group.
- **Filters.** Five chips: no card, no phone, anonymous, measured or documented, fresh. A text box filters by
  interface. The chips live only in the page. A reload clears them, and a link cannot carry them.
- **Themes.** Light and dark follow the system setting. There is no manual switch.
- **Record page.** Six facts sit above a detail table: verdict, parsed price, identity, binding limit, evidence,
  freshness. The evidence sits in a table below.
- **Symbols.** The home page explains the verdicts. The about page explains the rung, binding, identity and
  freshness. A topic page explains nothing.

### 3.3 What an agent reads

- `/llms.txt` follows the llms.txt format. It names topics, needs, the API and the MCP endpoint.
- `/t/<topic>.md` has one line per record. `/p/<id>.md` has a provider in full. `/need/<id>.md` has a ranking.
- `/llms-full.txt` and `/t/<topic>/llms-full*.txt` hold the full records in files of at most 300,000 bytes.
- Every HTML page that has a Markdown version carries a `link rel="alternate"` line.
- The API has `/api/v1/search`, `/records`, `/sql`, `/need`, `/record` and `/entity`. The MCP endpoint has the same
  tools. The whole store is one file, `/data/fshy-public.sqlite.gz`.
- Anchors are stable. A record has the id `<topic>--<slug>` on its provider page. A group has the id `usable`,
  `trial` or `paid`.

### 3.4 Gaps that this plan closes

| gap | evidence | recommendation |
| --- | --- | --- |
| No link from any page to a report form | `grep` of `publish/pages.py` and `publish/llms.py` finds no GitHub URL | R3 |
| The two issue forms do not check the entry rules | the forms have no scope field, no card or phone field | R4 |
| The paid group is 43 percent of the compute page | 294,629 of 684,756 bytes | R5 |
| A filter cannot be shared as a link | `app.js` writes only classes on `html` | R6 |
| No view of what is new or removed | the store has no added date; its 108 history items are not additions | R7 |
| The first scan has no signal for the best offers | the only star is the verdict word | R1 |
| 59 percent of summaries end in an ellipsis | 2,452 of 4,144 in `data/tables/record.jsonl` | R10 |
| The binding text prints three times on a record | see R12 | R12 |
| Facts do not align between rows | the facts line is a flex row | R9 |
| The topic bar wraps to three lines at about 800 px | screenshot of `t/inference/` | R18 |

### 3.5 An observation outside this plan

The changes page lists 108 history items. The title of one tells how the research is run, not a fact about an offer.
`AGENTS.md` section 2 says the published corpus is technical. A merge session should check whether the projection
should drop such entries. This plan does not change that.

## 4. Recommendations

Each recommendation has the same fields: change, reason, files, byte cost, acceptance check, priority.
The byte costs of CSS and JS come from a measurement: the draft snippet was appended to the shipped file and
the gzip sizes were compared. The scripts are in section 9.

### R1. A pick mark that the record fields compute

**Change.** Add one mark, "pick", for the offers that are usable, well evidenced and current. Print it as the
word `pick` with the emoji `⭐` in the facts line of a row and in the header of a record. Remove the `★` from the
verdict label, so one star has one meaning.

**Definition.** A record is a pick when all of these hold. No new field is needed.

| field | condition | reason |
| --- | --- | --- |
| `verdict` | `qualifies` | the read path was probed |
| `confidence` | `measured` or `documented` | a request or a quoted first-party page backs it |
| `verified_basis` | `live` | the record was checked against the service, not inherited |
| `stale_on` | later than today | the check is still current |
| `identity_basis` | `stated` | the identity cost was read, not a placeholder |
| `binding` | not empty | a limit is named, or `none` is stated |
| `duplicate_of` | empty | a duplicate never earns a mark |

On 2026-10-28 this selects 130 records. That is 9.4 percent of the 1,388 usable records and 5.7 percent of the
2,286 records that are not rejected or dead. The fmhy share is 10 to 18 percent of bullets, so the rate is in range.
A pick has no hand-set part. It appears when the fields satisfy the rule, and it goes when one field changes, for
example when the record goes stale. There is no manual removal. A reader who disagrees opens a correction (R4).

The pick does not test card or phone. The verdict already covers an identity that fails. A reader who wants no card
uses the chip, and a pick plus the chip gives both.

**Reason.** fmhy's star is its most used device. A reader scans for stars and ignores the rest (section 2.1). Our only
star is the word `qualifies`, and it ignores evidence and age. Of the 218 `qualifies` records, 88 fail one of the
other tests.

**Files and functions.**

- `publish/schema.sql`. Add a view, so that the Worker and the build share one definition:

```sql
CREATE VIEW pick AS
SELECT rid FROM record
WHERE verdict = 'qualifies' AND confidence IN ('measured', 'documented')
  AND verified_basis = 'live' AND identity_basis = 'stated'
  AND binding IS NOT NULL AND duplicate_of IS NULL AND stale_on > date('now');
```

- `publish/pages.py`. In `Site.row_attrs`, add `pick` to the `data-f` flags when the rid is in the view. In
  `Site.badges`, emit `<span class="pk">⭐ pick</span>` as the first item of the facts line. In `Site.facts`, show the
  pick in the verdict cell. In `record_section`, add a one-sentence reason line (see the mock in section 8). Change
  `VERDICT_LABEL["qualifies"]` from `★ qualifies` to `qualifies`. `Site.lane` computes the lane width from the
  label length. The label gets two characters shorter, so check that no list changes its lane class.
- `site/static/assets/app.js`. In the array `VL`, change `★ qualifies` to `qualifies`. After the `fresh()` call,
  hide a `.pk` whose row is stale (the code is in section 9).
- `site/static/assets/style.css`. Add the tokens `--pk` and `--pkb`, the rule `.pk`, and the filter rule for the
  chip of R6. The code is in section 5.

**Byte cost.** CSS +254 raw, +74 gzip. JS +250 raw, +59 gzip. HTML +about 45 bytes for each of the 130 picks, 5.9 KB
in all.

**Acceptance check.**

1. `python publish/build.py --site site/dist` exits 0.
2. `grep -c 'class="pk"' site/dist/t/inference/index.html` gives the count of picks in that topic.
3. Set the system date after a pick's `stale_on`, or edit one `data-stale-on` in a built page to a past date.
   Reload. The mark disappears.
4. The row text reads correctly with the emoji removed, because the word `pick` stays.
5. Run `python publish/test_llms.py --site site/dist` (R16 adds the Markdown part).

**Priority.** P1.

### R2. A key for every symbol

**Change.** Add a `details` element with the title "Key" to every topic page, under the filter chips. It holds the
emoji legend of section 6 and the six verdict words. Add the same legend, as a table, to `/about/#legend`. Link from
each record page's fact block with the word "key".

**Reason.** The home page is the only page that explains verdicts. A reader who arrives on a topic page from a
search sees pills and symbols with no explanation. fmhy lists an "Emoji Legend" in its menu. That page was not readable, so how well it explains the symbols is unknown. The README of `fmhy/edit` repeats the three main marks.

**Files.** `publish/pages.py`: add `Site.key()` next to `Site.chips()`, and call it from `Site.topic`, the rejected
page and `Site.need`. Reuse the table that `Site.home` builds for "Reading a verdict". Add the legend table to
`Site.about`. `style.css`: the `.key` rules.

**Byte cost.** CSS +217 raw, +35 gzip. HTML +about 900 bytes for each topic, need and rejected page. That is about
40 pages, so 36 KB in all. The provider pages do not change.

**Acceptance check.** Each topic page has a `details.key` element. Its table has one row for each emoji in
section 6. A test in `publish/test_llms.py` or a new test finds every emoji that `pages.py` can print and checks
that the legend names it. Add this test so a new emoji cannot ship without a legend line.

**Priority.** P1.

### R3. Report links, and a contribute page

**Change.**

1. Add `/contribute/`. It has the entry rules, the three forms and what happens next. It is the page version of
   [`../CONTRIBUTING.md`](../CONTRIBUTING.md). The Markdown version `/contribute.md` has the same text.
2. Add a footer link "Contribute" to the page shell.
3. Add a "report" link to the meta line of every record. The link opens the Correction form with the record id
   filled in. The script builds it, so the HTML does not change.

**Reason.** No page links to GitHub today. A reader who sees a wrong price has no path to report it. fmhy puts "Edit
this page" on every page and a feedback page in the menu. The cheapest report is one click with the record already
named.

GitHub issue forms accept a query string whose keys are field ids. The Correction form has a field with the id
`record`. So the URL `https://github.com/Azathothas/fshy.ajam.dev/issues/new?template=correction.yml&record=compute/groq-cloud`
fills it. The URL holds a record id and no personal data.

**Files.**

- `publish/pages.py`: `Site.page`, in the `footer` string, add `&middot; <a href="/contribute/">Contribute</a>`. Add
  `Site.contribute()` and call it in `render`. Add the path to the sitemap list.
- `publish/llms.py`: write `/contribute.md` from the same text. Add the page to `llms.txt` under "Optional".
- `site/static/assets/app.js`: the script in section 9 appends the link.
- `.github/ISSUE_TEMPLATE/correction.yml`: keep the field id `record`. R4 changes the other fields.

**Byte cost.** JS +439 raw, +184 gzip. The footer link adds 46 bytes raw to each of about 2,950 pages, which is 136
KB raw across the site and about 30 bytes gzip for each page. The shell stays at about 2,034 bytes raw.

**Acceptance check.** Open a record page with JavaScript on. The meta line ends with "report". Its `href` holds the
record id. Open the same page with JavaScript off. The footer link "Contribute" is still there. `/contribute/` lists
the three forms.

**Priority.** P1.

### R4. New issue forms, labels and a triage workflow

This recommendation is the largest. Section 7 holds the full design: the forms, the label set, the workflow and the
rules for reading an issue as data. Summary of the change:

- Replace the two forms with four: new offer, correction, closed or changed, and still works.
- Switch off blank issues. Add contact links to search and to `/contribute/`.
- Create a label set with the prefixes `type:`, `topic:` and `status:`.
- Add `.github/workflows/triage.yml` and `publish/triage.py`. They label an issue from its form fields and find a
  probable duplicate. They never close an issue and never run issue text.
- Add `docs/triage.md` for the merge session.

**Reason.** Section 2.3 and section 2.4 show the same pattern in every project that handles many submissions: reduce
input with entry rules, force structure with a form, check mechanically before a human reads, and label by status.

**Byte cost.** None in the browser.

**Acceptance check.** See section 7.7.

**Priority.** P1.

### R5. Move paid offers off each topic page

**Change.** Keep usable and trial offers on `/t/<topic>/`. Move the paid group to `/t/<topic>/paid/`, a page that
has the same layout as the existing `/t/<topic>/rejected/` page. Keep an `h2` with the id `paid` on the main page. It
holds the count and a link to the new page, so `#paid` still works as an anchor.

**Reason.** The compute page is 684,756 bytes raw and 99,037 gzip. The paid group is 294,629 raw and 40,541 gzip. The
move takes the page to 390,127 raw and about 58,500 gzip, which is 41 percent less. A reader who wants free
capacity does not read the paid list, and an agent has the Markdown files. The reader's need is free capacity,
so paid-only offers are the lowest-value block on the page.

**Files.** `publish/pages.py`, `Site.topic`. The code loops over `GROUPS[:3]` and writes the sections. Take `paid` out
of that loop. Write a second page with the same loop body and the title "Paid only". Update `Site.stats` so the
paid count links to `paid/`. Add the 13 new URLs to the sitemap. `publish/llms.py` keeps the paid group in the topic
Markdown, so agents lose nothing.

**Byte cost.** No shared bytes. The site gains 13 pages and loses about 0.7 MB of repeated rows in the topic pages.

**Acceptance check.** `wc -c site/dist/t/compute/index.html` is below 400,000. `site/dist/t/compute/paid/index.html`
exists and has 489 rows. `#paid` on the main page shows a link to it. The jump links of the main page still work.

**Priority.** P1.

### R6. A "picks only" chip, filters kept in the URL, picks on the home page

**Change.**

1. Add a chip "picks" to `Site.chips()`, first in the row. The rule `html.f-pick [data-f]:not([data-f~=pick])` hides
   the other rows. fmhy's toggle does the same for stars.
2. Keep the chosen chips in the URL query as `?f=nocard,pick`. The page reads the query on load and presses the
   named chips. A link now carries a filter, for a human and for an agent.
3. On the home page, add a line to each topic tile: "N picks", linked to `/t/<topic>/?f=pick`.

**Reason.** fmhy's starred toggle is the way readers shrink a long page. Our compute page has 504 usable rows. A
reload clears the chips today, and a reader cannot send a colleague the filtered view.

**Files.** `publish/pages.py`: `Site.chips`, `Site.home` (the tile loop). `app.js`: the filter code after the chip
handlers (section 9). `style.css`: add `html.f-pick` to the existing hide rule.

**Byte cost.** CSS +about 40 raw, included in R1's rule. JS +519 raw, +137 gzip. HTML +about 30 bytes for each of 13
tiles.

**Acceptance check.** Open `/t/compute/?f=pick,nocard`. Both chips show as pressed and the count line reads "N of M
shown". Press a chip. The address bar changes and the page does not reload. With JavaScript off, the page shows all rows.

**Priority.** P1.

### R7. An added date, and a page of new and removed offers

**Change.**

1. Add a field `added_on` to each record in the public store. It is the date the record first appeared in the
   research repository.
2. Add `/new/`. It lists the offers added in the last 60 days, newest first, grouped by day, and the offers that
   became `dead` or `fails-*` in the same window.
3. Print the emoji `🆕` and the word "new" on a row that is at most 30 days old. The script decides, so a page
   built today stays right tomorrow.

**Reason.** fmhy has two views for this: monthly posts and a 30-day page of removals (section 2.1). Readers return to
a catalogue to see what changed. Today we cannot answer "what was added this month". The store has no added date, and
the ledger cannot give one. The ledger has 821 rows, all dated 2026-10-28. Of these, 227 rows for 88 records have an
empty `path`. They may mark creation, but this is not verified. Check `scripts/fr add` in the research repository
before you rely on them. Verdict changes are in the ledger under the path `$.verdict`: 10 rows so far. They feed the
"removed" half of the page.

**Files and process.**

- Research repository, `scripts/fshy/build.py` and `scripts/fshy/rules/projection.json`: add `added_on`. Compute it in
  one pass with `git log --diff-filter=A --format=%as --name-only -- dossier/` and take the earliest date of each
  path. Records that came with the first import all get one date. Publish `added_on` for them as empty, or the
  `/new/` page will list the whole corpus.
- This repository, `publish/schema.sql`: add the column. `publish/export.py` carries it. A merge session runs the
  export (`AGENTS.md` section 2, rule 1). Do not edit `data/` by hand.
- `publish/pages.py`: add `Site.new_page()`. In `Site.row_attrs`, add `data-added` only when the record is at most 90
  days old at build time. Print `<span class="nw" data-added="..." >🆕 new</span>`.
- `app.js`: hide a `.nw` older than 30 days (section 9).

**Byte cost.** CSS +38 raw, +9 gzip. JS +151 raw, +58 gzip. The `data-added` attribute costs 24 bytes for each record added in
the last 90 days.

**Acceptance check.** `/new/` exists, is in the sitemap and has a Markdown version `/new.md`. With no record newer
than 60 days, the page prints one sentence that says so. A row 31 days old shows no `new` mark after the script runs.

**Priority.** P1. The data part needs a merge session, so start it first.

### R8. Requirement and evidence icons in the facts line, and a verdict stripe

**Change.**

1. In `Site.badges`, prefix each extra requirement with an emoji and keep the word. The three forms are `💳 card`,
   `📱 phone` and `🏫 institution`. Prefix the evidence rung the same way: `🔬 measured`, `📄 documented` and
   `💬 reported`. The script prints `⏳ stale`. `inferred` and `unverified` stay plain grey text, so the weak
   rungs do not draw the eye.
2. Add a 3 px left stripe to each row, in the colour of its verdict group. CSS only, through `:has()`.

**Reason.** A reader needs to see at once which rows ask for a card or a phone. The facts line is one run of text
today. Privacy Guides and Wotaku both use short cells and icons for this. Each emoji has a word beside it. The word
keeps meaning for a reader without the emoji font and for an agent.

**Files.** `publish/pages.py` `Site.badges`. `style.css` stripe rules (section 5). `app.js`: `fresh()` adds the
`⏳` text to the stale label.

**Byte cost.** CSS +275 raw, +79 gzip. HTML about +9 bytes a row, so about +10 KB raw on the compute page. It
compresses well because the same emoji repeat.

**Acceptance check.** In the compute usable group, a row that needs a card shows `💳 card`. Turn off the emoji with
a browser extension or a font that lacks them. The row is still readable. The stripe contrast ratios are in
section 5.

**Priority.** P2.

### R9. Aligned fact columns on wide screens

**Change.** At 64 rem and wider, show the facts line as a grid with fixed columns: identity, card, phone, binding,
evidence, freshness. Every row then puts the same fact in the same place.

**Reason.** Fixed columns are what makes the Wotaku and Privacy Guides tables fast to scan. Our facts line is a
flex row, and its items shift when one is absent. The card and phone items are absent in many rows.

**Files.** `publish/pages.py` `Site.badges`: always emit a slot for card and phone, empty when not needed
(`<span></span>`). `style.css`: the rule in the cost table.

**Byte cost.** CSS +151 raw, +36 gzip. HTML +about 13 bytes for each row that lacks a card or phone item. On the compute
page that is about 12 KB raw.

**Acceptance check.** At 1280 px width, the fifth item of each facts line starts at the same x position in 20
sampled rows. Below 64 rem, the layout is unchanged.

**Priority.** P2.

### R10. A clean one-line headline for each offer

**Change.** Stop cutting summaries at 160 characters in the middle of a word.

- Step 1, no data change. Cut at the last sentence end or the last space before the limit, and end with a full stop
  or the ASCII `...` only when text was dropped.
- Step 2, a research task. Add a dossier field `headline` of at most 100 characters in ASD-STE100, written when a
  record is created or verified. Rows show `headline` and fall back to the cut summary.

**Reason.** 2,452 of the 4,144 summaries in `data/tables/record.jsonl` end with an ellipsis. Examples cut inside a
token, such as "Qwen3Guard-G...". The cut is made before the data reaches this repository, in the research
repository's projection. fmhy rows are one short line each. A reader decides from that line.

**Files.** The projection in the research repository (find the function that writes `summary` in `scripts/fshy/`).
The row code in `publish/pages.py` `Site.entry` already prints `c["summary"]`. For step 2 add `headline` to
`publish/schema.sql` and to `CARD` in `publish/llms.py`.

**Byte cost.** Neutral. Shorter lines save about 40 bytes a row.

**Acceptance check.** No row ends in a half token. `grep -c '\.\.\.<' site/dist/t/compute/index.html` drops below 10
percent of its present value after step 1.

**Priority.** P2.

### R11. Search that knows picks and topics

**Change.**

1. Boost an entity that has a pick in the name search, as fmhy boosts starred links.
2. Show `⭐` in the drop-down row of an entity that has a pick.
3. Accept a topic word as a scope: `compute gpu` filters the name hits to entities that have a compute record. The
   scope applies only when the first word is a topic id.

**Reason.** fmhy ranks starred links higher. For a short query such as "gpu" or "email", the best-evidenced provider
should come first.

**Files.** `publish/site_gen.py`, the `names` loop near line 105: add a ninth value, the count of picks of the
entity. `site/static/assets/app.js`: in `loadNames`, add `boostDocument` to `searchOptions`, add `p` to `storeFields`,
and add the mark in `renderDrop`. Update `site/worker/api.js` `scoreNames` to use the same boost, so the API and the page
agree.

**Byte cost.** JS +77 raw, +34 gzip for the boost. The scope parser adds about 200 raw. `names.json` grows by about 9 KB raw
and 1 KB gzip.

**Acceptance check.** In the page, the query "groq" puts a pick above a non-pick of equal text score. `node
site/worker/test/run.mjs` passes. Add a test that the API order and the page order agree.

**Priority.** P2.

### R12. State the binding limit once on a record page

**Change.** A record prints the binding limit three times: as the highlighted item in the Limits list, as the grey
line under that list, and as the Binding row. Keep the highlighted item and the Binding row only if they hold
different text. Otherwise drop the grey line and the Binding row, and put the word "binding" on the list item (it
already has one through CSS).

**Reason.** On `p/groq/` the same 300-character sentence appears three times for one record. In a sample of 353
records the Binding rows alone are 73,652 bytes. That is 209 bytes for each record, or about 0.9 MB raw for all
4,188 records. This is an estimate. A human and an agent both read the sentence three times.

**Files.** `publish/pages.py` `Site.record_section`, the `lims` block and the Binding `kv` row.

**Byte cost.** No shared bytes. About 0.9 MB raw less in the provider pages, an estimate.

**Acceptance check.** On `p/groq/` the sentence occurs once. A record whose binding kind has no limit row still
shows its Binding row.

**Priority.** P2.

### R13. A monthly digest page

**Change.** Generate `/changes/<yyyy-mm>/` for each month. Its sections follow the fmhy post template: added, picks
changed, removed. Use the `added_on` field (R7), the ledger rows with the path `$.verdict` and the history items of
that month. List the digests on `/changes/` and in the RSS feed.

**Reason.** fmhy's monthly post is its main changelog and the unit that its RSS carries. Today our changes page is
one long list of 360 KB raw, 108 corrections and 500 ledger rows, with no month structure.

**Files.** `publish/pages.py` `Site.changes` and the RSS code in it. `publish/llms.py`: a Markdown version.

**Byte cost.** None shared. `/changes/` gets smaller, because it lists digests instead of every row.

**Acceptance check.** `/changes/2026-10/` exists. `changes.xml` has one item for the month. The page lists a record
once for each kind of change.

**Priority.** P2. It needs R7.

### R14. A weight budget test and a pull request template

**Change.**

1. Add `publish/test_weight.py`. It reads `site/dist` and fails when a limit in the table below is exceeded.
2. Add `.github/pull_request_template.md` with the checklist in section 9.3. Add the test to `.github/workflows/build.yml`
   and to `AGENTS.md` section 4.

| limit | value |
| --- | --- |
| `style.css` plus `app.js`, gzip | 12,000 bytes |
| page shell, raw | 2,200 bytes |
| a topic page, gzip | 70,000 bytes |
| a need page, gzip | 30,000 bytes |
| a provider page, gzip, except the five largest | 12,000 bytes |
| a file written by `llms.py` | 300,000 bytes (already enforced) |

Done on 2026-10-29 in `publish/test_weight.py`. The page limits there come from a measurement of the data of that
day and keep about a third of room, so a publish that adds records passes: a topic page or its paid page 80,000, a
rejected page 160,000, a need page 40,000, a provider page or a record page 30,000, the graveyard and the changes
page 40,000, and any file 70 percent of the 25 MiB asset limit. The shared files and the shell keep the limits above.

**Reason.** The only protection against bloat today is a sentence in `site/README.md`. awesome and free-for-dev
enforce their rules with a checklist and a tool. A number in a test cannot be forgotten.

**Byte cost.** None.

**Acceptance check.** Raise `app.js` by 3 KB on purpose. The test fails and names the file and the limit.

**Priority.** P2.

### R15. Copies and permalinks on the about page

**Change.** Add a section "Copies and links" to `/about/`. It lists the ways to hold a full copy: the store file
`/data/fshy-public.sqlite.gz`, the files `/llms-full.txt`, the repository archive and the JSONL tables in `data/`. It
explains the permalink `/r/<topic>/<slug>`, which the Worker already serves, and the anchors `#<topic>--<slug>` and
`#usable`.

**Reason.** fmhy keeps a whole page of backups and mirrors. A catalogue about resources that die should say how to
keep a copy. Stable URLs are the main help we give agents, and we do not write them down for humans.

**Files.** `publish/pages.py` `Site.about`.

**Byte cost.** None shared. The about page grows by about 700 bytes.

**Acceptance check.** Every URL in the section returns 200 on a local `wrangler dev` run, or exists in `site/dist`.

**Priority.** P2.

### R16. The same signals for agents: files, API and MCP

**Change.**

- `publish/llms.py`, `entry_md` and `record_md`: print `pick` after the verdict token when the record is a pick. Print
  `added <date>` when the field exists. Do not print emoji in any Markdown file.
- `reading_rules`: add one paragraph that defines `pick` and `added` in the words of section 6.
- `llms.txt`: add `/new.md` and `/contribute.md`.
- `site/worker/api.js`: add `pick` to `FILTER_KEYS`. In the `where` list, add `rid IN (SELECT rid FROM pick)`. The MCP
  `filter` tool shares this code.
- `publish/primer.py`: add one worked example, "picks for each topic".
- Text rule for a pick: the files state it as a computed fact with its date, and never as advice. A pick is data.

**Reason.** Agents should get the new signals in text, with no emoji and no script. The Markdown route is the agent
path (section 3.3).

**Byte cost.** None in the browser. `llms-full` grows by about 6 bytes for each pick line, 780 bytes in all.

**Acceptance check.** `python publish/test_llms.py --site site/dist` passes. It checks that the count of `pick`
tokens equals the count of rows in the `pick` view. `/api/v1/records?topic=compute&pick=1` returns only picks.

**Priority.** P2.

### R17. The colour theme: tokens and forced colours

**Change.** Adopt the token set of section 5. It keeps today's neutrals and verdict colours, which already pass.
It adds the pick colours, and it raises the control border contrast. Add a rule for forced-colour mode. Do not add a
manual theme switch.

**Reason.** The contrast of every pair was computed in today's stylesheet. All text pairs pass 4.5. The control
border `--ctl` is the weakest, at 3.03 in light. A manual switch costs more than it gives. It needs the dark token
set a second time, about +336 raw. It needs an inline script in the `head` of every page to avoid a flash, and
that script would add about 120 bytes to each of 2,950 pages. The system setting already works, and fmhy's
AMOLED variant has no value that the dark theme lacks for our table layout.

**Files.** `style.css` top block. Section 5 has the full text.

**Byte cost.** CSS +about 100 raw, +25 gzip with the forced-colour rule.

**Acceptance check.** Run the script in section 5. Every listed pair meets its minimum. Open the site in a
browser with forced colours on. The pills and the pick keep a visible border.

**Priority.** P2.

### R18. A one-line topic bar on mid-width screens

**Change.** The topic bar wraps to three lines between 48 rem and about 70 rem. Make it a one-line scroller up to
72 rem, as it already is below 48 rem.

**Reason.** The screenshot of `t/inference/` at 800 px width shows three lines of topic links before the title. The
reader scrolls past navigation before any content.

**Files.** `style.css`, the `@media (max-width:47.99rem)` block for `.topics`. Add `max-width:71.99rem` for `.topics`.

**Byte cost.** About 0 (a changed number).

**Acceptance check.** At 800 px, the topic bar is one line and scrolls sideways. The current topic stays in view,
as the first block of `app.js` already ensures.

**Priority.** P3.

### R19. Sort by price on a topic page

**Change.** Add two buttons to a group heading: "price" and "verdict". "price" sorts the group by the parsed price,
cheapest first, and puts rows with no price last. The group has a `data-p` value on each row for the number.

**Reason.** Price is the second question after "is it free". Privacy Guides and Wotaku show columns for this, and
the best-per-need pages already sort by price. A topic page cannot.

**Files.** `publish/pages.py` `row_attrs`: add `data-p` from `usd_month` or `usd_per_tb_month`. `app.js`: the sort
handler in section 9. `style.css`: reuse the chip style.

**Byte cost.** JS +346 raw, +88 gzip. HTML +about 12 bytes for each of the 540 records with a parsed price.

**Acceptance check.** Pressing "price" in the storage usable group puts the cheapest priced row first and leaves
the rows with no price at the end, in their old order.

**Priority.** P3.

## 5. The colour theme

The structure stays: system light and dark, CSS custom properties, one block at the top of `style.css`. The values
below keep every colour that exists today. They change `--ctl`, and add `--pk` and `--pkb`. The comment names the use.

```css
:root{color-scheme:light dark;--w:72rem;
/* surface */
--bg:#fafbfc;--sf:#ffffff;--sk:#f2f4f6;--ln:#e4e7eb;--ln2:#cfd4dc;
/* text */
--fg:#16181d;--fg2:#394150;--mut:#5b6370;
/* link, focus, current item */
--acc:#1a56db;--accb:#dde7fc;
/* control border (inputs, chips): raised for 3:1 */
--ctl:#7b838f;
/* verdict groups: usable, caveat, trial, paid, fails, dead */
--q:#137443;--qf:#ffffff;--ok:#12663a;--okb:#e2f3e9;--wa:#8c4800;--wab:#fcefd9;
--pd:#3240a3;--pdb:#e8ebfb;--bad:#a31f2c;--badb:#fbe7e9;--dd:#575e69;--ddb:#eaecef;
/* pick (new) */
--pk:#6b4200;--pkb:#fdf0c8}
@media (prefers-color-scheme:dark){:root{
--bg:#0e1013;--sf:#15181d;--sk:#1d2127;--ln:#262b33;--ln2:#373e49;
--fg:#e8eaee;--fg2:#c3c9d2;--mut:#99a1ad;
--acc:#82aaff;--accb:#1f3157;--ctl:#7a8390;
--q:#4bc58a;--qf:#04170c;--ok:#7dd5a2;--okb:#13281c;--wa:#f0b866;--wab:#2d2211;
--pd:#aeb8ff;--pdb:#1d2142;--bad:#ff9ca4;--badb:#36191d;--dd:#a7aeb8;--ddb:#23272e;
--pk:#f5cf6b;--pkb:#2e2508}}
@media (forced-colors:active){.v,.pk,.nw{border:1px solid}}
```

Notes for the implementer.

- In the shipped file the tokens `--sans`, `--mono`, `--i1` and `--i2` sit in the same block. Keep them.
- Replace the old `--ctl:#8a929e` and the dark `--ctl:#68717e` with the values above.
- The tag colours keep one job each. Green is for usable, amber for trial, indigo for paid, red for fails and grey for
  dead. Colour never carries a meaning alone, because each pill holds the word.

WCAG 2.x contrast ratios. Each ratio uses the relative luminance formula of WCAG 2.x. The minimum is 4.5 for
text and 3.0 for a control border, a stripe or a focus ring.

| pair | light | dark | minimum |
| --- | --- | --- | --- |
| text `--fg` on `--bg` | 17.14 | 15.82 | 4.5 |
| text `--fg2` on `--sf` | 10.26 | 10.68 | 4.5 |
| muted `--mut` on `--bg` | 5.85 | 7.31 | 4.5 |
| muted `--mut` on `--sk` | 5.50 | 6.20 | 4.5 |
| link `--acc` on `--bg` | 5.97 | 8.30 | 4.5 |
| link `--acc` on `--sf` | 6.18 | 7.75 | 4.5 |
| current topic `--acc` on `--accb` | 4.98 | 5.59 | 4.5 |
| qualifies pill `--qf` on `--q` | 5.82 | 8.52 | 4.5 |
| caveat pill `--ok` on `--okb` | 6.10 | 8.84 | 4.5 |
| trial pill `--wa` on `--wab` | 6.08 | 8.72 | 4.5 |
| paid pill `--pd` on `--pdb` | 7.38 | 8.23 | 4.5 |
| fails pill `--bad` on `--badb` | 6.35 | 8.03 | 4.5 |
| dead pill `--dd` on `--ddb` | 5.53 | 6.70 | 4.5 |
| pick pill `--pk` on `--pkb` | 7.68 | 10.13 | 4.5 |
| fresh text `--ok` on `--sf` | 7.03 | 10.09 | 4.5 |
| stale text `--wa` on `--sf` | 6.90 | 9.96 | 4.5 |
| pressed chip `--sf` on `--acc` | 6.18 | 7.75 | 4.5 |
| control border `--ctl` on `--bg` | 3.70 | 4.97 | 3.0 |
| stripe `--q` on `--bg` | 5.62 | 8.76 | 3.0 |
| stripe `--wa` on `--bg` | 6.66 | 10.66 | 3.0 |
| stripe `--pd` on `--bg` | 8.45 | 10.07 | 3.0 |
| stripe `--bad` on `--bg` | 7.27 | 9.57 | 3.0 |
| stripe `--dd` on `--bg` | 6.31 | 8.52 | 3.0 |
| focus ring `--acc` on `--bg` | 5.97 | 8.30 | 3.0 |

Before this change the control border was 3.03 in light and 3.86 in dark. It passed by a thin margin in light, so the new value is higher.

The stripe rules, with the cost measured in R8:

```css
.e{padding-left:.625rem;border-left:3px solid var(--vc,transparent)}
.e:has(.v-qualifies,.v-qualifies-with-caveat){--vc:var(--q)}
.e:has(.v-trial-only){--vc:var(--wa)}
.e:has(.v-paid-only){--vc:var(--pd)}
.e:has([class*=v-fails]){--vc:var(--bad)}
.e:has(.v-dead){--vc:var(--dd)}
```

The pick rules:

```css
.pk{padding:0 .375rem;border-radius:4px;background:var(--pkb);color:var(--pk);font-weight:650}
html.f-pick [data-f]:not([data-f~=pick]){display:none}
```

To recompute the ratios, run this script. It needs only Python.

```python
def lin(c):
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
def lum(h):
    h = h.lstrip('#'); r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
def ratio(a, b):
    x, y = sorted((lum(a), lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)
print(round(ratio('#6b4200', '#fdf0c8'), 2))   # 7.68
```

## 6. The emoji legend

Rule: an emoji never stands alone. The word stays beside it, and the Markdown files use the word only. Each emoji is
neutral and has one meaning. The legend goes in the `details.key` of R2 and on `/about/#legend`.

| emoji | word | where | meaning | derived from |
| --- | --- | --- | --- | --- |
| `⭐` | pick | row facts, record header, search drop-down | usable, measured or documented, checked live, not stale | the `pick` view (R1) |
| `🆕` | new | row facts | added in the last 30 days | `added_on` (R7) |
| `💳` | card | row facts, record facts | the offer asks for a payment card | `needs_card = 1` |
| `📱` | phone | row facts, record facts | the offer asks for a phone number | `needs_phone = 1` |
| `🏫` | institution | row facts, record facts | the offer asks for membership of an institution | `needs_institution = 1` |
| `🔬` | measured | row facts | a live request was made and its output kept | `confidence = measured` |
| `📄` | documented | row facts | a first-party page was read and the sentence quoted | `confidence = documented` |
| `💬` | reported | row facts | a third party said so | `confidence = reported` |
| `⏳` | stale | row facts, record facts | the check date is past the stale date | `stale_on <= today` |
| `⚠` | disagrees | row facts | sibling records disagree on a fact | a row in the `drift` table |

Ten symbols. `⚠` is also one of the five markers that `conventions.md` allows. `inferred` and `unverified` have no
emoji on purpose. A weak rung should not attract the eye. No emoji marks "free" or "paid", because the verdict pill
does that.

Rows with `needs_card`, `needs_phone` or `needs_institution` empty (unknown) show the word with a question mark, as
the code does today, and no emoji. On 2026-10-28, 214 of the 1,388 usable records have an unknown card value.

## 7. Handling submission volume

### 7.1 Principles

1. Every report is a lead. A research lane checks it against the provider's own pages. This is the rule in
   `AGENTS.md` section 2, rule 6, and it stays.
2. The form does the sorting. A field with a fixed list of values beats free text.
3. A machine checks first and a human reads second. The machine labels and comments. It never closes, never merges and
   never runs text from an issue.
4. A report that carries evidence outranks a report that carries an opinion. Privacy Guides separates the two. We do
   the same.
5. A count of votes is not a signal. It is easy to inflate and it tells us nothing about the provider's page.

### 7.2 The forms

Put these in `.github/ISSUE_TEMPLATE/`. Keep the existing `report` label on all of them. Field ids in lower case.

| file | title | required fields | extra labels |
| --- | --- | --- | --- |
| `new-offer.yml` | New offer | topic (dropdown), provider, what it offers, source URL with date, identity (check boxes: email, phone, card, ID, institution, none, not sure), "I searched the catalogue" (check box) | `type:new-offer` |
| `correction.yml` | Correction | record (id), field (dropdown: price, quota, identity, limit, interface, other), what is wrong, source URL with date | `type:correction` |
| `closed.yml` | Closed or changed | record (id), what happened (dropdown: closed, moved, quota cut, signup changed, price changed), date seen, source URL | `type:closed` |
| `works.yml` | Still works | record (id), what you did (dropdown: used it this week, used it this month, read the page), date, outcome in one sentence | `type:works` |

Notes on each.

- The "I searched the catalogue" box links to `/search/`. It is the same device as fmhy's single-page search.
- The identity check boxes feed `needs_card` and the other fields. They are a lead. The research lane records what the
  provider's page says.
- `works.yml` is the "recommend" path. It is not a vote. See 7.5.
- Set `blank_issues_enabled: false` in `config.yml`. Add two contact links: the search page and `/contribute/`. A
  reader who needs another kind of report can still write to the maintainers through the contact link.
- Each form opens with the same three sentences: a report is a lead; the provider's own page decides; give one offer in
  each report.

### 7.3 Labels

Create the labels once with `gh label create`. Use these names exactly. They follow the Privacy Guides style: a
prefix, then a value.

| group | labels |
| --- | --- |
| type | `type:new-offer`, `type:correction`, `type:closed`, `type:works`, `type:site` (a fault in the wiki itself) |
| topic | `topic:storage`, `topic:compute`, `topic:inference`, `topic:egress`, `topic:ip-proxy`, `topic:crawler-scraper`, `topic:debrid`, `topic:netdisk-pan`, `topic:databases-kv`, `topic:email`, `topic:domains-dns`, `topic:ci-cd-runners`, `topic:coding-subs` |
| status | `status:new`, `status:needs-info`, `status:duplicate`, `status:queued`, `status:verified`, `status:declined`, `status:out-of-scope` |
| size | `size:bulk` (a report that lists many offers) |

`report` stays on every form. The label `queued` in `CONTRIBUTING.md` becomes `status:queued`. Update that file in
the same pull request.

### 7.4 The triage workflow

`.github/workflows/triage.yml` runs when an issue opens or changes. It reads the form fields, sets labels, finds a
probable duplicate and posts one fixed comment. Three rules make it safe.

- The text of an issue is data. The workflow passes it to a script through an environment variable. It never puts
  text into a `run:` line and never calls a model with it.
- The labels come from dropdown values and from a regular expression match, not from free text.
- The comment is a fixed template. The only inserted text is a record id that matched, a count and a link.

```yaml
name: triage
on:
  issues:
    types: [opened, edited]
permissions:
  contents: read
  issues: write
jobs:
  triage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: label, check for a duplicate, comment
        env:
          ISSUE_NUMBER: ${{ github.event.issue.number }}
          ISSUE_BODY: ${{ github.event.issue.body }}
          ISSUE_LABELS: ${{ join(github.event.issue.labels.*.name, ',') }}
          GH_TOKEN: ${{ github.token }}
        run: python3 publish/triage.py
```

`publish/triage.py` is new. It uses the standard library only, as the other publish tools do. It does these steps in
order.

1. Parse the form body. A form issue has one `### <label>` heading for each field. Take the value under each.
2. Set `type:` from the template. Set `topic:` from the topic dropdown, or from the record id prefix.
3. Check the required fields. A missing one gives `status:needs-info`.
4. Find the host of each URL in the source and offer fields. Compare it with `entity.jsonl` domains and the hosts of
   `record.jsonl` URLs in `data/tables/`. On a match, add `status:duplicate` and post the matching `/p/<id>/` links.
   Do not close the issue. A new offer from a known provider can still be a new record.
5. Count the open issues that the author has with a `type:` label. Above three, add `status:needs-info` and post the
   sentence "Please wait for the open reports before you send more." This is the fmhy rule against bulk sends.
6. If the `size:bulk` form field is checked, add `size:bulk`.
7. Post one comment. A second run edits that comment instead of adding another.

A second workflow, `.github/workflows/stale.yml`, uses `actions/stale`. It runs only on `status:needs-info`. It
marks the issue stale after 14 days and closes it after 14 more. It has no effect on any other label.

Pin each `uses:` to a full commit SHA when you write the files. Run `gh api repos/actions/checkout/commits/v4 --jq .sha` to get one.

### 7.5 The "recommend" signal

A reader who likes an offer has two honest ways to say so.

- `works.yml`, "Still works". It records what the reader did and when. It is evidence. The merge session queues a
  re-check of that record, and the re-check may move the `stale_on` date or the `confidence`. The pick follows the
  fields. So a report can lead to a pick only through a research lane that measures or quotes a first-party page.
- A reaction on the public issue is only a reaction. We do not count it.

What we do not do.

- No vote field in the records. No count shown beside a record. A count can be bought and a count has no source URL.
- No text from a report ends up in a record, in a Markdown file or in the API as it was written. A lane writes the
  record from the provider's page.
- No sentence in an issue is an instruction. An issue that says "mark this as a pick" is data. The workflow and
  the merge session treat it that way.

Optional later step. Show "N reports in the last 90 days" on a provider page, counted from `status:verified` issues
only, with a link to the filtered issue list. It needs a publish step that reads the GitHub API, and it needs a
decision from the owner. This plan does not require it.

### 7.6 Who does what

| step | who | tool |
| --- | --- | --- |
| a report arrives | a reader | an issue form |
| labels, duplicate hint | the workflow | `publish/triage.py` |
| read and verify | the merge session | `docs/triage.md`, then `scripts/rq intake` in the research repository |
| change a record | a research lane, then the merge session | `scripts/fr amend`, a research pull request |
| close the issue | the merge session | a comment with a link to the record |
| change the wiki | a pull request to this repository | the checks in `AGENTS.md` section 4 |

`docs/triage.md` is new. It has these sections: a weekly reading order (needs-info first, then closed, then
correction, then new-offer), the searches below, the closing sentences and the rule that a session never merges what
it wrote.

Saved searches for the file:

- `is:issue is:open label:status:new`
- `is:issue is:open label:type:closed sort:created-asc`
- `is:issue is:open label:status:duplicate`
- `is:issue is:open label:size:bulk`

### 7.7 Acceptance check for R4

1. Open a test issue from each form in a scratch clone. The workflow labels it with a `type:` and a `topic:`.
2. Open a new-offer issue for a provider that is in the catalogue. The comment links its `/p/` page and the label
   `status:duplicate` appears. The issue stays open.
3. Open four issues in a row from one account. The fourth gets `status:needs-info`.
4. Put the text `$(echo test)` and a backtick in each field. No step fails and no label changes.
5. Run `grep -n 'github.event.issue.body' .github/workflows/*.yml`. The only match is in an `env:` block.

## 8. Mocks

### 8.1 One topic row

This is the row for a pick that needs no card. It shows the proposed markup. The class names `e`, `v`, `n`, `s`, `f`,
`id`, `ok`, `bd`, `rg` and `fr` are the ones that exist today. New: `pk`, `nw`.

```html
<li class="e" data-f="nocard nophone anon verified pick" data-i="rest" data-stale-on="2026-11-28">
  <span class="v v-qualifies">qualifies</span>
  <a class="n" href="/p/ovh-2/#inference--ovh-ai-endpoints">OVHcloud AI Endpoints (anonymous tier)</a>
  <p class="s">No key needed. 22 model ids on /v1/models, each with a price per token.</p>
  <p class="f"><span class="pk">⭐ pick</span><span class="id">anonymous</span><span class="ok">no card</span><span class="ok">no phone</span><span class="bd">request-rate</span><span class="rg">🔬 measured</span><span class="fr" data-basis="live" data-checked="2026-10-29"></span></p>
</li>
```

This is the row for an offer that is not a pick and that asks for a card. The card and phone items show their
emoji and word.

```html
<li class="e" data-f="verified" data-i="rest" data-stale-on="2026-11-28">
  <span class="v v-qualifies-with-caveat">caveat</span>
  <a class="n" href="/p/groq/#inference--groq">Groq</a>
  <p class="s">Free plan per model: 30 requests a minute and 1,000 a day.</p>
  <p class="f"><span class="id">email</span><span class="w">💳 card</span><span class="w">📱 phone</span><span class="bd">request-rate</span><span class="rg">📄 documented</span><span class="fr" data-basis="live" data-checked="2026-10-29"></span></p>
</li>
```

Read the first row with no emoji: "qualifies, OVHcloud AI Endpoints. pick, anonymous, no card, no phone, binds
request-rate, measured, fresh." It is complete.

### 8.2 One record header

```html
<section class="rec" id="inference--ovh-ai-endpoints" data-f="nocard nophone anon verified pick" data-i="rest" data-stale-on="2026-11-28">
  <div class="rh">
    <h2><a href="#inference--ovh-ai-endpoints">OVHcloud AI Endpoints (anonymous tier)</a></h2>
    <span class="tp">Inference</span>
    <span class="pk">⭐ pick</span>
  </div>
  <p class="meta"><a href="https://endpoints.ai.cloud.ovh.net/" rel="nofollow noopener">endpoints.ai.cloud.ovh.net</a><code>inference/ovh-ai-endpoints</code><a href="/api/v1/record/inference/ovh-ai-endpoints.json">JSON</a><a href="/compare/?r=inference/ovh-ai-endpoints">compare</a><a href="/about/#legend">key</a></p>
  <p class="why">Pick because the record is measured, was checked live on 2026-10-29 and stays fresh until 2026-11-28.</p>
  <dl class="facts">
    <div><dt>Verdict</dt><dd><span class="v v-qualifies">qualifies</span><small>usable as stated; the read path was probed</small></dd></div>
    <div><dt>Parsed price</dt><dd><span class="na">none parsed</span></dd></div>
    <div><dt>Identity</dt><dd>anonymous<small>no card, no phone</small></dd></div>
    <div><dt>Binding limit</dt><dd>request-rate<small>requests per unit of time</small></dd></div>
    <div><dt>Evidence</dt><dd>🔬 measured<small>6 sources; a live request was made</small></dd></div>
    <div><dt>Freshness</dt><dd><span class="fr" data-basis="live" data-checked="2026-10-29"></span><small>checked 2026-10-29 (live); stale on 2026-11-28</small></dd></div>
  </dl>
</section>
```

The sentence in `.why` comes from the fields. The code writes it. A record that is not a pick gets a sentence that
names the first failed test, for example "Not a pick: the evidence rung is reported." This sentence gives a reader
and an agent the exact way to move a record into the pick set, which is the research.

`record_section` already writes the six-cell block through `Site.facts`. The change adds the pick, the `why` line and
the emoji.

### 8.3 The key

```html
<details class="key"><summary>Key</summary>
<dl>
<dt>⭐ pick</dt><dd>Usable, measured or documented, checked live, not stale.</dd>
<dt>🆕 new</dt><dd>Added in the last 30 days.</dd>
<dt>💳 card</dt><dd>The offer asks for a payment card.</dd>
<dt>📱 phone</dt><dd>The offer asks for a phone number.</dd>
<dt>🏫 institution</dt><dd>The offer asks for membership of an institution.</dd>
<dt>🔬 measured</dt><dd>A live request was made and its output kept.</dd>
<dt>📄 documented</dt><dd>A first-party page was read and the sentence quoted.</dd>
<dt>💬 reported</dt><dd>A third party said so.</dd>
<dt>⏳ stale</dt><dd>The check date is past the stale date.</dd>
<dt>⚠ disagrees</dt><dd>Sibling records disagree on a fact.</dd>
</dl></details>
```

## 9. Byte costs, scripts and the review checklist

### 9.1 How the costs were measured

For each CSS or JS change, the draft text was appended to the shipped file, and the difference of
`gzip -9` sizes was taken. The base sizes are 4,810 bytes for `style.css` and 4,812 bytes for `app.js`. Repeat the method like
this.

```python
import gzip
base = open('site/static/assets/style.css', 'rb').read()
add = open('draft.css', 'rb').read()
print(len(add), len(gzip.compress(base + add, 9)) - len(gzip.compress(base, 9)))
```

| draft | raw bytes | gzip bytes |
| --- | --- | --- |
| R1 CSS tokens, pill, chip rule | 254 | 74 |
| R1 JS pick expiry | 250 | 59 |
| R2 CSS key and reason line | 217 | 35 |
| R3 JS report link | 439 | 184 |
| R6 JS filters in the URL | 519 | 137 |
| R7 CSS new mark | 38 | 9 |
| R7 JS new expiry | 151 | 58 |
| R8 CSS stripe | 275 | 79 |
| R9 CSS aligned columns | 151 | 36 |
| R11 JS search boost | 77 | 34 |
| R17 forced colours and `--ctl` | about 100 | about 25 |
| R19 JS sort | 346 | 88 |

The sum of the gzip column is 818 bytes. The shared total would be 10,440 bytes if everything ships. The cap in R14
is 12,000.

### 9.2 The scripts

R1, pick expiry. Add this after the `fresh()` call in `app.js`:

```js
$$('.pk').forEach(function (p) {
  var h = p.closest('[data-stale-on]'), so = h && h.getAttribute('data-stale-on');
  if (so && so <= today) { p.hidden = true; h.setAttribute('data-f', h.getAttribute('data-f').replace(/\bpick\b ?/, '')); }
});
```

R3, report link:

```js
$$('section.rec .meta').forEach(function (m) {
  var c = $('code', m), a = document.createElement('a');
  if (!c) { return; }
  a.href = 'https://github.com/Azathothas/fshy.ajam.dev/issues/new?template=correction.yml&record=' + encodeURIComponent(c.textContent);
  a.textContent = 'report'; a.rel = 'nofollow noopener'; m.appendChild(a);
});
```

R6, filters in the URL:

```js
var fq = new URLSearchParams(location.search).get('f');
if (fq) { fq.split(',').forEach(function (k) { var b = $('.chips [data-chip="' + k + '"]'); if (b) { b.click(); } }); }
function keep() {
  var on = $$('.chips [aria-pressed=true]').map(function (b) { return b.getAttribute('data-chip'); }).join(',');
  history.replaceState(null, '', on ? '?f=' + on + location.hash : location.pathname + location.hash);
}
$$('.chips button[data-chip]').forEach(function (b) { b.addEventListener('click', keep); });
```

R7, new expiry:

```js
$$('.nw').forEach(function (n) {
  var d = n.getAttribute('data-added');
  if (d && Date.parse(today) - Date.parse(d) > 2592e6) { n.hidden = true; }
});
```

Run these after the chip handlers are bound. The R6 code clicks the chips, so it must come after the code that
binds them, and before the final `recount()` call or with a second `recount()`.

### 9.3 Pull request checklist

Put this in `.github/pull_request_template.md`. Keep it short.

- [ ] `python publish/build.py --site site/dist` exits 0.
- [ ] `node site/worker/test/run.mjs` and `python publish/test_llms.py --site site/dist` pass.
- [ ] `python publish/test_weight.py --site site/dist` passes.
- [ ] The pull request states the byte cost of the shared CSS and JS, before and after, in gzip.
- [ ] A new symbol has a line in the key and a Markdown word.
- [ ] A new sentence follows `docs/conventions.md`.
- [ ] No file in `data/` changed.

## 10. Order of work

| step | recommendations | why this order |
| --- | --- | --- |
| 1 | R7 data part: ask a merge session to add `added_on` in the research repository | it has the longest lead time |
| 2 | R4 and R3 | they open the submission path and need no browser code |
| 3 | R5 and R14 | they cut page weight and lock the budget before more is added |
| 4 | R1, R2, R6 | they form one pull request: the pick, its key and its filter |
| 5 | R7 page part, R13 | they need step 1 |
| 6 | R12, R10 step 1, R16 | they clean text and extend the files for agents |
| 7 | R8, R9, R11, R15, R17 | they sharpen the scan |
| 8 | R18, R19 | they are small gains |

Check at the end of each step, in a browser at 375 px and 1280 px, in light and dark. Check also with JavaScript off.
A page must stay readable and every link must work.

## 11. Sources

All pages were fetched on 2026-10-28. This plan quotes at most the names of fields and files.

- fmhy site: [fmhy.net](https://fmhy.net), [fmhy.net/beginners-guide](https://fmhy.net/beginners-guide),
  [fmhy.net/ai](https://fmhy.net/ai), [fmhy.net/posts](https://fmhy.net/posts),
  [fmhy.net/recently-removed](https://fmhy.net/recently-removed), [fmhy.net/feedback](https://fmhy.net/feedback),
  [fmhy.net/other/contributing](https://fmhy.net/other/contributing), [fmhy.net/other/FAQ](https://fmhy.net/other/FAQ).
- fmhy repositories: [github.com/fmhy/edit](https://github.com/fmhy/edit), [github.com/fmhy/FMHY](https://github.com/fmhy/FMHY),
  [FMHY Backups](https://github.com/fmhy/FMHY/wiki/Backups). Files read in `fmhy/edit`:
  `.github/CONTRIBUTING.md`, `.github/ISSUE_TEMPLATE/wiki.yml`, `.github/POST_TEMPLATE.md`, `.github/labeler.yml`,
  `.github/CODEOWNERS`, `.github/workflows/*.yml`, `scripts/lint-markdown.js`, `scripts/generate-removed.js`,
  `scripts/generate-single-page.js`, `api/routes/feedback.post.ts`, `docs/.vitepress/constants.ts`,
  `docs/.vitepress/markdown/toggleStarred.ts`, `docs/.vitepress/theme/themes/README.md`.
- Others: [free-for.dev](https://free-for.dev/), [free-for-dev](https://github.com/ripienaar/free-for-dev),
  [Privacy Guides criteria](https://www.privacyguides.org/en/about/criteria/),
  [Privacy Guides repository](https://github.com/privacyguides/privacyguides.org),
  [awesome](https://github.com/sindresorhus/awesome), [FilterLists](https://filterlists.com/),
  [FilterLists repository](https://github.com/collinbarrett/FilterLists), [Wotaku](https://wotaku.wiki/),
  [Wotaku repository](https://github.com/wotakumoe/wotaku).
- WCAG 2.x contrast: [w3.org/TR/WCAG21/#contrast-minimum](https://www.w3.org/TR/WCAG21/#contrast-minimum).
