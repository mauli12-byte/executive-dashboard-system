import requests
from bs4 import BeautifulSoup
import re
import time
import pyodbc
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

#DATABASE
DB_STRING = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=maulimittal\\SQLEXPRESS;"
    "DATABASE=social_listening;"
    "Trusted_Connection=yes;"
    "TrustServerCertificate=yes;"
)

def get_conn():
    return pyodbc.connect(DB_STRING)

def fetch_companies(conn, limit=None):
    cursor = conn.cursor()
    top_clause = f"TOP {limit}" if limit else ""
    query = f"""
        SELECT {top_clause}
            CompanyID,
            CompanyName,
            LinkedInURL
        FROM listedcompanies
        WHERE metadatacheckedat IS NULL 
        AND LinkedInURL IS NOT NULL
        ORDER BY CompanyID
    """
    cursor.execute(query)
    companies = []
    for row in cursor.fetchall():
        companies.append({
            "id": row[0],
            "name": row[1],
            "linkedin_url": row[2]
        })
    return companies

def update_company(conn, company_id, metadata):
    cursor = conn.cursor()
    query = """
        UPDATE listedcompanies
        SET 
            foundedyear = ?,
            headquarters = ?,
            employeecount = ?,
            metadatasource = ?,
            metadatacheckedat = GETDATE()
        WHERE CompanyID = ?
    """
    cursor.execute(
        query,
        metadata.get('foundedyear'),
        metadata.get('headquarters'),
        metadata.get('employeecount'),
        metadata.get('metadatasource', 'web_scraping'),
        company_id
    )
    conn.commit()

#IMPROVED SCRAPING WITH REQUESTS

def scrape_linkedin_page(linkedin_url):
    """Scrape LinkedIn company page with improved extraction"""
    if not linkedin_url:
        return ""
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    try:
        response = requests.get(linkedin_url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove script and style
            for tag in soup(['script', 'style', 'noscript']):
                tag.decompose()
            
            text = soup.get_text(separator=" ", strip=True)
            text = re.sub(r'\s+', ' ', text)
            
            # Also try to extract from meta tags
            meta_data = {}
            
            # Meta tags often contain structured data
            meta_tags = soup.find_all('meta')
            for tag in meta_tags:
                if tag.get('property') == 'og:title':
                    meta_data['title'] = tag.get('content', '')
                if tag.get('property') == 'og:description':
                    meta_data['description'] = tag.get('content', '')
                if tag.get('name') == 'description':
                    meta_data['description'] = tag.get('content', '')
            
            # Combine meta description with page text
            if meta_data.get('description'):
                text = meta_data['description'] + " " + text
            
            return text
        else:
            logger.warning(f"Status {response.status_code} for {linkedin_url}")
            return ""
            
    except Exception as e:
        logger.error(f"Error scraping {linkedin_url}: {str(e)}")
        return ""

#IMPROVED EXTRACTION

def extract_founded_year(text):
    """Extract founded year with multiple patterns"""
    if not text:
        return None
    
    patterns = [
        r'[Ff]ounded\s+[Ii]n\s+(\d{4})',
        r'[Ff]ounded\s+[:\-]?\s*(\d{4})',
        r'[Ee]stablished\s+[Ii]n\s+(\d{4})',
        r'[Ee]stablished\s+[:\-]?\s*(\d{4})',
        r'[Ii]ncorporated\s+[Ii]n\s+(\d{4})',
        r'[Ss]ince\s+[:\-]?\s*(\d{4})',
        r'[Yy]ear\s+[Ff]ounded\s*[:\-]?\s*(\d{4})',
        r'[Cc]ompany\s+[Ff]ounded\s+(\d{4})',
        r'(\d{4})\s+[Ee]mployees',  # Often appears with employee count
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            year = match.group(1)
            try:
                year_int = int(year)
                if 1900 <= year_int <= 2026:
                    logger.info(f" Found founded year: {year}")
                    return year
            except:
                pass
    
    return None

def extract_headquarters(text):
    """Extract headquarters with improved patterns"""
    if not text:
        return None
    
    patterns = [
        r'[Hh]eadquarters\s*[:\-]?\s*([A-Za-z\s,]+?)(?:\.|,|;|\n|$)',
        r'[Hh]eadquartered\s+[Ii]n\s+([A-Za-z\s,]+?)(?:\.|,|;|\n|$)',
        r'[Hh]ead\s+[Oo]ffice\s*[:\-]?\s*([A-Za-z\s,]+?)(?:\.|,|;|\n|$)',
        r'[Cc]orporate\s+[Hh]eadquarters\s*[:\-]?\s*([A-Za-z\s,]+?)(?:\.|,|;|\n|$)',
        r'[Bb]ased\s+[Ii]n\s+([A-Za-z\s,]+?)(?:\.|,|;|\n|$)',
        r'[Ll]ocation\s*[:\-]?\s*([A-Za-z\s,]+?)(?:\.|,|;|\n|$)',
        r'[Gg]lobal\s+[Hh]eadquarters\s*[:\-]?\s*([A-Za-z\s,]+?)(?:\.|,|;|\n|$)',
        r'[Pp]rincipal\s+[Oo]ffice\s*[:\-]?\s*([A-Za-z\s,]+?)(?:\.|,|;|\n|$)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            hq = match.group(1).strip()
            hq = re.sub(r'\s+', ' ', hq)
            hq = re.sub(r'[,.;:]+$', '', hq)
            
            # Check if it looks like a valid location
            if ',' in hq and len(hq) > 3 and len(hq) < 100:
                logger.info(f" Found headquarters: {hq}")
                return hq
            # Or if it's a short location without comma
            elif len(hq.split()) <= 3 and len(hq) > 3:
                logger.info(f" Found headquarters: {hq}")
                return hq
    
    return None

def extract_employee_count(text):
    """Extract employee count with improved patterns"""
    if not text:
        return None
    
    patterns = [
        r'(\d[\d,]*)\+?\s+[Ee]mployees',
        r'(\d[\d,]*)\s+[Ee]mployees',
        r'(\d[\d,]*)\+?\s+[Pp]eople',
        r'(\d[\d,]*)\+?\s+[Ss]taff',
        r'[Cc]ompany\s+[Ss]ize\s*[:\-]?\s*([\d,]+)',
        r'[Oo]ver\s+(\d[\d,]*)\s+[Ee]mployees',
        r'(\d[\d,]*)\+?\s+[Ww]orkforce',
        r'[Ee]mployee\s+[Cc]ount\s*[:\-]?\s*([\d,]+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            count = match.group(1).replace(',', '')
            try:
                count_int = int(count)
                if count_int > 0:
                    formatted = f"{count_int:,}+ employees"
                    logger.info(f" Found employee count: {formatted}")
                    return formatted
            except:
                pass
    
    return None

#ENRICH COMPANY

def enrich_company(company):
    logger.info("=" * 60)
    logger.info(f"Enriching: {company['name']}")
    logger.info("=" * 60)
    
    metadata = {
        'foundedyear': None,
        'headquarters': None,
        'employeecount': None,
        'metadatasource': 'web_scraping'
    }
    
    # Scrape LinkedIn page
    text = scrape_linkedin_page(company['linkedin_url'])
    
    if text and len(text) > 100:
        logger.info(f"Extracted {len(text)} characters")
        
        # Extract data
        founded = extract_founded_year(text)
        if founded:
            metadata['foundedyear'] = founded
        
        hq = extract_headquarters(text)
        if hq:
            metadata['headquarters'] = hq
        
        employees = extract_employee_count(text)
        if employees:
            metadata['employeecount'] = employees
        
        logger.info(f"\n Extracted Data:")
        logger.info(f"  Founded Year: {metadata['foundedyear'] or ' Not found'}")
        logger.info(f"  Headquarters: {metadata['headquarters'] or ' Not found'}")
        logger.info(f"  Employee Count: {metadata['employeecount'] or ' Not found'}")
    else:
        logger.warning(f"No data extracted")
    
    # Update database
    conn = get_conn()
    try:
        update_company(conn, company['id'], metadata)
    finally:
        conn.close()
    
    return metadata

#BATCH PROCESS

def process_batch(limit=10):

    conn = get_conn()
    
    try:
        companies = fetch_companies(conn, limit)
        
        if not companies:
            logger.info("No companies to process")
            return

        logger.info(f"Processing {len(companies)} companies")
        
        success_count = 0
        for i, company in enumerate(companies, 1):
            logger.info(f"\n{'='*20} {i}/{len(companies)} {'='*20}")
            
            try:
                result = enrich_company(company)
                if result and (result.get('foundedyear') or result.get('headquarters')):
                    success_count += 1
                    logger.info(f" SUCCESS: {company['name']}")
                else:
                    logger.warning(f" No data: {company['name']}")
                
                if i < len(companies):
                    time.sleep(3)
                    
            except Exception as e:
                logger.error(f"Error: {str(e)}")
        
        logger.info(f"\n{'='*60}")
        logger.info(f"SUMMARY: {success_count}/{len(companies)} enriched")
        
    finally:
        conn.close()


def run_metadata_enrichment():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) 
        FROM listedcompanies 
        WHERE metadatacheckedat IS NULL 
        AND LinkedInURL IS NOT NULL
    """)
    count = cursor.fetchone()[0]
    conn.close()

    if count == 0:
        logger.info("[METADATA] No pending companies — skipping this run.")
        return

    logger.info(f"[METADATA] {count} companies pending — processing batch of up to 50.")
    process_batch(limit=50)   


if __name__ == "__main__":
    print(" Company Metadata Enrichment - Free Version")
    print("=" * 60)
    
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) 
        FROM listedcompanies 
        WHERE metadatacheckedat IS NULL 
        AND LinkedInURL IS NOT NULL
    """)
    count = cursor.fetchone()[0]
    conn.close()
    
    print(f"\n Companies with LinkedIn URLs pending: {count}")
    
    if count == 0:
        print("\n No companies to process!")
        exit(0)
    
    limit = input("\nNumber of companies to process (default: 100): ").strip()
    limit = int(limit) if limit else 100
    
    process_batch(limit)
    print("\n Done!")





