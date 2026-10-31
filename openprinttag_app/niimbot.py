"""Bounded NIIMBOT USB serial transport, B3S_P / B1 profiles only.

Protocol references (no upstream implementation is imported):
https://github.com/MultiMote/niimbluelib (models, B1 task, MIT)
https://github.com/eigger/hass-niimbot/tree/master/docs (wire documentation)
"""
from functools import reduce
import struct
import time

PROFILES = {"b3s_p": {"id": 272, "head": 576, "max_mm": 72, "name": "NIIMBOT B3S_P", "legacy": True},
            "b1": {"id": 4096, "head": 384, "max_mm": 50, "name": "NIIMBOT B1"}}


class LabelError(ValueError):
    pass


def packet(command, data):
    if len(data) > 255:
        raise LabelError("Trame d’impression trop longue.")
    body = bytes((command, len(data))) + data
    return b"\x55\x55" + body + bytes((reduce(int.__xor__, body),)) + b"\xaa\xaa"


class Niimbot:
    def __init__(self, port, transport=None):
        if transport is None:
            import serial
            transport = serial.Serial(port, 115200, timeout=0.1, write_timeout=2, exclusive=True)
        self.transport = transport
        self.buffer = bytearray()
        self.completed_pages = 0
        self.print_started = False

    def close(self):
        self.transport.close()

    def send(self, command, data):
        wire = packet(command, data)
        if command == 0xC1:
            wire = b"\x03" + wire
        if self.transport.write(wire) != len(wire):
            raise LabelError("Transmission USB interrompue. Vérifier l’étiquette avant de réimprimer.")

    def receive(self, deadline):
        while time.monotonic() < deadline:
            self.buffer.extend(self.transport.read(1024))
            if len(self.buffer) > 65536:
                raise LabelError("Réponse de l’imprimante trop volumineuse.")
            while len(self.buffer) >= 4:
                start = self.buffer.find(b"\x55\x55")
                if start < 0:
                    self.buffer[:] = self.buffer[-1:]
                    break
                if start:
                    del self.buffer[:start]
                if len(self.buffer) < 4:
                    break
                length = self.buffer[3] + 7
                if len(self.buffer) < length:
                    break
                wire = bytes(self.buffer[:length])
                del self.buffer[:length]
                if wire[-2:] != b"\xaa\xaa" or reduce(int.__xor__, wire[2:-2]) != 0:
                    raise LabelError("Réponse USB endommagée.")
                command, data = wire[2], wire[4:-3]
                if command == 0xDB:
                    raise LabelError("L’imprimante signale une erreur (papier, capot ou tâche refusée). Vérifier son écran.")
                if command == 0xE0 and len(data) >= 2:
                    self.completed_pages = max(self.completed_pages, int.from_bytes(data[:2], "big"))
                yield command, data

    def query(self, command, data, reply, timeout=2):
        self.send(command, data)
        for received, payload in self.receive(time.monotonic() + timeout):
            if received == reply:
                return payload
        raise LabelError("L’imprimante USB ne répond pas. Vérifier son alimentation et le câble de données.")

    def identify(self):
        data = self.query(0x40, b"\x08", 0x48)
        if len(data) not in {1, 2}:
            raise LabelError("Identification de l’imprimante non reconnue.")
        identifier = data[0] << 8 if len(data) == 1 else int.from_bytes(data, "big")
        model = next((name for name, profile in PROFILES.items() if profile["id"] == identifier), None)
        return {"model_id": identifier, "model": model, "name": PROFILES[model]["name"] if model else "Modèle non pris en charge"}

    def accepted(self, command, data, reply):
        result = self.query(command, data, reply)
        if not result or result[0] != 1:
            raise LabelError("L’imprimante a refusé la préparation de l’étiquette.")

    def print_image(self, image, model, density=3):
        connection = self.query(0xC1, b"\x01", 0xC2)
        if not connection or connection[0] not in {1, 2, 3}:
            raise LabelError("L’imprimante n’a pas accepté la connexion USB.")
        detected = self.identify()
        if detected["model"] != model:
            raise LabelError("Le modèle détecté ne correspond pas au profil configuré. Corriger Configuration avant d’imprimer.")
        profile = PROFILES[model]
        if image.mode != "1" or image.width > profile["head"] or image.width % 8 or not 1 <= density <= 5:
            raise LabelError("Format bitmap incompatible avec le profil d’impression.")
        self.completed_pages = 0
        self.accepted(0x21, bytes((density,)), 0x31)
        self.accepted(0x23, b"\x01", 0x33)  # die-cut labels, no calibration/feed command
        legacy = profile.get("legacy", False)
        self.print_started = True
        self.accepted(0x01, b"\x01" if legacy else struct.pack(">H", 1) + b"\0\0\0\0\0", 0x02)
        self.accepted(0x03, b"\x01", 0x04)
        self.accepted(0x13, struct.pack(">HH", image.height, image.width) + (b"" if legacy else b"\0\x01"), 0x14)
        if legacy:
            self.accepted(0x15, b"\0\x01", 0x16)
        return self._finish_page(image, profile)

    def _finish_page(self, image, profile):
        baseline = self.query(0xA3, b"\x01", 0xB3)
        started = len(baseline) >= 4 and (int.from_bytes(baseline[:2], "big") == 0 or baseline[2] < 100)
        # Pillow mode 1 stores white bits; the printer expects black bits.
        raster = bytes(value ^ 255 for value in image.tobytes())
        stride = image.width // 8
        chunk = profile["head"] // 8 // 3
        for row in range(image.height):
            data = raster[row * stride:(row + 1) * stride]
            if not any(data) and not profile.get("legacy"):
                self.send(0x84, struct.pack(">HB", row, 1))
            else:
                if len(data) <= chunk * 3 and not profile.get("legacy"):
                    counts = [sum(x.bit_count() for x in data[n * chunk:(n + 1) * chunk]) for n in range(3)]
                else:
                    count = sum(x.bit_count() for x in data)
                    counts = [0, count & 255, count >> 8]
                self.send(0x85, struct.pack(">HBBBB", row, *counts, 1) + data)
            if row and row % 100 == 0:
                state = self.query(0xA3, b"\x01", 0xB3)
                started = started or (len(state) >= 4 and state[2] < 100)
            time.sleep(0.01 if profile.get("legacy") else 0.002)
        self.accepted(0xE3, b"\x01", 0xE4)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = self.query(0xA3, b"\x01", 0xB3)
            if len(state) < 4 or (len(state) >= 10 and state[6]):
                raise LabelError("État d’impression incomplet ou en erreur. Vérifier l’étiquette.")
            page = int.from_bytes(state[:2], "big")
            started = started or page == 0 or state[2] < 100
            if self.completed_pages >= 1 or (started and page >= 1 and state[2] == 100):
                self.accepted(0xF3, b"\x01", 0xF4)
                return {"status": "complete", "detail": "Une étiquette imprimée selon le retour de l’imprimante. Vérifier la lisibilité du QR."}
            time.sleep(0.2)
        raise LabelError("Fin d’impression non confirmée. Vérifier l’étiquette avant de réimprimer; aucune répétition automatique.")
