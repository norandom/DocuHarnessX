"""Unit tests for the project-configurable vocabulary (task 2.2).

Covers the ``Vocabulary`` value object, ``load_vocabulary``, ``default_profile``,
``default_profile_config``, and ``vocabulary_to_config`` from
``docuharnessx/ontology/vocabulary.py`` (Req 1.1-1.9, 2.1-2.3, 2.5, 2.6, 11.4).
"""

from __future__ import annotations

import textwrap

import pytest

from docuharnessx.ontology.errors import MalformedConfigError
from docuharnessx.ontology.model import AxisTerm
from docuharnessx.ontology.vocabulary import (
    Vocabulary,
    default_profile,
    default_profile_config,
    load_vocabulary,
    vocabulary_to_config,
)

# Expected default-profile members (Req 2.1, 2.2, 1.4).
DEFAULT_ROLE_IDS = (
    "possible-adopter",
    "developer",
    "tech-savvy-user",
    "manager",
    "devops-admin",
    "researcher",
    "security-compliance-officer",
    "contributor",
    "integrator",
    "support-sre",
)
DEFAULT_INTENT_IDS = (
    "install",
    "configure",
    "use",
    "troubleshoot",
    "monitor",
    "operate",
    "integrate",
    "extend",
    "evaluate",
    "assess-quality",
    "understand",
    "contribute",
    "deliver",
)
DEFAULT_PREFIXES = ("component:", "tech:", "artifact:", "topic:")


# --------------------------------------------------------------------------- #
# Default profile contents (Req 1.4, 2.1, 2.2, 2.3)                            #
# --------------------------------------------------------------------------- #


def test_default_profile_has_exactly_ten_roles_in_order():
    vocab = default_profile()
    assert tuple(r.id for r in vocab.roles) == DEFAULT_ROLE_IDS
    assert len(vocab.roles) == 10


def test_default_profile_has_exactly_thirteen_intents_in_order():
    vocab = default_profile()
    assert tuple(i.id for i in vocab.intents) == DEFAULT_INTENT_IDS
    assert len(vocab.intents) == 13


def test_default_profile_has_four_prefixes_in_stable_order():
    vocab = default_profile()
    assert tuple(vocab.subject_prefixes) == DEFAULT_PREFIXES


def test_default_profile_roles_have_labels_and_descriptions():
    vocab = default_profile()
    by_id = {r.id: r for r in vocab.roles}
    assert by_id["developer"].label == "Developer"
    assert by_id["possible-adopter"].label == "Possible Adopter"
    # every role carries a non-empty label
    assert all(r.label for r in vocab.roles)


def test_default_profile_is_deterministic():
    assert default_profile() == default_profile()


# --------------------------------------------------------------------------- #
# Vocabulary accessors (Req 2.3, 2.5, 2.6)                                     #
# --------------------------------------------------------------------------- #


def test_has_role_and_has_intent_membership():
    vocab = default_profile()
    assert vocab.has_role("developer") is True
    assert vocab.has_role("not-a-role") is False
    assert vocab.has_intent("install") is True
    assert vocab.has_intent("not-an-intent") is False


def test_intent_order_is_canonical_default_order():
    vocab = default_profile()
    assert vocab.intent_order() == DEFAULT_INTENT_IDS


def test_subject_prefixes_returns_written_colon_form():
    vocab = default_profile()
    assert "component:" in vocab.subject_prefixes
    assert "component" not in vocab.subject_prefixes


def test_vocabulary_equality_is_meaningful():
    a = Vocabulary(
        roles=(AxisTerm("developer", "Developer"),),
        intents=(AxisTerm("use", "Use"),),
        subject_prefixes=("component:",),
    )
    b = Vocabulary(
        roles=(AxisTerm("developer", "Developer"),),
        intents=(AxisTerm("use", "Use"),),
        subject_prefixes=("component:",),
    )
    c = Vocabulary(
        roles=(AxisTerm("manager", "Manager"),),
        intents=(AxisTerm("use", "Use"),),
        subject_prefixes=("component:",),
    )
    assert a == b
    assert a != c


# --------------------------------------------------------------------------- #
# default_profile_config seed (Req 1.4, 1.9)                                   #
# --------------------------------------------------------------------------- #


def test_default_profile_config_is_serializable_seed_dict():
    cfg = default_profile_config()
    assert isinstance(cfg, dict)
    assert [r["id"] for r in cfg["roles"]] == list(DEFAULT_ROLE_IDS)
    assert [i["id"] for i in cfg["intents"]] == list(DEFAULT_INTENT_IDS)
    assert cfg["subjects"] == list(DEFAULT_PREFIXES)
    # each role/intent entry carries id/label/description
    for entry in cfg["roles"] + cfg["intents"]:
        assert set(entry) >= {"id", "label", "description"}


def test_default_profile_config_loads_back_to_default_profile():
    assert load_vocabulary(default_profile_config()) == default_profile()


# --------------------------------------------------------------------------- #
# load_vocabulary from a config file (Req 1.1, 1.2, 1.7)                       #
# --------------------------------------------------------------------------- #


def _write(tmp_path, text):
    cfg = tmp_path / "ontology.yaml"
    cfg.write_text(textwrap.dedent(text), encoding="utf-8")
    return cfg


def test_config_file_yields_its_configured_vocabulary(tmp_path):
    cfg = _write(
        tmp_path,
        """
        roles:
          - id: pilot
            label: Pilot
            description: Flies
        intents:
          - id: fly
            label: Fly
            description: ""
        subjects:
          - "aircraft:"
          - "route:"
        """,
    )
    vocab = load_vocabulary(cfg)
    assert tuple(r.id for r in vocab.roles) == ("pilot",)
    assert tuple(i.id for i in vocab.intents) == ("fly",)
    assert tuple(vocab.subject_prefixes) == ("aircraft:", "route:")
    assert vocab.has_role("pilot")
    assert not vocab.has_role("developer")


def test_identical_config_yields_identical_vocabulary(tmp_path):
    body = """
    roles:
      - id: pilot
        label: Pilot
    intents:
      - id: fly
        label: Fly
    subjects:
      - "aircraft:"
    """
    cfg1 = _write(tmp_path, body)
    sub = tmp_path / "sub"
    sub.mkdir()
    cfg2 = sub / "ontology.yaml"
    cfg2.write_text(textwrap.dedent(body), encoding="utf-8")
    assert load_vocabulary(cfg1) == load_vocabulary(cfg2)


# --------------------------------------------------------------------------- #
# Missing-file fallback (Req 1.3)                                             #
# --------------------------------------------------------------------------- #


def test_missing_file_yields_default_profile(tmp_path):
    missing = tmp_path / "does-not-exist.yaml"
    assert load_vocabulary(missing) == default_profile()


# --------------------------------------------------------------------------- #
# Profile resolution: base then overrides (Req 1.5)                           #
# --------------------------------------------------------------------------- #


def test_profile_reference_resolves_base_then_overrides(tmp_path):
    cfg = _write(
        tmp_path,
        """
        profile: default
        roles:
          - id: developer
            label: Software Engineer
            description: Overridden label
          - id: pilot
            label: Pilot
        """,
    )
    vocab = load_vocabulary(cfg)
    by_id = {r.id: r for r in vocab.roles}
    # base default roles still present
    assert "manager" in by_id
    # overridden role keeps id, takes new label
    assert by_id["developer"].label == "Software Engineer"
    # added role is appended
    assert "pilot" in by_id
    # intents inherited from the base profile (not overridden)
    assert vocab.intent_order() == DEFAULT_INTENT_IDS
    # prefixes inherited from base profile
    assert tuple(vocab.subject_prefixes) == DEFAULT_PREFIXES


def test_profile_reference_overrides_are_deterministic(tmp_path):
    body = """
    profile: default
    intents:
      - id: install
        label: Set Up
    """
    cfg = _write(tmp_path, body)
    v1 = load_vocabulary(cfg)
    v2 = load_vocabulary(cfg)
    assert v1 == v2
    by_id = {i.id: i for i in v1.intents}
    assert by_id["install"].label == "Set Up"
    # order preserved (override does not reorder)
    assert v1.intent_order() == DEFAULT_INTENT_IDS


# --------------------------------------------------------------------------- #
# Malformed / missing-key config (Req 1.6)                                    #
# --------------------------------------------------------------------------- #


def test_unparseable_yaml_raises_malformed_config(tmp_path):
    cfg = tmp_path / "ontology.yaml"
    cfg.write_text("roles: [unterminated\n", encoding="utf-8")
    with pytest.raises(MalformedConfigError) as exc:
        load_vocabulary(cfg)
    assert str(cfg) in str(exc.value)


def test_missing_required_key_raises_malformed_config(tmp_path):
    # No profile and missing 'intents' / 'subjects' keys -> invalid.
    cfg = _write(
        tmp_path,
        """
        roles:
          - id: pilot
            label: Pilot
        """,
    )
    with pytest.raises(MalformedConfigError):
        load_vocabulary(cfg)


def test_role_entry_missing_id_raises_malformed_config(tmp_path):
    cfg = _write(
        tmp_path,
        """
        roles:
          - label: No Id Here
        intents:
          - id: fly
            label: Fly
        subjects:
          - aircraft:
        """,
    )
    with pytest.raises(MalformedConfigError):
        load_vocabulary(cfg)


def test_non_mapping_config_raises_malformed_config(tmp_path):
    cfg = tmp_path / "ontology.yaml"
    cfg.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(MalformedConfigError):
        load_vocabulary(cfg)


# --------------------------------------------------------------------------- #
# Round-trip vocabulary_to_config <-> load_vocabulary (Req 1.9)               #
# --------------------------------------------------------------------------- #


def test_vocabulary_to_config_matches_schema():
    cfg = vocabulary_to_config(default_profile())
    assert set(cfg) >= {"roles", "intents", "subjects"}
    assert [r["id"] for r in cfg["roles"]] == list(DEFAULT_ROLE_IDS)
    assert cfg["subjects"] == list(DEFAULT_PREFIXES)


def test_vocabulary_to_config_is_deterministic():
    assert vocabulary_to_config(default_profile()) == vocabulary_to_config(
        default_profile()
    )


def test_roundtrip_default_profile():
    v = default_profile()
    assert load_vocabulary(vocabulary_to_config(v)) == v


def test_roundtrip_custom_vocabulary():
    v = Vocabulary(
        roles=(
            AxisTerm("pilot", "Pilot", "Flies the plane"),
            AxisTerm("nav", "Navigator"),
        ),
        intents=(
            AxisTerm("fly", "Fly"),
            AxisTerm("land", "Land", "Touch down"),
        ),
        subject_prefixes=("aircraft:", "route:"),
    )
    assert load_vocabulary(vocabulary_to_config(v)) == v


def test_roundtrip_via_yaml_file(tmp_path):
    import yaml

    v = Vocabulary(
        roles=(AxisTerm("pilot", "Pilot"),),
        intents=(AxisTerm("fly", "Fly"),),
        subject_prefixes=("aircraft:",),
    )
    cfg = tmp_path / "ontology.yaml"
    cfg.write_text(yaml.safe_dump(vocabulary_to_config(v)), encoding="utf-8")
    assert load_vocabulary(cfg) == v
