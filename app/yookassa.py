"""Минимальный клиент ЮKassa (REST API v3)."""
import logging

import httpx

from .utils import kopecks_to_str

log = logging.getLogger("yookassa")


class YooKassaError(Exception):
    pass


class YooKassa:
    BASE = "https://api.yookassa.ru/v3"

    def __init__(self, shop_id: str, secret_key: str) -> None:
        self._client = httpx.AsyncClient(auth=(shop_id, secret_key), timeout=20)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, *, idem: str | None = None, json: dict | None = None) -> dict:
        headers = {"Idempotence-Key": idem} if idem else {}
        last_exc: Exception | None = None
        # Повтор безопасен: тот же Idempotence-Key не создаст дубль платежа/возврата.
        for _ in range(3 if idem else 1):
            try:
                resp = await self._client.request(method, f"{self.BASE}{path}", headers=headers, json=json)
            except httpx.TransportError as exc:
                last_exc = exc
                continue
            if resp.status_code >= 500 and idem:
                last_exc = YooKassaError(f"{resp.status_code}: {resp.text[:300]}")
                continue
            if resp.status_code >= 400:
                log.error("YooKassa %s %s -> %s %s", method, path, resp.status_code, resp.text[:500])
                raise YooKassaError(f"{resp.status_code}: {resp.text[:300]}")
            return resp.json()
        raise YooKassaError(f"network error: {last_exc}")

    async def create_payment(
        self,
        *,
        order_id: str,
        amount_kopecks: int,
        description: str,
        return_url: str,
        receipt: dict | None = None,
    ) -> dict:
        body: dict = {
            "amount": {"value": kopecks_to_str(amount_kopecks), "currency": "RUB"},
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": return_url},
            "description": description[:128],
            "metadata": {"order_id": order_id},
        }
        if receipt:
            body["receipt"] = receipt
        return await self._request("POST", "/payments", idem=f"pay-{order_id}", json=body)

    async def get_payment(self, payment_id: str) -> dict:
        return await self._request("GET", f"/payments/{payment_id}")

    async def refund(
        self,
        *,
        order_id: str,
        payment_id: str,
        amount_kopecks: int,
        receipt: dict | None = None,
    ) -> dict:
        body: dict = {
            "payment_id": payment_id,
            "amount": {"value": kopecks_to_str(amount_kopecks), "currency": "RUB"},
        }
        if receipt:
            body["receipt"] = receipt
        # Один ключ на заказ: повторное нажатие «Возврат» не вернёт деньги дважды.
        return await self._request("POST", "/refunds", idem=f"refund-{order_id}", json=body)
