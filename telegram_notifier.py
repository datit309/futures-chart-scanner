import aiohttp
from typing import Optional

class TelegramNotifier:
    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self.bot_token = bot_token.strip()
        self.chat_id = str(chat_id).strip()
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id and not self.bot_token.startswith("YOUR_"))

    async def send_chart_alert(
        self, 
        photo_bytes: bytes, 
        caption: str, 
        filename: str = "chart.png"
    ) -> bool:
        """
        Send a photo alert with HTML caption to Telegram.
        """
        if not self.is_configured:
            print("[TelegramNotifier] Token/ChatID not configured — skipping Telegram dispatch.")
            return False

        url = f"{self.base_url}/sendPhoto"
        data = aiohttp.FormData()
        data.add_field("chat_id", self.chat_id)
        data.add_field("caption", caption)
        data.add_field("parse_mode", "HTML")
        data.add_field("photo", photo_bytes, filename=filename, content_type="image/png")

        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, data=data) as resp:
                    res_json = await resp.json()
                    if resp.status == 200 and res_json.get("ok"):
                        print(f"[TelegramNotifier] Alert successfully sent to Telegram ({self.chat_id})")
                        return True
                    else:
                        print(f"[TelegramNotifier] Error sending alert: {res_json}")
                        return False
        except Exception as e:
            print(f"[TelegramNotifier] Exception dispatching Telegram alert: {e}")
            return False

    async def send_text_message(self, text: str) -> bool:
        """
        Send a plain/HTML text message to Telegram.
        """
        if not self.is_configured:
            return False

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json=payload) as resp:
                    return resp.status == 200
        except Exception as e:
            print(f"[TelegramNotifier] Exception sending text: {e}")
            return False
