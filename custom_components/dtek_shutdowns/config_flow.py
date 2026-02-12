import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from .const import DOMAIN, CONF_REGION, CONF_GROUP, CONF_CITY, CONF_STREET, CONF_HOUSE, CONF_AGENT_URL, CONF_GROUP_BY_ADDRESS, GROUP_LIST

REGIONS = {"Kyiv City": "kem", "Kyiv Region": "krem", "Odesa Region": "oem", "Dnipro Region": "dnem"}

class DtekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title=user_input.get(CONF_NAME, "Home"), data=user_input)

        g_opts = {CONF_GROUP_BY_ADDRESS: "By Address"}
        for g in GROUP_LIST: g_opts[g] = g

        sch = vol.Schema({
            vol.Optional(CONF_NAME, default="Home"): str,
            vol.Required(CONF_REGION, default="Kyiv Region"): vol.In(list(REGIONS.keys())),
            vol.Required(CONF_AGENT_URL, default="http://localhost:8080"): str,
            vol.Required(CONF_GROUP, default=CONF_GROUP_BY_ADDRESS): vol.In(g_opts),
            vol.Optional(CONF_CITY): str,
            vol.Optional(CONF_STREET): str,
            vol.Optional(CONF_HOUSE): str,
        })
        return self.async_show_form(step_id="user", data_schema=sch, errors=errors)