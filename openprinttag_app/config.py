from dataclasses import dataclass
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    data_dir: Path = ROOT / "var"
    mode: str = "simulation"
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "[::1]", "testserver")
    camera_enabled: bool = False
    network_enabled: bool = False
    network_url: str = ""
    https_config: Path | None = None

    def __post_init__(self):
        if self.mode not in {"simulation", "hardware"}:
            raise ValueError("OPENPRINTTAG_MODE doit être simulation ou hardware.")

    @property
    def database(self) -> Path:
        # Le stock d'essai ne sera jamais chargé en mode matériel.
        return Path(self.data_dir) / ("simulation.sqlite3" if self.mode == "simulation" else "inventory.sqlite3")

    @classmethod
    def from_env(cls):
        hosts = tuple(x.strip() for x in os.getenv("OPENPRINTTAG_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if x.strip())
        return cls(Path(os.getenv("OPENPRINTTAG_DATA_DIR", str(ROOT / "var"))), os.getenv("OPENPRINTTAG_MODE", "simulation"), hosts,
                   os.getenv("OPENPRINTTAG_CAMERA", "0").lower() in {"1", "true", "yes"},
                   os.getenv("OPENPRINTTAG_NETWORK", "0").lower() in {"1", "true", "yes"},
                   os.getenv("OPENPRINTTAG_NETWORK_URL", ""),
                   Path(os.environ["OPENPRINTTAG_HTTPS_CONFIG"]) if os.getenv("OPENPRINTTAG_HTTPS_CONFIG") else None)
