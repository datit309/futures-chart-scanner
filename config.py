import os
import json
from dataclasses import dataclass, asdict

@dataclass
class ScannerConfig:
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    timeframe: str = "15m"
    top_n_coins: int = 30
    min_rr: float = 2.0
    min_trendline_touches: int = 3
    scan_interval_seconds: int = 300
    alert_cooldown_minutes: int = 60
    binance_fapi_url: str = "https://fapi.binance.com"

    @classmethod
    def from_dict(cls, data: dict) -> "ScannerConfig":
        valid_keys = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)

    @classmethod
    def load(cls, file_path: str = "config.json") -> "ScannerConfig":
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return cls.from_dict(data)
            except Exception as e:
                print(f"[Warning] Failed to read {file_path}: {e}")
        
        # Fallback to environment variables
        return cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            timeframe=os.getenv("TIMEFRAME", "15m"),
            top_n_coins=int(os.getenv("TOP_N_COINS", "30")),
            min_rr=float(os.getenv("MIN_RR", "2.0")),
            min_trendline_touches=int(os.getenv("MIN_TRENDLINE_TOUCHES", "3")),
            scan_interval_seconds=int(os.getenv("SCAN_INTERVAL_SECONDS", "300")),
            alert_cooldown_minutes=int(os.getenv("ALERT_COOLDOWN_MINUTES", "60")),
            binance_fapi_url=os.getenv("BINANCE_FAPI_URL", "https://fapi.binance.com")
        )

    def save(self, file_path: str = "config.json"):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=4)
