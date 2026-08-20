import asyncio
import logging
import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN, calculate_checksum

_LOGGER = logging.getLogger(__name__)

def make_scan_poll_packet(room_id: int) -> bytes:
    # 🌟 스캔(Polling)은 가장 안전한 00 00 A0 표준을 사용합니다.
    base_packet = bytearray([0x00, 0x00, 0xA0, room_id, 0x00, 0x00, 0x09])
    base_packet.append(calculate_checksum(base_packet))
    return bytes(base_packet)

async def async_sniff_rs485(host, port, scan_duration=5.0):
    discovered = set()
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3.0)
        buffer = bytearray()
        
        async def read_responses():
            while True:
                try:
                    data = await asyncio.wait_for(reader.read(1024), timeout=0.5)
                    if not data: break
                    buffer.extend(data)
                    
                    # 🌟 0x10 검열을 삭제하여 어떤 응답이든 16바이트면 분석합니다.
                    while len(buffer) >= 8:
                        matched = False
                        if len(buffer) >= 16:
                            if buffer[15] == calculate_checksum(buffer[:15]):
                                discovered.add(buffer[4])
                                del buffer[:16]
                                matched = True
                        if not matched and len(buffer) >= 8:
                            if buffer[7] == calculate_checksum(buffer[:7]):
                                del buffer[:8]
                                matched = True
                        if not matched:
                            del buffer[0:1]
                except asyncio.TimeoutError: continue
                except Exception: break

        read_task = asyncio.create_task(read_responses())

        for room_id in range(32):
            try:
                writer.write(make_scan_poll_packet(room_id))
                await writer.drain()
                await asyncio.sleep(0.05)
            except Exception: break

        await asyncio.sleep(max(0.5, scan_duration - 1.6))
        read_task.cancel()
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        _LOGGER.error(f"스마트 스캔 중 오류 발생: {e}")
        
    return sorted(list(discovered))

class LGACConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.host = None
        self.port = None
        self.update_interval = 10
        self.header_type = "legacy" # 🌟 헤더 타입 기본값 저장
        self.discovered_ids = []

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self.host = user_input["host"]
            self.port = user_input["port"]
            self.update_interval = user_input["update_interval"]
            self.header_type = user_input["header_type"] # 🌟 선택한 헤더 방식 저장
            scan_duration = user_input["scan_duration"]
            
            self.discovered_ids = await async_sniff_rs485(self.host, self.port, scan_duration)
            return await self.async_step_mapping()

        # 🌟 UI에 헤더 방식 선택 드롭다운 메뉴 추가
        data_schema = vol.Schema({
            vol.Required("host", default="192.168.0."): str,
            vol.Required("port", default=8899): int,
            vol.Required("update_interval", default=10): vol.In({5: "5초", 10: "10초", 30: "30초", 60: "1분"}),
            vol.Required("header_type", default="legacy"): vol.In({
                "legacy": "레거시 하이브리드 (제어 80 00 A3 / 상태 00 00 A0)",
                "lgap": "LGAP 표준 전용 (제어/상태 모두 00 00 A0)"
            }),
            vol.Required("scan_duration", default=5.0): vol.In({3.0: "3초 (빠른 스캔)", 5.0: "5초 (기본값)", 10.0: "10초 (정밀 스캔)"}),
        })
        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def async_step_mapping(self, user_input=None):
        if user_input is not None:
            mapping_parts = []
            for room_id in self.discovered_ids:
                hw_hex = f"{room_id:02x}"
                entity_val = user_input.get(f"entity_{hw_hex}", f"{room_id:02x}")
                name_val = user_input.get(f"name_{hw_hex}", f"에어컨 {entity_val}")
                heat_val = "1" if user_input.get(f"heat_{hw_hex}", False) else "0"
                plasma_val = "1" if user_input.get(f"plasma_{hw_hex}", False) else "0"
                sys_type = user_input.get(f"type_{hw_hex}", "M")
                
                mapping_parts.append(f"{entity_val}:{hw_hex}/{name_val}/{heat_val}/{plasma_val}/{sys_type}")

            manual_mapping = user_input.get("manual_mapping", "").strip()
            if manual_mapping:
                mapping_parts.append(manual_mapping)

            data = {
                "host": self.host,
                "port": self.port,
                "temp_step": 1.0, 
                "update_interval": self.update_interval,
                "header_type": self.header_type, # 🌟 최종 저장소에 헤더 방식 기록
                "mapping": ", ".join(mapping_parts)
            }
            await self.async_set_unique_id(self.host)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=f"LG 에어컨 ({self.host})", data=data)

        schema_dict = {}
        for room_id in self.discovered_ids:
            hw_hex = f"{room_id:02x}"
            default_entity = f"{room_id:02x}" 
            
            schema_dict[vol.Required(f"entity_{hw_hex}", default=default_entity)] = str
            schema_dict[vol.Required(f"name_{hw_hex}", default=f"에어컨 {default_entity}")] = str
            schema_dict[vol.Required(f"type_{hw_hex}", default="M")] = vol.In({"M": "다배관 (시스템)", "S": "단배관 (가정용)"})
            schema_dict[vol.Required(f"heat_{hw_hex}", default=False)] = bool
            schema_dict[vol.Required(f"plasma_{hw_hex}", default=False)] = bool
            
        default_manual_value = ""
        if not self.discovered_ids:
            default_manual_value = "01:01/거실 에어컨/0/0/M, 02:02/안방 에어컨/0/0/M"

        schema_dict[vol.Optional("manual_mapping", default=default_manual_value)] = str
        desc = "기기 옵션을 설정하세요. 수동 매핑 형식: `엔티티번호:통신주소/기기이름/난방(1/0)/음이온(1/0)/타입(M/S)`"
        return self.async_show_form(step_id="mapping", data_schema=vol.Schema(schema_dict), description_placeholders={"description": desc})