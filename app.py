from flask_sqlalchemy import SQLAlchemy
from flask import Flask, render_template, request,redirect
import math
import pyodbc
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy import text
from flask import jsonify
from flask import flash
from website_validation_scheduler import start_scheduler
from news_fetch_module import fetch_news_for_company
from company_scraper import scrape_company_data

app = Flask(__name__)
app.secret_key = "mauli_dashboard_secret_key"
app.config['SQLALCHEMY_DATABASE_URI']=(
    "mssql+pyodbc://@MAULIMITTAL\\SQLEXPRESS/social_listening"
    "?driver=ODBC+Driver+17+for+SQL+Server"
    "&trusted_connection=yes"
    "&TrustServerCertificate=yes"
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS']=False
db=SQLAlchemy(app)

class listedcompanies(db.Model):
    __tablename__='listedcompanies'
    CompanyID = db.Column(
        db.Integer,
        primary_key=True
    )
    CompanyName = db.Column(db.String(255))
    Address = db.Column(db.Text)
    Phone = db.Column(db.String(50))
    Website = db.Column(db.String(255))
    Sector = db.Column(db.String(255))
    Industry = db.Column(db.String(255))
    Description = db.Column(db.Text)
    addedDt = db.Column(db.DateTime)
    yahooFinanceURL = db.Column(db.String(255))
    StatusCode=db.Column(db.Integer)
    HTTPSAvailable=db.Column(db.Boolean)
    ValidationMessage=db.Column(
        db.String(255)
    )  
    LastCheckedDate=db.Column(
        db.DateTime
    )
    StatusCHangeCount=db.Column(
        db.Integer,
        default=0
    )
    ValidationIntervalSeconds=db.Column(
        db.Integer,
        default=86400
    )
    LinkedInURL=db.Column(db.String(500))
    LinkedInConfidence=db.Column(db.String(20))
    LinkedInScore=db.Column(db.Float)
    LinkedInCheckedAt=db.Column(db.DateTime)
    headquarters=db.Column(db.String(600))
    employeecount=db.Column(db.String(200))
    foundedyear=db.Column(db.String(40))


class listedcompaniesexecutives(db.Model):
    __tablename__ ='listedcompaniesexecutives'
    ExecutiveID = db.Column(
        db.Integer,
        primary_key=True
    )
    CompanyID = db.Column(db.Integer)
    Name = db.Column(db.String(255))
    Title = db.Column(db.String(255))

    Pay = db.Column(db.Float)
    Exercised = db.Column(db.Float)
    YearBorn = db.Column(db.Integer)
    addedDt = db.Column(db.DateTime)  
    Selected=db.Column(
        db.Boolean,
        default=False
    )
    SelectedCount=db.Column(
        db.Integer,
        default=0
    )
    Printed=db.Column(
        db.Boolean,
        default=False
    )
    PrintCount=db.Column(
        db.Integer,
        default=0
    )
    LastSelectedDate=db.Column(
        db.DateTime
    )
    LastPrintedDate=db.Column(
        db.DateTime
    )
    LinkedInURL=db.Column(db.String(500))
    LinkedInConfidence=db.Column(db.String(20))
    LinkedInScore=db.Column(db.Float)
    LinkedInCheckedAt=db.Column(db.DateTime)
   
class Outreach(db.Model):
     id=db.Column(db.Integer, primary_key=True)
     executive_name=db.Column(db.String(100))
     company=db.Column(db.String(100))
     status=db.Column(db.String(100))
     notes=db.Column(db.Text)
     last_contacted=db.Column(db.String(100))
     followup_datetime=db.Column(db.String(100)) 
     executive_id=db.Column(db.Integer)
     updated_at=db.Column(
          db.DateTime,
          default=lambda:
          datetime.now(
               ZoneInfo("Asia/Kolkata")
          ),
           onupdate=datetime.now(
               ZoneInfo("Asia/Kolkata")
    )
     )

class CompanyNews(db.Model):
    __tablename__ = 'CompanyNews'
    NewsID         = db.Column(db.Integer, primary_key=True)
    EntityType     = db.Column(db.String(20))
    EntityID       = db.Column(db.Integer)
    EntityName     = db.Column(db.String(255))
    NewsHeadline   = db.Column(db.String(500))
    #NewsSource     = db.Column(db.String(255))
    #PublishedDate  = db.Column(db.DateTime)
    ArticleURL     = db.Column(db.String(500))
    FetchedAt      = db.Column(db.DateTime)


#dashboard page
@app.route("/")
def dashboard():
    stats = {
          "companies":
    listedcompanies.query.count(),
    "executives":
    listedcompaniesexecutives.query.count(),
    "sectors":
    db.session.query(
        listedcompanies.Sector
    ).distinct().count(),
    "contacted":
    Outreach.query.filter(
        Outreach.status != 'Non Contacted'
    ).count()

    }
    outreach_records = Outreach.query.all()
    events = []
    for record in outreach_records:
        if (
            record.followup_datetime
            and
            record.status in
            ['Follow-Up Pending',
             'Interested','Contacted']
        ):
            events.append({
                "title":
                f"{record.company}",
                "start":
                str(record.followup_datetime),
                "url":
                f"/outreach/{record.executive_id}"
            })

              # RECENT EXECUTIVES
    recent_executives = \
listedcompaniesexecutives.query.order_by(
    listedcompaniesexecutives.ExecutiveID.desc()
).limit(3).all()

    # COMPANY DATA FETCH
    for executive in recent_executives:
        company_data = \
        listedcompanies.query.get(
            executive.CompanyID
        )
        executive.company_name = \
        company_data.CompanyName
        executive.sector_name = \
        company_data.Sector

            # LATEST OUTREACH STATUS
        latest_outreach = \
        Outreach.query.filter_by(
            executive_name=executive.Name
        ).order_by(
            Outreach.updated_at.desc()
        ).first()

        # STATUS
        if latest_outreach and latest_outreach.status:
            executive.current_status = \
            latest_outreach.status
        else:
            executive.current_status = \
            "Non Contacted"

    # SECTOR DATA
    sector_data = db.session.query(
       listedcompanies.Sector,
       db.func.count(
           listedcompanies.CompanyID
        )
    ).group_by(
       listedcompanies.Sector
    ).all()
    sector_labels = [
       data[0]
       for data in sector_data
    ]
    sector_counts = [
       data[1]
       for data in sector_data
    ]

    #sector analytics
    sector_data=db.session.query(
       listedcompanies.Sector,
       db.func.count(
           listedcompanies.CompanyID
       )
    ).group_by(
       listedcompanies.Sector
    ).all()
    sector_labels=[
        data[0]
        for data in sector_data
    ]
    sector_counts=[
        data[1]
        for data in sector_data
    ]

    # INDUSTRY ANALYTICS
    industry_data = db.session.query(
        listedcompanies.Industry,
        db.func.count(
            listedcompanies.CompanyID
        )
    ).group_by(
        listedcompanies.Industry
    ).all()
    industry_labels = [
        data[0]
        for data in industry_data
    ]
    industry_counts = [
    data[1]
    for data in industry_data
]
    return render_template(
        "dashboard.html",
        stats=stats,
        recent_executives=recent_executives,
        sector_labels=sector_labels,
        sector_counts=sector_counts,
        industry_labels=industry_labels,
        industry_counts=industry_counts,
        events=events
    )

@app.route("/executives")
def executives():
    # GET SEARCH VALUES
    search_query = request.args.get("search", "").strip().lower()
    print("SEARCH=", search_query)

    # FILTER VALUES
    sector_filter   = request.args.get("sector", "").strip().lower()
    industry_filter = request.args.get("industry", "").strip().lower()
    title_filter    = request.args.get("title", "").strip().lower()
    status_filter   = request.args.get("status", "").strip().lower()
    company_filter  = request.args.get("company", "").strip().lower()

    # PAGINATION
    per_page = 20
    page = request.args.get("page", 1, type=int)

    latest_outreach_ids = db.session.query(
        Outreach.executive_name,
        db.func.max(Outreach.id).label("max_id")
    ).group_by(
        Outreach.executive_name
    ).subquery()

    latest_outreach = db.session.query(
        Outreach.executive_name,
        Outreach.status
    ).join(
        latest_outreach_ids,
        db.and_(
            Outreach.executive_name == latest_outreach_ids.c.executive_name,
            Outreach.id == latest_outreach_ids.c.max_id
        )
    ).subquery()

    current_status_expr = db.func.coalesce(
        latest_outreach.c.status, "Non Contacted"
    ).label("current_status")

    query = db.session.query(
        listedcompaniesexecutives,
        listedcompanies.CompanyName,
        listedcompanies.Sector,
        listedcompanies.Industry,
        listedcompanies.Website,
        current_status_expr
    ).join(
        listedcompanies,
        listedcompaniesexecutives.CompanyID == listedcompanies.CompanyID
    ).outerjoin(
        latest_outreach,
        latest_outreach.c.executive_name == listedcompaniesexecutives.Name
    )

    # COMPANY FILTER
    if company_filter:
        query = query.filter(
            listedcompanies.CompanyName.ilike(f"%{company_filter}%")
        )

    designation_map = {
        "ceo": "chief executive officer",
        "cto": "chief technology officer",
        "cfo": "chief financial officer",
        "md": "managing director",
        "chairman": "chairman",
        'coo':   'Chief Operating Officer',
        'cmo':   'Chief Marketing Officer',
        'cio':   'Chief Information Officer',
        'cso':   'Chief Strategy Officer',
        'cpo':   'Chief Product Officer',
        'cmd':   'Chairman & Managing Director',
        'wtd':   'Whole-Time Director',
        'vp':    'Vice President',
        'svp':   'Senior Vice President',
        'evp':   'Executive Vice President',
        'avp':   'Assistant Vice President',
        'gm':    'General Manager',
        'dgm':   'Deputy General Manager',
        'agm':   'Assistant General Manager',
        'ed':    'Executive Director',
        'dir':   'Director'
    }
    search_terms = [search_query]
    if search_query in designation_map:
        search_terms.append(designation_map[search_query].lower())
    for short_form, full_form in designation_map.items():
        if search_query == full_form.lower():
            search_terms.append(short_form.lower())

    if search_query:
        conditions = []
        for term in search_terms:
            conditions.extend([
                listedcompaniesexecutives.Name.ilike(f"%{term}%"),
                listedcompaniesexecutives.Title.ilike(f"%{term}%"),
                listedcompanies.CompanyName.ilike(f"%{term}%")
            ])
        query = query.filter(db.or_(*conditions))

    # SECTOR FILTER
    if sector_filter:
        query = query.filter(listedcompanies.Sector.ilike(sector_filter))

    # INDUSTRY FILTER
    if industry_filter:
        query = query.filter(listedcompanies.Industry.ilike(industry_filter))

    # TITLE FILTER
    if title_filter:
        query = query.filter(
            listedcompaniesexecutives.Title.ilike(f"%{title_filter}%")
        )

    # STATUS FILTER 
    if status_filter:
        query = query.filter(
            db.func.lower(current_status_expr) == status_filter
        )

    print("SELECTED STATUS=", status_filter)

    # TOTAL COUNT
    total_records = query.count()
    total_pages = (total_records + per_page - 1) // per_page
    if total_pages == 0:
        total_pages = 1

    # DB-LEVEL PAGINATION 
    rows = query.order_by(
        listedcompaniesexecutives.ExecutiveID.asc()
    ).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    # FINAL EXECUTIVES 
    paginated_executives = []
    for (
        executive,
        company_name,
        sector_name,
        industry_name,
        website_name,
        current_status
    ) in rows:
        executive.company_name    = company_name
        executive.sector_name     = sector_name
        executive.industry_name   = industry_name
        executive.website_name    = website_name
        executive.current_status  = current_status
        paginated_executives.append(executive)

    sectors = db.session.query(
        listedcompanies.Sector
    ).filter(
        listedcompanies.Sector.isnot(None),
        listedcompanies.Sector != ""
    ).distinct().all()

    titles = db.session.query(
        listedcompaniesexecutives.Title
    ).filter(
        listedcompaniesexecutives.Title.isnot(None),
        listedcompaniesexecutives.Title != ""
    ).distinct().all()

    industries = db.session.query(
        listedcompanies.Industry
    ).filter(
        listedcompanies.Industry.isnot(None),
        listedcompanies.Industry != ""
    ).distinct().all()

    print("TOTAL PAGES=", total_pages)
    print("TOTAL RECORDS=", total_records)

    return render_template(
        "executives.html",
        executives=paginated_executives,
        page=page,
        total_pages=total_pages,
        total_records=total_records,
        search_query=search_query,
        sector_filter=sector_filter,
        industry_filter=industry_filter,
        title_filter=title_filter,
        sectors=sectors,
        titles=titles,
        industries=industries,
        company_filter=company_filter,
        status_filter=status_filter
    )

@app.route('/profile/<int:id>')
def profile(id):
     selected_executive=listedcompaniesexecutives.query.get(id)

     company_data =listedcompanies.query.get(
          selected_executive.CompanyID
     )
     print("FOUNDED =",company_data.foundedyear)
     print("HQ =",company_data.headquarters)
     print("EMP =",company_data.employeecount)

     company_news = CompanyNews.query.filter_by(
         EntityType="company",
         EntityID=company_data.CompanyID
     ).order_by(
         CompanyNews.FetchedAt.desc()
     ).all()

     return render_template(
        'profile.html',
        executive=selected_executive,
        company_data=company_data,
        company_news=company_news
     )     

@app.route('/search-profile')
def search_profile():
    query = request.args.get('query', '').lower()
    all_executives = listedcompaniesexecutives.query.all()
    for executive in all_executives:
        if query in executive.Name.lower():
            return redirect(f"/profile/{executive.ExecutiveID}")
    return "Executive Not Found"   

@app.route('/outreach/<int:id>',methods=['GET', 'POST'])
def executive_outreach(id):
     executive=listedcompaniesexecutives.query.get(id)
     company_data = listedcompanies.query.get(
               executive.CompanyID
               )
     if request.method=='POST':
          outreach_record=Outreach(
               executive_name=executive.Name ,
               executive_id=executive.ExecutiveID,
               company=company_data.CompanyName,
               status=request.form['status'],
               notes=request.form['notes'],
               last_contacted=datetime.now(
                    ZoneInfo("Asia/Kolkata")
               ),

               followup_datetime=request.form['followup_datetime']
          )
          db.session.add(outreach_record)
          db.session.commit()
          return redirect(f'/outreach/{id}')
     outreach_records=Outreach.query.filter_by(
          executive_name=executive.Name
     ).all()
     return render_template(
          'outreach.html',
          executive=executive,
          company_data=company_data,
          outreach_records=outreach_records
    )

@app.route('/delete-outreach/<int:id>')
def delete_outreach(id):
     outreach_record=Outreach.query.get(id)
     db.session.delete(outreach_record)
     db.session.commit()
     return redirect(request.referrer)

@app.route('/outreach')
def outreach_logs():
    filter_type = request.args.get("filter")
    query = Outreach.query
    if filter_type == "active":
        query = query.filter(
            Outreach.status.in_([
                "Interested",
                "Contacted",
                "Follow-Up Pending"
            ])
        )

    records = query.order_by(
       Outreach.id.desc()
    ).all()
    return render_template(
        'outreach_logs.html',
        records=records
    ) 
 
@app.route("/companies")
def companies():
     page=request.args.get("page",1,type=int)
     per_page=20
     sector_filter=request.args.get(
         "sector",
         ""
     ).strip()
     industry_filter=request.args.get(
         "industry",
         ""
     ).strip()
     status_filter=request.args.get(
         "status",
         ""
     ).strip()
     query=db.session.query(
          listedcompanies.CompanyName,
          listedcompanies.Sector,
          listedcompanies.Industry,
          listedcompanies.Website,
          db.func.count(
            listedcompaniesexecutives.ExecutiveID
          ).label("total_executives"),
          db.func.max(
              Outreach.status
          ).label("company_status")
     ).outerjoin(
     listedcompaniesexecutives,
     listedcompanies.CompanyID
     ==
     listedcompaniesexecutives.CompanyID).outerjoin(
         Outreach,
         Outreach.company==listedcompanies.CompanyName
     )
     if sector_filter:
         query=query.filter(
             listedcompanies.Sector==sector_filter
         )
     if industry_filter:
         query=query.filter(
             listedcompanies.Industry==industry_filter
         )
     if status_filter:
         query=query.filter(
             Outreach.status==status_filter
         )    
     all_companies=query.group_by(
        listedcompanies.CompanyName,
        listedcompanies.Sector,
        listedcompanies.Industry,
        listedcompanies.Website,
        Outreach.status
    ).order_by(
    listedcompanies.CompanyName
)
     total_companies=len(
        all_companies.all()
     )
     total_pages=(
         total_companies+per_page -1
     )//per_page
     companies=(
    all_companies
    .offset((page-1)*per_page)
        .limit(per_page)
        .all()
    )     
     sectors=db.session.query(
         listedcompanies.Sector
     ).distinct().all()
     industries=db.session.query(
         listedcompanies.Industry    
     ).distinct().all()
     print("TOTAL COMPANIES =", total_companies)
     print("TOTAL PAGES =", total_pages)
     print("CURRENT PAGE =", page)
     return render_template(
          "companies.html",
          companies=companies,
          page=page,
          total_pages=total_pages,
          sectors=sectors,
          industries=industries,
          sector_filter=sector_filter,
          industry_filter=industry_filter,
          status_filter=status_filter
     )
@app.route("/sector-analytics")
def sector_analytics():
    sector_data = db.session.query(
        listedcompanies.Sector,
        db.func.count(
            db.distinct(
                listedcompanies.CompanyID
            )
        ),
        db.func.count(
            listedcompaniesexecutives.ExecutiveID
        )
    ).outerjoin(
        listedcompaniesexecutives,
        listedcompanies.CompanyID
        ==
        listedcompaniesexecutives.CompanyID
    ).group_by(
        listedcompanies.Sector
    ).all()
    sector_labels = []
    company_counts = []
    executive_counts = []
    for data in sector_data:
        sector_labels.append(
            data[0] if data[0] else "Unknown"
        )
        company_counts.append(
            int(data[1]) if data[1] else 0
        )
        executive_counts.append(
            int(data[2]) if data[2] else 0
        )
    total_companies = sum(
        company_counts
    )
    total_executives = sum(
        executive_counts
    )
    total_sectors = len(
        sector_labels
    )
    largest_sector = sector_labels[
        company_counts.index(
            max(company_counts)
        )
    ]
    return render_template(
        "sector_analytics.html",
        sector_labels=sector_labels,
        company_counts=company_counts,
        executive_counts=executive_counts,
        total_companies=total_companies,
        total_executives=total_executives,
        total_sectors=total_sectors,
        largest_sector=largest_sector
    )
@app.route("/reports")
def reports():
    #total contactd
    total_contacted=Outreach.query.filter(
        Outreach.status!="Non Contacted"
    ).count()
    ##interested
    interested_count=Outreach.query.filter_by(
        status="Interested"
    ).count()
    #rejected
    rejected_count=Outreach.query.filter_by(
        status="Rejected"
    ).count()
    followup_count=Outreach.query.filter_by(
        status="Follow-Up Pending"
    ).count()
    #Pie chart data
    status_labels=[
        "Interested",
        "Rejected",
        "Follow-Up Pending",
        "Contacted"
    ]
    status_counts=[
        interested_count,
        rejected_count,
        followup_count,
        Outreach.query.filter_by(
            status="Contacted"
        ).count()
    ]
    all_records=Outreach.query.order_by(
        Outreach.updated_at.desc()
    ).all()
    seen_executives=set()
    recent_records=[]
    for record in all_records:
        if record.executive_id not in seen_executives:
            recent_records.append(record)
            seen_executives.add(
                record.executive_id
            )
            if len(recent_records)==10:
                break
    return render_template(
        "reports.html",
        total_contacted=total_contacted,
        interested_count=interested_count,
        rejected_count=rejected_count,
        followup_count=followup_count,
        status_labels=status_labels,
        status_counts=status_counts,
        recent_records=recent_records
    )

@app.route('/check-website/<int:company_id>')
def check_website(company_id):
    company=listedcompanies.query.get(company_id)
    if not company:
        return{
            "status":"error",
            "message":"Company not found"
        }
    website=company.Website
    try:
        response=request.get(
            website,
            timeout=5
        )
        return{
            "status":"success",
            "status_code":response.status_code,
            "website":website
        }
    except request.exceptions.Timeout:
        return{
            "status":"error",
            "message":"Website Timeout"
        }
    except request.exceptions.ConnectionError:
        return{
            "status":"error",
            "message":"Connection Error"
        }
    
@app.route('/website-validation')
def website_validation():
    page             = request.args.get('page', 1, type=int)
    per_page         = 20
    company_filter   = request.args.get('company',     '').strip()
    https_filter     = request.args.get('https',       '').strip()
    website_filter   = request.args.get('website',     '').strip()
    status_code_filter = request.args.get('status_code', '').strip()

    # BASE QUERY
    query = listedcompanies.query

    # Filter 1 — Company name search
    if company_filter:
        query = query.filter(
            listedcompanies.CompanyName.ilike(f"%{company_filter}%")
        )

    # Filter 2 — Website availability (status code 200 = available)
    if website_filter == "available":
        query = query.filter(listedcompanies.StatusCode == 200)
    elif website_filter == "not_available":
        query = query.filter(
            db.or_(
                listedcompanies.StatusCode != 200,
                listedcompanies.StatusCode == None
            )
        )

    # Filter 3-HTTPS
    if https_filter == "1":
        query = query.filter(listedcompanies.HTTPSAvailable == True)
    elif https_filter == "0":
        query = query.filter(
            db.or_(
                listedcompanies.HTTPSAvailable == False,
                listedcompanies.HTTPSAvailable == None
            )
        )

    # Filter 4-Status code
    if status_code_filter and status_code_filter.isdigit():
        query = query.filter(
            listedcompanies.StatusCode == int(status_code_filter)
        )

    # TOTAL COUNT
    total_records = query.count()
    total_pages   = math.ceil(total_records / per_page) if total_records > 0 else 1

    # PAGINATE
    companies = query.order_by(
        listedcompanies.CompanyID
    ).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return render_template(
        'website_validation.html',
        companies          = companies,
        page               = page,
        total_pages        = total_pages,
        total_records      = total_records,
        company_filter     = company_filter,
        https_filter       = https_filter,
        website_filter     = website_filter,
        status_code_filter = status_code_filter,
    )

@app.route("/print-executives", methods=["POST"])
def print_executives():
    selected_ids = request.form.getlist("executive_ids")
    if not selected_ids:
        return redirect("/executives")
    ids_str = ",".join(selected_ids)
    return redirect(f"/print-labels?ids={ids_str}")

def get_label_title(title):
    if not title:
        return ""
    title=title.lower()
    title_map=[
        ("chief executive officer","CEO"),
        ("ceo","CEO"),
        ("chief financial officer","CFO"),
        ("cfo","CFO"),
                ("chief operating officer", "COO"),
        (" coo ", "COO"),

        ("chief technology officer", "CTO"),
        (" cto ", "CTO"),

        ("chief information officer", "CIO"),
        (" cio ", "CIO"),

        ("chairman & managing director", "CMD"),
        ("cmd", "CMD"),

        ("managing director", "MD"),
        (" md ", "MD"),

        ("executive vice president", "EVP"),
        ("evp", "EVP"),

        ("senior vice president", "SVP"),
        ("svp", "SVP"),

        ("vice president", "VP"),
        ("vp", "VP"),

        ("executive director", "Executive Director"),

        ("whole time director", "WTD"),

        ("independent director", "Independent Director"),

        ("director", "Director"),

        ("chairman", "Chairman"),

        ("company secretary", "CS")
    ]

    for keyword, short_title in title_map:
        if keyword in title:
            return short_title

    return title.title()
@app.route("/print-labels")
def print_labels():
    ids_str = request.args.get("ids", "")

    if not ids_str:
        return redirect("/executives")

    ids = [int(i) for i in ids_str.split(",") if i.strip().isdigit()]
    executives_data = []

    for exec_id in ids:
        executive = listedcompaniesexecutives.query.get(exec_id)
        if not executive:
            continue

        company = listedcompanies.query.get(executive.CompanyID)

        executive.company_name = company.CompanyName if company else ""
        executive.address = (company.Address or "").strip() if company else ""
        executive.label_title=get_label_title(
            executive.Title
        )

        raw_comp = (company.Phone or "").strip() if company else ""
        raw_exec = ""

        executive.company_phone = raw_comp if raw_comp else None
        executive.exec_phone    = raw_exec if raw_exec else None

        executives_data.append(executive)

    return render_template(
        "print_labels.html",
        executives=executives_data,
        exec_ids=ids_str          
    )

@app.route("/mark-printed", methods=["POST"])
def mark_printed():
    data    = request.get_json(force=True)
    ids_str = data.get("ids", "")

    if not ids_str:
        return jsonify({"status": "ok"})
    ids = [int(i) for i in ids_str.split(",") if i.strip().isdigit()]
    for exec_id in ids:
        executive = listedcompaniesexecutives.query.get(exec_id)
        if executive:
            executive.Printed         = True
            executive.PrintCount      = (executive.PrintCount or 0) + 1
            executive.LastPrintedDate = datetime.now(ZoneInfo("Asia/Kolkata"))
            executive.Selected        = True
            executive.SelectedCount   = (executive.SelectedCount or 0) + 1
            executive.LastSelectedDate = datetime.now(ZoneInfo("Asia/Kolkata"))
    db.session.commit()
    return jsonify({"status": "ok", "marked": len(ids)})

@app.route("/select-executive", methods=["POST"])
def select_executive():
    print("ROUTE HIT")
    data = request.get_json(force=True)
    print("DATA =", data)
    executive = listedcompaniesexecutives.query.get(
        data["executive_id"]
    )
    print(
    "ID =", executive.ExecutiveID,
    "Selected =", executive.Selected,
    "SelectedCount =", executive.SelectedCount
)
    if (executive.SelectedCount or 0)>0:
        return jsonify({
            "already_selected": True
        })
    executive.Selected = True
    executive.SelectedCount=1
    executive.LastSelectedDate = (
        datetime.now(
            ZoneInfo("Asia/Kolkata")
        )
    )
    db.session.commit()
    return jsonify({
        "already_selected": False
    })

@app.route('/api/companies-search')
def api_companies_search():
    term = request.args.get('q', '').strip()
    if not term or len(term) < 2:
        return jsonify([])

    #matches = listedcompanies.query.filter(
     #   listedcompanies.CompanyName.ilike(f"%{term}%")
    #).order_by(
     #   listedcompanies.CompanyName.asc()
    #).limit(10).all()
    matches = listedcompanies.query.filter(
        listedcompanies.CompanyName.ilike(f"%{term}%")
    ).order_by(
        listedcompanies.CompanyName.asc()
    ).all()

    results = []
    seen = set()

    for c in matches:
        company_name = (c.CompanyName or "").strip().lower()

        if company_name in seen:
            continue

        seen.add(company_name)

        results.append({
            "company_id": c.CompanyID,
            "company_name": c.CompanyName,
            "website": c.Website or "",
            "phone": c.Phone or "",
            "address": c.Address or ""
        })

        if len(results) == 10:
            break

    return jsonify(results)

    #results = [
     #   {
      #      "company_id": c.CompanyID,
       #     "company_name": c.CompanyName,
        #    "website": c.Website or "",
         #   "phone": c.Phone or "",
          #  "address": c.Address or ""
        #}
        #for c in matches
    #]
    #return jsonify(results)
@app.route('/add-executive', methods=['GET', 'POST'])
def add_executive():
    if request.method == 'POST':
        company_name   = " ".join(request.form.get('company_name', '').split())
        website        = request.form.get('website', '').strip()
        phone          = request.form.get('phone', '').strip()
        address        = request.form.get('address', '').strip()
        executive_name = " ".join(request.form.get('executive_name', '').split())
        title          = " ".join(request.form.get('title', '').split())
        pay            = request.form.get('pay', '').strip()
        year_born      = request.form.get('year_born', '').strip()

        if not company_name or not executive_name or not title:
            flash("Company Name, Executive Name and Title are required.", "error")
            return render_template('add_executive.html', form_data=request.form)

        company_name_key = company_name.lower()
        executive_name_key = executive_name.lower()

        all_companies = listedcompanies.query.all()
        company = None
        for c in all_companies:
            if c.CompanyName and c.CompanyName.strip().lower() == company_name_key:
                company = c
                break

        #if not company:
         #   company = listedcompanies(
          #      CompanyName = company_name,
           #     Website     = website or None,
            #    Phone       = phone or None,
             #   Address     = address or None,
              #  addedDt     = datetime.now(ZoneInfo("Asia/Kolkata"))
           # )
            #db.session.add(company)
        #    db.session.commit()
         #   print(f"[ADD-EXEC] New company created: '{company_name}' (ID={company.CompanyID})")
        #else:
         #   print(f"[ADD-EXEC] Matched existing company: '{company.CompanyName}' (ID={company.CompanyID})")
        if not company:
            company = listedcompanies(
                CompanyName = company_name,
                Website     = website or None,
                Phone       = phone or None,
                Address     = address or None,
                addedDt     = datetime.now(ZoneInfo("Asia/Kolkata"))
            )
            db.session.add(company)
            db.session.commit()
            print(f"[ADD-EXEC] New company created: '{company_name}' (ID={company.CompanyID})")
 
            # ── AUTO-SCRAPE
            try:
                scraped = scrape_company_data(company_name)
 
                if scraped.get("sector"):
                    company.Sector      = scraped["sector"]
                if scraped.get("industry"):
                    company.Industry    = scraped["industry"]
                if scraped.get("description"):
                    company.Description = scraped["description"]
                if scraped.get("founded_year"):
                    company.foundedyear = scraped["founded_year"]
                if scraped.get("employees"):
                    company.employeecount = scraped["employees"]
                if scraped.get("headquarters"):
                    company.headquarters  = scraped["headquarters"]
                if scraped.get("yahoo_url"):
                    company.yahooFinanceURL = scraped["yahoo_url"]     
 
                db.session.commit()
                print(f"[ADD-EXEC] Scraped data saved for '{company_name}'")
 
            except Exception as e:
                print(f"[ADD-EXEC] Scraping failed (non-fatal): {e}")
 
        else:
            print(f"[ADD-EXEC] Matched existing company: '{company.CompanyName}' (ID={company.CompanyID})")
        existing_execs_for_company = listedcompaniesexecutives.query.filter(
            listedcompaniesexecutives.CompanyID == company.CompanyID
        ).all()

        print(f"[ADD-EXEC] Checking against {len(existing_execs_for_company)} "
              f"existing executives for CompanyID={company.CompanyID}")

        duplicate_found = None
        for ex in existing_execs_for_company:
            if ex.Name and ex.Name.strip().lower() == executive_name_key:
                duplicate_found = ex
                break

        if duplicate_found:
            print(f"[ADD-EXEC] DUPLICATE DETECTED: '{duplicate_found.Name}' "
                  f"(ExecutiveID={duplicate_found.ExecutiveID})")
            flash(
                f"'{executive_name}' already exists for '{company_name}'. "
                f"Duplicate entry was NOT added.",
                "error"
            )
            return render_template(
                'add_executive.html',
                form_data=request.form
            )

        new_exec = listedcompaniesexecutives(
            CompanyID = company.CompanyID,
            Name      = executive_name,
            Title     = title,
            Pay       = float(pay) if pay else None,
            YearBorn  = int(year_born) if year_born else None,
            addedDt   = datetime.now(ZoneInfo("Asia/Kolkata"))
        )
        db.session.add(new_exec)
        db.session.commit()
        print(f"[ADD-EXEC] New executive added: '{executive_name}' "
              f"(ExecutiveID={new_exec.ExecutiveID})")

        flash("Executive added successfully!", "success")
        return redirect('/executives')

    return render_template('add_executive.html', form_data=None)

@app.route('/fetch-company-news/<int:company_id>', methods=['POST'])
def fetch_company_news(company_id):
    company = listedcompanies.query.get(company_id)
    if not company:
        return jsonify({"status": "error", "message": "Company not found"})

    result = fetch_news_for_company(company.CompanyName)

    if result["status"] == "captcha":
        return jsonify({
            "status": "captcha",
            "message": "Google CAPTCHA is there. Wait for sometime."
        })

    if result["status"] == "error":
        return jsonify({
            "status": "error",
            "message": result.get("message", "Unknown error")
        })

    saved_count = 0
    for article in result["articles"]:
        existing = CompanyNews.query.filter_by(
            EntityType="company",
            EntityID=company_id,
            ArticleURL=article["url"]
        ).first()

        if existing:
            continue  # duplicate URL — skip 

        new_news = CompanyNews(
            EntityType    = "company",
            EntityID      = company_id,
            EntityName    = company.CompanyName,
            NewsHeadline  = article["headline"],
            #NewsSource    = article["source"],
            #PublishedDate = None,
            ArticleURL    = article["url"],
            FetchedAt     = datetime.now(ZoneInfo("Asia/Kolkata"))
        )
        db.session.add(new_news)
        saved_count += 1

    db.session.commit()

    return jsonify({
        "status": "ok",
        "found": len(result["articles"]),
        "saved": saved_count
    })

with app.app_context():
     db.create_all() 
if __name__=="__main__":
    start_scheduler()
    app.run(
        debug=True,
        use_reloader=False)