DOMAIN = "lgac_pi485_ew11"

def calculate_checksum(packet: bytes) -> int:
    return (sum(packet) & 0xFF) ^ 0x55

def make_poll_packet(room_id: int) -> bytes:
    """상태 업데이트(Polling) 요청 패킷 (마스터 제어기 헤더 0x00)"""
    base_packet = bytearray([0x00, 0x00, 0xA0, room_id, 0x00, 0x00, 0x00])
    base_packet.append(calculate_checksum(base_packet))
    return bytes(base_packet)