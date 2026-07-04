"""
executive_linkedin_scraper_hybrid.py
Hybrid: Fast Search + Sentence Embeddings for better matching
Only uses embeddings when fuzzy match is below threshold
"""

import pyodbc
import time
import re
import logging
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import quote_plus

# Install: pip install rapidfuzz sentence-transformers
from rapidfuzz import fuzz

# Sentence embedding - optional, load only once
try:
    from sentence_transformers import SentenceTransformer, util
    model = SentenceTransformer('all-MiniLM-L6-v2')
    USE_EMBEDDINGS = True
    print(" Sentence embedding model loaded")
except:
    model = None
    USE_EMBEDDINGS = False
    print(" Sentence embedding not available (install sentence-transformers)")

# CONFIGURATION
DB_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=maulimittal\\SQLEXPRESS;"
    "DATABASE=social_listening;"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)

HEADLESS_MODE = True
SEARCH_DELAY = 1
MAX_SEARCH_RESULTS = 5
SCHEDULER_PER_RUN_LIMIT = 20

# LOGGING 
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# DATABASE FUNCTIONS

def get_conn():
    return pyodbc.connect(DB_STRING)

def fetch_executives(conn, limit=None):
    cursor = conn.cursor()
    top_clause = f"TOP {limit}" if limit else ""
    
    query = f"""
        SELECT {top_clause}
            e.ExecutiveID,
            e.Name,
            e.Title,
            c.CompanyName,
            e.LinkedInURL
        FROM ListedCompaniesExecutives e
        INNER JOIN ListedCompanies c ON e.CompanyID = c.CompanyID
        WHERE (e.LinkedInURL IS NULL OR e.LinkedInURL = '')
        ORDER BY e.ExecutiveID
    """
    
    cursor.execute(query)
    executives = []
    for row in cursor.fetchall():
        executives.append({
            "id": row[0],
            "name": row[1] if row[1] else "",
            "title": row[2] if row[2] else "",
            "company": row[3] if row[3] else "",
            "linkedin_url": row[4] if row[4] else ""
        })
    
    logger.info(f" Found {len(executives)} NEW executives needing LinkedIn URLs")
    return executives

def update_executive(conn, executive_id, linkedin_url, confidence_score=50.0, methods_used=""):
    cursor = conn.cursor()
    
    if confidence_score >= 80:
        confidence_text = "High"
    elif confidence_score >= 50:
        confidence_text = "Medium"
    else:
        confidence_text = "Low"
    
    query = """
        UPDATE ListedCompaniesExecutives
        SET 
            LinkedInURL = ?,
            LinkedInConfidence = ?,
            LinkedInScore = ?,
            LinkedInSource = ?,
            LinkedInCheckedAt = GETDATE()
        WHERE ExecutiveID = ?
    """
    
    try:
        cursor.execute(query, linkedin_url, confidence_text, confidence_score, f"Hybrid_{methods_used}", executive_id)
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating: {str(e)}")
        conn.rollback()
        return False

def update_not_found(conn, executive_id):
    cursor = conn.cursor()
    query = """
        UPDATE ListedCompaniesExecutives
        SET 
            LinkedInURL = 'Not Found',
            LinkedInConfidence = 'Low',
            LinkedInScore = 0,
            LinkedInSource = 'Hybrid',
            LinkedInCheckedAt = GETDATE()
        WHERE ExecutiveID = ?
        AND (LinkedInURL IS NULL OR LinkedInURL = '')
    """
    try:
        cursor.execute(query, executive_id)
        conn.commit()
        return True
    except:
        return False

def get_pending_count(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) 
        FROM ListedCompaniesExecutives e
        WHERE (e.LinkedInURL IS NULL OR e.LinkedInURL = '')
    """)
    return cursor.fetchone()[0]

def get_not_found_count(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) 
        FROM ListedCompaniesExecutives e
        WHERE e.LinkedInURL = 'Not Found'
    """)
    return cursor.fetchone()[0]

# SELENIUM SETUP
_driver = None

def get_driver():
    global _driver
    if _driver is None:
        logger.info(" Starting Chrome browser...")
        options = Options()
        
        if HEADLESS_MODE:
            options.add_argument("--headless=new")
        
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
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
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        
        logger.info(" Browser started successfully")
    
    return _driver

def close_driver():
    global _driver
    if _driver:
        _driver.quit()
        _driver = None
        logger.info("Browser closed")

# SEARCH FUNCTIONS 

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text.lower()

def extract_name_parts(name):
    if not name:
        return {"first": "", "last": ""}
    
    name = re.sub(r'^(Mr\.|Ms\.|Mrs\.|Dr\.|Prof\.)\s*', '', name, flags=re.IGNORECASE)
    parts = name.strip().split()
    
    return {
        "first": parts[0] if parts else "",
        "last": parts[-1] if len(parts) > 1 else ""
    }

def fuzzy_match_score(name1, name2):
    if not name1 or not name2:
        return 0
    
    name1_clean = clean_text(name1)
    name2_clean = clean_text(name2)
    
    if name1_clean == name2_clean:
        return 100
    
    return fuzz.token_sort_ratio(name1_clean, name2_clean)

def semantic_match_score(text1, text2):
    """Sentence embedding based matching - 0-100 scale"""
    if not USE_EMBEDDINGS or not model or not text1 or not text2:
        return 0.0
    
    try:
        # Encode texts
        emb1 = model.encode(text1, convert_to_tensor=True)
        emb2 = model.encode(text2, convert_to_tensor=True)
        
        # Calculate similarity
        similarity = util.pytorch_cos_sim(emb1, emb2)
        return float(similarity[0][0]) * 100  # Convert to 0-100
    except:
        return 0.0

def search_google_fast(driver, executive):
    name = executive['name']
    company = executive['company']
    title = executive['title']
    
    search_queries = [
        f'site:linkedin.com/in/ "{name}" "{company}"',
        f'"{name}" "{company}" LinkedIn',
    ]
    
    all_results = []
    
    for query in search_queries:
        google_url = f"https://www.google.com/search?q={quote_plus(query)}&num=5"
        
        try:
            driver.get(google_url)
            time.sleep(1.5)
            
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "h3"))
            )
            
            results = driver.find_elements(By.CSS_SELECTOR, "a h3")
            
            for result in results[:5]:
                try:
                    parent = result.find_element(By.XPATH, "./..")
                    link = parent.get_attribute("href")
                    
                    if link and "linkedin.com/in/" in link:
                        clean_url = link.split('?')[0]
                        title_text = result.text.strip()
                        
                        all_results.append({
                            "url": clean_url,
                            "title": title_text
                        })
                except:
                    continue
                    
        except Exception as e:
            continue
        
        if len(all_results) >= 3:
            break
    
    return all_results

def calculate_confidence_hybrid(executive, result):
    """
    Hybrid confidence: Fuzzy + Semantic (if available)
    Semantic only used when fuzzy score is low
    """
    name = executive['name']
    company = executive['company']
    title = executive['title']
    
    title_text = result['title']
    url = result['url']
    
    # Extract username from URL
    url_match = re.search(r'linkedin\.com/in/([\w-]+)', url)
    url_username = url_match.group(1) if url_match else ""
    url_username_clean = url_username.replace('-', ' ').replace('_', ' ')
    
    scores = []
    methods_used = []
    
    # 1. Fuzzy: Match name with title text
    name_fuzzy = fuzzy_match_score(name, title_text)
    if name_fuzzy > 30:
        scores.append(name_fuzzy)
        methods_used.append("fuzzy")
    
    # 2. Fuzzy: Match name with URL username
    url_fuzzy = fuzzy_match_score(name, url_username_clean)
    if url_fuzzy > 30:
        scores.append(url_fuzzy)
        methods_used.append("url_match")
    
    # 3. Fuzzy: Match company with title
    company_fuzzy = fuzzy_match_score(company, title_text)
    if company_fuzzy > 30:
        scores.append(company_fuzzy * 0.8)
        methods_used.append("company")
    
    # 4. Fuzzy: Match title with title text
    if title:
        title_fuzzy = fuzzy_match_score(title, title_text)
        if title_fuzzy > 30:
            scores.append(title_fuzzy * 0.6)
            methods_used.append("title")
    
    # 5. SEMANTIC: Use only if fuzzy scores are low (below 60)
    fuzzy_avg = sum(scores) / len(scores) if scores else 0
    
    if USE_EMBEDDINGS and fuzzy_avg < 60:
        executive_context = f"{name} {company} {title}"
        result_context = f"{title_text} {url_username_clean}"
        
        semantic_score = semantic_match_score(executive_context, result_context)
        if semantic_score > 30:
            scores.append(semantic_score * 0.7)
            methods_used.append("semantic")
    
    # 6. Check if name appears in URL (quick check)
    name_parts = extract_name_parts(name)
    if name_parts['first'] and name_parts['last']:
        url_lower = url.lower()
        if name_parts['first'].lower() in url_lower and name_parts['last'].lower() in url_lower:
            scores.append(90)
            methods_used.append("url_pattern")
    
    if not scores:
        return 0.0, "none"
    
    weights = {
        "fuzzy": 1.0,
        "url_match": 0.9,
        "company": 0.7,
        "title": 0.6,
        "semantic": 0.8,
        "url_pattern": 1.0
    }
    
    weighted_sum = 0
    weight_sum = 0
    
    for method, score in zip(methods_used, scores):
        weight = weights.get(method, 0.5)
        weighted_sum += score * weight
        weight_sum += weight
    
    final_score = weighted_sum / weight_sum if weight_sum > 0 else 0
    
    methods_str = ",".join(set(methods_used))
    
    return final_score, methods_str

def smart_match_hybrid(executive, search_results):
    if not search_results:
        return None, 0.0, "none"
    
    best_match = None
    best_score = 0.0
    best_methods = "none"
    
    for result in search_results:
        score, methods = calculate_confidence_hybrid(executive, result)
        
        if score > best_score:
            best_score = score
            best_match = result['url']
            best_methods = methods
    
    if best_score >= 40:
        return best_match, round(best_score, 2), best_methods
    else:
        return None, round(best_score, 2), best_methods

# MAIN ENRICHMENT

def enrich_executive(executive):
    logger.info("=" * 50)
    logger.info(f"Processing: {executive['name']}")
    logger.info(f"Company: {executive['company']}")
    logger.info(f"Methods: {'Fuzzy + Semantic' if USE_EMBEDDINGS else 'Fuzzy Only'}")
    logger.info("=" * 50)
    
    driver = get_driver()
    
    search_results = search_google_fast(driver, executive)
    
    if not search_results:
        logger.warning(" No search results")
        update_not_found(get_conn(), executive['id'])
        return None
    
    best_url, confidence, methods = smart_match_hybrid(executive, search_results)
    
    conn = get_conn()
    try:
        if best_url and confidence >= 40:
            update_executive(conn, executive['id'], best_url, confidence, methods)
            logger.info(f" Found: {best_url} (Score: {confidence}, Methods: {methods})")
            return best_url
        else:
            update_not_found(conn, executive['id'])
            logger.warning(f" Not found (Score: {confidence}, Methods: {methods})")
            return None
    finally:
        conn.close()

# BATCH PROCESSING 

def process_batch(limit=200):
    conn = get_conn()
    
    try:
        total_pending = get_pending_count(conn)
        total_not_found = get_not_found_count(conn)
        
        logger.info(f" NEW (NULL/empty): {total_pending}")
        logger.info(f" Already 'Not Found': {total_not_found}")
        
        if total_pending == 0:
            logger.info(" No new executives to process!")
            return
        
        executives = fetch_executives(conn, limit)
        
        if not executives:
            return
        
        logger.info(f" Processing {len(executives)} NEW executives")
        logger.info(f" Using: {'Fuzzy + Semantic' if USE_EMBEDDINGS else 'Fuzzy Only'}")
        
        success_count = 0
        not_found_count = 0
        start_time = time.time()
        
        for i, exec_data in enumerate(executives, 1):
            logger.info(f"\n [{i}/{len(executives)}]")
            
            try:
                result = enrich_executive(exec_data)
                if result:
                    success_count += 1
                else:
                    not_found_count += 1
                
                if i < len(executives):
                    time.sleep(SEARCH_DELAY)
                    
            except Exception as e:
                logger.error(f"Error: {str(e)}")
                not_found_count += 1
        
        elapsed = time.time() - start_time
        
        remaining = get_pending_count(conn)
        total_not_found_new = get_not_found_count(conn)
        
        logger.info("\n" + "=" * 60)
        logger.info(f" BATCH SUMMARY")
        logger.info(f"   Found: {success_count}")
        logger.info(f"   Not Found: {not_found_count}")
        logger.info(f"   Total processed: {len(executives)}")
        logger.info(f"   Time: {elapsed:.2f} seconds")
        logger.info(f"   Still NULL/empty: {remaining}")
        logger.info(f"   Total 'Not Found': {total_not_found_new}")
        logger.info("=" * 60)
        
    finally:
        conn.close()
        close_driver()

# >>> YEH NAYA FUNCTION HAI <<<  SCHEDULER ISI KO CALL KAREGA
def run_executive_linkedin_enrichment():
    """
    website_validation_scheduler.py isi function ko import karega
    aur scheduler mein 'interval, hours=24' job ke roop mein
    register karega.

    Koi input() nahi hai isके andar — background mein chalta hai
    bina kisi terminal-interaction ke. Sirf NAYE executives
    (LinkedInURL NULL/empty) process karta hai, max 20 per run.
    """
    conn = get_conn()
    try:
        total_pending = get_pending_count(conn)

        if total_pending == 0:
            logger.info("[EXEC-LINKEDIN] No new executives pending — skipping this run.")
            conn.close()
            return

        logger.info(f"[EXEC-LINKEDIN] {total_pending} new executives pending — "
                    f"processing batch of up to {SCHEDULER_PER_RUN_LIMIT}.")

        executives = fetch_executives(conn, limit=SCHEDULER_PER_RUN_LIMIT)
        conn.close()

        if not executives:
            logger.info("[EXEC-LINKEDIN] Fetch returned 0 records.")
            return

        success_count = 0
        not_found_count = 0

        for i, exec_data in enumerate(executives, 1):
            try:
                logger.info(f"[EXEC-LINKEDIN] [{i}/{len(executives)}] "
                            f"{exec_data['name']} ({exec_data['company']})")
                result = enrich_executive(exec_data)
                if result:
                    success_count += 1
                else:
                    not_found_count += 1
                time.sleep(SEARCH_DELAY)
            except Exception as e:
                logger.error(f"[EXEC-LINKEDIN] Error processing "
                             f"{exec_data.get('name','?')}: {e}")
                not_found_count += 1

        logger.info(f"[EXEC-LINKEDIN] Run complete. "
                    f"Found:{success_count}  Not Found:{not_found_count}")

    except Exception as e:
        logger.error(f"[EXEC-LINKEDIN] Error during scheduled run: {e}")
    finally:
        try:
            close_driver()
        except Exception:
            pass


# DEBUG 

def debug_executive():
    conn = get_conn()
    cursor = conn.cursor()
    
    query = """
        SELECT TOP 1
            e.ExecutiveID,
            e.Name,
            e.Title,
            c.CompanyName
        FROM ListedCompaniesExecutives e
        INNER JOIN ListedCompanies c ON e.CompanyID = c.CompanyID
        WHERE (e.LinkedInURL IS NULL OR e.LinkedInURL = '')
        ORDER BY e.ExecutiveID
    """
    
    cursor.execute(query)
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        print(" No new executives found")
        return
    
    executive = {
        "id": row[0],
        "name": row[1],
        "title": row[2],
        "company": row[3]
    }
    
    print("\n DEBUG")
    print("=" * 50)
    print(f"Name: {executive['name']}")
    print(f"Company: {executive['company']}")
    print(f"Title: {executive['title']}")
    print("=" * 50)
    
    result = enrich_executive(executive)
    print(f"\nResult: {result}")

# MAIN 

if __name__ == "__main__":
    print(" Hybrid LinkedIn URL Enricher")
    print(f" Sentence Embeddings: {' Enabled' if USE_EMBEDDINGS else ' Disabled'}")
    print("=" * 50)
    
    conn = get_conn()
    try:
        total_new = get_pending_count(conn)
        total_not_found = get_not_found_count(conn)
        
        print(f"\n NEW (NULL/empty): {total_new}")
        print(f" Already 'Not Found': {total_not_found}")
        
        if total_new == 0:
            print("\n No new executives to process!")
            conn.close()
            exit(0)
        
        print("\nOptions:")
        print("1. Process batch")
        print("2. Debug single")
        
        choice = input("\nEnter choice: ").strip()
        
        if choice == "1":
            limit = input("Number to process (default: 200): ").strip()
            limit = int(limit) if limit else 200
            process_batch(limit)
        elif choice == "2":
            debug_executive()
        else:
            process_batch(10)
            
    except Exception as e:
        logger.error(f"Error: {str(e)}")
    finally:
        conn.close()
        close_driver()
        print("\n Done!")

