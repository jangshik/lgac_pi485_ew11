import asyncio
import logging
import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_sniff_rs485(host, port, timeout=5.0):
    """EW11 소켓 패킷 수집 및 실내기 ID 추출 (esphome-lgap 프로토콜 규격 반영)"""
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
                    if buffer[0] == 0x80 or buffer[0] == 0x10:
                        room_idx = 3 if buffer[0] == 0x80 else 4
                        packet_len = 8 if buffer[0] == 0x80 else 16
                        if len(buffer) >= packet_len:
                            discovered.add(buffer[room_idx])
                            del buffer[:packet_len]
                        else:
                            break
                    else:
                        del buffer[0:1]
            except asyncio.TimeoutError:
                continue
            
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
        self.has_heat = True
        self.discovered_ids = []

    async def async_step_user(self, user_input=None):
        """STEP 1: 기본 통신 정보 및 난방 옵션 입력"""
        if user_input is not None:
            self.host = user_input["host"]
            self.port = user_input["port"]
            self.temp_step = user_input["temp_step"]
            # bool 타입은 체크 해제 시 안전하게 False로 바인딩되도록 get 처리
            self.has_heat = user_input.get("has_heat", False) 
            
            # 🌟 [수정 포인트] 내부 함수이므로 import 문을 삭제하고 바로 호출합니다.
            self.discovered_ids = await async_sniff_rs485(self.host, self.port, timeout=5.0)
            return await self.async_step_mapping()

        data_schema = vol.Schema({
            vol.Required("host", default="192.168.0."): str,
            vol.Required("port", default=8899): int,
            vol.Required("temp_step", default=1.0): vol.In({0.5: "0.5도 단위", 1.0: "1.0도 단위"}),
            vol.Required("has_heat", default=True): bool,
        })
        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def async_step_mapping(self, user_input=None):
        """STEP 2: 엔티티 및 이름 매핑"""
        if user_input is not None:
            mapping_parts = []
            for room_id in self.discovered_ids:
                hw_hex = f"{room_id:02x}"
                entity_val = user_input.get(f"entity_{hw_hex}", f"{room_id + 1:02x}")
                name_val = user_input.get(f"name_{hw_hex}", f"에어컨 {entity_val}")
                mapping_parts.append(f"{entity_val}:{hw_hex}/{name_val}")
            
            manual_mapping = user_input.get("manual_mapping", "").strip()
            if manual_mapping:
                mapping_parts.append(manual_mapping)

            data = {
                "host": self.host,
                "port": self.port,
                "temp_step": self.temp_step,
                "has_heat": self.has_heat,
                "mapping": ", ".join(mapping_parts)
            }
            
            await self.async_set_unique_id(self.host)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=f"LG 에어컨 ({self.host})", data=data)

        schema_dict = {}
        for room_id in self.discovered_ids:
            hw_hex = f"{room_id:02x}"
            default_entity = f"{room_id + 1:02x}"
            schema_dict[vol.Required(f"entity_{hw_hex}", default=default_entity)] = str
            schema_dict[vol.Required(f"name_{hw_hex}", default=f"에어컨 {default_entity}")] = str
        
        schema_dict[vol.Optional("manual_mapping", default="01:01/거실 에어컨")] = str

        desc = ("각 기기의 **엔티티 번호**(HA에 생성될 ID)와 **표시 이름**을 설정하세요.\n"
                "(예: 엔티티 번호를 '01'로 지정하면 `climate.lgac_01_cm`으로 생성됩니다.)")

        return self.async_show_form(
            step_id="mapping", 
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"description": desc}
        )