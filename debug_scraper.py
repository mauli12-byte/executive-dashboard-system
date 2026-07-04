import pyodbc
import argparse
import time
import re
import random
import logging
from datetime import datetime
from urllib.parse import quote, unquote
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from rapidfuzz import fuzz
from sentence_transformers import SentenceTransformer, util

logger = logging.getLogger(__name__)

# DB CONNECTION
DB_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=maulimittal\\SQLEXPRESS;"
    "DATABASE=social_listening;"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)

MAX_ATTEMPTS = 3  

# LOAD EMBEDDING MODEL 
_model = None

def get_model():
    global _model
    if _model is None:
        print("Loading embedding model...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        print("Model ready!\n")
    return _model


# DB FUNCTIONS
def get_conn():
    return pyodbc.connect(DB_STRING)


def ensure_columns(conn):
    cursor = conn.cursor()
    for col, dtype in [
        ("LinkedInURL",        "NVARCHAR(500) NULL"),
        ("LinkedInConfidence", "NVARCHAR(20)  NULL"),
        ("LinkedInScore",      "FLOAT         NULL"),
        ("LinkedInCheckedAt",  "DATETIME      NULL"),
    ]:
        cursor.execute(f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.columns
                WHERE object_id = OBJECT_ID('ListedCompaniesExecutives')
                AND name = '{col}'
            )
            ALTER TABLE ListedCompaniesExecutives ADD {col} {dtype}
        """)

    for col, dtype in [
        ("LinkedInURL",        "NVARCHAR(500) NULL"),
        ("LinkedInConfidence", "NVARCHAR(20)  NULL"),
        ("LinkedInScore",      "FLOAT         NULL"),
        ("LinkedInCheckedAt",  "DATETIME      NULL"),
        ("LinkedInAttempts",   "INT           NULL DEFAULT 0"),
    ]:
        cursor.execute(f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.columns
                WHERE object_id = OBJECT_ID('ListedCompanies')
                AND name = '{col}'
            )
            ALTER TABLE ListedCompanies ADD {col} {dtype}
        """)
    conn.commit()

    cursor.execute("""
        UPDATE ListedCompanies
        SET LinkedInAttempts = 0
        WHERE LinkedInAttempts IS NULL
    """)
    conn.commit()
    print("DB columns ready!")


# COMPANY DB FUNCTIONS
def fetch_companies(conn, limit=None):
    cursor = conn.cursor()
    lim    = f"TOP {limit}" if limit else ""
    cursor.execute(f"""
        SELECT {lim}
            CompanyID,
            CompanyName,
            Sector,
            Industry
        FROM ListedCompanies
        WHERE LinkedInURL IS NULL 
        ORDER BY CompanyID ASC
    """)
    return [
        {
            "id":       r[0],
            "name":     r[1] or "",
            "sector":   r[2] or "",
            "industry": r[3] or "",
        }
        for r in cursor.fetchall()
    ]


def save_company_result(conn, company_id, url, score, confidence):
    cursor = conn.cursor()
    save_url = url if url else "NOT_FOUND"

    if url:
        cursor.execute("""
            UPDATE ListedCompanies
            SET LinkedInURL=?, LinkedInConfidence=?,
                LinkedInScore=?, LinkedInCheckedAt=?
            WHERE CompanyID=?
        """, (save_url, confidence, score, datetime.now(), company_id))
    else:
        cursor.execute("""
            UPDATE ListedCompanies
            SET LinkedInURL=?, LinkedInConfidence=?,
                LinkedInScore=?, LinkedInCheckedAt=?,
                LinkedInAttempts = ISNULL(LinkedInAttempts, 0) + 1
            WHERE CompanyID=?
        """, (save_url, confidence, score, datetime.now(), company_id))

    conn.commit()


# NAME / TITLE / COMPANY CLEANER
def clean_name(name):
    name = re.sub(
        r'^\s*(Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?|Shri\.?|Smt\.?|'
        r'Col\.?|Brig\.?|Cmdr\.?|Capt\.?)\s+',
        '', name, flags=re.IGNORECASE
    )
    name = re.sub(
        r'\s+(M\.Sc\.?|B\.Tech\.?|MBA|IAS|IPS|PhD|CA|CFA|'
        r'B\.E\.?|M\.E\.?|M\.Tech\.?)\s*$',
        '', name, flags=re.IGNORECASE
    )
    name = re.sub(r'\s+[A-Z]\.\s+', ' ', name)
    name = re.sub(r'\s+[A-Z]\.\s*$', '', name)
    return ' '.join(name.split()).strip()


def clean_title(title):
    title = re.sub(
        r'\s+(of|for|&|and|-)\s+.*$',
        '', title, flags=re.IGNORECASE
    )
    return title.strip()


def clean_company(company):
    company = re.sub(
        r'\s+(Limited|Ltd\.?|Pvt\.?|Corporation|Inc\.?|Co\.?)\s*$',
        '', company, flags=re.IGNORECASE
    )
    words = company.split()
    return ' '.join(words[:3]).strip()


def build_query(name, company, title):
    n = clean_name(name)
    c = clean_company(company)
    t = clean_title(title)
    return f"{n} {c} {t}".strip()


def clean_company_for_search(company):
    company = re.sub(
        r'\s+(Limited|Ltd\.?|Pvt\.?|Private|Corporation|Corp\.?|Inc\.?|Co\.?|LLP)\s*$',
        '', company, flags=re.IGNORECASE
    )
    words = company.split()
    if len(words) > 4:
        for idx, w in enumerate(words):
            if w.lower() in ("and", "&") and idx >= 2:
                words = words[:idx]
                break
        company = " ".join(words[:4])
    return company.strip()


def build_company_query(company_name, sector):
    c = clean_company_for_search(company_name)
    s = sector.split()[0] if sector else ""
    return f"{c} {s}".strip()


def score_company_match(db_company, profile_name, profile_company, url):
    scores = {}
    candidates = [profile_name, profile_company]
    best_comp  = 0
    for candidate in candidates:
        if candidate:
            f = fuzzy(db_company, candidate)
            e = embed(db_company, candidate)
            score = round(f * 0.5 + e * 0.5, 2)
            best_comp = max(best_comp, score)

    comp_words = clean_company_for_search(db_company).lower().split()
    url_low    = url.lower()
    url_match  = sum(1 for w in comp_words if len(w) > 2 and w in url_low)
    url_score  = round((url_match / len(comp_words)) * 70, 2) if comp_words else 0

    scores["company"] = max(best_comp, url_score)
    final = scores["company"]
    if final >= 75:   conf = "High"
    elif final >= 55: conf = "Medium"
    elif final >= 30: conf = "Low"
    else:             conf = "Not Found"
    return final, conf, scores


def parse_google_title(title_text):
    data = {"name": "", "title": "", "company": ""}
    if not title_text:
        return data
    text = re.sub(r'\s*\|?\s*LinkedIn\s*$', '', title_text, flags=re.IGNORECASE).strip()
    m = re.match(r'^(.+?)\s*[-–]\s*(.+?)\s+at\s+(.+)$', text, re.IGNORECASE)
    if m:
        data["name"]    = m.group(1).strip()
        data["title"]   = m.group(2).strip()
        data["company"] = m.group(3).strip()
        return data
    parts = [p.strip() for p in re.split(r'[|–]', text) if p.strip()]
    if len(parts) >= 3:
        data["name"], data["title"], data["company"] = parts[0], parts[1], parts[2]
    elif len(parts) == 2:
        data["name"], data["title"] = parts[0], parts[1]
    elif parts:
        data["name"] = parts[0]
    return data


def fuzzy(t1, t2):
    if not t1 or not t2:
        return 0
    t1, t2 = t1.lower().strip(), t2.lower().strip()
    return max(
        fuzz.ratio(t1, t2),
        fuzz.partial_ratio(t1, t2),
        fuzz.token_sort_ratio(t1, t2),
        fuzz.token_set_ratio(t1, t2)
    )


def embed(t1, t2):
    if not t1 or not t2:
        return 0
    try:
        model = get_model()
        e1 = model.encode(t1, convert_to_tensor=True)
        e2 = model.encode(t2, convert_to_tensor=True)
        return round(max(0, util.cos_sim(e1, e2).item() * 100), 2)
    except:
        return 0


# SELENIUM SCRAPER
_driver = None


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


def wait_for_captcha_solve(driver, original_url, max_wait=300):
    print("\n" + "!"*60)
    print("  CAPTCHA DETECTED!")
    print("!"*60 + "\n")
    waited   = 0
    interval = 3
    while waited < max_wait:
        time.sleep(interval)
        waited += interval
        if not is_captcha(driver):
            print(f"   CAPTCHA solved! ({waited}s mein)")
            time.sleep(2)
            return True
        if waited % 30 == 0:
            print(f"   Still waiting... ({waited}s / {max_wait}s)")
    print("  CAPTCHA timeout — skipping this search")
    return False


def smart_wait(driver, min_sec=4, max_sec=8):
    delay = random.uniform(min_sec, max_sec)
    print(f"  Waiting {delay:.1f}s...")
    time.sleep(delay)


def get_driver(headless=True):
    global _driver
    if _driver is None:
        print("  Browser starting...")
        options = Options()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_argument("--window-size=1920,1080")
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
        )
        _driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=options
        )
        _driver.execute_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
        )
    return _driver


def close_driver():
    global _driver
    if _driver is not None:
        try:
            _driver.quit()
        except Exception:
            pass
        _driver = None


def clean_url(href):
    if not href:
        return None
    href = href.split("#")[0].split("?")[0].rstrip("/")
    href = re.sub(r'https?://(in\.|www\.)?linkedin', 'https://www.linkedin', href)
    if "/in/" not in href and "/company/" not in href:
        return None
    if "/in/" in href:
        slug = href.split("/in/")[-1]
    else:
        slug = href.split("/company/")[-1]
    if not slug or len(slug) < 3:
        return None
    bad = ["search","feed","login","jobs","pulse","learning","pub/dir","showcase"]
    if any(b in slug.lower() for b in bad):
        return None
    return href


def search_company_linkedin(comp_data, headless=True, max_captcha_wait=60):
    query = build_company_query(comp_data["name"], comp_data["sector"])
    search_url = (
        "https://www.google.com/search?q="
        + quote(f"{query} site:linkedin.com/company")
        + "&num=5&hl=en"
    )
    driver = get_driver(headless=headless)
    try:
        driver.get(search_url)
        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div#search"))
            )
        except:
            time.sleep(3)

        if is_captcha(driver):
            solved = wait_for_captcha_solve(driver, search_url, max_wait=max_captcha_wait)
            if not solved:
                return None, 0, "Not Found", {}

        raw = driver.execute_script("""
            var items = [];
            document.querySelectorAll('div.g').forEach(function(block) {
                var a = block.querySelector('a[href*="linkedin.com/company"]');
                if (!a) return;
                var h3  = block.querySelector('h3');
                var snp = block.querySelector('.VwiC3b,.s3v9rd,.IsZvec,[data-sncf]');
                items.push({
                    url:     a.href || '',
                    title:   h3  ? h3.innerText  : '',
                    snippet: snp ? snp.innerText : block.innerText || ''
                });
            });
            return items;
        """) or []

        if not raw:
            for a in driver.find_elements(By.CSS_SELECTOR, "a[href*='linkedin.com/company']"):
                href = a.get_attribute("href") or ""
                if href:
                    raw.append({"url": href, "title": a.text or "", "snippet": ""})

        smart_wait(driver)

        if not raw:
            return None, 0, "Not Found", {}

        candidates = []
        print(f"  {len(raw)} raw results milen — scoring...")

        for item in raw:
            url = clean_url(item.get("url", ""))
            if not url:
                continue
            if "/company/" not in url:
                continue
            if any(x in url for x in ["search","feed","login","jobs"]):
                continue

            title   = item.get("title",   "")
            snippet = item.get("snippet", "")
            text = re.sub(r'\s*\|?\s*LinkedIn\s*$', '', title, flags=re.IGNORECASE)
            text = re.sub(r':\s*(Overview|About|Posts|Jobs).*$', '', text, flags=re.IGNORECASE)
            profile_name    = text.strip()
            profile_company = text.strip()

            if not profile_name and snippet:
                first_line   = snippet.split("\n")[0]
                profile_name = re.sub(r'\s*\|.*$', '', first_line).strip()

            final, conf, breakdown = score_company_match(
                db_company      = comp_data["name"],
                profile_name    = profile_name,
                profile_company = profile_company,
                url             = url
            )

            print(f"    URL:     {url[:60]}")
            print(f"    Score:   {final}% → {conf}")

            candidates.append({
                "url":       url,
                "score":     final,
                "conf":      conf,
                "breakdown": breakdown
            })

        if not candidates:
            return None, 0, "Not Found", {}

        best = max(candidates, key=lambda x: x["score"])
        print(f"  BEST: {best['url']} | Score: {best['score']}% -> {best['conf']}")

        return best["url"], best["score"], best["conf"], best["breakdown"]

    except Exception as e:
        print(f"  Error: {e}")
        return None, 0, "Not Found", {}


def run_companies(conn, limit, headless=True, max_captcha_wait=60):
    """Companies pipeline"""
    print("\n" + "="*60)
    print("  COMPANIES PIPELINE")
    print("="*60)
    companies = fetch_companies(conn, limit)
    total     = len(companies)
    found     = 0
    not_found = 0
    print(f"\n  DB se {total} Companies jinka LinkedIn URL nahi mila abhi tak "
          f"(aur jo {MAX_ATTEMPTS} attempts se kam try hui hain).\n")
    if not companies:
        print("  Saari eligible companies process ho chuki hain "
              f"(ya unka URL mil gaya, ya {MAX_ATTEMPTS} attempts complete ho gaye)!")
        return
    for i, comp_data in enumerate(companies, 1):
        print(f"\n{'='*60}")
        print(f"  [{i}/{total}] {comp_data['name']}")
        print(f"{'='*60}")
        url, score, conf, breakdown = search_company_linkedin(
            comp_data, headless=headless, max_captcha_wait=max_captcha_wait
        )
        save_company_result(conn, comp_data["id"], url, score, conf)
        if url:
            found += 1
            print(f"\n   SAVED -> {url} | Score: {score}% | Confidence: {conf}")
        else:
            not_found += 1
            print(f"\n   Not Found — attempt count ++1")
    print(f"\n{'='*60}")
    print(f"  Companies Done! Found:{found}/{total}   Not Found:{not_found}/{total}")
    print(f"{'='*60}")

def run_linkedin_enrichment():
    conn = get_conn()
    try:
        ensure_columns(conn)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM ListedCompanies
            WHERE LinkedInURL IS NULL 
        """)
        count = cursor.fetchone()[0]

        if count == 0:
            logger.info("[LINKEDIN] No new companies pending — skipping this run.")
            return

        logger.info(f"[LINKEDIN] {count} new companies pending — processing batch of up to 20.")
        run_companies(conn, limit=20, headless=True, max_captcha_wait=60)

    except Exception as e:
        logger.error(f"[LINKEDIN] Error during scheduled run: {e}")
    finally:
        conn.close()


# MAIN
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode",  default="companies",
                        choices=["companies"],
                        help="Which process?")
    parser.add_argument("--limit", type=int, default=None,
                        help="How many records are there for processing?")
    args = parser.parse_args()
    print("="*60)
    print("  LinkedIn Dynamic Enrichment (manual mode)")
    print(f"  Limit: {args.limit or 'All'}")
    print("="*60)
    conn = get_conn()
    ensure_columns(conn)
    run_companies(conn, args.limit, headless=False, max_captcha_wait=300)
    close_driver()
    conn.close()
    print(f"\n{'='*60}")
    print(f"  Pipeline Complete!")
    print(f"{'='*60}")