# syntax=docker/dockerfile:1.7
# Touchstone sandbox image (ADR-002).
#
# This is the *guest* image the verification engine launches under gVisor/
# Firecracker to execute untrusted verifier code. It is deliberately minimal: a
# Python interpreter and nothing else — no package managers, no shells beyond the
# base, no application code. The job (verifier code + artifact) and the harness
# are bind-mounted read-only at /job at run time, and the container is started
# with --network=none, a read-only root fs, all capabilities dropped, and an
# unprivileged user (see OciSandbox.build_command).
FROM python:3.12-slim

# Drop setuid/setgid bits to shrink the privilege-escalation surface; the guest
# runs as an unprivileged user and never needs them.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null || true

# A baked copy of the harness so the image is runnable even without the mount;
# the engine normally mounts the current harness at /job/_harness.py.
COPY services/verification-engine/src/touchstone_verify/sandbox/_harness.py /opt/harness/_harness.py

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 65534:65534
ENTRYPOINT ["python", "-I"]
CMD ["/opt/harness/_harness.py"]
