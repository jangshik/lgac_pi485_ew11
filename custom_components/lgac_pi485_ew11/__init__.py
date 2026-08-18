import asyncio
import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.climate.const import HVACMode, FAN_MEDIUM, FAN_LOW, FAN_HIGH
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# 에어컨(climate)과 각종 센서(sensor)를 동시에 로드하도록 지정
PLATFORMS = ["climate", "sensor"]

class LGDeviceState:
    """esphome-lgap의 모든 센서와 제어 상태 정보를 담는 허브 객체"""
    def __init__(self, entity_idx, real_id, name, temp_step, has_heat):
        self.entity_idx = entity_idx
        self.real_id = real_id
        self.name = name
        self.temp_step = temp_step
        self.has_heat = has_heat
        
        # 기본 제어 상태
        self.is_on = False
        self.hvac_mode = HVACMode.OFF
        self.fan_mode = FAN_MEDIUM
        self.current_temp = 24.0
        self.target_temp = 24.0
        
        # esphome-lgap 전체 고급 센서 데이터 리스트 [protocol.md 기반]
        self.error_code = 0          # RX5
        self.swing_state = False     # RX6 bit3 (Auto Swing)
        self.pipe_in = 0.0           # RX9 (Pipe In Temp)
        self.pipe_out = 0.0          # RX10 (Pipe Out Temp)
        self.zone_active_load = 0    # RX11 (Dynamic Active Load)
        self.zone_power_flag = 0     # RX12 (Power state boolean)
        self.zone_design_load = 0    # RX13 (Rated Capacity Weight)
        self.odu_total_load = 0      # RX14 (Compressor System Load)
        self.child_lock = False      # RX1 bit2 (Control Lock Status)
        self.plasma_ion = False      # RX1 bit4 (Plasma Ion Status)
        
        self._listeners = []

    def register_listener(self, listener):
        self._listeners.append(listener)

    def update_from_packet(self, packet: bytes):
        """16바이트 응답 패킷의 모든 지표를 역산 파싱"""
        if len(packet) < 16 or packet[0] != 0x10: return
        try:
            # RX1 비트 마스킹
            self.is_on = bool(packet[1] & 0x01)
            self.child_lock = bool(packet[1] & 0x04)
            self.plasma_ion = bool(packet[1] & 0x10)
            
            # RX5 에러코드
            self.error_code = packet[5]
            
            # RX6 모드 / 스윙 / 풍속
            mode_raw = packet[6] & 0x07
            self.swing_state = bool(packet[6] & 0x08)
            fan_raw = (packet[6] >> 4) & 0x07
            
            # RX7, RX8 온도 공식 변환
            self.target_temp = float((packet[7] & 0x0F) + 15)
            self.current_temp = float((192 - packet[8]) / 3.0)
            
            # RX9, RX10 배관 온도 공식 변환
            self.pipe_in = float((192 - packet[9]) / 3.0)
            self.pipe_out = float((192 - packet[10]) / 3.0)
            
            # RX11 ~ RX14 LonWorks 매핑 지표
            self.zone_active_load = packet[11]
            self.zone_power_flag = packet[12]
            self.zone_design_load = packet[13]
            self.odu_total_load = packet[14]

            # HVAC 모드 확정
            if not self.is_on:
                self.hvac_mode = HVACMode.OFF
            else:
                if mode_raw == 0: self.hvac_mode = HVACMode.COOL
                elif mode_raw == 1: self.hvac_mode = HVACMode.DRY
                elif mode_raw == 2: self.hvac_mode = HVACMode.FAN_ONLY
                elif mode_raw == 4: self.hvac_mode = HVACMode.HEAT
                else: self.hvac_mode = HVACMode.AUTO
                
                # 풍속 확정
                if fan_raw == 1: self.fan_mode = FAN_LOW
                elif fan_raw == 2: self.fan_mode = FAN_MEDIUM
                elif fan_raw == 3: self.fan_mode = FAN_HIGH
                else: self.fan_mode = "auto"

            # 모든 엔티티 실시간 새로고침 브로드캐스트
            for listener in self._listeners:
                listener()
        except Exception as e:
            _LOGGER.error(f"고급 패킷 분석 오류: {e}")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})
    
    host = entry.data["host"]
    port = entry.data["port"]
    mapping_str = entry.data["mapping"]
    temp_step = entry.data.get("temp_step", 1.0)
    has_heat = entry.data.get("has_heat", True)

    devices = {}
    for item in mapping_str.split(","):
        if ":" in item:
            entity_val, rest = item.split(":")
            entity_val = entity_val.strip()
            real_id = int(rest.split("/")[0].strip(), 16)
            name = rest.split("/")[1].strip() if "/" in rest else f"에어컨 {entity_val}"
            
            # 실내기 번호를 기준으로 중앙 데이터 객체 생성
            devices[real_id] = LGDeviceState(entity_val, real_id, name, temp_step, has_heat)

    hass.data[DOMAIN][entry.entry_id] = {
        "devices": devices,
        "writer": None
    }

    # 🌟 [수정 포인트] 아래 정의된 함수명인 ew11_socket_task와 정확히 매칭하여 태스크 실행
    hass.loop.create_task(ew11_socket_task(hass, entry, host, port))
    
    # climate.py와 sensor.py를 한 번에 실행
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def ew11_socket_task(hass: HomeAssistant, entry: ConfigEntry, host: str, port: int):
    """EW11 스트림 소켓 감시 및 중앙 장치 분배 핸들러"""
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            hass.data[DOMAIN][entry.entry_id]["writer"] = writer
            _LOGGER.info(f"Connected to EW11 Stream Handler ({host}:{port})")

            buffer = bytearray()
            while True:
                data = await reader.read(1024)
                if not data: break
                buffer.extend(data)

                while len(buffer) >= 8:
                    if buffer[0] == 0x80 or buffer[0] == 0x10:
                        room_idx = 3 if buffer[0] == 0x80 else 4
                        packet_len = 8 if buffer[0] == 0x80 else 16
                        
                        if len(buffer) >= packet_len:
                            # 수신된 패킷이 0x10(상태 응답)일 경우 해당 기기 객체에 파싱 지시
                            if buffer[0] == 0x10:
                                real_id = buffer[room_idx]
                                devices = hass.data[DOMAIN][entry.entry_id]["devices"]
                                if real_id in devices:
                                    devices[real_id].update_from_packet(bytes(buffer[:16]))
                            
                            del buffer[:packet_len]
                        else:
                            break
                    else:
                        del buffer[0:1]
        except Exception as e:
            _LOGGER.error(f"EW11 TCP 소켓 연결 끊어짐 세션 재시도 (10초 대기): {e}")
            await asyncio.sleep(10)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok