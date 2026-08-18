import asyncio
import logging
import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_sniff_rs485(host, port, timeout=5.0):
    discovered = set()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3.0)
        end_time = asyncio.get_event_loop().time() + timeout
        buffer = bytearray()
        while asyncio.get_event_loop().time() < end_time:
            try:
                data = await asyncio.wait_for(reader.read(1024), timeout=1.0)
                if not data: break
                buffer.extend(data)
                while len(buffer) >= 8:
                    if buffer[0] in [0x80, 0x10]:
                        room_idx = 3 if buffer[0] == 0x80 else 4
                        packet_len = 8 if buffer[0] == 0x80 else 16
                        if len(buffer) >= packet_len:
                            discovered.add(buffer[room_idx])
                            del buffer[:packet_len]
                        else: break
                    else: del buffer[0:1]
            except asyncio.TimeoutError: continue
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        _LOGGER.error(f"스캔 오류: {e}")
    return sorted(list(discovered))

class LGACConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.host = None
        self.port = None
        self.temp_step = None
        self.update_interval = 10
        self.discovered_ids = []

    async def async_step_user(self, user_input=None):
        """STEP 1: 통신 정보 및 업데이트 주기 설정"""
        if user_input is not None:
            self.host = user_input["host"]
            self.port = user_input["port"]
            self.temp_step = user_input["temp_step"]
            self.update_interval = user_input["update_interval"]
            
            # 5초 동안 버스 패킷을 스캔하여 활성화된 에어컨 탐색
            self.discovered_ids = await async_sniff_rs485(self.host, self.port, timeout=5.0)
            return await self.async_step_mapping()

        data_schema = vol.Schema({
            vol.Required("host", default="192.168.0."): str,
            vol.Required("port", default=8899): int,
            vol.Required("temp_step", default=1.0): vol.In({0.5: "0.5도 단위", 1.0: "1.0도 단위"}),
            vol.Required("update_interval", default=10): vol.In({5: "5초", 10: "10초", 30: "30초", 60: "1분"}),
        })
        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def async_step_mapping(self, user_input=None):
        """STEP 2: 기기별 설정 (난방/플라즈마 기본값 False)"""
        if user_input is not None:
            mapping_parts = []
            for room_id in self.discovered_ids:
                hw_hex = f"{room_id:02x}"
                entity_val = user_input.get(f"entity_{hw_hex}", f"{room_id + 1:02x}")
                name_val = user_input.get(f"name_{hw_hex}", f"에어컨 {entity_val}")
                
                # 🌟 체크박스가 해제되어 있으면 기본적으로 False를 반환하여 0으로 기록
                heat_val = "1" if user_input.get(f"heat_{hw_hex}", False) else "0"
                plasma_val = "1" if user_input.get(f"plasma_{hw_hex}", False) else "0"
                
                # 포맷: entity:hw_id/name/heat/plasma
                mapping_parts.append(f"{entity_val}:{hw_hex}/{name_val}/{heat_val}/{plasma_val}")

            data = {
                "host": self.host,
                "port": self.port,
                "temp_step": self.temp_step,
                "update_interval": self.update_interval,
                "mapping": ", ".join(mapping_parts)
            }
            await self.async_set_unique_id(self.host)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=f"LG 에어컨 ({self.host})", data=data)

        schema_dict = {}
        # 각 기기별로 폼 생성
        for room_id in self.discovered_ids:
            hw_hex = f"{room_id:02x}"
            default_entity = f"{room_id + 1:02x}"
            schema_dict[vol.Required(f"entity_{hw_hex}", default=default_entity)] = str
            schema_dict[vol.Required(f"name_{hw_hex}", default=f"에어컨 {default_entity}")] = str
            
            # 🌟 난방(Heat)과 플라즈마(Plasma)를 기기별로 설정할 수 있게 하되, 기본적으로 체크 해제(False)
            schema_dict[vol.Required(f"heat_{hw_hex}", default=False)] = bool
            schema_dict[vol.Required(f"plasma_{hw_hex}", default=False)] = bool

        return self.async_show_form(step_id="mapping", data_schema=vol.Schema(schema_dict))