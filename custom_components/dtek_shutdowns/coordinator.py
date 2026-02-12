import logging
import random
import asyncio
import json
import re
import time
from datetime import timedelta, datetime
from dataclasses import dataclass
from typing import Optional
from curl_cffi import requests
import cloudscraper
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
from .const import (
    DOMAIN, CONF_REGION, CONF_GROUP, CONF_CITY, 
    CONF_STREET, CONF_HOUSE, CONF_AGENT_URL, CONF_GROUP_BY_ADDRESS
)

_LOGGER = logging.getLogger(__name__)

BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "uk,en-US;q=0.9,en;q=0.8",
}

@dataclass
class DtekState:
    schedule: list
    current_power: str
    current_group: str
    outage_type: str 
    message_start: str
    message_end: str
    last_update: str
    next_outages: list
    next_connections: list

@dataclass
class SessionCache:
    csrf_token: Optional[str] = None
    cookies: Optional[dict] = None
    created_at: Optional[float] = None
    strategy: Optional[str] = None 
    
    def is_expired(self, max_age_hours: float = 2.0) -> bool:
        if not self.created_at:
            return True
        return (time.time() - self.created_at) > (max_age_hours * 3600)

class DtekCoordinator(DataUpdateCoordinator[DtekState]):
    def __init__(self, hass, config):
        self.refresh_minutes = random.randint(85, 95)
        super().__init__(
            hass, 
            _LOGGER, 
            name=DOMAIN, 
            update_interval=timedelta(minutes=self.refresh_minutes)
        )
        self.config = config
        self.region_code = {
            "Kyiv City": "kem", "Kyiv Region": "krem", 
            "Odesa Region": "oem", "Dnipro Region": "dnem"
        }.get(config.get(CONF_REGION), "kem")
        self.session_cache = SessionCache()
        self.last_failed_time = 0 

    async def _async_update_data(self) -> DtekState:
        session = async_get_clientsession(self.hass)
        url = f"{self.config.get(CONF_AGENT_URL).rstrip('/')}/fetch"
        payload = {
            "region": self.region_code,
            "city": self.config.get(CONF_CITY),
            "street": self.config.get(CONF_STREET),
            "house": self.config.get(CONF_HOUSE)
        }

        for attempt in range(3):
            try:
                async with session.post(url, json=payload, timeout=120) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self.last_failed_time = 0
                        return self._parse_agent_data(data)
            except Exception:
                pass
            
            if attempt < 2:
                await asyncio.sleep(20)

        return await self.hass.async_add_executor_job(self._fetch_fallback_sync)

    def _parse_agent_data(self, data):
        info = data.get("house_info", {})
        raw_sched = data.get("raw_schedule", {})
        grp, pow_stat, out_type, ms, me = "Unknown", "Unknown", "Scheduled", "-", "-"
        
        if info:
            if str(info.get("type", "0")) == "2" or "Екстренні" in str(info.get("sub_type", "")) or "Аварійне" in str(info.get("sub_type", "")):
                out_type, ms, me, pow_stat = "Emergency", info.get("start_date", "-"), info.get("end_date", "-"), "Off"
            else:
                pow_stat = "On"
            reasons = info.get("sub_type_reason", [])
            if reasons: grp = reasons[0]

        if self.config.get(CONF_GROUP) != CONF_GROUP_BY_ADDRESS:
            grp = self.config.get(CONF_GROUP)

        sched, out, conn = [], [], []
        if raw_sched and grp != "Unknown":
            dc = raw_sched.get('data', {})
            tk = grp
            first_val = next(iter(dc.values())) if dc else {}
            if tk not in first_val:
                if f"GPV{tk}" in first_val: tk = f"GPV{tk}"
                elif tk.replace("GPV", "") in first_val: tk = tk.replace("GPV", "")

            sorted_ts = sorted([int(k) for k in dc.keys()])
            for ts in sorted_ts:
                gd = dc.get(str(ts), {}).get(tk, {})
                if not gd: continue
                bd = dt_util.as_local(dt_util.utc_from_timestamp(ts))
                for h in range(1, 25):
                    v = gd.get(str(h), "yes")
                    v1, v2 = (1, 1) if v=="no" else (0, 1) if v=="second" else (1, 0) if v=="first" else (1, 1) if v=="maybe" else (0, 0)
                    sched.append({"start": bd.replace(hour=h-1, minute=0).isoformat(), "value": v1})
                    sched.append({"start": bd.replace(hour=h-1, minute=30).isoformat(), "value": v2})

            now = datetime.now().astimezone()
            if out_type == "Scheduled":
                for b in sched:
                    if datetime.fromisoformat(b["start"]) > now:
                        idx = sched.index(b) - 1
                        if idx >= 0: pow_stat = "Off" if sched[idx]["value"] == 1 else "On"
                        break

            c_idx, pv = -1, 0
            for i, b in enumerate(sched):
                if datetime.fromisoformat(b["start"]) > now: c_idx = i; break
            if c_idx != -1:
                pv = sched[c_idx - 1]["value"]
                for i in range(c_idx, len(sched)):
                    v, ts = sched[i]["value"], sched[i]["start"]
                    if v == 1 and pv == 0: out.append(ts)
                    elif v == 0 and pv == 1: conn.append(ts)
                    pv = v
                    if len(out) >= 4 and len(conn) >= 4: break

        return DtekState(sched, pow_stat, grp.replace("GPV", ""), out_type, ms, me, datetime.now().strftime("%H:%M %d.%m.%Y"), out, conn)

    def _fetch_fallback_sync(self) -> DtekState:
        if self.last_failed_time > 0:
            cooldown_seconds = self.refresh_minutes * 60
            elapsed = time.time() - self.last_failed_time
            if elapsed < cooldown_seconds:
                if self.data: return self.data

        attempts = 3
        for attempt in range(attempts):
            try:
                if self.region_code == "kem":
                    result = self._fetch_kem()
                else:
                    result = self._fetch_non_kem()
                self.last_failed_time = 0
                return result
            except Exception:
                if attempt < attempts - 1:
                    time.sleep(5)
                else:
                    self.last_failed_time = time.time()
                    if self.data: return self.data
                    return DtekState([], "Unknown", "Unknown", "Unknown", "-", "-", "Failed", [], [])

    def _fetch_kem(self) -> DtekState:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )
        return self._execute_fetch_with_session(scraper, "cloudscraper")
        
    def _fetch_non_kem(self) -> DtekState:
        if (self.session_cache.csrf_token and 
            self.session_cache.cookies and 
            not self.session_cache.is_expired()):
            try:
                return self._try_cached_session()
            except Exception:
                self.session_cache = SessionCache()

        try:
            time.sleep(2)
            return self._try_cloudscraper()
        except Exception:
            pass

        try:
            time.sleep(2)
            return self._try_curl_cffi_safari()
        except Exception:
            pass

        try:
            time.sleep(2)
            return self._fetch_kem()
        except Exception:
            pass
             
        raise Exception("All fallback strategies exhausted")

    def _try_cached_session(self) -> DtekState:
        if self.session_cache.strategy == "cloudscraper":
            scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
            )
            for k, v in self.session_cache.cookies.items(): scraper.cookies.set(k, v)
            return self._execute_fetch_with_session(scraper, "cloudscraper", self.session_cache.csrf_token)
        else:
            session = requests.Session(impersonate="safari15_5")
            for k, v in self.session_cache.cookies.items(): session.cookies.set(k, v)
            return self._execute_fetch_with_session(session, "curl_cffi", self.session_cache.csrf_token)

    def _try_cloudscraper(self) -> DtekState:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
        )
        base_url = f"https://www.dtek-{self.region_code}.com.ua/ua/shutdowns"
        r = scraper.get(base_url, timeout=30)
        if r.status_code != 200: raise Exception(f"Status {r.status_code}")
        
        csrf = self._extract_csrf(r.text)
        if csrf:
            self.session_cache = SessionCache(csrf, scraper.cookies.get_dict(), time.time(), "cloudscraper")
        return self._execute_fetch_with_session(scraper, "cloudscraper", csrf)

    def _try_curl_cffi_safari(self) -> DtekState:
        session = requests.Session(impersonate="safari15_5")
        base_url = f"https://www.dtek-{self.region_code}.com.ua/ua/shutdowns"
        r = session.get(base_url, headers=BASE_HEADERS, timeout=30)
        if r.status_code != 200: raise Exception(f"Status {r.status_code}")

        csrf = self._extract_csrf(r.text)
        if csrf:
            self.session_cache = SessionCache(csrf, dict(session.cookies), time.time(), "curl_cffi")
        return self._execute_fetch_with_session(session, "curl_cffi", csrf)

    def _extract_csrf(self, text):
        match = re.search(r'<meta name="csrf-token" content="([^"]+)">', text)
        return match.group(1) if match else None

    def _execute_fetch_with_session(self, session, session_type, csrf_token=None) -> DtekState:
        street = self.config.get(CONF_STREET)
        house = self.config.get(CONF_HOUSE)
        city = self.config.get(CONF_CITY)
        group_conf = self.config.get(CONF_GROUP)
        
        current_group = group_conf if (group_conf and group_conf != CONF_GROUP_BY_ADDRESS) else "Unknown"
        base_url = f"https://www.dtek-{self.region_code}.com.ua/ua/shutdowns"
        ajax_url = f"https://www.dtek-{self.region_code}.com.ua/ua/ajax"
        
        if not csrf_token:
            if session_type == "cloudscraper": r_main = session.get(base_url, timeout=30)
            else: r_main = session.get(base_url, headers=BASE_HEADERS, timeout=30)
            
            if r_main.status_code == 200:
                csrf_token = self._extract_csrf(r_main.text)
                sched_match = re.search(r'DisconSchedule\.fact\s*=\s*({.*?})\s*(?:;|</script>)', r_main.text, re.DOTALL)
                if sched_match: 
                    try: raw_schedule_json = json.loads(sched_match.group(1))
                    except: raw_schedule_json = None
                else: raw_schedule_json = None
            else:
                raw_schedule_json = None

        house_info = None
        if street and house and csrf_token:
            headers = BASE_HEADERS.copy()
            headers.update({
                "X-CSRF-Token": csrf_token,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": base_url
            })
            
            payload = {"method": "getHomeNum"}
            idx = 0
            if self.region_code != "kem" and city:
                payload[f"data[{idx}][name]"] = "city"; payload[f"data[{idx}][value]"] = city; idx+=1
            payload[f"data[{idx}][name]"] = "street"; payload[f"data[{idx}][value]"] = street; idx+=1
            payload[f"data[{idx}][name]"] = "house"; payload[f"data[{idx}][value]"] = house
            
            time.sleep(1)
            try:
                r_ajax = session.post(ajax_url, data=payload, headers=headers, timeout=30)
                if r_ajax.status_code == 200:
                    data = r_ajax.json().get("data", {})
                    house_info = data.get(house)
                    if not house_info:
                        for k, v in data.items():
                            if k.lower() == str(house).lower(): house_info = v; break
                    
                    if house_info:
                        reasons = house_info.get("sub_type_reason", [])
                        if reasons: current_group = reasons[0]
            except Exception:
                pass

        outage_type = "Scheduled"
        msg_start, msg_end, current_power = "-", "-", "Unknown"
        
        if house_info:
            htype = str(house_info.get("type", "0"))
            stype = str(house_info.get("sub_type", ""))
            if htype == "2" or "Екстренні" in stype or "Аварійне" in stype:
                outage_type = "Emergency"
                msg_start = house_info.get("start_date", "-")
                msg_end = house_info.get("end_date", "-")
                current_power = "Off"
            else:
                current_power = "On"

        schedule, next_out, next_conn = [], [], []

        if 'raw_schedule_json' not in locals() or not raw_schedule_json:
             try:
                 r_m = session.get(base_url, headers=BASE_HEADERS, timeout=30)
                 match = re.search(r'DisconSchedule\.fact\s*=\s*({.*?})\s*(?:;|</script>)', r_m.text, re.DOTALL)
                 raw_schedule_json = json.loads(match.group(1)) if match else {}
             except: raw_schedule_json = {}

        if raw_schedule_json and current_group != "Unknown":
            data = raw_schedule_json.get('data', {})
            tk = current_group
            first = next(iter(data.values())) if data else {}
            if tk not in first:
                if f"GPV{tk}" in first: tk = f"GPV{tk}"
                elif tk.replace("GPV", "") in first: tk = tk.replace("GPV", "")
            
            for ts in sorted([int(k) for k in data.keys()]):
                day_data = data.get(str(ts), {}).get(tk, {})
                if not day_data: continue
                bd = dt_util.as_local(dt_util.utc_from_timestamp(ts))
                for h in range(1, 25):
                    v = day_data.get(str(h), "yes")
                    v1, v2 = (1, 1) if v=="no" else (0, 1) if v=="second" else (1, 0) if v=="first" else (1, 1) if v=="maybe" else (0, 0)
                    schedule.append({"start": bd.replace(hour=h-1, minute=0).isoformat(), "value": v1})
                    schedule.append({"start": bd.replace(hour=h-1, minute=30).isoformat(), "value": v2})
            
            now = datetime.now().astimezone()
            if outage_type == "Scheduled":
                for b in schedule:
                    if datetime.fromisoformat(b["start"]) > now:
                        idx = schedule.index(b) - 1
                        if idx >= 0: current_power = "Off" if schedule[idx]["value"] == 1 else "On"
                        break
            
            c_idx, pv = -1, 0
            for i, b in enumerate(schedule):
                if datetime.fromisoformat(b["start"]) > now: c_idx = i; break
            if c_idx != -1:
                pv = schedule[c_idx - 1]["value"]
                for i in range(c_idx, len(schedule)):
                    v, ts = schedule[i]["value"], schedule[i]["start"]
                    if v == 1 and pv == 0: next_out.append(ts)
                    elif v == 0 and pv == 1: next_conn.append(ts)
                    pv = v
                    if len(next_out) >= 4 and len(next_conn) >= 4: break

        return DtekState(
            schedule=schedule,
            current_power=current_power,
            current_group=current_group.replace("GPV", ""),
            outage_type=outage_type,
            message_start=msg_start,
            message_end=msg_end,
            last_update=datetime.now().strftime("%H:%M %d.%m.%Y"),
            next_outages=next_out,
            next_connections=next_conn
        )