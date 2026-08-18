DOMAIN = "lgac_pi485_ew11"

def calculate_checksum(packet: bytes) -> int:
    """esphome-lgap 체크섬: (sum % 256) XOR 0x55"""
    return (sum(packet) & 0xFF) ^ 0x55

def make_control_packet(room_id: int, mode_hex: int, fan_hex: int, target_temp: float, turn_on: bool) -> bytes:
    """esphome-lgap TX 제어 패킷 생성 (8 bytes)"""
    # TX0: 0x10, TX1: 0x00, TX2: 0xA0
    
    # TX4: 비트1(Write)=1 -> 0x02. 켜는 명령이면 비트0(Power)=1 추가 -> 0x03
    tx4 = 0x03 if turn_on else 0x02
    
    # TX5: 모드(0~2비트) | 풍량(4~6비트)
    tx5 = (mode_hex & 0x07) | ((fan_hex & 0x07) << 4)
    
    # TX6: 설정 온도 전송 공식 (온도 - 15)
    tx6 = int(target_temp) - 15
    if tx6 < 1: tx6 = 1
    if tx6 > 15: tx6 = 15
    
    base_packet = bytearray([0x10, 0x00, 0xA0, room_id, tx4, tx5, tx6])
    base_packet.append(calculate_checksum(base_packet))
    
    return bytes(base_packet)