"""Images des quatre caméras réseau : accès protégé, cache commun et RTSP via FFmpeg."""
from concurrent.futures import ThreadPoolExecutor
import shutil
import subprocess
import threading
import time
from urllib.parse import quote, urlsplit, urlunsplit

from .printer import PrinterError, checked_image, read_resource


class PrinterCameras:
    def __init__(self, configuration, fetch=read_resource, capture=None, clock=time.monotonic):
        self.configuration, self.fetch, self.clock = configuration, fetch, clock
        self.capture = capture or self._rtsp
        self.lock = threading.RLock()
        self.cache = {}
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="printer-camera")
        self.closed = False

    @staticmethod
    def _rtsp(camera):
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise PrinterError("Installez FFmpeg sur le Pi pour afficher les caméras RTSP.")
        url = camera["url"]
        if camera["auth"] != "none":
            parsed = urlsplit(url)
            login = quote(camera["username"], safe="") + ":" + quote(camera["secret"], safe="") + "@"
            url = urlunsplit((parsed.scheme, login + parsed.netloc, parsed.path, parsed.query, ""))
        try:
            result = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                                     "-protocol_whitelist", "rtsp,tcp,udp,rtp", "-rtsp_transport", "tcp", "-i", url,
                                     "-an", "-frames:v", "1", "-vf", "scale=960:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
                                    capture_output=True, timeout=12, check=False)
        except (subprocess.TimeoutExpired, OSError):
            raise PrinterError("La caméra RTSP n’a pas répondu à temps.") from None
        if result.returncode or not result.stdout or len(result.stdout) > 2_000_000:
            raise PrinterError("Flux RTSP indisponible. Vérifiez la caméra et ses identifiants.")
        return checked_image("image/jpeg", result.stdout)

    def _load(self, camera):
        if camera["url"].startswith("rtsp:"):
            return self.capture(camera)
        _, mime, data = self.fetch(camera["url"], camera["auth"], camera["username"], camera["secret"], limit=2_000_000, timeout=8)
        return checked_image(mime, data)

    def image(self, identifier):
        record = self.configuration.record()
        camera = next((c for c in record["cameras"] if c["id"] == identifier and c["enabled"]), None)
        if camera is None:
            raise PrinterError("Caméra absente ou désactivée.", 404)
        key = (record["revision"], identifier)
        with self.lock:
            if self.closed:
                raise PrinterError("La station s’arrête.")
            # Une requête par caméra au plus; partage entre tous les navigateurs.
            self.cache = {k: v for k, v in self.cache.items() if k[0] == record["revision"]}
            cached = self.cache.get(key)
            if cached is None or self.clock() - cached[0] >= 5 and cached[1].done():
                cached = (self.clock(), self.pool.submit(self._load, camera))
                self.cache[key] = cached
            future = cached[1]
        try:
            result = future.result(timeout=14)
        except TimeoutError:
            raise PrinterError("La caméra n’a pas répondu à temps.") from None
        if self.configuration.record()["revision"] != key[0]:
            raise PrinterError("La configuration caméra a changé. Actualisez l’image.", 409)
        return result

    def close(self):
        with self.lock:
            self.closed = True
        self.pool.shutdown(wait=False, cancel_futures=True)
