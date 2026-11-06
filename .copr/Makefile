# COPR "Build SRPM with: make_srpm" entry point.
#
# COPR clones the repository and runs:
#   make -f <clone>/.copr/Makefile srpm outdir="<outdir>" spec="<spec_path>"
# as root inside a mock chroot that has network access, so the build
# dependencies needed to *create* the SRPM can be installed here.  Nothing in
# this recipe builds the application: the upstream RPMs are downloaded,
# checksum- and header-verified and packed into one SRPM.

REPO := $(realpath $(dir $(lastword $(MAKEFILE_LIST)))..)
PYTHON ?= python3

# COPR may pass an empty spec= when the package has no spec file configured;
# fall back to the committed spec instead of failing with an empty path.
SPEC_PATH := $(if $(spec),$(spec),$(REPO)/deepseek-harness.spec)
OUTDIR := $(if $(outdir),$(outdir),$(CURDIR))

.PHONY: srpm

srpm:
	@command -v rpmbuild >/dev/null 2>&1 || dnf -y install rpm-build
	@command -v $(PYTHON) >/dev/null 2>&1 || dnf -y install python3
	@test -r /etc/pki/tls/certs/ca-bundle.crt || test -r /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem || dnf -y install ca-certificates
	$(PYTHON) "$(REPO)/scripts/make-srpm.py" \
		--manifest "$(REPO)/packaging/release.json" \
		--spec "$(SPEC_PATH)" \
		--outdir "$(OUTDIR)"
