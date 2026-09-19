"""What the assistant is told before it writes a host script.

The brief is the whole difference between a model that writes something which
runs on this machine and one that writes something plausible. It is also the
only place a value could accidentally leave — so both halves are worth pinning:
that the facts which make the answer correct are present, and that nothing but
names ever is.

Pure by construction: `_render_script` takes a brief and returns a string, so
none of this needs a database, a node or a provider.
"""

from cubicle.runtime.assistant import ScriptBrief, _render_script

SCRIPT = {
    "name": "nightly-backup",
    "description": "",
    "interpreter": "python3",
    "method": "POST",
    "path": "/run/nightly-backup",
    "working_dir": "/srv/app",
    "timeout_seconds": 300,
    "output_mode": "auto",
    "auth_required": True,
}

HOST = {
    "os": "Ubuntu 24.04.1 LTS",
    "kernel": "Linux 6.8.0-45-generic",
    "arch": "x86_64",
    "shell": "/usr/bin/dash",
    "python": "Python 3.12.3",
    "commands": "python3 bash docker git curl jq",
}


def brief(**overrides) -> ScriptBrief:
    data = {"script": {**SCRIPT, **overrides.pop("script", {})}}
    data.update(overrides)
    return ScriptBrief(**data)


# ── the script's own shape ───────────────────────────────────────────────────


def test_the_brief_names_what_the_script_is_configured_as():
    text = _render_script(brief(), None)
    assert "POST /run/nightly-backup" in text
    assert "written for: python3" in text
    assert "/srv/app" in text
    assert "killed after: 300s" in text


def test_the_shebang_interpreter_tells_the_model_to_write_the_line():
    text = _render_script(brief(script={"interpreter": "shebang"}), None)
    assert "#!" in text
    # Never the bare token — "written for: shebang" would read as an
    # interpreter called shebang.
    assert "written for: shebang" not in text


def test_json_mode_is_stated_as_a_requirement():
    text = _render_script(brief(script={"output_mode": "json"}), None)
    assert "MUST be valid JSON" in text


def test_text_mode_says_stdout_is_never_parsed():
    text = _render_script(brief(script={"output_mode": "text"}), None)
    assert "never parsed" in text


def test_a_keyed_script_is_not_flagged_as_public():
    assert "reachable without a key: no" in _render_script(brief(), None)


def test_a_public_script_is_flagged_loudly():
    """The model writes different code for an endpoint anyone can call, and it
    only knows to if it is told.
    """
    text = _render_script(brief(script={"auth_required": False}), None)
    assert "YES" in text
    assert "hostile" in text


# ── the machine ──────────────────────────────────────────────────────────────


def test_the_host_facts_are_in_the_brief():
    text = _render_script(brief(host=HOST), None)
    assert "Ubuntu 24.04.1 LTS" in text
    assert "Python 3.12.3" in text
    assert "python3 bash docker git curl jq" in text


def test_the_command_list_is_stated_as_exhaustive():
    """Listing what exists is not enough on its own — a model reads a list of
    six commands as examples unless it is told the list is the whole truth.
    """
    text = _render_script(brief(host=HOST), None)
    assert "NOT installed" in text


def test_an_unprobed_host_says_so_instead_of_guessing():
    text = _render_script(brief(host={}), None)
    assert "could not be probed" in text
    assert "Assume very little" in text


def test_a_partial_probe_omits_what_it_did_not_find():
    text = _render_script(brief(host={"os": "Alpine Linux v3.20"}), None)
    assert "Alpine Linux v3.20" in text
    # No blank "node:" line for a host with no node on it.
    assert "- node:" not in text


# ── what is withheld ─────────────────────────────────────────────────────────


def test_environment_variables_appear_as_names_only():
    text = _render_script(brief(env_keys=["API_TOKEN", "BACKUP_TARGET"]), None)
    assert "API_TOKEN" in text
    assert "BACKUP_TARGET" in text
    assert "values withheld" in text


def test_a_script_with_no_environment_says_so():
    text = _render_script(brief(env_keys=[]), None)
    assert "nothing configured" in text


def test_the_brief_is_built_from_names_so_a_value_cannot_reach_it():
    """`ScriptBrief.env_keys` is a list of strings, and the router fills it from
    the keys of the decrypted mapping. There is no field on the brief a value
    could travel in, which is the property this pins.
    """
    rendered = _render_script(brief(env_keys=["API_TOKEN"], host=HOST), None)
    assert "supersecret" not in rendered
    assert set(ScriptBrief.__dataclass_fields__) == {"script", "env_keys", "host", "siblings"}


# ── the rest ─────────────────────────────────────────────────────────────────


def test_sibling_scripts_are_listed_with_their_methods():
    text = _render_script(
        brief(siblings=[{"name": "purge-cache", "method": "GET", "description": "clears it"}]),
        None,
    )
    assert "GET /run/purge-cache" in text
    assert "clears it" in text


def test_the_current_script_is_included_when_there_is_one():
    text = _render_script(brief(), "print('hello')")
    assert "CURRENT SCRIPT" in text
    assert "print('hello')" in text


def test_writing_from_scratch_sends_no_current_script():
    """`generate_script` passes None in write mode, which has to mean the file
    is absent rather than empty — a model shown an empty block will preserve it.
    """
    text = _render_script(brief(), None)
    assert "CURRENT SCRIPT" not in text
