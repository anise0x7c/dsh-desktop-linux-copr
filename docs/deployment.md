# Deploying to COPR

These steps are written for the existing WIP project
`anise0x7c/DSHDesktopLinux` (project id 270178). Nothing here is done by
this repository automatically.

## 0. Prerequisites

* The repository is pushed to `https://github.com/anise0x7c/dsh-desktop-linux-copr`
  with `main` containing `deepseek-harness.spec`, `.copr/Makefile` and
  `packaging/`.
* The four chroots are enabled: `fedora-44-x86_64`, `fedora-44-aarch64`,
  `fedora-45-x86_64`, `fedora-45-aarch64`.
* The project's `enable_net` setting can stay `false`: the binary build is
  offline. Only the SRPM-creation step (`make_srpm`) needs network access to
  download the upstream assets, and COPR always allows that.

## 1. Create the `deepseek-harness` package configuration

In the COPR web UI, open the project → **Packages** → **New package**:

| Field | Value |
| --- | --- |
| Package name | `deepseek-harness` |
| Source type | Build from an SCM repository |
| SCM type | git |
| Clone URL | `https://github.com/anise0x7c/dsh-desktop-linux-copr.git` |
| Committish | `main` |
| Subdirectory | *(empty)* |
| Build SRPM with | `make_srpm` |
| Spec file | `deepseek-harness.spec` |

The existing `deepseek-harness-desktop` configuration has no builds; delete it
after the new configuration has built successfully, so the project does not
offer two package names.

COPR calls:

```console
make -f <clone>/.copr/Makefile srpm outdir="<outdir>" spec="<clone>/deepseek-harness.spec"
```

The recipe installs `rpm-build`/`python3` if needed, downloads both upstream
RPMs, verifies size, SHA-256 and RPM headers against `packaging/release.json`,
and writes one SRPM containing both architectures.

Expect the SRPM step to download roughly 470 MiB. The binary rebuild itself is
offline and takes a few minutes per chroot because the payload is ~1.1 GiB.

## 2. First build

Run a manual build for all four chroots and watch the **Build SRPM** phase first.
If it fails, the log names the exact check that rejected the release (missing
asset, changed checksum, header mismatch, stale spec).

The binary build log should end with every `%check`-style verification passing;
there is no compile step, so failures are limited to packaging mistakes.

## 3. Enable automatic rebuilds from GitHub

1. Enable **Auto-rebuild** for the `deepseek-harness` package
   (Packages → `deepseek-harness` → Edit → Auto-rebuild).
2. Open the project's **Settings → Integrations** page and copy the GitHub
   webhook URL. It has the form

   ```text
   https://copr.fedorainfracloud.org/webhooks/github/270178/<UUID>/
   ```

   `270178` is this project's id; `<UUID>` is generated per project and is
   visible only in the COPR UI. Treat it as a secret and do not commit it.
   Use the URL exactly as shown by COPR rather than reconstructing it.
3. On GitHub, repository **Settings → Webhooks → Add webhook**:
   * Payload URL: the COPR URL from the previous step
   * Content type: `application/json`
   * Secret: *(leave empty unless COPR asks for one)*
   * Events: **Just the push event** (add **Branch or tag creation** only if
     you later switch to tag-triggered builds)
4. Push a trivial commit to `main` (or use "Redeliver" on the webhook) and
   confirm COPR queues a build for `deepseek-harness`.

The update workflow only pushes to `automation/upstream-release`; the webhook
therefore only fires after a human merges the update PR into `main`.

Auto-rebuild has no path filter: every push to `main` queues a rebuild of all
enabled chroots, including documentation-only commits. The `Packaging` GitHub
Actions workflow skips those commits via `paths-ignore`, but COPR does not. If
that cost matters, batch documentation changes with real packaging changes, or
leave Auto-rebuild off and start builds by hand. If `Packaging` ever becomes a
required status check, a documentation-only pull request will not report it and
will stay pending; dispatch the workflow manually or add an always-running
companion check before enabling branch protection.

## 4. User-side verification

```console
$ sudo dnf copr enable anise0x7c/DSHDesktopLinux
$ sudo dnf install deepseek-harness
$ deepseek-harness
```

Checks worth doing once per Fedora release:

* the application starts and can open a workspace;
* `ls -l '/opt/DeepSeek Harness/chrome-sandbox'` shows mode `0755` and no `s`
  bit (the package intentionally does not ship a setuid helper);
* `/usr/bin/deepseek-harness` exists and points at
  `/opt/DeepSeek Harness/deepseek-harness`;
* `rpm -V deepseek-harness` is silent;
* upgrading from the upstream RPM (`deepseek-harness-0.2.2~rc.1-1`) keeps the
  `/usr/bin/deepseek-harness` entry: the upstream `%postun` removes it, and this
  package restores it in `%posttrans`;
* `sudo dnf remove deepseek-harness` removes both the private tree and the
  launcher.

If the application refuses to start with a Chromium sandbox error, check that
unprivileged user namespaces are available:

```console
$ sysctl kernel.unprivileged_userns_clone
```

Fedora enables them by default. This package deliberately does not work around
a hardened kernel by installing a setuid sandbox or by passing `--no-sandbox`.

## 5. Rolling back

```console
$ sudo dnf remove deepseek-harness
```

The package owns only `/opt/DeepSeek Harness`, the desktop entry, the icon and
`/usr/bin/deepseek-harness`; removing it leaves no configuration behind.

## 6. Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| `make_srpm` fails with "stale" spec diff | `deepseek-harness.spec` was edited by hand; run `scripts/make-spec.py` and commit |
| `make_srpm` fails with "published asset ... may have been replaced" | upstream re-uploaded an asset for an already packaged tag; verify manually and update the manifest deliberately |
| `make_srpm` fails with header mismatch | the release's RPM metadata disagrees with the tag-derived version; investigate upstream |
| aarch64 build fails to download | the aarch64 asset is missing from the release; the update tool would have refused it as well |
| COPR build succeeds but the package is not offered | check that the package configuration name is `deepseek-harness` and that the chroots are enabled |
