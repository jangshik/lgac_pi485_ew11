import asyncio
import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: dict):
    """YAML 설정을 통한 초기화 구성"""
    if DOMAIN not in config:
        return True
    
    hass.data[DOMAIN] = {}
    # 여기서는 간단히 climate 플랫폼을 로드하도록 트리거합니다.
    hass.async_create_task(
        hass.helpers.discovery.async_load_platform("climate", DOMAIN, config[DOMAIN], config)
    )
    return True

class LGACSocketManager:
    """EW11 소켓 통신 관리 클래스"""
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.reader = None
        self.writer = None

    async def connect(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.ip, self.port)
            _LOGGER.info(f"Connected to EW11 ({self.ip}:{self.port})")
            return True
        except Exception as e:
            _LOGGER.error(f"Failed to connect to EW11: {e}")
            return False

    async def send_packet(self, packet: bytes):
        if not self.writer:
            await self.connect()
        try:
            self.writer.write(packet)
            await self.writer.drain()
            _LOGGER.debug(f"Sent packet: {packet.hex()}")
        except Exception as e:
            _LOGGER.error(f"Socket send error: {e}")
            self.writer = None