from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from website_validator_multithreading import run_validation
from metadata_enrichment import run_metadata_enrichment
from debug_scraper import run_linkedin_enrichment
from execuutive_linkedin_scrapper import run_executive_linkedin_enrichment
scheduler = BackgroundScheduler()

def start_scheduler():
    scheduler.add_job(
        run_validation,
        'interval',
        minutes=5,
        max_instances=1,
        coalesce=True
    )

    scheduler.add_job(
        run_metadata_enrichment,
        'interval',
        minutes=5,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now()
    )

    scheduler.add_job(
        run_linkedin_enrichment,
        'interval',
        hours=24,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now()
    )

    scheduler.add_job(
        run_executive_linkedin_enrichment,
        'interval',
        hours=24,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now()
    )

    scheduler.start()
    print(
        "Website Validation Scheduler Started"
    )
    print(
        "Company Metadata Enrichment Scheduler Started "
        "(runs immediately, then every 5 minutes)"
    )
    print(
        "Company LinkedIn Enrichment Scheduler Started "
        "(runs immediately, then once per day; "
        "only processes new companies, ignores not found ones)"
    )
    print(
        "Executive LinkedIn Enrichment scheduler started"
        "(runs immediately, then once per day;" 
        "uses hybrid fuzzy+semantic matching, only new executives)"
    )