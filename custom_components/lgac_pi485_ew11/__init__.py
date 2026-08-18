import asyncio
import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.components.climate.const import HVACMode, FAN_MEDIUM, FAN_LOW, FAN_HIGH
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["climate", "sensor"]

class LGDeviceState:
    """esphome-lgap의 모든 센서와 제어 상태 정보를 담는 허브 객체"""
    def __init__(self, entity_idx, real_id, name, temp_step, has_heat):
        self.entity_idx = entity_idx
        self.real_id = real_id
        self.name = name
        self.temp_step = temp_step
        self.has_heat = has_heat
        
        # 🌟 기본 제어 상태
        self.is_on = False
        self.hvac_mode = HVACMode.OFF
        self.fan_mode = FAN_MEDIUM
        self.current_temp = 24.0
        self.target_temp = 24.0
        
        # 🌟 esphome-lgap 전체 고급 센서 데이터 리스트 [protocol.md 기반]
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
    has_heat = entry.data.get("has_heat", True) # 🌟 난방 여부 로드

    devices = {}
    for item in mapping_str.split(","):
        if ":" in item:
            entity_val, rest = item.split(":")
            entity_val = entity_val.strip()
            real_id = int(rest.split("/")[0].strip(), 16)
            name = rest.split("/")[1].strip() if "/" in rest else f"에어컨 {entity_val}"
            
            devices[real_id] = LGDeviceState(entity_val, real_id, name, temp_step, has_heat)

    hass.data[DOMAIN][entry.entry_id] = {"devices": devices, "writer": None}
    hass.loop.create_task(ew11_socket_task(hass, entry, host, port))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

# ... (ew11_socket_task 및 async_unload_entry 로직은 이전과 동일하게 유지) ...