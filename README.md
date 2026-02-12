# DTEK Shutdowns Integration

Custom Home Assistant integration for monitoring electricity outages (scheduled and emergency) from DTEK networks in Ukraine.

## Disclaimer
This component is an **unofficial** integration and is not affiliated with, endorsed by, or supported by DTEK. 
All data regarding schedules and outages is retrieved from the official DTEK websites and remains the intellectual property of the respective DTEK regional operators.

**Supports:** Kyiv City, Kyiv Region, Odesa Region, Dnipro Region.

## Features
- **Hybrid Fetching Engine:** - **Primary:** Uses a dedicated **Playwright Agent Add-on** to emulate a real browser and bypass complex WAF/Captchas reliably.
  - **Fallback:** Automatically switches to `cloudscraper` / `curl_cffi` direct scraping if the Agent is unavailable.
- **Smart Group Detection:** Auto-detects your shutdown group based on address (City/Street/House).
- **Emergency Alerts:** Distinguishes between "Scheduled" and "Emergency" outages.
- **Visual Graph:** Optimized configuration for ApexCharts Card.

## Architecture
This integration works best when paired with the **DTEK Playwright Agent** Add-on.
1. **The Integration** asks the **Add-on** to fetch data.
2. **The Add-on** spins up a headless browser, passes the WAF check, and returns clean JSON.
3. If the Add-on fails (or isn't installed), the integration attempts to fetch data directly using python libraries.

## Installation

### 1. Install the Add-on (Recommended)
*Requires Home Assistant OS or Supervised.*
1. Go to **Settings** > **Add-ons** > **Add-on Store**.
2. Click the three dots (top right) > **Repositories**.
3. Add the URL of this repository.
4. Install **DTEK Playwright Agent** (this may take a while).
5. Click **Start** (Watchdog is recommended).
6. Make sure you have enough free RAM (at least 300mb I think) as this agent basically launches a browser for a short time

### 2. Install the Integration
1. Go to **HACS** > **Integrations**.
2. Click the three dots (top right) > **Custom repositories**.
3. Add the URL of this repository.
4. Category: **Integration**.
5. Click **Add**, find "DTEK Shutdowns" in the list, and install.
6. Restart Home Assistant.

## Configuration
1. Go to **Settings** > **Devices & Services**.
2. Click **Add Integration** and search for **DTEK Shutdowns**.
3. **Agent URL**: Leave as `http://localhost:8080` if using the Add-on.
4. Select your **Region**.
5. Select **Shutdown Group**:
   - **By Address (Recommended):** Enter your City (if required), Street, and House Number.
   - **Manual:** Select a specific group (e.g., 4.1) if you know it.

> **Note on Refresh Rates:** Data refreshes approximately every 90 minutes to respect the DTEK servers and avoid IP bans.

## Dashboard Card
Recommended configuration for [ApexCharts Card](https://github.com/RomRider/apexcharts-card). 
This configuration pushes time labels **below** the chart and staggers them into two rows (Outages on bottom, Connections on top) to prevent overlapping.

### Today
```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Today
  show_states: false
graph_span: 24h
stacked: true
span:
  start: day
now:
  show: true
  label: ""
  color: "#304ffe"
apex_config:
  chart:
    height: 80px
  stroke:
    curve: stepline
    width: 0
  legend:
    show: false
  grid:
    show: false
    padding:
      left: 10
      right: 10
      bottom: 40
  xaxis:
    axisBorder:
      show: false
    axisTicks:
      show: false
    labels:
      show: false
    tooltip:
      enabled: false
  yaxis:
    show: false
    labels:
      show: false
  dataLabels:
    enabled: true
    background:
      enabled: false
    dropShadow:
      enabled: true
      top: 1
      left: 1
      blur: 0
      color: "#000000"
      opacity: 1
    style:
      colors:
        - "#ffffff"
      fontSize: 12px
      fontWeight: "900"
    offsetY: 25
    formatter: |
      EVAL:function(value, { w, seriesIndex, dataPointIndex }) {
        if (seriesIndex < 2) return "";
        let timestamp = w.globals.seriesX[seriesIndex][dataPointIndex];
        let date = new Date(timestamp);
        if (date.getHours() === 0 && date.getMinutes() === 0) return "";
        return date.toLocaleTimeString('uk-UA', { hour: '2-digit', minute: '2-digit' });
      }
series:
  - entity: sensor.home_schedule
    name: Power
    color: "#4caf50"
    type: area
    opacity: 1
    data_generator: |
      let schedule = entity.attributes.schedule;
      if (!schedule) return [];
      let today = new Date(); today.setHours(0,0,0,0);
      let endToday = new Date(today); endToday.setHours(23,59,59,999);
      return schedule.map(item => {
        let d = new Date(item.start);
        if (d >= today && d <= endToday) {
          return [d.getTime(), item.value === 0 ? 1 : 0];
        }
        return null;
      }).filter(i => i);
    show:
      datalabels: false
  - entity: sensor.home_schedule
    name: Outage
    color: "#f44336"
    type: area
    opacity: 1
    data_generator: |
      let schedule = entity.attributes.schedule;
      if (!schedule) return [];
      let today = new Date(); today.setHours(0,0,0,0);
      let endToday = new Date(today); endToday.setHours(23,59,59,999);
      return schedule.map(item => {
        let d = new Date(item.start);
        if (d >= today && d <= endToday) {
          return [d.getTime(), item.value === 1 ? 1 : 0];
        }
        return null;
      }).filter(i => i);
    show:
      datalabels: false
  - entity: sensor.home_schedule
    name: To Red
    type: line
    color: transparent
    stroke_width: 0
    data_generator: |
      let schedule = entity.attributes.schedule;
      if (!schedule) return [];
      let today = new Date(); today.setHours(0,0,0,0);
      let endToday = new Date(today); endToday.setHours(23,59,59,999);
      let points = [];
      let lastVal = null;
      schedule.sort((a,b) => new Date(a.start) - new Date(b.start));
      schedule.forEach((item) => {
        let d = new Date(item.start);
        if (d >= today && d <= endToday) {
          if (lastVal !== null && item.value !== lastVal && item.value === 1) {
            points.push([d.getTime(), 0]);  // Bottom Row
          }
          lastVal = item.value;
        }
      });
      return points;
    show:
      datalabels: true
  - entity: sensor.home_schedule
    name: To Green
    type: line
    color: transparent
    stroke_width: 0
    data_generator: |
      let schedule = entity.attributes.schedule;
      if (!schedule) return [];
      let today = new Date(); today.setHours(0,0,0,0);
      let endToday = new Date(today); endToday.setHours(23,59,59,999);
      let points = [];
      let lastVal = null;
      schedule.sort((a,b) => new Date(a.start) - new Date(b.start));
      schedule.forEach((item) => {
        let d = new Date(item.start);
        if (d >= today && d <= endToday) {
          if (lastVal !== null && item.value !== lastVal && item.value === 0) {
            points.push([d.getTime(), 0.25]); // Top Row
          }
          lastVal = item.value;
        }
      });
      return points;
    show:
      datalabels: true
yaxis:
  - show: false
    min: 0
    max: 1
```

### Tomorrow
```yaml
type: custom:apexcharts-card
header:
  show: true
  title: Tomorrow
  show_states: false
graph_span: 24h
stacked: true
span:
  start: day
  offset: +1d
apex_config:
  chart:
    height: 80px
  stroke:
    curve: stepline
    width: 0
  legend:
    show: false
  grid:
    show: false
    padding:
      left: 10
      right: 10
  xaxis:
    axisBorder:
      show: false
    axisTicks:
      show: false
    labels:
      show: false
    tooltip:
      enabled: false
  yaxis:
    show: false
    labels:
      show: false
  dataLabels:
    enabled: true
    background:
      enabled: false
    dropShadow:
      enabled: true
      top: 1
      left: 1
      blur: 0
      color: "#000000"
      opacity: 1
    style:
      colors:
        - "#ffffff"
      fontSize: 12px
      fontWeight: "900"
    offsetY: -2
    formatter: |
      EVAL:function(value, { w, seriesIndex, dataPointIndex }) {
        if (seriesIndex < 2) return "";
        let timestamp = w.globals.seriesX[seriesIndex][dataPointIndex];
        let date = new Date(timestamp);
        if (date.getHours() === 0 && date.getMinutes() === 0) return "";
        return date.toLocaleTimeString('uk-UA', { hour: '2-digit', minute: '2-digit' });
      }
series:
  - entity: sensor.home_schedule
    name: Power
    color: "#4caf50"
    type: area
    opacity: 1
    data_generator: |
      let schedule = entity.attributes.schedule;
      if (!schedule) return [];
      let today = new Date(); 
      today.setDate(today.getDate() + 1); 
      today.setHours(0,0,0,0);
      let endToday = new Date(today); 
      endToday.setHours(23,59,59,999);
      return schedule.map(item => {
        let d = new Date(item.start);
        if (d >= today && d <= endToday) {
          return [d.getTime(), item.value === 0 ? 1 : 0];
        }
        return null;
      }).filter(i => i);
    show:
      datalabels: false
  - entity: sensor.home_schedule
    name: Outage
    color: "#f44336"
    type: area
    opacity: 1
    data_generator: |
      let schedule = entity.attributes.schedule;
      if (!schedule) return [];
      let today = new Date(); 
      today.setDate(today.getDate() + 1); 
      today.setHours(0,0,0,0);
      let endToday = new Date(today); 
      endToday.setHours(23,59,59,999);
      return schedule.map(item => {
        let d = new Date(item.start);
        if (d >= today && d <= endToday) {
          return [d.getTime(), item.value === 1 ? 1 : 0];
        }
        return null;
      }).filter(i => i);
    show:
      datalabels: false
  - entity: sensor.home_schedule
    name: To Red
    type: line
    color: transparent
    stroke_width: 0
    data_generator: |
      let schedule = entity.attributes.schedule;
      if (!schedule) return [];
      let today = new Date(); 
      today.setDate(today.getDate() + 1); 
      today.setHours(0,0,0,0);
      let endToday = new Date(today); 
      endToday.setHours(23,59,59,999);
      let points = [];
      let lastVal = null;
      schedule.sort((a,b) => new Date(a.start) - new Date(b.start));
      schedule.forEach((item) => {
        let d = new Date(item.start);
        if (d >= today && d <= endToday) {
          if (lastVal !== null && item.value !== lastVal && item.value === 1) {
            points.push([d.getTime(), 0.2]); 
          }
          lastVal = item.value;
        }
      });
      return points;
    show:
      datalabels: true
  - entity: sensor.home_schedule
    name: To Green
    type: line
    color: transparent
    stroke_width: 0
    data_generator: |
      let schedule = entity.attributes.schedule;
      if (!schedule) return [];
      let today = new Date(); 
      today.setDate(today.getDate() + 1); 
      today.setHours(0,0,0,0);
      let endToday = new Date(today); 
      endToday.setHours(23,59,59,999);
      let points = [];
      let lastVal = null;
      schedule.sort((a,b) => new Date(a.start) - new Date(b.start));
      schedule.forEach((item) => {
        let d = new Date(item.start);
        if (d >= today && d <= endToday) {
          if (lastVal !== null && item.value !== lastVal && item.value === 0) {
            points.push([d.getTime(), 0.55]); 
          }
          lastVal = item.value;
        }
      });
      return points;
    show:
      datalabels: true
yaxis:
  - show: false
    min: 0
    max: 1