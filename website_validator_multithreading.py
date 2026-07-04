from apscheduler.schedulers.background import BackgroundScheduler
import pyodbc
import requests
from concurrent.futures import ThreadPoolExecutor
# DATABASE CONNECTION FUNCTION
def get_connection():
    return pyodbc.connect(
        'DRIVER={ODBC Driver 17 for SQL Server};'
        'SERVER=maulimittal\\SQLEXPRESS;'
        'DATABASE=social_listening;'
        'Trusted_Connection=yes;'
    )
# WEBSITE VALIDATION FUNCTION
def validate_website(company):
    company_id = company.CompanyID
    website = company.Website.strip()
    old_status=company.StatusCode
    old_https=company.HTTPSAvailable
    old_change_count=company.StatusChangeCount
    print(f"\nChecking CompanyID: {company_id}")
    print(f"Website: {website}")
    # Fix malformed URLs
    if website.startswith("https//"):
        website = website.replace(
            "https//",
            "https://"
        )
    elif website.startswith("http//"):
        website = website.replace(
            "http//",
            "http://"
        )
    elif not website.startswith(
        ("http://", "https://")
    ):
        website = "https://" + website
    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    try:
        response = requests.get(
             website,
            headers=headers,
            timeout=10,
            allow_redirects=True
        )
        status_code = response.status_code
        https_available = (
            response.url.startswith("https://")
        )
        if status_code == 200:
            validation_message = "Website Active"
        elif status_code in [301, 302, 307, 308]:
            validation_message = "Redirected"
        elif status_code == 400:
            validation_message = "Bad Request"
        elif status_code == 401:
            validation_message = "Unauthorized"
        elif status_code == 403:
            validation_message = "Forbidden"
        elif status_code == 404:
            validation_message = "Page Not Found"
        elif status_code == 406:
            validation_message = "Not Acceptable"
        elif status_code == 410:
            validation_message = (
                "Website Permanently Removed"
            )
        elif status_code >= 500:
            validation_message = "Server Error"
        else:
            validation_message = (
                f"HTTP {status_code}"
            )
    except requests.exceptions.Timeout:
        status_code = None
        https_available = False
        validation_message = "Timeout"
    except requests.exceptions.ConnectionError:
        status_code = None
        https_available = False
        validation_message = "Connection Error"
    except requests.exceptions.SSLError as e:
        status_code = None
        https_available = False
        validation_message = (
            f"SSL Error: {str(e)}"
        )
    except Exception as e:
        status_code = None
        https_available = False
        validation_message = (
            f"Unexpected Error: {str(e)}"
        )
    status_changed=(
        old_status != status_code
    )    
    https_changed=(
        old_https != https_available
    )
    new_change_count=old_change_count
    if status_changed or https_changed:
        new_change_count = min(
            old_change_count + 1,
            5
        )
    else:
        new_change_count = max(
            old_change_count -1,
            0
        )    
    if new_change_count >= 5:
        validation_interval = 10
    elif new_change_count >= 2:
        validation_interval=300
    else:
        validation_interval=86400            
    # SEPARATE DB CONNECTION PER THREAD
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE ListedCompanies
            SET StatusCode = ?,
                HTTPSAvailable = ?,
             LastCheckedDate = GETDATE(),
            ValidationMessage = ?,
               StatusChangeCount=?,
                ValidationIntervalSeconds=?
            WHERE CompanyID = ?
        """,
        status_code,
        https_available,
        validation_message,
        new_change_count,
        validation_interval,
        company_id)
        conn.commit()
        print(
            f"CompanyID:{company_id} | "
            f"Status:{status_code} | "
            f"Message:{validation_message}"
        )
        conn.close()
    except Exception as e:
        print(
            f"DB Update Failed "
            f"for CompanyID {company_id}: "
            f"{str(e)}"
        )
# MAIN PROGRAM
def run_validation():
    conn = get_connection()
    cursor = conn.cursor()
   
    cursor.execute("""
        SELECT 
            CompanyID,
            Website,
            StatusCode,
            HTTPSAvailable,
            ISNULL(StatusChangeCount,0) AS StatusChangeCount,
            ISNULL(ValidationIntervalSeconds,86400) AS ValidationIntervalSeconds
        FROM ListedCompanies
       WHERE Website IS NOT NULL 
        AND (
            LastCheckedDate IS NULL
            OR
            DATEDIFF(
                SECOND,
                LastCheckedDate,
                GETDATE()
            )>= ISNULL(
                   ValidationIntervalSeconds,
                   86400
            )
         )
    """)
    companies = cursor.fetchall()
    conn.close()
    if not companies:
        print("No companies due for validation")
        return
    print(
        f"\nStarting validation for "
        f"{len(companies)} companies..."
    )
    # MULTITHREADING
    with ThreadPoolExecutor(
        max_workers=10
    ) as executor:
        executor.map(
            validate_website,
            companies
        )
    print(
        "\nValidation Completed")
scheduler=BackgroundScheduler()
scheduler.add_job(
    run_validation,
    'interval',
    seconds=10
)


