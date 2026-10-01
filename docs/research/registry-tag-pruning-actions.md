# Research: GitHub Actions for pruning Docker image tags by name-pattern AND age (Docker Hub / Quay.io)

_Researched 2026-10-01. All facts verified against each action's own repo/README via the GitHub API._

## Summary

**No single, actively-maintained marketplace action deletes tags on BOTH Docker Hub AND
Quay.io with combined tag-name-pattern + age filtering.** The ecosystem splits by registry:
Docker Hub has several single-registry Python/JS actions (the only one that truly does
`regex × age` together is `lostlink/docker-cleanup`, but it is brand-new and unproven);
Quay.io has no real packaged action for this — and importantly **Quay has a native
auto-prune feature** (regex tag-match + age/count, org- or repo-level, usable via UI or API
on quay.io) that makes a Quay-specific action largely unnecessary. For a tool that must
span both registries with `pattern × age`, building our own (or wrapping `regclient/regctl`)
is the realistic path.

## Findings

### Docker Hub candidates

- **`lostlink/docker-cleanup`** — the only candidate that does **regex AND age together**,
  but it is immature. `custom-patterns` is a JSON map of `regex → retention-days`, so each
  tag matched by a regex is deleted once older than its per-pattern age threshold; built-in
  `pr-*`/`sha` patterns also have retention-days. Docker Hub only (`https://hub.docker.com/v2`).
  Auto-protects `latest`, `main/master/develop`, semver. Dry-run, multi-repo. Auth = Docker
  Hub username + password/PAT. Deletes via Docker Hub v2 API (tag delete; registry path falls
  back to manifest-by-digest). **Maturity risk: created 2025-08-10, last push 2025-08-12, 1
  star, 6 open issues, single maintainer, MIT.**
  [README](https://github.com/lostlink/docker-cleanup) ·
  delete + regex logic: `scripts/dockerhub-cleanup.py` (regex at lines 336/351/352/355, age
  cutoffs at 358-367, `requests.delete` at 285/304).

- **`maxisam/dockerhub-cleanup`** (marketplace: "DockerHub Cleanup Action") — age-based
  (`--retention-days`, default 90) + **prefix** preservation (`--preserve prefix:number`,
  `--preserve-last`), **not full regex/glob**. Docker Hub only. Auth = username + PAT
  (`read:write`). Dry-run, CSV/JSON audit output. Packaged action (`action.yml` + Dockerfile +
  `dockerhub_cleanup.py`). 2 stars, last push 2025-02-07, 0 open issues. Fork/adaptation of
  the non-action script `bekvbe/dockerhub-cleanup`.
  [Repo](https://github.com/maxisam/dockerhub-cleanup) ·
  [Marketplace](https://github.com/marketplace/actions/dockerhub-cleanup-action).

- **`joshbeard/docker-hub-tag-delete`** (marketplace: "Docker Hub Tag Deletion", verified
  partner badge) — tag-name filtering via **fnmatch glob patterns** (`1.*`, `2.*`), but age is
  **not relative**: you supply an explicit calendar deletion date per tag group via a JSON or
  Markdown table. So it is "delete these glob-matched tags on/after this date", not "older than
  N days". Docker Hub only. Auth = username + password/token. Python, 0BSD, 2 stars, last push
  2024-06-07, 0 open issues.
  [Repo/README](https://github.com/joshbeard/docker-hub-tag-delete).

- **`alesharik/delete-old-docker-tags`** (marketplace: "Delete Old Docker Tags") — **generic
  registry** (takes `registry` URL + username/password), so it can target any registry with a
  standard Docker Registry v2 API. BUT its model is **semver + keep-last count, not age**: it
  extracts semver via a `version-extractor` regex, sorts descending, and deletes everything
  below `keep-last`. No timestamp/age filter. **Deletes manifests (by digest)**, so a deleted
  tag's manifest removal also drops any other tag pointing at the same manifest. TypeScript,
  1 star, last push 2023-10-02, 8 open issues.
  [Repo/README](https://github.com/alesharik/delete-old-docker-tags).

- **`m3ntorship/action-dockerhub-cleanup`** (marketplace: "Delete old docker image tags") —
  **abandoned/empty**: README is just `# nile`, last push 2021-08-08. Marketplace blurb claims
  "filter by substrings and number of tags to keep" (no age). Do not use.
  [Repo](https://github.com/m3ntorship/action-dockerhub-cleanup).

### Quay.io candidates

- **Quay native auto-prune (recommended for Quay, not an Action)** — Quay supports
  organization- and repository-level auto-pruning policies that prune **by creation date (age)
  or by number of tags**, and **support regex tag matching** to target a subset of tags.
  Configurable via the Quay v2 UI or the Quay API, so it works on quay.io (SaaS) without any
  GitHub Action. This is the strongest "don't build it" signal for Quay specifically.
  [Red Hat Quay auto-pruning docs](https://docs.redhat.com/en/documentation/red_hat_quay/3/html/manage_red_hat_quay/red-hat-quay-namespace-auto-pruning-overview) ·
  [DeepWiki: quay auto-pruning](https://deepwiki.com/quay/quay/5.2-auto-pruning).

- **`cilium/scruffy`** — Quay-only GC tool (Go, run as `docker://quay.io/cilium/scruffy` in a
  workflow). Its policy is specialized: **keep tags that match a commit SHA of configured
  `--stable-branches`, delete the rest**. No general regex and **no age filter**. Auth = Quay
  OAuth token (`QUAY_TOKEN`). 1 star, last push 2023-06-12.
  [Repo/README](https://github.com/cilium/scruffy).

- **`parametalol/fetch-quay-tags`** — **not a packaged action** (no `action.yml`; just three
  shell scripts). Fetches Quay tags, filters by date (`older-than.sh "2 months ago"`), deletes
  via Quay API bearer token. Tag-name filtering would be manual (`grep`/`xargs`). Age: yes.
  Regex: not built in. 0 stars, last push 2022-05-09, no license.
  [Repo/README](https://github.com/parametalol/fetch-quay-tags).

### Generic primitive (build-your-own path)

- **`regclient` / `regctl`** — actively maintained Go OCI registry client/CLI. `regctl tag rm`
  **deletes a tag without deleting the shared manifest** (uses the OCI tag-delete API, or a
  dummy-manifest trick when the registry lacks it) — avoids the "deletes by digest, nukes
  co-tagged tags" footgun. No built-in age/regex *policy*; you script `regctl tag ls` +
  filtering yourself. Good building block if we roll our own multi-registry pruner.
  [Repo](https://github.com/regclient/regclient) ·
  [regctl tag delete docs](https://regclient.org/cli/regctl/tag/delete/).

## Capability matrix

| Action | Registries | Tag-name filter | Age filter | Combined regex×age | Deletes (API) | Auth | Last push / stars / open issues |
|---|---|---|---|---|---|---|---|
| lostlink/docker-cleanup | Docker Hub only | **regex** (per-pattern) | **yes** (retention-days) | **YES** | tag delete; digest fallback | user + pass/PAT | 2025-08-12 / 1 / 6 |
| maxisam/dockerhub-cleanup | Docker Hub only | prefix only | yes (retention-days) | no (prefix, not regex) | Docker Hub v2 | user + PAT | 2025-02-07 / 2 / 0 |
| joshbeard/docker-hub-tag-delete | Docker Hub only | glob (fnmatch) | explicit date, not "N days" | partial | Docker Hub v2 | user + pass/token | 2024-06-07 / 2 / 0 |
| alesharik/delete-old-docker-tags | generic v2 registry | semver regex (selector) | **no** (keep-last count) | no | manifest by digest | user + pass | 2023-10-02 / 1 / 8 |
| m3ntorship/action-dockerhub-cleanup | Docker Hub | substrings (claimed) | no | no | — | — | 2021-08-08 / 2 / 0 (dead) |
| cilium/scruffy | Quay only | commit-SHA match only | no | no | Quay API | Quay OAuth token | 2023-06-12 / 1 / 0 |
| parametalol/fetch-quay-tags | Quay only | manual grep | yes (date) | no (not packaged) | Quay API bearer | bearer token | 2022-05-09 / 0 / 0 |
| Quay native auto-prune | Quay.io (SaaS) | **regex** | **yes** (age or count) | **YES** (not a GH Action) | Quay engine | Quay creds / API | n/a (platform feature) |
| regclient/regctl | any OCI/v2 | DIY | DIY | DIY (script it) | OCI tag delete (safe) | per-registry | active / high |

## Sources

- Kept: lostlink/docker-cleanup (github.com/lostlink/docker-cleanup) — only Docker Hub action doing regex×age; verified in source.
- Kept: maxisam/dockerhub-cleanup (github.com/maxisam/dockerhub-cleanup) — age + prefix action, action.yml confirmed.
- Kept: joshbeard/docker-hub-tag-delete — glob + explicit-date, verified-partner marketplace entry.
- Kept: alesharik/delete-old-docker-tags — generic-registry but count/semver (no age); clarifies "generic multi-registry" claims.
- Kept: Quay auto-pruning docs + DeepWiki — native regex×age; reframes the Quay side of the question.
- Kept: cilium/scruffy, parametalol/fetch-quay-tags — the only Quay-targeting OSS tools; show neither fits.
- Kept: regclient/regctl — build-your-own primitive with safe tag-only deletion.
- Dropped: Azure ACR `acr purge` / karlsgate/acr-cli-purge — ACR-only, not Docker Hub/Quay.
- Dropped: DigitalOcean registry tag cleanup — DOCR-only.
- Dropped: tweedegolf/cleanup-images-action, GHCR gists, Docker metadata-action — GHCR/tagging, not Hub/Quay pruning.
- Dropped: m3ntorship/action-dockerhub-cleanup — abandoned, empty README.

## Details

- **"Deletes by digest vs by tag" is the main footgun.** Docker Hub's `v2` tag API can delete
  an individual tag, but several tools (alesharik, and lostlink's registry fallback) delete the
  *manifest by digest*, which removes every tag pointing at that manifest. If we need
  tag-precise deletion where tags share manifests, prefer tag-delete APIs or `regctl tag rm`.
- **"Age" is ambiguous across tools.** lostlink/maxisam use relative `retention-days` against
  Docker Hub's `last_updated`. joshbeard uses absolute calendar dates per tag group. alesharik
  ignores age entirely (count/semver). Quay tools use `last_modified`/`start_ts`.
- **Docker Hub auth** is consistently username + password/PAT against `hub.docker.com/v2`
  (this is the Hub web API, distinct from the registry `registry-1.docker.io` pull/push API).
- **Quay auth** is an OAuth/bot token (`QUAY_TOKEN` bearer) against the Quay API.

## Open questions / recommendation

- **If the requirement is literally one off-the-shelf Action for both Docker Hub and Quay with
  regex×age: it does not exist.** Decide between (a) two different mechanisms — a Docker Hub
  action (lostlink if we accept the maturity risk, else maxisam for age+prefix) plus Quay's
  native auto-prune — or (b) build one small tool (e.g. around `regclient/regctl` or raw Hub/Quay
  APIs) that applies uniform `regex × last-pushed-age` policy to both.
- Confirm whether our Quay usage is quay.io SaaS (native auto-prune applies, likely removing the
  need to build anything on the Quay side) or a self-hosted Quay (same feature, config-gated).
- If we build our own, confirm we need **tag-precise** deletion (shared-manifest safety) — this
  rules out the digest-deleting actions and argues for `regctl tag rm` or the Hub tag API.
