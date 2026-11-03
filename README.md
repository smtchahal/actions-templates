# actions-templates

Shared CI/CD workflows and a Claude hook for pnpm projects deployed to Cloudflare.

## Using it from a repo

One workflow file, jobs linked with `needs:`. Pin an exact release tag:

```yaml
jobs:
  ci:
    permissions:
      contents: read
    uses: smtchahal/actions-templates/.github/workflows/node-ci.yml@v2.1.0
    with:
      commands: |
        pnpm lint
        pnpm test
        pnpm build
      artifact-name: dist
      artifact-path: dist

  deploy:
    needs: ci
    permissions:
      contents: read
      pull-requests: write
    uses: smtchahal/actions-templates/.github/workflows/cloudflare-deploy.yml@v2.1.0
    with:
      project-name: my-pages-project
      artifact-name: dist
      artifact-path: dist
      preview-comment: true
    secrets:
      CLOUDFLARE_API_TOKEN: ${{ secrets.CLOUDFLARE_API_TOKEN }}
      CLOUDFLARE_ACCOUNT_ID: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
```

The shared workflows declare no `permissions` of their own: a called job that asks for more than
its caller grants fails at startup. The caller job must grant what the workflow needs (`pull-requests: read` for `gitleaks`, `pull-requests: write` for
`preview-comment`). Triggers and `concurrency` stay in the caller.

## Required check: `validate`

Every caller workflow ends with the same inline gate job, and `validate` is the only check a repo's
ruleset requires. What is mandatory is then the `needs:` list in that repo's workflow, so job names
and reusable-workflow changes never touch ruleset settings. Keep it inline: a reusable gate would
report as `<caller> / <job>` and make the check name unstable.

```yaml
  validate:
    name: validate
    needs: [ci]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - if: contains(needs.*.result, 'failure') || contains(needs.*.result, 'cancelled')
        run: exit 1
```

`if: always()` matters: a job whose dependency failed is skipped, and a skipped required check
passes. Leave `deploy` out of `needs`, since it has no secrets on Dependabot PRs.

## Supply-chain policy

Breaking in v2.0.0: the `pnpm-version` input is gone from `node-ci.yml`, `node-deploy.yml` and
`setup-node-pnpm`. The pnpm version comes only from `packageManager` in the caller's `package.json`,
and `pnpm/action-setup` is called without `version`, so it reads that field.

`node-ci.yml` enforces these inside the `ci` job, so they are already covered by `validate`'s
`needs: [ci]`. `node-deploy.yml` and `setup-node-pnpm` run the `packageManager` and
`minimumReleaseAge` checks as well, before installing:

- `packageManager` in `package.json` must be `pnpm@X.Y.Z`: an exact version, no range and no
  `latest`. It must be at least 11.1.3, the first pnpm that re-validates lockfile entries against the
  age policy on `--frozen-lockfile` installs. The install step also fails if the active pnpm differs
  from the pinned one, so that validation always happens in CI before any deploy.
- `minimum-release-age` (default 4320 minutes, 3 days): the repo's committed `pnpm-workspace.yaml`
  must set `minimumReleaseAge` to at least this. A higher value is fine, and `0` skips the check.
  The workflow no longer injects `npm_config_minimum_release_age`; the file is the only source.
- `dependabot-cooldown-days` (default 3): every entry in `.github/dependabot.yml` needs a
  `cooldown.default-days` at least this high, and a missing file fails. Add the cooldown by hand:

  ```yaml
      cooldown:
        default-days: 3
  ```

Pass `0` to `dependabot-cooldown-days` to switch that check off for one repo.

### Migrating from v1

1. Add `"packageManager": "pnpm@<exact version>"` (11.1.3 or later) to `package.json`.
2. Drop the `pnpm-version` input from the `with:` of every call.
3. Add `minimumReleaseAge: 4320` to `pnpm-workspace.yaml`.
4. Move any `pnpm.*` settings from `package.json` (`overrides`, `onlyBuiltDependencies` and so on) to
   `pnpm-workspace.yaml`, because pnpm 12 ignores them in `package.json`.

## Build-time env

`node-ci.yml`'s `env` input takes `KEY=VALUE` lines that are exported to the `commands` step after install,
for values such as `VITE_*`. A reusable-workflow call can interpolate `vars` but not `secrets` into `with:`,
so a build value that lives in a secret goes through the optional `BUILD_ENV` secret instead, same format:

```yaml
    with:
      env: |
        VITE_API_URL=${{ vars.VITE_API_URL }}
    secrets:
      BUILD_ENV: |
        VITE_CLIENT_ID=${{ secrets.VITE_CLIENT_ID }}
```

`BUILD_ENV` values are masked in the logs. Everything in `commands` can read both, so don't pass anything
the lint and test commands shouldn't see.

## Untrusted input

`commands` and `env` are executed or exported exactly as given, so callers must never interpolate
PR-controlled values such as `github.head_ref` or PR titles into them.

## Contents

| Path | What |
| --- | --- |
| `.github/workflows/node-ci.yml` | pnpm install under the pinned `packageManager`, caller-supplied commands, pnpm-version, release-age and Dependabot-cooldown policy checks, optional audit, gitleaks and artifact upload |
| `.github/workflows/cloudflare-deploy.yml` | Download the CI artifact and run `wrangler pages deploy`, optional PR preview comment |
| `.github/workflows/node-deploy.yml` | For Workers and anything else that needs installed dependencies: pnpm and release-age policy check, pnpm install, optional artifact download, then caller-supplied commands (such as `pnpm exec wrangler deploy`) with the Cloudflare secrets in the environment of that step only |
| `setup-node-pnpm/` | Composite action: policy check, pnpm (from `packageManager`), Node with cache, `pnpm install --frozen-lockfile` |
| `claude/hooks/check-branch-name.py` | `PreToolUse` hook that blocks branch names that are not flat lowercase-hyphenated or exceed 28 characters |

## Releasing

Callers pin the exact semver tag (`@v2.1.0`), never a moving `@v2`, and their Dependabot
`github-actions` entry opens a PR for each new tag. Release tags are immutable and never moved. Cut a
release per change:

```sh
git tag -a v2.1.0 -m v2.1.0 && git push origin v2.1.0
```

Bump the major for breaking input changes. Dependabot only follows tags, so every change callers
should pick up needs one.

## Claude hook

The hook is committed into each Cloudflare repo (`.claude/hooks/check-branch-name.py` plus a
`PreToolUse` entry in `.claude/settings.json`) because cloud sessions do not read `~/.claude`
or install plugins. This copy is the canonical one.
