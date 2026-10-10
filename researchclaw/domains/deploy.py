"""Profile-driven one-click domain deployment.

A *domain profile* is a single YAML file in ``researchclaw/domains/profiles/``
(or a user override directory) that describes everything the pipeline needs
to specialize for one research domain — prompt guidance, code-generation
hints, detection keywords, and now **deployment defaults** such as
``experiment.mode``, ``export.target_conference``, Docker image, pip
packages, etc.

This module turns a profile id into:

* a filesystem path (``resolve_profile_path``)
* a list of deployable profiles for the CLI (``list_deployable_profiles``)
* a config-dict overlay merged under the user's ``config.yaml``
  (``apply_profile_defaults``)

Design rules:

1. **User always wins.** Profile values only fill keys the user left unset.
2. **Zero regression.** If the user omits ``--profile`` and leaves
   ``project.profile: ""``, nothing changes anywhere in the pipeline.
3. **Extensible.** Users drop ``~/.researchclaw/profiles/<id>.yaml`` or
   ``./profiles/<id>.yaml`` to add new domains without editing the package.
4. **Single source of truth.** The YAML schema extends the existing
   :class:`~researchclaw.domains.detector.DomainProfile` keys; no separate
   preset format.
"""

from __future__ import annotations

import copy
import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Profile discovery
# ---------------------------------------------------------------------------

_PACKAGE_PROFILES_DIR = Path(__file__).parent / "profiles"


def profile_search_dirs(extra_dirs: list[Path] | None = None) -> list[Path]:
    """Return the ordered list of directories to search for profile YAMLs.

    Precedence (first hit wins): explicit ``extra_dirs`` →
    ``./profiles/`` (project-local) → ``~/.researchclaw/profiles/``
    (user-wide) → the bundled ``researchclaw/domains/profiles/``.

    Override the user dir by setting ``RESEARCHCLAW_PROFILES_DIR`` in the
    environment.
    """
    dirs: list[Path] = []
    if extra_dirs:
        dirs.extend(Path(d).expanduser().resolve() for d in extra_dirs)

    project_local = Path.cwd() / "profiles"
    if project_local.is_dir():
        dirs.append(project_local)

    env_override = os.environ.get("RESEARCHCLAW_PROFILES_DIR", "").strip()
    if env_override:
        user_dir = Path(env_override).expanduser().resolve()
    else:
        user_dir = Path.home() / ".researchclaw" / "profiles"
    if user_dir.is_dir():
        dirs.append(user_dir)

    if _PACKAGE_PROFILES_DIR.is_dir():
        dirs.append(_PACKAGE_PROFILES_DIR)

    # De-duplicate while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


def resolve_profile_path(
    profile_id: str,
    *,
    extra_dirs: list[Path] | None = None,
) -> Path | None:
    """Return the filesystem path of ``<profile_id>.yaml`` or ``None``."""
    pid = (profile_id or "").strip()
    if not pid:
        return None
    # Profile ids cannot contain path separators — prevents traversal.
    if "/" in pid or "\\" in pid or pid.startswith("."):
        return None
    for directory in profile_search_dirs(extra_dirs):
        candidate = directory / f"{pid}.yaml"
        if candidate.is_file():
            return candidate
    return None


def load_profile_yaml(
    profile_id: str,
    *,
    extra_dirs: list[Path] | None = None,
) -> dict[str, Any]:
    """Load a profile YAML into a plain dict. Raises FileNotFoundError."""
    path = resolve_profile_path(profile_id, extra_dirs=extra_dirs)
    if path is None:
        raise FileNotFoundError(
            f"Domain profile '{profile_id}' not found. Search paths: "
            + ", ".join(str(p) for p in profile_search_dirs(extra_dirs))
        )
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(
            f"Profile {path} must be a YAML mapping, got {type(data).__name__}"
        )
    return data


# ---------------------------------------------------------------------------
# Profile → config overlay mapping
# ---------------------------------------------------------------------------

# Maps profile top-level keys to dotted config paths.  Only listed keys are
# considered "deployment" fields; everything else in the profile (prompt
# guidance, detection keywords, etc.) is consumed elsewhere via the
# DomainProfile + PromptAdapter layers and should not touch config.yaml.
_SCALAR_FIELD_MAP: dict[str, str] = {
    "preferred_project_mode": "project.mode",
}

# Sequence fields: the whole list lands at the given dotted path if unset.

# Nested-block fields: entire sub-dicts (e.g. collider_agent, agentic,
# figure_agent) replace the corresponding sub-config only where the user
# has not set anything.


# ---------------------------------------------------------------------------
# Deep merge (user wins)
# ---------------------------------------------------------------------------


def _deep_merge_user_wins(
    base: Any,
    overlay: Any,
) -> Any:
    """Return ``base`` with keys from ``overlay`` filled in.

    Semantics:
    * If both are dicts, recurse; user keys stay, overlay keys fill the gaps.
    * If ``base`` is a non-None / non-empty-string scalar or a non-empty
      list, keep the user value. Only when ``base`` is missing / blank does
      the overlay value take effect.
    """
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = dict(base)
        for key, overlay_val in overlay.items():
            if key not in merged:
                merged[key] = copy.deepcopy(overlay_val)
            else:
                merged[key] = _deep_merge_user_wins(merged[key], overlay_val)
        return merged
    # Scalars / lists: user wins unless they left the slot blank.
    if base is None:
        return copy.deepcopy(overlay)
    if isinstance(base, str) and not base.strip():
        return copy.deepcopy(overlay)
    if isinstance(base, (list, tuple)) and len(base) == 0:
        return copy.deepcopy(overlay)
    return base


def _set_by_path(data: dict[str, Any], dotted: str, value: Any) -> None:
    """Set ``data[a][b][c] = value`` creating dicts along the way."""
    parts = dotted.split(".")
    cur: dict[str, Any] = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _get_by_path(data: dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _is_unset(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, tuple)) and len(value) == 0:
        return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_profile_defaults(
    config_data: dict[str, Any],
    profile_id: str,
    *,
    extra_dirs: list[Path] | None = None,
) -> dict[str, Any]:
    """Return a new config dict with the profile's deployment defaults merged in.

    The profile is *advisory*: every key the user has already set in
    ``config.yaml`` stays untouched.  The profile only fills blanks.

    Parameters
    ----------
    config_data:
        The raw dict parsed from ``config.yaml``.
    profile_id:
        Profile id, e.g. ``"hep_ph"`` or ``"ml_vision"``.

    Raises
    ------
    FileNotFoundError
        If the profile id is unknown.
    """
    profile = load_profile_yaml(profile_id, extra_dirs=extra_dirs)
    result: dict[str, Any] = copy.deepcopy(config_data) if config_data else {}

    # 1. Scalar fields — straight copy to a dotted path, user wins.
    for src_key, dotted in _SCALAR_FIELD_MAP.items():
        if src_key not in profile:
            continue
        overlay_val = profile[src_key]
        if overlay_val is None:
            continue
        if _is_unset(_get_by_path(result, dotted)):
            _set_by_path(result, dotted, copy.deepcopy(overlay_val))

    # 4. Top-level nested blocks (memory, skills, ...) — only the ones the
    #    profile explicitly mentions. Rare, but lets a profile preload a
    #    memory/skills config if desired.
    for top_key in ("skills", "web_search"):
        overlay_block = profile.get(top_key)
        if not isinstance(overlay_block, dict):
            continue
        user_block = result.get(top_key)
        if not isinstance(user_block, dict):
            user_block = {}
        result[top_key] = _deep_merge_user_wins(user_block, overlay_block)

    # 5. Echo the chosen profile into project.profile so downstream code
    #    (pipeline adapters, report header) can see what was deployed.
    project_section = result.get("project")
    if not isinstance(project_section, dict):
        project_section = {}
        result["project"] = project_section
    project_section["profile"] = str(profile_id).strip()

    logger.info(
        "Applied profile '%s' deployment defaults (source: %s)",
        profile_id,
        resolve_profile_path(profile_id, extra_dirs=extra_dirs),
    )
    return result
