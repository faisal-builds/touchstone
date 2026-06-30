"""Customer-authored ``limits`` must not be able to weaken the sandbox (M3).

A verifier *definition* is attacker-controlled. These tests pin the security
boundary: network isolation and resource caps are server-owned and rejected,
only timeouts tune (downward, clamped), and malformed input raises a clear
``ValueError``/``VerifierError`` rather than a silent ``TypeError`` or a
silently-honored weakening. None of these run a real subprocess, so they execute
on every platform.
"""

from __future__ import annotations

import pytest

from touchstone_verify.engine.base import VerifierError
from touchstone_verify.engine.code_verifier import CodeVerifier
from touchstone_verify.engine.process_verifier import ProcessVerifier
from touchstone_verify.sandbox.runner import (
    SandboxLimits,
    sanitize_definition_limits,
)

_CODE = "def check(a):\n return {'score': 1.0}"
_STEP = "def check_step(s, i):\n return {'score': 1.0}"


# --- sanitize_definition_limits: the boundary itself ----------------------- #
def test_none_and_empty_yield_server_defaults():
    base = SandboxLimits()
    assert sanitize_definition_limits(None) == base
    assert sanitize_definition_limits({}) == base


@pytest.mark.parametrize(
    "key",
    ["isolate_network", "memory_mb", "max_processes", "max_open_files", "max_file_size_mb"],
)
def test_server_owned_fields_are_rejected(key):
    # The headline M3 exploit: a definition trying to turn off the network
    # namespace or lift a DoS cap is refused, not silently splatted.
    with pytest.raises(ValueError, match="server-owned"):
        sanitize_definition_limits({key: 0})


def test_disabling_network_isolation_is_rejected():
    with pytest.raises(ValueError, match="isolate_network"):
        sanitize_definition_limits({"isolate_network": False})


def test_unknown_key_raises_valueerror_not_typeerror():
    # A bare SandboxLimits(**raw) would raise TypeError here; we want a clear error.
    with pytest.raises(ValueError, match="unknown limit key"):
        sanitize_definition_limits({"definitely_not_a_field": 1})


def test_non_dict_rejected():
    with pytest.raises(ValueError, match="must be an object"):
        sanitize_definition_limits([1, 2, 3])


@pytest.mark.parametrize("bad", [True, False, "5", None])
def test_tunable_must_be_a_number(bad):
    if bad is None:
        pytest.skip("None means 'no override'; covered elsewhere")
    with pytest.raises(ValueError, match="must be a number"):
        sanitize_definition_limits({"cpu_seconds": bad})


def test_timeout_cannot_exceed_server_default():
    base = SandboxLimits()  # cpu_seconds=5, wall_timeout_s=10.0
    out = sanitize_definition_limits(
        {"cpu_seconds": 100000, "wall_timeout_s": 100000}
    )
    assert out.cpu_seconds == base.cpu_seconds
    assert out.wall_timeout_s == base.wall_timeout_s


def test_timeout_can_tighten_downward():
    out = sanitize_definition_limits({"cpu_seconds": 2, "wall_timeout_s": 1.5})
    assert out.cpu_seconds == 2
    assert out.wall_timeout_s == 1.5
    # Untouched fields keep server defaults.
    assert out.isolate_network is True
    assert out.memory_mb == SandboxLimits().memory_mb


def test_timeout_clamped_up_to_floor():
    out = sanitize_definition_limits({"cpu_seconds": 0, "wall_timeout_s": 0.0})
    assert out.cpu_seconds == 1
    assert out.wall_timeout_s == 0.1


def test_cpu_seconds_kept_integer():
    out = sanitize_definition_limits({"cpu_seconds": 2.9})
    assert out.cpu_seconds == 2 and isinstance(out.cpu_seconds, int)


# --- The verifier constructors validate even with a runner injected -------- #
def test_code_verifier_rejects_isolation_weakening_even_with_runner():
    # Latent-today path: a shared runner is injected, so the limits would have
    # been ignored. We reject the definition anyway — no silent acceptance.
    with pytest.raises(VerifierError, match="server-owned"):
        CodeVerifier({"code": _CODE, "limits": {"isolate_network": False}}, runner=object())


def test_process_verifier_rejects_isolation_weakening_even_with_runner():
    with pytest.raises(VerifierError, match="server-owned"):
        ProcessVerifier({"step_code": _STEP, "limits": {"max_processes": 999999}}, runner=object())


def test_code_verifier_rejects_unknown_limit_key():
    with pytest.raises(VerifierError, match="unknown limit key"):
        CodeVerifier({"code": _CODE, "limits": {"nope": 1}}, runner=object())


def test_valid_limits_build_cleanly():
    # A well-formed tuning dict builds without error (runner injected => not run).
    CodeVerifier({"code": _CODE, "limits": {"cpu_seconds": 3}}, runner=object())
    ProcessVerifier({"step_code": _STEP, "limits": {"wall_timeout_s": 2.0}}, runner=object())
