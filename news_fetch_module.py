import time
import random
import re
from datetime import datetime, timedelta
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

MAX_ARTICLES_PER_COMPANY = 5


def create_news_driver():
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--window-size=1280,900")
    options.add_argument("--window-position=100,50")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )
    driver.execute_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    )
    return driver


def is_captcha(driver):
    title = driver.title.lower()
    url = driver.current_url.lower()
    page = driver.page_source.lower()

    captcha_signs = [
        "unusual traffic",
        "i'm not a robot",
        "verify you're human",
        "verify you are a human",
        "recaptcha challenge"
    ]
    if any(sign in page for sign in captcha_signs):
        return True
    if "sorry" in title and "google" in title:
        return True
    if "/sorry/" in url:
        return True
    return False


def bring_window_to_front(driver):
    try:
        driver.switch_to.window(driver.current_window_handle)
        driver.maximize_window()
        time.sleep(0.3)
        driver.set_window_size(1280, 900)
    except Exception:
        pass

# DATE PARSING 
def parse_news_date(date_text, reference_now=None):
    """
    Google News date formats handle karta hai:
    - "2 weeks ago", "3 days ago", "5 hours ago", "1 hour ago"
    - "Yesterday"
    - "26 Jun 2026", "9 Mar 2026" (absolute dates)

    Returns: datetime object (ya bahut purani fallback date agar
    parse na ho paaye — taaki woh list mein sabse neeche chala jaaye,
    error na de)
    """
    if reference_now is None:
        reference_now = datetime.now()

    if not date_text:
        return reference_now - timedelta(days=36500)  # bahut purani fallback

    text = date_text.strip().lower()

    # "X minute(s)/hour(s)/day(s)/week(s)/month(s)/year(s) ago"
    m = re.match(r'(\d+)\s*(minute|hour|day|week|month|year)s?\s*ago', text)
    if m:
        num  = int(m.group(1))
        unit = m.group(2)
        if unit == "minute":
            return reference_now - timedelta(minutes=num)
        if unit == "hour":
            return reference_now - timedelta(hours=num)
        if unit == "day":
            return reference_now - timedelta(days=num)
        if unit == "week":
            return reference_now - timedelta(weeks=num)
        if unit == "month":
            return reference_now - timedelta(days=num * 30)
        if unit == "year":
            return reference_now - timedelta(days=num * 365)

    if "yesterday" in text:
        return reference_now - timedelta(days=1)

    if "just now" in text or "moments ago" in text:
        return reference_now

    # Absolute date formats
    date_formats = [
        "%d %b %Y",    # 26 Jun 2025
        "%b %d, %Y",   # Jun 26, 2025
        "%B %d, %Y",   # June 26, 2025
        "%d %B %Y",    # 26 June 2025
        "%Y-%m-%d",    # 2025-06-26
    ]
    cleaned = date_text.strip()
    for fmt in date_formats:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue

    return reference_now - timedelta(days=36500)


def fetch_news_for_company(company_name, max_wait_captcha=90):
    query = f"{company_name} news"
    search_url = (
        "https://www.google.com/search?q="
        + quote(query)
        + "&tbm=nws"
        + "&tbs=sbd:1"
        + "&num=20&hl=en"
    )

    driver = create_news_driver()
    try:
        driver.get(search_url)

        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div#search, div#rso, div#main"))
            )
        except:
            time.sleep(3)

        if is_captcha(driver):
            print("\n" + "!"*60)
            print(f"  CAPTCHA DETECTED for '{company_name}'!")
            print("  See the browser window and solve the captcha manually.")
            print(f"  You have {max_wait_captcha} seconds.")
            print("!"*60 + "\n")

            bring_window_to_front(driver)

            waited = 0
            interval = 3
            while waited < max_wait_captcha:
                time.sleep(interval)
                waited += interval
                if not is_captcha(driver):
                    print(f"  CAPTCHA solved! (in {waited}s)")
                    time.sleep(2)
                    break
                if waited % 15 == 0:
                    print(f"  Still waiting... ({waited}s / {max_wait_captcha}s)")

            if is_captcha(driver):
                print("  CAPTCHA timeout — news is not found.")
                return {"status": "captcha", "articles": []}

        raw = driver.execute_script("""
            var items = [];
            var selectorSets = ['div.SoaBEf','div.WlydOe','div.xuvV6e','div.dbsr','g-card'];
            for (var s = 0; s < selectorSets.length; s++) {
                var blocks = document.querySelectorAll(selectorSets[s]);
                if (blocks.length === 0) continue;
                blocks.forEach(function(block) {
                    var linkEl = block.querySelector('a');
                    if (!linkEl) return;
                    var url = linkEl.href || '';
                    if (!url) return;
                    var headlineEl = block.querySelector(
                        'div[role="heading"], .n0jPhd, .mCBkyc, .JheGif, .nDgy9d'
                    );
                    var headline = headlineEl ? headlineEl.innerText : block.innerText.split('\\n')[0];
                    var sourceEl = block.querySelector('.MgUUmf, .NUnG9d span, cite, .CEMjEf span');
                    var source = sourceEl ? sourceEl.innerText : '';
                    var dateEl = block.querySelector('.OSrXXb, .LfVVr, span.r0bn4c, .ZE0LJd');
                    var dateText = dateEl ? dateEl.innerText : '';
                    if (url && headline) {
                        items.push({
                            url: url, headline: headline.trim(),
                            source: source.trim(), date_text: dateText.trim()
                        });
                    }
                });
                if (items.length > 0) break;
            }
            return items;
        """) or []

        print(f"  Method 1 (structured blocks): {len(raw)} found")

        if not raw:
            raw = driver.execute_script("""
                var items = [];
                var anchors = document.querySelectorAll('#search a, #rso a, #main a');
                anchors.forEach(function(a) {
                    var url = a.href || '';
                    if (!url || url.indexOf('google.com') !== -1) return;
                    if (url.indexOf('webcache') !== -1) return;
                    var text = a.innerText.trim();
                    if (!text || text.length < 15) return;

                    // Parent container ka poora text — usme date
                    // chhupi ho sakti hai (jaise "... . 26 Jun 2025"
                    // ya "... . 2 weeks ago")
                    var container = a.closest('div');
                    var fullText  = container ? container.innerText : text;

                    items.push({
                        url: url, headline: text,
                        source: '', full_text: fullText
                    });
                });
                return items;
            """) or []
            print(f"  Method 2 (fallback link-scan): {len(raw)} found")

            date_patterns = [
                r'(\d+\s*(?:minute|hour|day|week|month|year)s?\s*ago)',
                r'(yesterday)',
                r'(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})',   # "26 Jun 2025"
            ]
            for item in raw:
                full_text = item.get("full_text", "")
                date_text = ""
                for pattern in date_patterns:
                    m = re.search(pattern, full_text, re.IGNORECASE)
                    if m:
                        date_text = m.group(1)
                        break
                item["date_text"] = date_text

        results = []
        seen_urls = set()
        for item in raw:
            url = item.get("url", "").split("&")[0]
            headline = item.get("headline", "").strip()
            if not url or not headline or url in seen_urls:
                continue
            seen_urls.add(url)

            date_text = item.get("date_text", "")
            parsed_date = parse_news_date(date_text)

            results.append({
                "headline":  headline[:500],
                "source":    item.get("source", "")[:255],
                "url":       url[:500],
                "date_text": date_text,
                "_sort_date": parsed_date,
            })

        # EXPLICIT SORT
        results.sort(key=lambda x: x["_sort_date"], reverse=True)

        for r in results:
            del r["_sort_date"]

        return {"status": "ok", "articles": results[:MAX_ARTICLES_PER_COMPANY]}

    except Exception as e:
        return {"status": "error", "message": str(e), "articles": []}

    finally:
        driver.quit()