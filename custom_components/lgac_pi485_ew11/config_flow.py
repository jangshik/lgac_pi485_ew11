import asyncio
import logging
import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# 🌟 백그라운드 실시간 패킷 스니핑 (약 5초 진행)
async def async_sniff_rs485(host, port, timeout=5.0):
    """EW11 소켓에 연결하여 지정된 시간 동안 패킷을 수집하고 활성화된 실내기 ID를 추출합니다."""
    discovered = set()
    try:
        # 소켓 연결 시도 (최대 3초 대기)
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=3.0)
        end_time = asyncio.get_event_loop().time() + timeout
        buffer = bytearray()
        
        while asyncio.get_event_loop().time() < end_time:
            try:
                # 1초 단위로 끊어서 데이터 수신
                data = await asyncio.wait_for(reader.read(1024), timeout=1.0)
                if not data: break
                buffer.extend(data)
                
                # LG 에어컨 프로토콜 동기화 및 룸 ID 추출
                while len(buffer) >= 8:
                    if buffer[0] in [0x10, 0x80, 0x00]:
                        if len(buffer) >= 16:
                            room_id = buffer[3]
                            discovered.add(room_id) # 중복 없이 방 번호 저장
                            del buffer[:16]
                        else:
                            break
                    else:
                        del buffer[0:1]
            except asyncio.TimeoutError:
                continue # 1초 타임아웃 발생해도 남은 시간 동안 계속 스니핑
            
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        _LOGGER.error(f"스캐닝 중 오류 발생: {e}")
        
    return sorted(list(discovered))


class LGACConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.host = None
        self.port = None
        self.temp_step = None
        self.discovered_ids = []

    # ---------------------------------------------------------
    # STEP 1: 네트워크 정보 입력
    # ---------------------------------------------------------
    async def async_step_user(self, user_input=None):
        if user_input is not None:
            self.host = user_input["host"]
            self.port = user_input["port"]
            self.temp_step = user_input["temp_step"]
            
            # 다음 폼으로 넘어가기 전, 5초 동안 백그라운드 스캐닝 진행
            # (이 동안 HA 화면의 '확인' 버튼은 로딩 스피너 상태가 됩니다)
            self.discovered_ids = await async_sniff_rs485(self.host, self.port, timeout=5.0)
            
            # 스캐닝이 끝나면 이름 입력 단계(STEP 2)로 이동
            return await self.async_step_mapping()

        data_schema = vol.Schema({
            vol.Required("host", default="192.168.0."): str,
            vol.Required("port", default=8899): int,
            vol.Required("temp_step", default=1.0): vol.In({0.5: "0.5도 단위", 1.0: "1.0도 단위"}),
        })
        return self.async_show_form(step_id="user", data_schema=data_schema)

    # ---------------------------------------------------------
    # STEP 2: 감지된 기기 이름 매핑 및 수동 추가
    # ---------------------------------------------------------
    async def async_step_mapping(self, user_input=None):
        if user_input is not None:
            mapping_parts = []
            
            # 1. 자동 검색된 기기들의 한글 이름 포맷팅 ("01:01/거실 에어컨")
            for room_id in self.discovered_ids:
                hex_str = f"{room_id:02x}"
                name = user_input.get(f"name_{hex_str}", f"LG 에어컨 {hex_str}")
                mapping_parts.append(f"{hex_str}:{hex_str}/{name}")
            
            # 2. 스캔에서 누락된 기기 수동 추가 반영
            manual = user_input.get("manual_ids", "")
            if manual:
                for m in manual.split(","):
                    m = m.strip()
                    if m:
                        mapping_parts.append(f"{m}:{m}/수동추가 {m}")

            # __init__.py가 읽을 수 있도록 하나의 문자열로 결합
            final_mapping = ", ".join(mapping_parts)

            data = {
                "host": self.host,
                "port": self.port,
                "temp_step": self.temp_step,
                "mapping": final_mapping
            }
            
            await self.async_set_unique_id(self.host)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=f"LG EW11 Gateway", data=data)

        # -------------------------------------
        # STEP 2 화면 UI 그리기 (동적 폼)
        # -------------------------------------
        schema_dict = {}
        
        # 감지된 기기 수만큼 텍스트 입력창을 동적으로 생성
        for room_id in self.discovered_ids:
            hex_str = f"{room_id:02x}"
            schema_dict[vol.Required(f"name_{hex_str}", default=f"에어컨 {hex_str}")] = str
        
        # 혹시나 전원이 꺼져있어 스캔되지 않은 기기를 위한 수동 추가란
        schema_dict[vol.Optional("manual_ids", default="")] = str

        # 팁 메시지용
        description = f"🎉 총 {len(self.discovered_ids)}대의 에어컨이 감지되었습니다. 각 기기의 이름을 지정해주세요.\n\n"
        description += "스캔되지 않은 에어컨이 있다면 아래 '수동 추가' 칸에 16진수 번호를 쉼표로 구분하여 적어주세요. (예: 03, 0a)"

        return self.async_show_form(
            step_id="mapping", 
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"description": description}
        )