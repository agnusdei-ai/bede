"""The local model lineup: non-Chinese by default, Qwen only when asked for.

docs/DECISIONS.md entry 43 (owner ruling 2026-11-16). The same facts live in
several files: two installer tables (packaging/unix/install.sh and
packaging/windows/Setup-Bede.ps1), the Mac helper
(packaging/bundle/record-local-ai.sh), the vLLM default in core/config.py and
docker-compose.yml, the setup wizard's hint, the Spanish probe's lineup, and
the tables in docs/UNIX_INSTALLER.md, docs/WINDOWS_INSTALLER.md,
docs/PARENT_SETUP.md, docs/PROVIDER_ADAPTERS.md and docs/DECISIONS.md. This
file checks that they agree, and it RUNS the installers' tier code rather
than reading it: the bash region under bash, the PowerShell region under
pwsh (CI sets BEDE_REQUIRE_PWSH so a missing pwsh fails instead of
skipping).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = ROOT / "packaging" / "unix" / "install.sh"
SETUP_PS1 = ROOT / "packaging" / "windows" / "Setup-Bede.ps1"
MAC_HELPER = ROOT / "packaging" / "bundle" / "record-local-ai.sh"
WIZARD = ROOT / "scripts" / "setup_wizard" / "wizard.py"
PROBE = ROOT / "homeschool-api" / "scripts" / "spanish_local_model_probe.py"
COMPOSE = ROOT / "docker-compose.yml"
API_ENV_EXAMPLE = ROOT / "homeschool-api" / ".env.example"
UNIX_DOC = ROOT / "docs" / "UNIX_INSTALLER.md"
WINDOWS_DOC = ROOT / "docs" / "WINDOWS_INSTALLER.md"
PARENT_DOC = ROOT / "docs" / "PARENT_SETUP.md"
PROVIDER_DOC = ROOT / "docs" / "PROVIDER_ADAPTERS.md"
DECISIONS_DOC = ROOT / "docs" / "DECISIONS.md"
SECURITY_DOC = ROOT / "docs" / "SECURITY.md"
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"

TIERS = ("gpu20", "gpu10", "gpu5", "gpu_small", "ram16", "ram_small")

# The Qwen tiers exactly as they were before the ruling. The Qwen option must
# keep returning these, so this is the one table here written out by hand: it
# is the old behaviour being preserved, not a copy of the new one.
QWEN_TIERS_BEFORE_THE_RULING = {
    "gpu20": "qwen3:32b",
    "gpu10": "qwen3:14b",
    "gpu5": "qwen3:8b",
    "gpu_small": "qwen3:4b",
    "ram16": "qwen3:4b",
    "ram_small": "qwen3:1.7b",
}

# How each docs table row names a tier.
DOC_ROW_TIER = {
    "≥20GB VRAM": "gpu20",
    "≥10GB VRAM": "gpu10",
    "≥5GB VRAM": "gpu5",
    "GPU present but <5GB VRAM": "gpu_small",
    "No usable GPU, ≥16GB RAM": "ram16",
    "No usable GPU, <16GB RAM": "ram_small",
}

_REGION_SH = re.compile(r"^# region local-model-tiers\n(.*?)^# endregion local-model-tiers$",
                        re.MULTILINE | re.DOTALL)
_REGION_PS = re.compile(r"^#region local-model-tiers\n(.*?)^#endregion local-model-tiers$",
                        re.MULTILINE | re.DOTALL)


def _bash_region() -> str:
    match = _REGION_SH.search(INSTALL_SH.read_text(encoding="utf-8"))
    assert match, "install.sh lost its '# region local-model-tiers' block"
    return match.group(1)


def _ps_region() -> str:
    match = _REGION_PS.search(SETUP_PS1.read_text(encoding="utf-8"))
    assert match, "Setup-Bede.ps1 lost its '#region local-model-tiers' block"
    return match.group(1)


def _bash(snippet: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", _bash_region() + "\n" + snippet],
                          capture_output=True, text=True, timeout=30)


def _bash_out(snippet: str) -> str:
    result = _bash(snippet)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _bash_table(family: str) -> dict[str, str]:
    return {t: _bash_out(f'ollama_model_for_tier {family} {t}') for t in TIERS}


def _ps_table_static(family: str) -> dict[str, str]:
    """Read $OllamaModelTiers without running PowerShell, so this half of the
    comparison runs everywhere, not only where pwsh is installed."""
    region = _ps_region()
    block = re.search(rf"^\s*{family} = @\{{\n(.*?)^\s*\}}", region, re.MULTILINE | re.DOTALL)
    assert block, f"$OllamaModelTiers has no '{family}' block"
    return dict(re.findall(r"^\s*(\w+)\s*=\s*'([^']+)'", block.group(1), re.MULTILINE))


def _doc_table(doc: Path, heading: str) -> dict[str, tuple[str, str]]:
    """{tier: (model, size)} from the first table after `heading`."""
    text = doc.read_text(encoding="utf-8")
    start = text.index(heading)
    rows: dict[str, tuple[str, str]] = {}
    for line in text[start:].splitlines()[1:]:
        if rows and not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and cells[0] in DOC_ROW_TIER:
            rows[DOC_ROW_TIER[cells[0]]] = (cells[1].strip("`"), cells[-1])
    assert set(rows) == set(TIERS), f"{doc.name}: table under {heading!r} is missing tiers"
    return rows


DEFAULT = _bash_table("default")


# ── The default lineup is non-Qwen at every tier, in both installers ─────────

def test_the_default_lineup_is_non_qwen_at_every_tier():
    for tier, model in DEFAULT.items():
        assert model and "qwen" not in model.lower(), f"default {tier} picks {model}"


def test_the_qwen_option_returns_the_tiers_from_before_the_ruling():
    assert _bash_table("qwen") == QWEN_TIERS_BEFORE_THE_RULING


def test_both_installers_hold_the_same_table():
    assert _ps_table_static("default") == DEFAULT
    assert _ps_table_static("qwen") == QWEN_TIERS_BEFORE_THE_RULING


def test_the_installers_pick_only_plain_ollama_library_tags():
    """docs/SECURITY.md says the installers can only pull plain library tags:
    no other registry, and no Ollama cloud model (which would run on Ollama's
    servers, off the computer)."""
    for family in ("default", "qwen"):
        for model in _bash_table(family).values():
            assert re.fullmatch(r"[a-z0-9][a-z0-9.\-]*:[a-z0-9.\-]+", model), model
            assert "cloud" not in model and "/" not in model, model


@pytest.mark.parametrize("vram,ram,tier", [
    ("25000", 8, "gpu20"), ("20000", 8, "gpu20"), ("19999", 64, "gpu10"),
    ("10000", 8, "gpu10"), ("9999", 8, "gpu5"), ("5000", 8, "gpu5"),
    ("4999", 64, "gpu_small"), ("2048", 8, "gpu_small"),
    ("", 16, "ram16"), ("", 64, "ram16"), ("", 15, "ram_small"), ("", 4, "ram_small"),
])
def test_hardware_tier_boundaries(vram, ram, tier):
    assert _bash_out(f'hardware_tier "{vram}" {ram}') == tier


def test_an_unknown_family_or_tier_is_refused_not_guessed():
    assert _bash("ollama_model_for_tier chinese gpu20").returncode != 0
    assert _bash("ollama_model_for_tier default gpu99").returncode != 0
    assert _bash("resolve_model_family qwen3").returncode != 0
    assert _bash_out("resolve_model_family ''") == "default"
    assert _bash_out("resolve_model_family qwen") == "qwen"


def test_install_sh_refuses_an_unknown_family_before_doing_anything(tmp_path):
    """The option is parsed before Docker, git or Ollama is touched, so a typo
    stops the installer instead of installing the wrong lineup. HOME is a
    throwaway folder so a regression could not touch the real one."""
    env = {**os.environ, "HOME": str(tmp_path)}
    for args, extra in ((["--model-family", "qwen3"], {}), (["--bogus"], {}),
                        ([], {"BEDE_MODEL_FAMILY": "chinese"})):
        result = subprocess.run(["bash", str(INSTALL_SH), *args], env={**env, **extra},
                                capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        assert result.returncode != 0, (args, extra)
        assert "==>" not in result.stdout, "the installer started a step before refusing"
    assert not any(tmp_path.iterdir())


# ── An existing installation keeps its model ─────────────────────────────────

def test_an_existing_configured_and_installed_model_is_kept(tmp_path):
    env = tmp_path / ".env"
    env.write_text("PARENT_PASSWORD=x\nLOCAL_LLM_MODEL=qwen3:8b\n")
    configured = _bash_out(f'configured_local_model "{env}"')
    assert configured == "qwen3:8b"
    installed = "granite3.3:8b\nqwen3:8b"
    assert _bash_out(f'model_to_keep "{configured}" "{installed}"') == "qwen3:8b"


@pytest.mark.parametrize("env_text,installed", [
    ("LOCAL_LLM_MODEL=qwen3:8b\n", "granite3.3:8b"),       # gone from Ollama: pick again
    ("OTHER=1\n", "qwen3:8b"),                             # never configured
    ("LOCAL_LLM_MODEL=bad name;rm\n", "bad name;rm"),      # not a plain model name
])
def test_nothing_is_kept_that_is_not_both_configured_and_installed(tmp_path, env_text, installed):
    env = tmp_path / ".env"
    env.write_text(env_text)
    configured = _bash_out(f'configured_local_model "{env}"')
    assert _bash_out(f'model_to_keep "{configured}" "{installed}"') == ""


def test_setup_local_ai_keeps_a_model_only_when_no_family_was_asked_for():
    """Invocation guard: the keep logic is useless unless setup_local_ai calls
    it, and only on the no-explicit-family path, before any pull."""
    body = INSTALL_SH.read_text(encoding="utf-8")
    fn = body[body.index("setup_local_ai() {"):]
    fn = fn[:fn.index("\n}\n")]
    keep = fn.index('model_to_keep "$(configured_local_model "$APP_DIR/.env")"')
    assert fn.index('if [ -z "$MODEL_FAMILY_REQUESTED" ]') < keep < fn.index('ollama pull "$model"')
    ps = SETUP_PS1.read_text(encoding="utf-8")
    ps_fn = ps[ps.index("function Set-LocalAI {"):]
    ps_keep = ps_fn.index("Select-ModelToKeep -Configured (Get-ConfiguredLocalModel")
    assert ps_fn.index("if (-not $ModelFamilyRequested)") < ps_keep < ps_fn.index("& ollama pull $model")


def test_recommended_model_uses_the_resolved_family():
    body = INSTALL_SH.read_text(encoding="utf-8")
    fn = body[body.index("recommended_ollama_model() {"):]
    fn = fn[:fn.index("\n}\n")]
    assert 'ollama_model_for_tier "$MODEL_FAMILY" "$(hardware_tier "$vram_mb" "$ram_gb")"' in fn
    ps = SETUP_PS1.read_text(encoding="utf-8")
    ps_fn = ps[ps.index("function Get-RecommendedOllamaModel {"):]
    ps_fn = ps_fn[:ps_fn.index("\n}\n")]
    assert "Get-OllamaModelForTier -Family $ResolvedModelFamily -Tier (Get-HardwareTier" in ps_fn


# ── The PowerShell region, run for real ──────────────────────────────────────

_PWSH = shutil.which("pwsh")


@pytest.fixture
def pwsh():
    if _PWSH is None:
        if os.environ.get("BEDE_REQUIRE_PWSH") == "1":
            pytest.fail("BEDE_REQUIRE_PWSH=1 but pwsh is not installed")
        pytest.skip("pwsh not installed (CI sets BEDE_REQUIRE_PWSH=1 and runs this)")
    return _PWSH


def _ps_json(pwsh: str, body: str):
    script = _ps_region() + "\n" + body
    result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_powershell_tiers_and_tables_match_bash(pwsh):
    cases = [(v or 0, r, t) for v, r, t in [
        (25000, 8, "gpu20"), (19999, 64, "gpu10"), (9999, 8, "gpu5"), (4999, 64, "gpu_small"),
        (0, 16, "ram16"), (0, 15, "ram_small")]]
    calls = "; ".join(f"Get-HardwareTier -VramMB {v} -RamGB {r}" for v, r, _ in cases)
    got = _ps_json(pwsh, f"@({calls}) | ConvertTo-Json -Compress")
    assert got == [t for _, _, t in cases]
    for family, expected in (("default", DEFAULT), ("qwen", QWEN_TIERS_BEFORE_THE_RULING)):
        calls = "; ".join(f"Get-OllamaModelForTier -Family {family} -Tier {t}" for t in TIERS)
        got = _ps_json(pwsh, f"@({calls}) | ConvertTo-Json -Compress")
        assert dict(zip(TIERS, got)) == expected


def test_powershell_family_and_keep_logic(pwsh, tmp_path):
    env = tmp_path / ".env"
    env.write_text("LOCAL_LLM_MODEL=qwen3:8b\n")
    got = _ps_json(pwsh, f"""
        $r = [ordered]@{{}}
        $r.def = Resolve-ModelFamily ''
        $r.qwen = Resolve-ModelFamily 'qwen'
        try {{ Resolve-ModelFamily 'qwen3' | Out-Null; $r.bad = 'accepted' }} catch {{ $r.bad = 'refused' }}
        $c = Get-ConfiguredLocalModel '{env}'
        $r.configured = $c
        $r.kept = Select-ModelToKeep -Configured $c -Installed @('granite3.3:8b', 'qwen3:8b')
        $r.gone = Select-ModelToKeep -Configured $c -Installed @('granite3.3:8b')
        $r | ConvertTo-Json -Compress
    """)
    assert got == {"def": "default", "qwen": "qwen", "bad": "refused",
                   "configured": "qwen3:8b", "kept": "qwen3:8b", "gone": None}


def test_ci_requires_pwsh_for_the_backend_tests():
    workflow = TEST_WORKFLOW.read_text(encoding="utf-8")
    step = workflow[workflow.index("- name: Run affected backend tests and record evidence"):]
    step = step[:step.index("- name:", 10)]
    assert "BEDE_REQUIRE_PWSH: '1'" in step


# ── The Mac helper agrees with install.sh's RAM tiers ────────────────────────

def _fake_ollama(models):
    payload = json.dumps({"models": [{"name": m} for m in models]}).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.parametrize("family", ["default", "qwen"])
@pytest.mark.parametrize("ram_gib,tier", [(16, "ram16"), (8, "ram_small")])
def test_the_mac_helper_records_the_installers_model_for_this_ram(tmp_path, family, ram_gib, tier):
    table = _bash_table(family)
    other = _bash_table("qwen" if family == "default" else "default")
    server = _fake_ollama([table[tier], other[tier], "something-else:1b"])
    env = {**os.environ, "BEDE_OLLAMA_URL": f"http://127.0.0.1:{server.server_address[1]}",
           "BEDE_HOST_RAM_BYTES": str(ram_gib * 1073741824)}
    if family == "qwen":
        env["BEDE_MODEL_FAMILY"] = "qwen"
    else:
        env.pop("BEDE_MODEL_FAMILY", None)
    try:
        subprocess.run(["bash", str(MAC_HELPER), str(tmp_path)], env=env, check=True, timeout=20)
    finally:
        server.shutdown()
    marker = json.loads((tmp_path / "local-ai.json").read_text())
    assert marker["model"] == table[tier]


# ── The vLLM default in config, compose and docs ─────────────────────────────

def test_the_vllm_default_is_non_qwen_and_everywhere_the_same():
    from core import config

    assert "qwen" not in config.LOCAL_LLM_DEFAULT_MODEL.lower()
    assert config.Settings.model_fields["local_llm_model"].default == config.LOCAL_LLM_DEFAULT_MODEL
    compose = COMPOSE.read_text(encoding="utf-8")
    defaults = re.findall(r"LOCAL_LLM_MODEL=\$\{LOCAL_LLM_MODEL:-([^}]*)\}", compose)
    assert defaults and set(defaults) == {config.LOCAL_LLM_DEFAULT_MODEL}
    assert f"# LOCAL_LLM_MODEL={config.LOCAL_LLM_DEFAULT_MODEL}" in API_ENV_EXAMPLE.read_text()
    assert f"| `LOCAL_LLM_MODEL` | `{config.LOCAL_LLM_DEFAULT_MODEL}` |" in PROVIDER_DOC.read_text()


def test_the_docs_and_config_state_the_same_vllm_requirement():
    """One fact (the vLLM default needs about 55 GB of GPU memory and vLLM
    0.9.1 or later) in config and four documents."""
    from core import config

    gb = config.LOCAL_LLM_DEFAULT_GPU_MEMORY_GB
    vllm = config.LOCAL_LLM_DEFAULT_MIN_VLLM
    phrase_gb = f"about {gb} GB"
    phrase_vllm = f"vLLM {vllm} or later"
    for doc in (PROVIDER_DOC, DECISIONS_DOC):
        text = re.sub(r"\s+", " ", doc.read_text(encoding="utf-8"))
        assert phrase_gb in text and phrase_vllm in text, doc.name
        assert config.LOCAL_LLM_DEFAULT_MODEL in text, doc.name
    env_text = re.sub(r"\s+", " ", API_ENV_EXAMPLE.read_text(encoding="utf-8"))
    assert f"about {gb} GB" in env_text and f"vLLM {vllm} or later" in env_text
    # Nothing states a different figure for it.
    for doc in (PROVIDER_DOC, DECISIONS_DOC, API_ENV_EXAMPLE):
        for other in re.findall(r"about (\d+) GB of GPU memory", doc.read_text(encoding="utf-8")):
            assert int(other) == gb, (doc.name, other)


# ── The docs name the same models the scripts pick ───────────────────────────

@pytest.mark.parametrize("doc", [UNIX_DOC, WINDOWS_DOC], ids=lambda p: p.name)
def test_installer_docs_tables_match_the_scripts(doc):
    default = _doc_table(doc, "**Default lineup**")
    qwen = _doc_table(doc, "**Qwen lineup (optional)**")
    assert {t: m for t, (m, _) in default.items()} == DEFAULT
    assert {t: m for t, (m, _) in qwen.items()} == QWEN_TIERS_BEFORE_THE_RULING


def test_every_doc_gives_each_model_the_same_size():
    sizes: dict[str, set[str]] = {}
    for doc in (UNIX_DOC, WINDOWS_DOC):
        for heading in ("**Default lineup**", "**Qwen lineup (optional)**"):
            for model, size in _doc_table(doc, heading).values():
                sizes.setdefault(model, set()).add(size)
    for line in PARENT_DOC.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\| `([^`]+)`[^|]*\| (~[\d.]+GB) \|$", line)
        if m:
            sizes.setdefault(m.group(1), set()).add(m.group(2))
    for model, found in sizes.items():
        assert len(found) == 1, f"{model} is given different sizes: {found}"


def test_parent_setup_and_the_decision_name_the_default_lineup():
    parent = PARENT_DOC.read_text(encoding="utf-8")
    parent_models = set(re.findall(r"^\| `([^`]+)`", parent, re.MULTILINE))
    assert set(DEFAULT.values()) <= parent_models
    assert not any("qwen" in m for m in parent_models)
    entry = DECISIONS_DOC.read_text(encoding="utf-8")
    entry = entry[entry.index("## 43. "):]
    table = set(re.findall(r"^\| [^|]+ \| `([^`]+)` \|", entry, re.MULTILINE))
    assert table == set(DEFAULT.values())


def test_the_wizard_hint_names_a_default_model():
    text = WIZARD.read_text(encoding="utf-8")
    placeholder = re.search(r'name="local_model"[^>]*placeholder="([^"]+)"', text).group(1)
    hint = re.search(r"e\.g\. (\S+) for Ollama", text).group(1)
    assert placeholder == hint and placeholder in DEFAULT.values()


def test_the_spanish_probe_checks_the_default_lineup():
    namespace: dict = {}
    source = PROBE.read_text(encoding="utf-8")
    block = re.search(r"^DEFAULT_LINEUP = \((.*?)^\)", source, re.MULTILINE | re.DOTALL).group(0)
    exec(block, namespace)
    expected = tuple(dict.fromkeys(DEFAULT[t] for t in TIERS))
    assert namespace["DEFAULT_LINEUP"] == expected


def test_security_doc_states_what_is_enforced_and_what_is_not():
    text = SECURITY_DOC.read_text(encoding="utf-8")
    section = text[text.index("## Local model files and network"):text.index("## Known open gaps")]
    for rule in ("GGUF and safetensors only", "No China-hosted AI APIs",
                 "the model runs offline; only the download reaches the library",
                 "| Enforced | Recommended only |", "ollama pull"):
        assert rule in section, rule
