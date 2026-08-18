import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN

class LGACConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self.host = None
        self.port = None
        self.temp_step = None
        self.has_heat = True
        self.discovered_ids = []

    async def async_step_user(self, user_input=None):
        """STEP 1: 기본 통신 정보 및 난방 옵션 입력"""
        if user_input is not None:
            self.host = user_input["host"]
            self.port = user_input["port"]
            self.temp_step = user_input["temp_step"]
            self.has_heat = user_input["has_heat"] # 🌟 난방 유무 토글 값 저장
            
            # 스캐닝 5초 진행
            from .config_flow import async_sniff_rs485
            self.discovered_ids = await async_sniff_rs485(self.host, self.port, timeout=5.0)
            return await self.async_step_mapping()

        data_schema = vol.Schema({
            vol.Required("host", default="192.168.0."): str,
            vol.Required("port", default=8899): int,
            vol.Required("temp_step", default=1.0): vol.In({0.5: "0.5도 단위", 1.0: "1.0도 단위"}),
            vol.Required("has_heat", default=True): bool, # 🌟 난방(Heat) 지원 여부 토글 스위치
        })
        return self.async_show_form(step_id="user", data_schema=data_schema)

    async def async_step_mapping(self, user_input=None):
        """STEP 2: 엔티티 및 이름 매핑"""
        if user_input is not None:
            mapping_parts = []
            for room_id in self.discovered_ids:
                hw_hex = f"{room_id:02x}"
                entity_val = user_input.get(f"entity_{hw_hex}", f"{room_id + 1:02x}")
                name_val = user_input.get(f"name_{hw_hex}", f"에어컨 {entity_val}")
                mapping_parts.append(f"{entity_val}:{hw_hex}/{name_val}")
            
            manual_mapping = user_input.get("manual_mapping", "").strip()
            if manual_mapping:
                mapping_parts.append(manual_mapping)

            data = {
                "host": self.host,
                "port": self.port,
                "temp_step": self.temp_step,
                "has_heat": self.has_heat, # 🌟 데이터 전송
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
        
        schema_dict[vol.Optional("manual_mapping", default="")] = str

        return self.async_show_form(step_id="mapping", data_schema=vol.Schema(schema_dict))