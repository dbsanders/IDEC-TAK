import asyncio
import ssl
from typing import Any


class TakClient:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.enabled = bool(config.get("enabled", False))

    async def send_event(self, cot_xml: str) -> None:
        if not self.enabled:
            return

        host = self.config["host"]
        port = int(self.config["port"])
        protocol = self.config.get("protocol", "tcp").lower()
        ssl_context = None

        if protocol == "tls":
            ssl_context = self._build_ssl_context()

        reader, writer = await asyncio.open_connection(host=host, port=port, ssl=ssl_context)
        try:
            data = cot_xml.strip().encode("utf-8") + b"\n"
            writer.write(data)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    def _build_ssl_context(self) -> ssl.SSLContext | None:
        ssl_context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ca_file = self.config.get("ca_file")
        if ca_file:
            ssl_context.load_verify_locations(cafile=ca_file)
        else:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        cert_file = self.config.get("cert_file")
        key_file = self.config.get("key_file")
        if cert_file and key_file:
            ssl_context.load_cert_chain(certfile=cert_file, keyfile=key_file)
        return ssl_context
