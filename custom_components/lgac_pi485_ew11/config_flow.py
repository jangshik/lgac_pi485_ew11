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
                
                # 가변 패킷 처리 동기화 루프
                while len(buffer) >= 8:
                    if buffer[0] == 0x80:  # 🌟 제어/명령 패킷 (8바이트)
                        room_id = buffer[3]  # TX3가 실내기 번호
                        discovered.add(room_id)
                        del buffer[:8]
                    elif buffer[0] == 0x10:  # 🌟 상태/응답 패킷 (16바이트)
                        if len(buffer) >= 16:
                            room_id = buffer[4]  # RX4가 실내기 번호
                            discovered.add(room_id)
                            del buffer[:16]
                        else:
                            break  # 데이터가 더 채워질 때까지 대기
                    else:
                        del buffer[0:1]  # 싱크 유실 시 1바이트 쉬프트
            except asyncio.TimeoutError:
                continue
            
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        _LOGGER.error(f"스캐닝 세션 접속 실패 또는 분석 오류: {e}")
        
    return sorted(list(discovered))


class LGACConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.host = None
        self.port = None
        self.temp_step = None
        self.discovered_ids = []

    async def async_step_user(self, user_input=None):
        """STEP 1: 게이트웨이 IP 및 통신 정보 설정"""
        if user_input is not None:
            self.host = user_input["host"]
            self.port = user_input["port"]
            self.temp_step = user_input["temp_step"]
            
            # 다음 매핑 페이지로 진입하기 전 5초간 스캐닝 구동
            self.discovered_ids = await async_sniff_rs485(self.host, self.port, timeout=5.0)
            return await self.async_step_mapping()

        data_schema = vol.Schema({
            vol.Required("host", default="192.168.0."): str,
            vol.Required("port", default=8899): int,
            vol.Required("temp_step", default=1.0): vol.In({0.5: "0.5도 단위 조절", 1.0: "1.0도 단위 조절"}),
        })
        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def async_step_mapping(self, user_input=None):
        """STEP 2: 감지된 기기 매핑 및 한글 이름 커스텀 설정 창"""
        if user_input is not None:
            mapping_parts = []
            
            # 1. 자동 스캔으로 잡힌 기기 처리
            for room_id in self.discovered_ids:
                hex_str = f"{room_id:02x}"
                name = user_input.get(f"name_{hex_str}", f"에어컨 {hex_str}")
                mapping_parts.append(f"{hex_str}:{hex_str}/{name}")
            
            # 2. 수동 주소 지정 칸에 적힌 기기들 처리 (치환 기능 결합)
            # 입력 형식 예시: "00:01/거실, 01:02/안방" 형태로 직접 유연하게 입력 가능
            manual_mapping = user_input.get("manual_mapping", "").strip()
            if manual_mapping:
                mapping_parts.append(manual_mapping)

            final_mapping = ", ".join(mapping_parts)

            data = {
                "host": self.host,
                "port": self.port,
                "temp_step": self.temp_step,
                "mapping": final_mapping
            }
            
            await self.async_set_unique_id(self.host)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=f"LG 에어컨 게이트웨이 ({self.host})", data=data)

        # UI 스키마 동적 정의
        schema_dict = {}
        
        # 만약 스캔된 주소가 있다면 상단에 한글 이름 입력창 배치
        for room_id in self.discovered_ids:
            hex_str = f"{room_id:02x}"
            schema_dict[vol.Required(f"name_{hex_str}", default=f"에어컨 {hex_str.upper()}")] = str
        
        # 🌟 핵심 보완: 자동 스캔에 실패하더라도 수동으로 한 번에 적어 넣을 수 있는 통합 입력 폼 배치
        schema_dict[vol.Optional(
            "manual_mapping", 
            default="00:01/거실 에어컨, 01:02/안방 에어컨"
        )] = str

        # 상단 안내 문구 조립
        if self.discovered_ids:
            description = f"🎉 버스 스니핑 결과 총 {len(self.discovered_ids)}대의 에어컨 실내기가 자동 식별되었습니다!\n"
            description += "각 기기의 대시보드 표시용 이름을 입력해 주세요.\n\n"
        else:
            description = "⚠️ 5초 동안 활성화된 에어컨 패킷이 감지되지 않았습니다. (에어컨이 모두 꺼져있거나 대기 모드일 수 있음)\n"
            description += "아래 [수동 매핑 지정] 칸에 규칙에 맞게 콤마(,)로 구분하여 입력하시면 스캔 없이 즉시 기기가 생성됩니다.\n\n"
            
        description += "**[수동 매핑 입력 가이드]**\n`엔티티번호:실제RS485주소/한글이름` 형태로 작성하시면 요청하신 주소 치환 기법이 자동으로 적용됩니다."

        return self.async_show_form(
            step_id="mapping", 
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"description": description}
        )