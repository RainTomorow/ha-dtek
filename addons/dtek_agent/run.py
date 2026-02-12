import json, re, asyncio, gc, ctypes
from aiohttp import web
from playwright.async_api import async_playwright

def force_cleanup():
    gc.collect()
    try:
        ctypes.CDLL('libc.so.6').malloc_trim(0)
    except:
        pass

async def fetch_dtek(request):
    try:
        data = await request.json()
        region = data.get("region", "kem")
        city = data.get("city")
        street = data.get("street")
        house = data.get("house")
        
        print(f"Fetching: {region} | {street} {house}")
        
        url = f"https://www.dtek-{region}.com.ua/ua/shutdowns"
        ajax = f"https://www.dtek-{region}.com.ua/ua/ajax"
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage", # Saves RAM
                    "--disable-gpu",           # Saves RAM
                    "--disable-infobars",
                    "--window-position=0,0",
                    "--ignore-certificate-errors",
                    "--disable-extensions",
                    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
                ]
            )
            
            ctx = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='uk-UA',
                timezone_id='Europe/Kiev'
            )
            
            await ctx.route("**/*", lambda route: route.abort() 
                if route.request.resource_type in ["image", "media", "font", "stylesheet"] 
                else route.continue_())
            
            await ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            page = await ctx.new_page()
            
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=90000)
                
                try:
                    await page.wait_for_selector('input[name="street"]', timeout=15000)
                    print("Page loaded successfully (Search form found).")
                except:
                    print("Search form missing. Waiting for WAF/Captcha to clear...")
                    try:
                        await page.wait_for_selector('meta[name="csrf-token"]', timeout=30000)
                    except:
                        print(f"WAF Timeout - dumping title: {await page.title()}")
                        return web.json_response({"error": "WAF Timeout"}, status=503)

                csrf = None
                csrf_el = await page.query_selector('meta[name="csrf-token"]')
                if csrf_el:
                    csrf = await csrf_el.get_attribute('content')
                
                if not csrf:
                    content = await page.content()
                    match = re.search(r'"csrf-token":\s*"([^"]+)"', content) or re.search(r'csrfToken\s*=\s*[\'"]([^\'"]+)[\'"]', content)
                    if match: csrf = match.group(1)

                if not csrf:
                    return web.json_response({"error": "No CSRF Token"}, status=500)

                raw_sched = {}
                try:
                    match = re.search(r'DisconSchedule\.fact\s*=\s*({.*?})\s*(?:;|</script>)', await page.content(), re.DOTALL)
                    if match: raw_sched = json.loads(match.group(1))
                except: pass

                house_info = {}
                if street and house:
                    form = {
                        "method": "getHomeNum",
                        "data[0][name]": "street", "data[0][value]": street,
                        "data[1][name]": "house", "data[1][value]": house
                    }
                    if region != "kem" and city:
                        form = {
                            "method": "getHomeNum",
                            "data[0][name]": "city", "data[0][value]": city,
                            "data[1][name]": "street", "data[1][value]": street,
                            "data[2][name]": "house", "data[2][value]": house
                        }

                    resp = await page.evaluate(f'''async (data) => {{
                        const r = await fetch("{ajax}", {{
                            method: "POST",
                            headers: {{
                                "X-CSRF-Token": "{csrf}",
                                "X-Requested-With": "XMLHttpRequest",
                                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
                            }},
                            body: new URLSearchParams(data)
                        }});
                        return await r.json();
                    }}''', form)
                    
                    d_block = resp.get('data', {})
                    house_info = d_block.get(house)
                    
                    if not house_info:
                        for k, v in d_block.items():
                            if str(house).lower() in k.lower():
                                house_info = v
                                break
                    
                    if not house_info: house_info = {}

                return web.json_response({"raw_schedule": raw_sched, "house_info": house_info})

            finally:
                await browser.close()

    except Exception as e:
        print(f"Server Error: {e}")
        return web.json_response({"error": str(e)}, status=500)
    
    finally:
        force_cleanup()
        print("RAM Cleanup executed.")

app = web.Application()
app.router.add_post('/fetch', fetch_dtek)

if __name__ == '__main__':
    print("DTEK Agent listening on port 8080...")
    web.run_app(app, port=8080)