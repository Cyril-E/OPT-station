"""One PC/SC transaction per process; only changed SLIX2 user blocks can be written.

ACS v1.09 sections 5.3.3.1 and 5.3.4.2; NXP SL2S2602 Rev 4.2 sections
9.5.3.18 and 9.5.3.21. No passwords, lock, privacy or reader-setting commands.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys

from .domain import DomainError, TagImage
from .readers import revision


class NFCError(Exception):
    def __init__(self, message, kind="unavailable", dirty=False):
        super().__init__(message)
        self.kind, self.dirty = kind, dirty


class PCSCSession:
    def __init__(self):
        try:
            from smartcard import scard
        except ImportError as exc:
            raise NFCError("Les composants NFC ne sont pas installés. Suivre l’installation PC/SC du guide Pi.") from exc
        self.sc = scard
        self.context = self.card = None
        self.transaction = False

    def check(self, result, action):
        if result != self.sc.SCARD_S_SUCCESS:
            raise NFCError(f"{action} : {self.sc.SCardGetErrorMessage(result)}. Vérifier le lecteur et le tag.")

    def __enter__(self):
        result, self.context = self.sc.SCardEstablishContext(self.sc.SCARD_SCOPE_USER)
        self.check(result, "Accès au lecteur NFC")
        return self

    def __exit__(self, *_):
        if self.card is not None:
            if self.transaction:
                self.sc.SCardEndTransaction(self.card, self.sc.SCARD_LEAVE_CARD)
            self.sc.SCardDisconnect(self.card, self.sc.SCARD_LEAVE_CARD)
        if self.context is not None:
            self.sc.SCardReleaseContext(self.context)

    def readers(self):
        result, names = self.sc.SCardListReaders(self.context, [])
        if result == self.sc.SCARD_E_NO_READERS_AVAILABLE:
            return []
        self.check(result, "Liste des lecteurs")
        return [name for name in names if "ACR1552" in name and "PICC" in name]

    def connect(self, name, direct=False):
        mode = self.sc.SCARD_SHARE_DIRECT if direct else self.sc.SCARD_SHARE_SHARED
        protocols = self.sc.SCARD_PROTOCOL_UNDEFINED if direct else self.sc.SCARD_PROTOCOL_T0 | self.sc.SCARD_PROTOCOL_T1
        result, card, self.protocol = self.sc.SCardConnect(self.context, name, mode, protocols)
        if result == self.sc.SCARD_E_NO_SMARTCARD:
            raise NFCError("Aucun tag présent. Posez un seul tag NFC-V au centre du lecteur.")
        self.check(result, "Connexion au tag")
        self.card = card
        if not direct:
            self.check(self.sc.SCardBeginTransaction(self.card), "Réservation du lecteur")
            self.transaction = True

    def present(self, name):
        result, states = self.sc.SCardGetStatusChange(
            self.context, 0, [(name, self.sc.SCARD_STATE_UNAWARE)]
        )
        self.check(result, "État du lecteur")
        if len(states) != 1:
            raise NFCError("L’état du lecteur NFC est incomplet.")
        return bool(states[0][1] & self.sc.SCARD_STATE_PRESENT)

    def transmit(self, command):
        result, response = self.sc.SCardTransmit(self.card, self.protocol, command)
        self.check(result, "Échange NFC")
        data = bytes(response)
        if len(data) < 2 or data[-2:] != b"\x90\x00":
            raise NFCError("Le tag a refusé la commande NFC (" + data[-2:].hex().upper() + ").")
        return data[:-2]

    def uid(self):
        wire = self.transmit([0xFF, 0xCA, 0, 0, 0])
        if len(wire) != 8 or wire[-1] != 0xE0:
            raise NFCError("Ce badge n’est pas un tag NFC-V/ISO15693 pris en charge.", "invalid")
        return wire

    def iso(self, command, uid, data=b"", manufacturer=None):
        # Explicit addressing binds every RF operation to the UID just checked.
        body = bytes([command]) + (bytes([manufacturer]) if manufacturer is not None else b"") + uid + bytes(data)
        reply = self.transmit([0xFF, 0xFB, 0, 0x22, len(body), *body])
        if not reply or reply[0] & 1:
            raise NFCError("Le tag NFC-V a refusé la lecture ou l’écriture demandée.")
        return reply[1:]


def geometry(data, uid):
    if len(data) < 9 or data[1:9] != uid or not data[0] & 4:
        raise NFCError("La géométrie du tag NFC-V n’a pas pu être vérifiée.", "invalid")
    offset = 9 + bool(data[0] & 1) + bool(data[0] & 2)
    if offset + 2 > len(data):
        raise NFCError("Informations mémoire NFC-V incomplètes.", "invalid")
    blocks, size = data[offset] + 1, (data[offset + 1] & 31) + 1
    reference = data[offset + 2] if data[0] & 8 and offset + 2 < len(data) else None
    if blocks * size > 2040:
        raise NFCError("Ce tag dépasse la capacité prise en charge par cette station.", "invalid")
    return blocks, size, reference


def read_record(session):
    uid = session.uid()
    system_info = session.iso(0x2B, uid)
    blocks, size, reference = geometry(system_info, uid)
    image = bytearray()
    for block in range(blocks):
        content = session.iso(0x20, uid, bytes([block]))
        if len(content) != size:
            raise NFCError("Un bloc NFC est incomplet. Relire le tag.")
        image.extend(content)
    security = session.iso(0x2C, uid, bytes([0, blocks - 1]))
    if len(security) != blocks or session.uid() != uid:
        raise NFCError("Le tag ou ses informations de protection ont changé. Relire le tag.")
    canonical = uid[::-1].hex().upper()
    slix2 = canonical.startswith("E00401") and (blocks, size, reference) == (80, 4, 1)
    nxp = b""
    if slix2:
        try:
            nxp = session.iso(0xAB, uid, manufacturer=4)
        except NFCError:
            pass  # Keep reading possible, but refuse writes with unknown protection.
    known = slix2 and len(nxp) == 7 and nxp[0] <= 78 and not nxp[1] & 0xCC
    usable = 312 if slix2 else blocks * size
    blocked = set(range(blocks))
    if known:
        blocked = {index for index, value in enumerate(security) if value}
        pointer, conditions = nxp[:2]
        blocked.update(index for index in range(79)
                       if conditions & (0x02 if index < pointer else 0x20))
        blocked.update(range(usable // size, blocks))
    if image[:1] == b"\xe1" and image[1] & 3:
        blocked.update(range(blocks))
    main_blocks = aux_blocks = set(range(usable // size))
    if any(image[:usable]):
        try:
            parsed = TagImage.from_bytes(image, canonical)
            def region_blocks(name):
                offset, length = parsed.regions.get(name, (0, 0))
                start = parsed.payload_offset + offset
                return set(range(start // size, (start + length - 1) // size + 1)) if length else set()
            main_blocks, aux_blocks = region_blocks("main"), region_blocks("aux")
        except DomainError:
            pass
    signature = hashlib.sha256(system_info + security + nxp).hexdigest()
    return {"uid": canonical, "image": bytes(image).hex(), "main_locked": bool(main_blocks & blocked),
            "aux_locked": bool(aux_blocks & blocked), "protection_signature": signature,
            "security": security.hex(), "blocked_blocks": sorted(blocked), "block_bytes": size,
            "usable_capacity": usable, "write_supported": known,
            "write_reason": "" if known else "L’écriture exige un ICODE SLIX2 identifié et des protections vérifiées.",
            "nxp_system_info": nxp.hex()}


def check_proposal(current, proposed, *, reuse=False):
    before = bytes.fromhex(current["image"])
    if not current["write_supported"]:
        raise NFCError(current["write_reason"], "protected")
    if len(proposed) != len(before):
        raise NFCError("La capacité du tag a changé.", "conflict")
    usable = current["usable_capacity"]
    if before[usable:] != proposed[usable:]:
        raise NFCError("L’opération toucherait un bloc réservé du tag.", "protected")
    try:
        after_tag = TagImage.from_bytes(proposed, current["uid"])
        if not any(before[:usable]) or reuse:
            if proposed[2] * 8 != usable:
                raise DomainError("Le conteneur doit respecter la mémoire utilisateur disponible.")
        else:
            before_tag = TagImage.from_bytes(before, current["uid"])
            if (before_tag.instance_uuid != after_tag.instance_uuid or before_tag.regions != after_tag.regions
                    or before_tag.payload_offset != after_tag.payload_offset):
                raise DomainError("L’identité ou la structure du tag ne peut pas changer pendant une modification.")
            allowed = set()
            for name in ("main", "aux"):
                if name in before_tag.regions:
                    start, length = before_tag.regions[name]
                    allowed.update(range(before_tag.payload_offset + start, before_tag.payload_offset + start + length))
            if any(old != new and offset not in allowed for offset, (old, new) in enumerate(zip(before, proposed))):
                raise DomainError("Une modification toucherait les en-têtes ou les métadonnées du tag.")
    except DomainError as exc:
        raise NFCError(str(exc), "invalid") from exc
    size = current["block_bytes"]
    changed = [index for index in range(len(before) // size)
               if before[index * size:(index + 1) * size] != proposed[index * size:(index + 1) * size]]
    if not changed:
        raise NFCError("Aucune modification à écrire.", "invalid")
    if set(changed) & set(current["blocked_blocks"]):
        raise NFCError("Un bloc à modifier est protégé. Aucune écriture n’a été lancée.", "protected")
    return changed


def save_private(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def write_image(session, request):
    current = read_record(session)
    before = bytes.fromhex(current["image"])
    record = {**current, "image": before}
    if current["uid"] != request["expected_uid"] or revision(record) != request["expected_revision"]:
        raise NFCError("Le tag ou ses protections ont changé. Relire et préparer à nouveau.", "conflict")
    proposed = bytes.fromhex(request["image"])
    reuse = request.get("reuse", False)
    if type(reuse) is not bool:
        raise NFCError("La confirmation de réutilisation du tag est invalide.", "invalid")
    changed = check_proposal(current, proposed, reuse=reuse)
    try:
        directory = Path(request["backup_dir"])
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + current["uid"] + "-" + secrets.token_hex(4)
        backup = directory / (identifier + ".bin")
        save_private(backup, before)
        metadata = {"uid": current["uid"], "before_sha256": hashlib.sha256(before).hexdigest(),
                    "proposed_sha256": hashlib.sha256(proposed).hexdigest(), "blocks": changed,
                    "security": current["security"], "nxp_system_info": current["nxp_system_info"], "status": "pending", "reuse": reuse}
        metadata_path = directory / (identifier + ".json")
        save_private(metadata_path, json.dumps(metadata, ensure_ascii=False).encode())
        if sys.platform == "linux":
            for path in (directory.parent, directory):
                descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
    except OSError as exc:
        raise NFCError("La sauvegarde du tag n’a pas pu être enregistrée. Aucune écriture n’a été lancée.") from exc
    dirty = False
    try:
        size = current["block_bytes"]
        uid = bytes.fromhex(current["uid"])[::-1]
        # Finish the payload first on initialization; publish its CC/header last.
        if (not any(before[:current["usable_capacity"]]) or reuse) and 0 in changed:
            changed = [index for index in changed if index != 0] + [0]
        for block in changed:
            dirty = True  # A failed transport cannot prove that no EEPROM write occurred.
            session.iso(0x21, uid, bytes([block]) + proposed[block * size:(block + 1) * size])
            if session.iso(0x20, uid, bytes([block])) != proposed[block * size:(block + 1) * size]:
                raise NFCError("La relecture d’un bloc ne correspond pas aux données demandées.")
        observed = read_record(session)
        if observed["uid"] != current["uid"] or bytes.fromhex(observed["image"]) != proposed:
            raise NFCError("La vérification complète du tag n’a pas réussi.")
        metadata["status"] = "verified"
        return {"verified": True, "backup": str(backup), "written_blocks": changed}
    except Exception as exc:
        metadata["status"] = "uncertain" if dirty else "rejected"
        raise NFCError("L’écriture n’est pas confirmée. Relire le tag avant toute nouvelle tentative.", dirty=dirty) from exc
    finally:
        temporary = metadata_path.with_suffix(".next")
        save_private(temporary, json.dumps(metadata, ensure_ascii=False).encode())
        os.replace(temporary, metadata_path)


def execute(request, session):
    names = session.readers()
    if len(names) != 1:
        message = "Raccordez un lecteur ACS ACR1552U-M1 en USB." if not names else "Laissez un seul lecteur ACR1552 branché pour choisir le tag sans ambiguïté."
        if request["operation"] == "status":
            return {"connected": False, "present": False, "detected_readers": names, "message": message}
        raise NFCError(message)
    if request["operation"] == "status":
        present = session.present(names[0])
        return {"connected": True, "present": present, "pcsc_name": names[0], "detected_readers": names,
                "message": "Tag présent sur le lecteur." if present else "Présentez un tag NFC-V sur le lecteur."}
    session.connect(names[0])
    if request["operation"] == "read":
        return read_record(session)
    if request["operation"] == "write":
        return write_image(session, request)
    raise NFCError("Commande NFC inconnue.", "invalid")


def main():
    try:
        request = json.loads(sys.stdin.read(32_000))
        if request.get("operation") not in {"status", "read", "write"}:
            raise NFCError("Commande NFC inconnue.", "invalid")
        with PCSCSession() as session:
            result = execute(request, session)
        response = {"ok": True, "result": result}
    except NFCError as exc:
        response = {"ok": False, "message": str(exc), "kind": exc.kind, "dirty": exc.dirty}
    except Exception:
        response = {"ok": False, "message": "La communication NFC a été interrompue. Relire le tag.", "dirty": True}
    print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
