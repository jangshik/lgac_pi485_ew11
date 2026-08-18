import asyncio
import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    host = entry.data["host"]
    port = entry.data["port"]

    # 소켓 및 감지 상태 저장 장소 초기화
    hass.data[DOMAIN][entry.entry_id] = {
        "discovered_rooms": set(),
        "async_add_entities_fn": None,
        "writer": None
    }

    # 백그라운드 리스너 시작
    hass.loop.create_task(async_packet_listener(hass, entry, host, port))
    
    await hass.config_entries.async_forward_entry_setups(entry, ["climate"])
    return True

async def async_packet_listener(hass: HomeAssistant, entry: ConfigEntry, host: str, port: int):
    """EW11로부터 무한 루프로 패킷을 읽어와 실내기를 자동 감지"""
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            hass.data[DOMAIN][entry.entry_id]["writer"] = writer
            _LOGGER.info(f"Connected to EW11 for auto-discovery sniffing.")

            while True:
                # 버스 특성상 데이터가 조각나서 올 수 있으므로 최소 단위 스트리밍 버퍼 처리 필요
                data = await reader.read(100)
                if not data:
                    break

                # 패킷 파싱 예시 로직 (문서 7페이지 구조 참고)
                # 데이터 예시: 10 02 83 00 00 00... 형태의 바이트 배열 매칭 루프
                # 여기서는 원본 패킷 중 헤더 매칭 구조(예: 헤더가 0x80 0x00 0xA3 이거나 0x10 0x02 등 기종별 구조 확인)
                i = 0
                while i < len(data) - 4:
                    # 응답/태스크 패킷 헤더 구조 감지 (제공해주신 데이터 패턴 기반 맵핑 필요)
                    if data[i] == 0x10 and data[i+1] == 0x02: # 문서 5페이지, 7페이지 데이터 유추 규칙
                        room_id = data[i+3] # 패킷 내 실내기 ID 바이트 인덱스 추출 [cite: 14, 261, 264]
                        
                        entry_data = hass.data[DOMAIN][entry.entry_id]
                        if room_id not in entry_data["discovered_rooms"]:
                            _LOGGER.info(f"🎉 New LG AC Indoor Unit Detected! Room ID: {room_id:02X}")
                            entry_data["discovered_rooms"].add(room_id)
                            
                            # climate 플랫폼에 동적으로 새 기기 추가 트리거
                            if entry_data["async_add_entities_fn"]:
                                from .climate import LGAirConditionerEntity
                                entry_data["async_add_entities_fn"]([
                                    LGAirConditionerEntity(writer, room_id)
                                ])
                    i += 1

        except Exception as e:
            _LOGGER.error(f"Sniffer connection error: {e}. Retrying in 10s...")
            await asyncio.sleep(10)