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
    mapping_str = entry.data.get("room_mapping", "00:01")
    piping_type = entry.data.get("piping_type", "multi")

    # 주소 치환 맵 빌드 {"00": 1, "01": 2}
    mapping_dict = {}
    for item in mapping_str.split(","):
        if ":" in item:
            entity_part, real_part = item.split(":")
            try:
                mapping_dict[entity_part.strip()] = int(real_part.strip(), 16)
            except ValueError:
                continue

    # 엔티티 객체들을 참조하기 위한 딕셔너리 마련
    hass.data[DOMAIN][entry.entry_id] = {
        "writer": None,
        "mapping": mapping_dict,
        "piping_type": piping_type,
        "entities": {}  # {real_room_id: entity_instance}
    }

    # 백그라운드에서 실시간 패킷 리스너 가동
    hass.loop.create_task(async_packet_listener(hass, entry, host, port))

    await hass.config_entries.async_forward_entry_setups(entry, ["climate"])
    return True

async def async_packet_listener(hass: HomeAssistant, entry: ConfigEntry, host: str, port: int):
    """RS485 버스로부터 유입되는 데이터를 실시간 스니핑 및 파싱"""
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            hass.data[DOMAIN][entry.entry_id]["writer"] = writer
            _LOGGER.info(f"Connected to EW11 Stream Reader ({host}:{port})")

            buffer = bytearray()
            while True:
                data = await reader.read(100)
                if not data:
                    _LOGGER.warning("EW11 Connection closed by remote host.")
                    break
                
                buffer.extend(data)

                # LG 에어컨 응답 패킷 프레임 분석 루프
                # 예: 10 02 83 ... 구조나 일반 데이터 프레임 동기화 기법 적용
                while len(buffer) >= 7:
                    # 패킷 헤더 매칭 (원본 문서의 10 02 83 이나 80 00 A3 스트림 인덱싱 규칙 기반)
                    if buffer[0] in [0x10, 0x80]: 
                        # 주소 데이터 유추 바이트 위치 (가장 흔한 인덱스 기반, 기종별 조율 필요)
                        real_room_id = buffer[3] 
                        
                        # 해당 실제 주소를 가진 기기가 내 엔티티 리스트에 있는지 확인
                        entities_map = hass.data[DOMAIN][entry.entry_id]["entities"]
                        if real_room_id in entities_map:
                            target_entity = entities_map[real_room_id]
                            
                            # 추출된 패킷 슬라이스를 해당 엔티티로 넘겨 실시간 갱신 처리
                            # (체크섬 검증 통과 가정을 포함하여 고정 길이 파싱 혹은 가변 처리)
                            target_packet = bytes(buffer[:16]) # 예시 슬라이싱
                            target_entity.update_status_from_packet(target_packet)
                        
                        # 처리한 패킷만큼 버퍼에서 제거
                        del buffer[:16] # 실제 패킷 길이에 맞춤 (예시 16바이트)
                    else:
                        # 싱크가 안 맞으면 헤더를 찾을 때까지 1바이트씩 쉬프트
                        del buffer[0]

        except Exception as e:
            _LOGGER.error(f"Real-time listener connection error: {e}. Reconnecting in 10s...")
            await asyncio.sleep(10)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["climate"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok