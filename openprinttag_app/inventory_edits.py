"""Inventory corrections preserve physical tag observations until explicitly reconciled."""
from copy import deepcopy

from .domain import spool_snapshot, validate_fields

IMMUTABLE_MAIN = {"instance_uuid", "write_protection"}


def merge_fields(original, patch):
    result = deepcopy(original)
    for name, value in patch.items():
        if value is None:
            result.pop(name, None)
        else:
            result[name] = value
    return result


def validated_patch(region, patch):
    patch = {} if patch is None else patch
    if not isinstance(patch, dict):
        raise ValueError("Les corrections main et aux doivent être des objets de champs.")
    if region == "main" and set(patch) & IMMUTABLE_MAIN:
        raise ValueError("L’identité de la bobine et la protection du tag ne sont pas modifiables par MCP.")
    return validate_fields(region, patch)


def rebuild(snapshot, main, aux):
    validated = spool_snapshot({**main, "instance_uuid": snapshot["instance_uuid"]}, aux)
    if "instance_uuid" not in main:
        validated["main"].pop("instance_uuid")
    result = deepcopy(snapshot)
    for name in ("main", "aux", "remaining_weight", "remaining_estimated"):
        result[name] = validated[name]
    return result


def validate_local_edits(snapshot):
    edits = snapshot.get("local_edits")
    if edits is None:
        return
    if (not isinstance(edits, dict) or set(edits) != {"version", "main", "aux", "tag_main", "tag_aux"}
            or type(edits["version"]) is not int or edits["version"] != 1):
        raise ValueError("Les corrections locales de la bobine sont invalides.")
    main, aux = validated_patch("main", edits["main"]), validated_patch("aux", edits["aux"])
    if not main and not aux:
        raise ValueError("Une correction locale vide doit être supprimée.")
    validate_fields("main", edits["tag_main"], partial=False)
    validate_fields("aux", edits["tag_aux"], partial=False)
    if edits["tag_main"].get("instance_uuid", snapshot["instance_uuid"]) != snapshot["instance_uuid"]:
        raise ValueError("L’identité du dernier tag lu ne correspond pas à la bobine.")
    expected = rebuild(snapshot, merge_fields(edits["tag_main"], main), merge_fields(edits["tag_aux"], aux))
    if any(snapshot.get(name) != expected[name] for name in ("main", "aux", "remaining_weight", "remaining_estimated")):
        raise ValueError("Les corrections locales ne correspondent pas à la fiche de bobine.")


def patch_snapshot(snapshot, main=None, aux=None, *, rfid=False, reset_tag_overrides=False):
    validate_local_edits(snapshot)
    changes = {"main": validated_patch("main", main), "aux": validated_patch("aux", aux)}
    if not changes["main"] and not changes["aux"] and (not reset_tag_overrides or "local_edits" not in snapshot):
        return deepcopy(snapshot)
    if not rfid:
        return rebuild(snapshot, merge_fields(snapshot["main"], changes["main"]), merge_fields(snapshot["aux"], changes["aux"]))
    previous = snapshot.get("local_edits", {})
    base = {region: deepcopy(previous.get("tag_" + region, snapshot[region])) for region in ("main", "aux")}
    patches = {}
    for region in ("main", "aux"):
        patch = {**({} if reset_tag_overrides else previous.get(region, {})), **changes[region]}
        patches[region] = {name: value for name, value in patch.items() if value != base[region].get(name)}
    result = rebuild(snapshot, merge_fields(base["main"], patches["main"]), merge_fields(base["aux"], patches["aux"]))
    result.pop("local_edits", None)
    if patches["main"] or patches["aux"]:
        result["local_edits"] = {"version": 1, **patches, "tag_main": base["main"], "tag_aux": base["aux"]}
    return result


def observe_with_edits(observed, previous):
    validate_local_edits(previous)
    edits = previous.get("local_edits")
    if not edits:
        return observed
    # A matching reread acknowledges that field. Other local corrections stay
    # explicit even if the printer has changed the physical tag in the meantime.
    return patch_snapshot(observed, edits["main"], edits["aux"], rfid=True)
