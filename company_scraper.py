import time
import re
from bs4 import BeautifulSoup


def _get_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def _is_garbage_description(text: str) -> bool:
    """Address ya garbage text filter karo."""
    bad_patterns = [
        r"^\s*address\s*:",           # "Address : ..."
        r"^\s*\d+",                    # Number se shuru (pin code etc)
        r"floor|sector \d+|plot no",   # Address keywords
        r"google reviews",
        r"wikipedia",
        r"\d{6}",                      # PIN code
        r"@|\.com|\.in\b",            # Email/website
    ]
    text_lower = text.lower()
    for pattern in bad_patterns:
        if re.search(pattern, text_lower):
            return True
    return False


def _scrape_google(driver, company_name: str) -> dict:
    
    data = {}

    url = (
        "https://www.google.com/search?q="
        + company_name.replace(" ", "+")
        + "+company&hl=en&gl=in"
    )
    print(f"[SCRAPER] Google: {url}")
    driver.get(url)
    time.sleep(3)

    soup = BeautifulSoup(driver.page_source, "html.parser")

    #Structured data
    for tag in soup.find_all(attrs={"data-attrid": True}):
        attrid = tag.get("data-attrid", "").lower()
        text = re.sub(r"^[^:]+:\s*", "", tag.get_text(separator=" ").strip()).strip()

        if not text or len(text) > 300:
            continue

        bad_kw = ["yahoo", "http", "dashboard", "www", "search", "finance."]
        is_bad = any(b in text.lower() for b in bad_kw)

        if "founded" in attrid and not data.get("founded"):
            data["founded"] = text

        elif "headquarter" in attrid and not data.get("headquarters"):
            data["headquarters"] = text

        elif "employee" in attrid and not data.get("employees"):
            data["employees"] = text

        elif "industry" in attrid and not data.get("sector") and not is_bad:
            if len(text) < 80:
                data["sector"] = text

        elif "description" in attrid and not data.get("description"):
            if not _is_garbage_description(text) and len(text) > 60:
                data["description"] = text

    if not data.get("description"):
        for div in soup.find_all("div", class_=re.compile(r"kno-rdesc|LGOjhe")):
            for span in div.find_all("span"):
                text = span.get_text(separator=" ").strip()
                if (len(text) > 80
                        and not _is_garbage_description(text)):
                    data["description"] = text
                    break
            if data.get("description"):
                break

    #Description fallback
    if not data.get("description"):
        candidates = []
        for tag in soup.find_all(["span", "div"]):
            text = tag.get_text(separator=" ").strip()
            if (80 < len(text) < 600
                    and not _is_garbage_description(text)
                    and tag.find("a") is None):   # link wale skip
                candidates.append(text)
        if candidates:
            # Sabse lamba meaningful text lo
            best = max(candidates, key=len)
            data["description"] = best

    print(f"[SCRAPER] Google result: {data}")
    return data


def _scrape_yahoo_listed(driver, company_name: str) -> dict:
    
    data = {}
    try:
        search_url = (
            "https://finance.yahoo.com/search/?query="
            + company_name.replace(" ", "+")
        )
        print(f"[SCRAPER] Yahoo search: {search_url}")
        driver.get(search_url)
        time.sleep(3)

        soup = BeautifulSoup(driver.page_source, "html.parser")

        quote_url = None
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/quote/" in href:
                label = a.get_text().strip().lower()
                name_lower = company_name.lower()
                
                words = name_lower.split()
                if any(w in label for w in words if len(w) > 3):
                    if href.startswith("/"):
                        quote_url = "https://finance.yahoo.com" + href.split("?")[0]
                    else:
                        quote_url = href.split("?")[0]
                    break

        if not quote_url:
            print("[SCRAPER] Yahoo: No matching quote found — skipping")
            return data

        profile_url = quote_url.rstrip("/") + "/profile/"
        print(f"[SCRAPER] Yahoo profile: {profile_url}")
        driver.get(profile_url)
        time.sleep(3)

        soup2 = BeautifulSoup(driver.page_source, "html.parser")
        page_text = soup2.get_text(separator="\n")

        sector_m = re.search(r"Sector\s*\n([^\n]+)", page_text)
        if sector_m:
            val = sector_m.group(1).strip()
            if val and len(val) < 60:
                data["sector"] = val

        industry_m = re.search(r"Industry\s*\n([^\n]+)", page_text)
        if industry_m:
            val = industry_m.group(1).strip()
            if val and len(val) < 80:
                data["industry"] = val

        emp_m = re.search(r"Full[- ]?Time Employees\s*\n([^\n]+)", page_text)
        if emp_m:
            val = emp_m.group(1).strip()
            if val:
                data["employees"] = val

        # Description
        best_desc = ""
        for p in soup2.find_all("p"):
            text = p.get_text(separator=" ").strip()
            if len(text) > len(best_desc) and len(text) > 100:
                if not _is_garbage_description(text):
                    best_desc = text
        if best_desc:
            data["description"] = best_desc

        data["yahoo_url"] = quote_url
        print(f"[SCRAPER] Yahoo result: {data}")

    except Exception as e:
        print(f"[SCRAPER] Yahoo error: {e}")

    return data


def scrape_company_data(company_name: str) -> dict:
   
    result = {}
    driver = None

    try:
        driver = _get_driver()

        # Step 1: Google (description, founded, HQ, sector)
        google_data = _scrape_google(driver, company_name)
        result.update(google_data)

        # Step 2: Yahoo Finance
        time.sleep(1)
        yahoo_data = _scrape_yahoo_listed(driver, company_name)
        for k, v in yahoo_data.items():
            
            if k in ("sector", "industry", "employees", "yahoo_url", "description"):
                if v:
                    result[k] = v
            elif k not in result:
                result[k] = v

    except Exception as e:
        print(f"[SCRAPER] Fatal error: {e}")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    # Clean founded year
    if result.get("founded"):
        yr = re.search(r"\b(1[89]\d{2}|20[012]\d)\b", result["founded"])
        result["founded_year"] = yr.group(1) if yr else result["founded"]
        del result["founded"]

    # Clean employees
    if result.get("employees"):
        result["employees"] = re.sub(
            r"employees?", "", result["employees"], flags=re.IGNORECASE
        ).strip()

    print(f"\n[SCRAPER] FINAL for '{company_name}': {result}")
    return result


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python company_scraper.py <company name>")
        print('Example: python company_scraper.py "Reliance Industries"')
    else:
        company = " ".join(sys.argv[1:])
        scrape_company_data(company)