import asyncio
import logging
import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN, calculate_checksum

_LOGGER = logging.getLogger(__name__)

def make_scan_poll_packet(room_id: int) -> bytes:
    base_packet = bytearray([0x10, 0x00, 0xA0, room_id, 0x00, 0x00, 0x00])
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
                    while len(buffer) >= 8:
                        if buffer[0] in [0x80, 0x10]:
                            # 🌟 [치명적 버그 수정] 어떤 패킷이든 기기 주소는 무조건 4번째 바이트(index 3)입니다!
                            room_idx = 3 
                            packet_len = 8 if buffer[0] == 0x80 else 16
                            if len(buffer) >= packet_len:
                                discovered.add(buffer[room_idx])
                                del buffer[:packet_len]
                            else: break
                        else: del buffer[0:1]
                except asyncio.TimeoutError: continue
                except Exception: break

        read_task = asyncio.create_task(read_responses())

        # 0x00 ~ 0x1F 능동 찌르기
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
        self.temp_step = None
        self.update_interval = 10
        self.discovered_ids = []

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self.host = user_input["host"]
            self.port = user_input["port"]
            self.temp_step = user_input["temp_step"]
            self.update_interval = user_input["update_interval"]
            scan_duration = user_input["scan_duration"]
            
            self.discovered_ids = await async_sniff_rs485(self.host, self.port, scan_duration=scan_duration)
            return await self.async_step_mapping()

        data_schema = vol.Schema({
            vol.Required("host", default="192.168.0."): str,
            vol.Required("port", default=8899): int,
            vol.Required("temp_step", default=1.0): vol.In({0.5: "0.5도 단위", 1.0: "1.0도 단위"}),
            vol.Required("update_interval", default=10): vol.In({5: "5초", 10: "10초", 30: "30초", 60: "1분"}),
            vol.Required("scan_duration", default=5.0): vol.In({3.0: "3초 (빠른 스캔)", 5.0: "5초 (기본값)", 10.0: "10초 (정밀 스캔)"}),
        })
        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def async_step_mapping(self, user_input=None):
        if user_input is not None:
            mapping_parts = []
            for room_id in self.discovered_ids:
                hw_hex = f"{room_id:02x}"
                entity_val = user_input.get(f"entity_{hw_hex}", f"{room_id + 1:02x}")
                name_val = user_input.get(f"name_{hw_hex}", f"에어컨 {entity_val}")
                heat_val = "1" if user_input.get(f"heat_{hw_hex}", False) else "0"
                plasma_val = "1" if user_input.get(f"plasma_{hw_hex}", False) else "0"
                
                mapping_parts.append(f"{entity_val}:{hw_hex}/{name_val}/{heat_val}/{plasma_val}")

            manual_mapping = user_input.get("manual_mapping", "").strip()
            if manual_mapping:
                mapping_parts.append(manual_mapping)

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
        for room_id in self.discovered_ids:
            hw_hex = f"{room_id:02x}"
            default_entity = f"{room_id + 1:02x}"
            schema_dict[vol.Required(f"entity_{hw_hex}", default=default_entity)] = str
            schema_dict[vol.Required(f"name_{hw_hex}", default=f"에어컨 {default_entity}")] = str
            schema_dict[vol.Required(f"heat_{hw_hex}", default=False)] = bool
            schema_dict[vol.Required(f"plasma_{hw_hex}", default=False)] = bool
            
        default_manual_value = ""
        if not self.discovered_ids:
            default_manual_value = "01:01/거실 에어컨/0/1, 02:02/안방 에어컨/0/1"

        schema_dict[vol.Optional("manual_mapping", default=default_manual_value)] = str

        if self.discovered_ids:
            desc = f"🎉 **능동 스캔 성공!** 총 {len(self.discovered_ids)}대의 에어컨 실내기가 감지되었습니다.\n\n"
            desc += "누락된 기기가 있다면 맨 아래 '수동 매핑 지정' 칸에 누락된 기기만 적어주세요. (예: `02:02/안방/0/1`)"
        else:
            desc = "⚠️ **안내: 능동 스캔 시간 동안 응답한 에어컨이 없습니다.**\n"
            desc += "아래 입력창에 예시가 채워져 있으니 숫자와 명칭만 수정하여 등록해 주세요.\n\n"
            
        desc += "\n--- \n"
        desc += "**[✍️ 수동 매핑 입력 형식 규칙]**\n"
        desc += "`엔티티번호:통신주소/기기이름/난방유무(1또는0)/플라즈마유무(1또는0)`\n"
        desc += "(여러 대를 한 번에 등록할 때는 쉼표(,)로 구분)"

        return self.async_show_form(
            step_id="mapping", 
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"description": desc}
        )