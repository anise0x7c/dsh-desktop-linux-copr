# dsh-desktop-linux-copr

Fedora packages for [DeepSeek Harness Desktop](https://github.com/ffyfox/dsh-desktop-linux),
built in COPR from the prebuilt RPMs the upstream project publishes.

This repository is **a repack, not a source build**. The upstream project builds
an Electron application with bundled Node.js and Python runtimes and ships
unsigned RPMs for `x86_64` and `aarch64`. This repository verifies those RPMs,
installs Fedora-appropriate metadata around them, and produces one source RPM
that builds on Fedora 44 and 45 for both architectures.

* COPR project: `anise0x7c/DeepSeekHarnessDesktop`
* Package name: `deepseek-harness` (same as upstream)
* COPR build method: SCM Git + `make_srpm`

## Layout

| Path | Purpose |
| --- | --- |
| `packaging/release.json` | Single source of truth: upstream tag/commit, version, release, per-architecture asset checksums, license expression, runtime dependencies |
| `packaging/deepseek-harness.spec.tmpl` | Spec template; version-specific values are substituted |
| `deepseek-harness.spec` | Generated spec, committed so COPR and reviewers see exactly what is built |
| `.copr/Makefile` | `srpm` target invoked by COPR's `make_srpm` |
| `scripts/make-spec.py` | Regenerate or verify the spec from the manifest |
| `scripts/make-srpm.py` | Download, verify and pack both upstream RPMs into one SRPM |
| `scripts/update-release.py` | Discover a newer upstream release and refresh the manifest/spec |
| `scripts/check-rpmlint.py` | Fail on rpmlint findings not listed in `packaging/rpmlint-exceptions.txt` |
| `.github/workflows/` | Upstream update PRs and the four-target packaging CI |
| `docs/deployment.md` | Step-by-step COPR and webhook setup |

Never edit `deepseek-harness.spec` by hand: change the manifest (or the template)
and run `python3 scripts/make-spec.py`. CI rejects a stale spec.

## Local workflow

```console
$ python3 -m unittest discover -s tests -v     # unit tests
$ python3 scripts/make-spec.py --check         # spec matches the manifest
$ python3 scripts/make-srpm.py                 # download + verify + build SRPM
$ python3 scripts/update-release.py --check    # is there a newer upstream release?
```

`make-srpm.py` caches the downloaded RPMs in `.work/cache/` and re-verifies their
size and SHA-256 every run. It refuses to build when the RPM header does not
match the manifest, or when a published asset no longer matches the recorded
checksum.

To shake out the spec without COPR, rebuild the SRPM locally:

```console
$ rpmbuild --rebuild \
    --define "_topdir $PWD/.work/rebuild" \
    --define "_tmppath $PWD/.work/rebuild/tmp" \
    dist/*.src.rpm
```

The resulting binary RPM must be byte-identical in payload to the upstream
archive; the spec re-checks this during `%install`.

## Packaging decisions

* The application stays in `/opt/DeepSeek Harness` (note the space), so an
  upgrade from the upstream package keeps working and the private Node.js and
  Python runtimes remain self-contained.
* `/usr/bin/deepseek-harness` is a symlink owned by this package. Upstream's
  `%postun` removes that path unconditionally, which would break upgrades, so
  the package repairs it in `%posttrans`.
* `chrome-sandbox` is installed `0755` without setuid. The application uses
  unprivileged user namespaces; the spec never injects `--no-sandbox`.
* Automatic dependency generation is disabled (`AutoReqProv: no`) and the
  runtime dependencies are listed explicitly, so bundled private sonames never
  leak into the distribution's dependency graph.
* `__os_install_post` and `__arch_install_post` are disabled: the payload must
  not be stripped, byte-compiled, given new build-ids or hardlinked.
* `/usr/lib/.build-id` links from the upstream archives are not installed; the
  package owns nothing outside its own tree except the desktop entry, icon and
  launcher symlink.
* The license expression is an aggregate of the audited payload (Electron,
  Chromium, bundled npm and Python packages, fonts), not just the MIT license in
  the upstream RPM header. See `packaging/release.json` → `audit`.

## Updating

A scheduled GitHub Actions workflow checks upstream daily and opens (or updates)
one pull request against `main`. The tool follows annotated tags to commits,
accepts alpha/beta/rc releases, compares RPM versions with RPM's own ordering,
and requires both architectures, a GitHub-reported SHA-256 digest, matching RPM
headers and a numeric release. Anything it does not understand fails the run
instead of guessing.

Merging the PR triggers COPR through its native GitHub webhook.

## Limitations

* The upstream RPMs are unsigned; this repository verifies them by SHA-256 from
  the GitHub release API, not by a signature.
* The aarch64 package is built and smoke-tested in CI, but the GUI has not been
  exercised on aarch64 hardware here.
* This is a COPR/WIP package, not part of Fedora. The license expression is an
  honest aggregate, not a legal review.
