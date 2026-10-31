"""Diagnostic ACS ACR1552 : identification et commandes NFC en lecture seule."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from smartcard import scard as sc


def emit(event, **data):
    print(json.dumps({"event": event, **data}, ensure_ascii=False), flush=True)


def message(result):
    return sc.SCardGetErrorMessage(result)


def memory_geometry(data, uid):
    if len(data) < 9 or data[1:9] != uid or not data[0] & 0x04:
        raise SystemExit("Les informations ISO15693 ne décrivent pas la mémoire attendue.")
    position = 9
    info = {}
    for mask, name in ((0x01, "dsfid"), (0x02, "afi")):
        if data[0] & mask:
            if position >= len(data):
                raise SystemExit("Informations ISO15693 tronquées.")
            info[name] = data[position]
            position += 1
    if position + 2 > len(data):
        raise SystemExit("Géométrie mémoire ISO15693 tronquée.")
    info["blocks"] = data[position] + 1
    info["block_bytes"] = (data[position + 1] & 0x1F) + 1
    position += 2
    if data[0] & 0x08 and position < len(data):
        info["ic_reference"] = data[position]
    if info["blocks"] * info["block_bytes"] > 8192:
        raise SystemExit("Mémoire hors limite du diagnostic (8192 octets).")
    return info


def transmit(card, protocol, command):
    result, response = sc.SCardTransmit(card, protocol, command)
    data = bytes(response)
    if result != sc.SCARD_S_SUCCESS or len(data) < 2 or data[-2:] != b"\x90\x00":
        raise SystemExit("Lecture NFC refusée : " + message(result) + " / " + data.hex().upper())
    return data[:-2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--iso15693", action="store_true", help="Lire les informations d’un tag NFC-V.")
    parser.add_argument("--dump", type=Path, help="Enregistrer une copie privée de la mémoire, sans écrire sur le tag.")
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 60:
        parser.error("Le délai doit être compris entre 0 et 60 secondes.")
    if args.dump and not args.iso15693:
        parser.error("--dump demande --iso15693.")
    result, context = sc.SCardEstablishContext(sc.SCARD_SCOPE_USER)
    if result != sc.SCARD_S_SUCCESS:
        raise SystemExit("PC/SC : " + message(result))
    try:
        result, names = sc.SCardListReaders(context, [])
        if result != sc.SCARD_S_SUCCESS:
            raise SystemExit("Liste des lecteurs : " + message(result))
        emit("readers", names=names)
        candidates = [name for name in names if "ACR1552" in name and "PICC" in name]
        if len(candidates) != 1:
            raise SystemExit("Un seul lecteur ACR1552 PICC doit être raccordé.")
        name = candidates[0]
        result, card, protocol = sc.SCardConnect(
            context, name, sc.SCARD_SHARE_DIRECT, sc.SCARD_PROTOCOL_UNDEFINED
        )
        emit("direct_connection", status=message(result))
        if result == sc.SCARD_S_SUCCESS:
            try:
                # ACS manual v1.09, section 6.2.1: firmware query, no setting changed.
                result, response = sc.SCardControl(
                    card, sc.SCARD_CTL_CODE(3500), [0xE0, 0, 0, 0x18, 0]
                )
                data = bytes(response)
                firmware = None
                if result == sc.SCARD_S_SUCCESS and data[:4] == b"\xe1\x00\x00\x00" and len(data) >= 5 + data[4]:
                    firmware = data[5:5 + data[4]].decode("ascii", "replace")
                emit("firmware", status=message(result), response_hex=data.hex().upper(), version=firmware)
                result, response = sc.SCardControl(card, sc.SCARD_CTL_CODE(3400), [])
                emit("pcsc_features", status=message(result), response_hex=bytes(response).hex().upper())
                if result == sc.SCARD_S_SUCCESS:
                    features = bytes(response)
                    for offset in range(0, len(features) - 5, 6):
                        # PC/SC Part 10 FEATURE_GET_TLV_PROPERTIES, read-only.
                        if features[offset:offset + 2] != b"\x12\x04":
                            continue
                        code = int.from_bytes(features[offset + 2:offset + 6], "big")
                        result, response = sc.SCardControl(card, code, [])
                        properties = bytes(response)
                        emit("pcsc_properties", status=message(result), response_hex=properties.hex().upper())
                        position = 0
                        while result == sc.SCARD_S_SUCCESS and position + 2 <= len(properties):
                            tag, length = properties[position:position + 2]
                            position += 2
                            if position + length > len(properties):
                                break
                            value = properties[position:position + length]
                            position += length
                            if tag == 0x08:
                                emit("firmware_property", version=value.rstrip(b"\x00").decode("ascii", "replace"))
            finally:
                sc.SCardDisconnect(card, sc.SCARD_LEAVE_CARD)
        deadline = time.monotonic() + args.wait_seconds
        while True:
            result, card, protocol = sc.SCardConnect(
                context, name, sc.SCARD_SHARE_SHARED, sc.SCARD_PROTOCOL_T0 | sc.SCARD_PROTOCOL_T1
            )
            if result == sc.SCARD_S_SUCCESS:
                break
            if result not in (sc.SCARD_E_NO_SMARTCARD, sc.SCARD_W_REMOVED_CARD):
                raise SystemExit("Connexion au tag : " + message(result))
            if time.monotonic() >= deadline:
                emit("tag_absent", status=message(result))
                return
            time.sleep(0.5)
        try:
            result, reader, state, active_protocol, atr = sc.SCardStatus(card)
            emit("tag_present", status=message(result), atr=bytes(atr).hex().upper())
            # ACS manual v1.09, section 5.3.3.1: UID and activation data only.
            for title, parameter in (("uid", 0x00), ("activation_data", 0x80)):
                result, response = sc.SCardTransmit(card, protocol, [0xFF, 0xCA, parameter, 0, 0])
                data = bytes(response)
                emit(title, status=message(result), data=data[:-2].hex().upper(), sw=data[-2:].hex().upper())
                if title == "uid":
                    uid = data[:-2] if result == sc.SCARD_S_SUCCESS and data[-2:] == b"\x90\x00" else b""
            if args.iso15693:
                if len(uid) != 8 or 0xE0 not in (uid[0], uid[-1]):
                    raise SystemExit("L’identifiant ne correspond pas au tag ISO15693 attendu.")
                # ACS manual v1.09, sections 5.3.4.2 and 5.3.4.2.2.
                commands = (
                    ("iso15693_system_info", [0xFF, 0xFB, 0, 0, 1, 0x2B]),
                    ("iso15693_block_zero", [0xFF, 0xFB, 0, 0, 2, 0x20, 0]),
                    ("iso15693_security_zero", [0xFF, 0xFB, 0, 0, 3, 0x2C, 0, 0]),
                )
                for title, command in commands:
                    result, response = sc.SCardTransmit(card, protocol, command)
                    data = bytes(response)
                    emit(title, status=message(result), data=data[:-2].hex().upper(), sw=data[-2:].hex().upper())
                    if title == "iso15693_system_info":
                        system_info = data[:-2] if result == sc.SCARD_S_SUCCESS and data[-2:] == b"\x90\x00" else b""
                if args.dump:
                    geometry = memory_geometry(system_info, uid)
                    emit("memory_geometry", **geometry)
                    result = sc.SCardBeginTransaction(card)
                    if result != sc.SCARD_S_SUCCESS:
                        raise SystemExit("Transaction PC/SC : " + message(result))
                    try:
                        image = bytearray()
                        for block in range(geometry["blocks"]):
                            content = transmit(card, protocol, [0xFF, 0xFB, 0, 0, 2, 0x20, block])
                            if len(content) != geometry["block_bytes"]:
                                raise SystemExit("Taille inattendue lors de la lecture d’un bloc.")
                            image.extend(content)
                        security = transmit(card, protocol, [0xFF, 0xFB, 0, 0, 3, 0x2C, 0, geometry["blocks"] - 1])
                        if len(security) != geometry["blocks"]:
                            raise SystemExit("Statuts de sécurité incomplets.")
                        if transmit(card, protocol, [0xFF, 0xCA, 0, 0, 0]) != uid:
                            raise SystemExit("Le tag a changé pendant la lecture; copie abandonnée.")
                    finally:
                        sc.SCardEndTransaction(card, sc.SCARD_LEAVE_CARD)
                    args.dump.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                    descriptor = os.open(args.dump, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, "wb") as output:
                        output.write(image)
                    emit("memory_copy", path=str(args.dump), bytes=len(image), all_zero=not any(image), sha256=hashlib.sha256(image).hexdigest(), uid=uid[::-1].hex().upper(), security_hex=security.hex().upper(), permanently_locked_blocks=[index for index, value in enumerate(security) if value & 1])
        finally:
            sc.SCardDisconnect(card, sc.SCARD_LEAVE_CARD)
    finally:
        sc.SCardReleaseContext(context)


if __name__ == "__main__":
    main()
