# Operator guide — `checkout_command` (Windows / org clones)

Use this when the default checkout (`gh repo clone` + detached worktree under `reviews/.../commits/<sha>/checkout`) hits **Filename too long** on Windows (see [retro.md](retro.md) § Windows checkout path length). DOTNETIOT-2550 smoke (Zuul#156) expects this path.

## Contract

When `checkout_command` is set in `.review-ticket.yaml`, `ensure_checkout` runs your template **instead of** the built-in clone/worktree flow. After your command exits successfully, review-ticket runs `git rev-parse HEAD` in `{dest}` and raises `ToolError` unless the result equals `{sha}`.

### Placeholders

| Token | Value |
| --- | --- |
| `{owner}` | GitHub owner (e.g. `kwik-trip-iot`) |
| `{repo}` | Repository name (e.g. `KT.IoT.Zuul`) |
| `{sha}` | Reviewed commit (40-char) |
| `{dest}` | Artifact checkout directory for this SHA |
| `{repository}` | `owner/repo` |

If the template contains **no** `{token}` substrings, review-ticket appends `{repository}`, `{sha}`, and `{dest}` as extra argv words (legacy behavior).

Your script must leave `{dest}` as a **git** working tree whose `HEAD` is `{sha}`. Common patterns:

1. **Short worktree + junction** — Add a detached worktree under `C:\repos\<org>\_review-wt\{sha}` (short MAX_PATH), then create a directory junction from `{dest}` to that worktree so verification still runs in `{dest}`.
2. **Fetch/checkout in org clone** — `git fetch origin <sha>` and `git worktree add --detach` into a short path, then junction `{dest}` → that path.

Do not rely on editing Python in review-pilot; configuration only.

## Kwik-trip-iot triple (DOTNETIOT-2550)

Map each tracked repository to an existing clone under `C:\repos\kwik-trip-iot\`:

| `repository` | Typical local clone | Example PR |
| --- | --- | --- |
| `kwik-trip-iot/KT.IoT.Zuul` | `C:\repos\kwik-trip-iot\KT.IoT.Zuul` | #156 |
| `kwik-trip-iot/KT.IoT` | `C:\repos\kwik-trip-iot\KT.IoT` | #144 |
| `kwik-trip-iot/KT.IoT.UI.Admin` | `C:\repos\kwik-trip-iot\KT.IoT.UI.Admin` | #354 |

Use `pr select` between PRs; checkout runs per active PR SHA.

## Sample `.review-ticket.yaml` block

Replace `<CHECKOUT_SCRIPT>` with your checked-in PowerShell (or cmd) helper. Paths below are **placeholders** — adjust to your machine.

```yaml
github_org: kwik-trip-iot

# checkout_command: >
#   powershell -NoProfile -ExecutionPolicy Bypass
#   -File C:\repos\burtlo\review-pilot\scripts\<CHECKOUT_SCRIPT>.ps1
#   {owner} {repo} {sha} {dest}
```

### Illustrative PowerShell sketch (not shipped)

Logic only — save as your own script and wire the path above:

```powershell
# Args: Owner, Repo, Sha, Dest
param($Owner, $Repo, $Sha, $Dest)
$cloneRoot = "C:\repos\kwik-trip-iot"
$clone = Join-Path $cloneRoot $Repo
$shortWt = Join-Path $cloneRoot ("_review-wt\" + $Sha.Substring(0, 12))
if (-not (Test-Path $shortWt)) {
  git -C $clone fetch origin $Sha
  git -C $clone worktree add --detach $shortWt $Sha
}
if (Test-Path $Dest) { Remove-Item -Force -Recurse $Dest }
New-Item -ItemType Junction -Path $Dest -Target $shortWt | Out-Null
```

## Verification

- **Automated:** `pytest tests/test_checkout.py -k checkout_command`
- **Manual:** On Windows, `review-ticket DOTNETIOT-2550 run-review` with active Zuul#156 and org `checkout_command`; confirm checkout/diff complete without worktree errors under a deep `reviews\...\checkout` path used only as junction target or omitted via short worktree.

## Related

- [spec.md](spec.md) — D2, AC1, AC2
- [implementation.md](implementation.md) — package P2
- [README.md](../../../README.md) — configuration summary
