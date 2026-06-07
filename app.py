from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
from werkzeug.utils import secure_filename
import re
import pdfplumber

app = Flask(__name__)

# Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///trucking_company.db'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# Database Models
class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    owner_name = db.Column(db.String(200))
    dot_number = db.Column(db.String(50))
    mc_number = db.Column(db.String(50))
    ein_number = db.Column(db.String(50))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    address = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.now)

class Driver(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'))
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    license_number = db.Column(db.String(50))
    license_expiration = db.Column(db.DateTime)
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    address = db.Column(db.Text)
    personal_info = db.Column(db.Text)
    call_status = db.Column(db.String(50), default='Active')
    call_expiration = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now)

class Insurance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'))
    policy_number = db.Column(db.String(100))
    expiration_date = db.Column(db.DateTime, nullable=False)
    coverage_type = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.now)

class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'))
    vin_number = db.Column(db.String(50), nullable=False, unique=True)
    license_plate = db.Column(db.String(50))
    vehicle_type = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.now)

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver.id'))
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'))
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'))
    document_type = db.Column(db.String(100))
    file_path = db.Column(db.String(500))
    uploaded_at = db.Column(db.DateTime, default=datetime.now)

# COI Parsing Function
def parse_coi_pdf(pdf_path):
    """Extract insurance, driver, and company info from COI PDF"""
    extracted_data = {
        'insurance': {},
        'driver': {},
        'company': {}
    }
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Extract all text from all pages
            full_text = ""
            for page in pdf.pages:
                full_text += page.extract_text() + "\n"
        
        # Extract dates (MM/DD/YYYY or M/D/YYYY format)
        date_pattern = r'(\d{1,2}/\d{1,2}/\d{4})'
        dates = re.findall(date_pattern, full_text)
        
        if dates:
            # Usually the expiration date is one of the later dates
            for date_str in reversed(dates):
                try:
                    parsed_date = datetime.strptime(date_str, '%m/%d/%Y')
                    if parsed_date > datetime.now():
                        extracted_data['insurance']['expiration_date'] = parsed_date.strftime('%Y-%m-%d')
                        break
                except:
                    pass
        
        # Extract policy number (common patterns)
        policy_patterns = [
            r'Policy\s*(?:Number|No\.?|#)?\s*[:#]?\s*(\w{2,20})',
            r'Policy\s*(\w{2,20})',
            r'(?:Policy|PO)\s*[:#]?\s*(\w{2,20})'
        ]
        
        for pattern in policy_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                extracted_data['insurance']['policy_number'] = match.group(1).strip()
                break
        
        # Extract insurance company name
        insurer_patterns = [
            r'(?:Insurer|Insurance Company|Underwriter|Carrier)[\s:]+([A-Z][^,\n]{10,50})',
            r'(?:Insurance\s+Co\.?|Insurance\s+Company)\s+([A-Z][^,\n]{5,40})'
        ]
        
        for pattern in insurer_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                company_name = match.group(1).strip()
                if len(company_name) > 5 and len(company_name) < 100:
                    extracted_data['company']['name'] = company_name
                    break
        
        # Extract phone numbers
        phone_pattern = r'\(?(\d{3})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})'
        phone_match = re.search(phone_pattern, full_text)
        if phone_match:
            phone = f"({phone_match.group(1)}) {phone_match.group(2)}-{phone_match.group(3)}"
            # Could be company or driver phone - try both
            extracted_data['company']['phone'] = phone
            extracted_data['driver']['phone'] = phone
        
        # Extract email addresses
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        email_match = re.search(email_pattern, full_text)
        if email_match:
            extracted_data['company']['email'] = email_match.group(0)
            extracted_data['driver']['email'] = email_match.group(0)
        
        # Extract addresses (look for patterns with street, city, state, zip)
        address_pattern = r'(\d+\s+[A-Za-z\s,]+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|Circle|Ct))[,\s]+([A-Za-z\s]+),\s*([A-Z]{2})\s*(\d{5})'
        address_match = re.search(address_pattern, full_text)
        if address_match:
            address = f"{address_match.group(1)}, {address_match.group(2)}, {address_match.group(3)} {address_match.group(4)}"
            extracted_data['company']['address'] = address
            extracted_data['driver']['address'] = address
        
        # Extract names (look for common patterns in COI)
        # This is tricky - look for names after "Named Insured" or "Insured"
        named_insured_pattern = r'(?:Named\s+Insured|Insured)\s*[:\n]+\s*([A-Z][a-zA-Z\s&,\.]{5,80}?)(?:\n|$)'
        name_match = re.search(named_insured_pattern, full_text)
        if name_match:
            name_text = name_match.group(1).strip()
            # Try to split into first and last name
            name_parts = name_text.split()
            if len(name_parts) >= 2:
                extracted_data['driver']['first_name'] = name_parts[0]
                extracted_data['driver']['last_name'] = ' '.join(name_parts[1:])
                extracted_data['company']['owner_name'] = name_text
            elif len(name_parts) == 1:
                extracted_data['driver']['first_name'] = name_parts[0]
                extracted_data['company']['owner_name'] = name_parts[0]
        
        # Extract coverage type
        coverage_patterns = [
            r'(?:Coverage|Type of Coverage)\s*[:\n]+\s*([A-Za-z\s,]+?)(?:\n|$)',
            r'(General\s+Liability|Auto\s+Liability|Workers?[\s\']?Compensation|Commercial\s+General\s+Liability)'
        ]
        
        for pattern in coverage_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                extracted_data['insurance']['coverage_type'] = match.group(1).strip()
                break
        
        return extracted_data
    
    except Exception as e:
        return {'error': str(e)}

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/parse-coi', methods=['POST'])
def parse_coi():
    """Parse COI PDF and extract information"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        # Save temporary file
        filename = secure_filename(f"temp_coi_{datetime.now().timestamp()}.pdf")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # Parse the PDF
        extracted = parse_coi_pdf(file_path)
        
        # Clean up temp file
        try:
            os.remove(file_path)
        except:
            pass
        
        return jsonify(extracted)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/companies', methods=['GET', 'POST', 'PUT'])
def companies():
    if request.method == 'POST':
        data = request.get_json()
        new_company = Company(
            name=data['name'],
            owner_name=data.get('owner_name'),
            dot_number=data.get('dot_number'),
            mc_number=data.get('mc_number'),
            ein_number=data.get('ein_number'),
            phone=data.get('phone'),
            email=data.get('email'),
            address=data.get('address')
        )
        db.session.add(new_company)
        db.session.commit()
        return jsonify({'id': new_company.id, 'name': new_company.name})
    
    elif request.method == 'PUT':
        data = request.get_json()
        company = Company.query.get(data['id'])
        if company:
            company.name = data.get('name', company.name)
            company.owner_name = data.get('owner_name', company.owner_name)
            company.dot_number = data.get('dot_number', company.dot_number)
            company.mc_number = data.get('mc_number', company.mc_number)
            company.ein_number = data.get('ein_number', company.ein_number)
            company.phone = data.get('phone', company.phone)
            company.email = data.get('email', company.email)
            company.address = data.get('address', company.address)
            db.session.commit()
            return jsonify({'success': True})
        return jsonify({'success': False}), 404
    
    companies = Company.query.all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'owner_name': c.owner_name,
        'dot': c.dot_number,
        'mc': c.mc_number,
        'ein': c.ein_number,
        'phone': c.phone,
        'email': c.email,
        'address': c.address
    } for c in companies])

@app.route('/api/drivers', methods=['GET', 'POST', 'PUT'])
def drivers():
    if request.method == 'POST':
        data = request.get_json()
        new_driver = Driver(
            company_id=data['company_id'],
            first_name=data['first_name'],
            last_name=data['last_name'],
            license_number=data.get('license_number'),
            license_expiration=datetime.fromisoformat(data['license_expiration']) if data.get('license_expiration') else None,
            phone=data.get('phone'),
            email=data.get('email'),
            address=data.get('address'),
            personal_info=data.get('personal_info'),
            call_status=data.get('call_status', 'Active'),
            call_expiration=datetime.fromisoformat(data['call_expiration']) if data.get('call_expiration') else None
        )
        db.session.add(new_driver)
        db.session.commit()
        return jsonify({'id': new_driver.id, 'name': f"{new_driver.first_name} {new_driver.last_name}"})
    
    elif request.method == 'PUT':
        data = request.get_json()
        driver = Driver.query.get(data['id'])
        if driver:
            driver.first_name = data.get('first_name', driver.first_name)
            driver.last_name = data.get('last_name', driver.last_name)
            driver.license_number = data.get('license_number', driver.license_number)
            driver.phone = data.get('phone', driver.phone)
            driver.email = data.get('email', driver.email)
            driver.address = data.get('address', driver.address)
            if data.get('license_expiration'):
                driver.license_expiration = datetime.fromisoformat(data['license_expiration'])
            if data.get('call_expiration'):
                driver.call_expiration = datetime.fromisoformat(data['call_expiration'])
            db.session.commit()
            return jsonify({'success': True})
        return jsonify({'success': False}), 404
    
    company_id = request.args.get('company_id')
    query = Driver.query
    if company_id:
        query = query.filter_by(company_id=company_id)
    
    drivers = query.all()
    return jsonify([{
        'id': d.id,
        'name': f"{d.first_name} {d.last_name}",
        'first_name': d.first_name,
        'last_name': d.last_name,
        'license_number': d.license_number,
        'license_expiration': d.license_expiration.isoformat() if d.license_expiration else None,
        'phone': d.phone,
        'email': d.email,
        'address': d.address,
        'call_status': d.call_status,
        'call_expiration': d.call_expiration.isoformat() if d.call_expiration else None
    } for d in drivers])

@app.route('/api/insurance', methods=['GET', 'POST'])
def insurance():
    if request.method == 'POST':
        data = request.get_json()
        new_insurance = Insurance(
            company_id=data['company_id'],
            policy_number=data.get('policy_number'),
            expiration_date=datetime.fromisoformat(data['expiration_date']),
            coverage_type=data.get('coverage_type')
        )
        db.session.add(new_insurance)
        db.session.commit()
        return jsonify({'id': new_insurance.id, 'policy': new_insurance.policy_number})
    
    company_id = request.args.get('company_id')
    query = Insurance.query
    if company_id:
        query = query.filter_by(company_id=company_id)
    
    insurances = query.all()
    return jsonify([{
        'id': i.id,
        'policy_number': i.policy_number,
        'expiration_date': i.expiration_date.isoformat(),
        'coverage_type': i.coverage_type
    } for i in insurances])

@app.route('/api/vehicles', methods=['GET', 'POST', 'PUT'])
def vehicles():
    if request.method == 'POST':
        data = request.get_json()
        new_vehicle = Vehicle(
            company_id=data['company_id'],
            vin_number=data['vin_number'],
            license_plate=data.get('license_plate'),
            vehicle_type=data.get('vehicle_type')
        )
        db.session.add(new_vehicle)
        db.session.commit()
        return jsonify({'id': new_vehicle.id, 'vin': new_vehicle.vin_number})
    
    elif request.method == 'PUT':
        data = request.get_json()
        vehicle = Vehicle.query.get(data['id'])
        if vehicle:
            vehicle.vin_number = data.get('vin_number', vehicle.vin_number)
            vehicle.license_plate = data.get('license_plate', vehicle.license_plate)
            vehicle.vehicle_type = data.get('vehicle_type', vehicle.vehicle_type)
            db.session.commit()
            return jsonify({'success': True})
        return jsonify({'success': False}), 404
    
    company_id = request.args.get('company_id')
    query = Vehicle.query
    if company_id:
        query = query.filter_by(company_id=company_id)
    
    vehicles = query.all()
    return jsonify([{
        'id': v.id,
        'vin_number': v.vin_number,
        'license_plate': v.license_plate,
        'vehicle_type': v.vehicle_type
    } for v in vehicles])

@app.route('/api/upload', methods=['POST'])
def upload_document():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    doc_type = request.form.get('document_type')
    driver_id = request.form.get('driver_id')
    company_id = request.form.get('company_id')
    vehicle_id = request.form.get('vehicle_id')
    
    filename = secure_filename(f"{datetime.now().timestamp()}_{file.filename}")
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)
    
    doc = Document(
        driver_id=driver_id if driver_id else None,
        company_id=company_id if company_id else None,
        vehicle_id=vehicle_id if vehicle_id else None,
        document_type=doc_type,
        file_path=file_path
    )
    db.session.add(doc)
    db.session.commit()
    
    return jsonify({'id': doc.id, 'filename': filename, 'message': 'File uploaded successfully'})

@app.route('/api/documents', methods=['GET'])
def get_documents():
    driver_id = request.args.get('driver_id')
    company_id = request.args.get('company_id')
    vehicle_id = request.args.get('vehicle_id')
    
    query = Document.query
    if driver_id:
        query = query.filter_by(driver_id=driver_id)
    elif company_id:
        query = query.filter_by(company_id=company_id)
    elif vehicle_id:
        query = query.filter_by(vehicle_id=vehicle_id)
    
    docs = query.all()
    return jsonify([{
        'id': d.id,
        'document_type': d.document_type,
        'file_path': d.file_path,
        'uploaded_at': d.uploaded_at.isoformat()
    } for d in docs])

@app.route('/api/daily-check', methods=['GET'])
def daily_check():
    today = datetime.now()
    
    expired = {
        'drivers_licenses': [],
        'insurance': [],
        'call_status': []
    }
    
    drivers = Driver.query.all()
    for driver in drivers:
        if driver.license_expiration and driver.license_expiration.date() <= today.date():
            expired['drivers_licenses'].append({
                'id': driver.id,
                'name': f"{driver.first_name} {driver.last_name}",
                'expiration': driver.license_expiration.isoformat()
            })
        
        if driver.call_expiration and driver.call_expiration.date() <= today.date():
            expired['call_status'].append({
                'id': driver.id,
                'name': f"{driver.first_name} {driver.last_name}",
                'expiration': driver.call_expiration.isoformat()
            })
    
    insurances = Insurance.query.all()
    for ins in insurances:
        if ins.expiration_date and ins.expiration_date.date() <= today.date():
            company = Company.query.get(ins.company_id)
            expired['insurance'].append({
                'id': ins.id,
                'policy': ins.policy_number,
                'company': company.name if company else 'Unknown',
                'expiration': ins.expiration_date.isoformat()
            })
    
    return jsonify(expired)

@app.route('/api/weekly-report', methods=['GET'])
def weekly_report():
    today = datetime.now()
    thirty_days = today + timedelta(days=30)
    
    report = {
        'generated_at': today.isoformat(),
        'summary': {
            'total_companies': Company.query.count(),
            'total_drivers': Driver.query.count(),
            'total_vehicles': Vehicle.query.count(),
            'total_insurance_policies': Insurance.query.count()
        },
        'expiring_soon': {
            'drivers_licenses': [],
            'insurance': [],
            'call_status': []
        }
    }
    
    drivers = Driver.query.all()
    for driver in drivers:
        if driver.license_expiration and today.date() < driver.license_expiration.date() <= thirty_days.date():
            report['expiring_soon']['drivers_licenses'].append({
                'name': f"{driver.first_name} {driver.last_name}",
                'expiration': driver.license_expiration.isoformat()
            })
        
        if driver.call_expiration and today.date() < driver.call_expiration.date() <= thirty_days.date():
            report['expiring_soon']['call_status'].append({
                'name': f"{driver.first_name} {driver.last_name}",
                'expiration': driver.call_expiration.isoformat()
            })
    
    insurances = Insurance.query.all()
    for ins in insurances:
        if today.date() < ins.expiration_date.date() <= thirty_days.date():
            company = Company.query.get(ins.company_id)
            report['expiring_soon']['insurance'].append({
                'policy': ins.policy_number,
                'company': company.name if company else 'Unknown',
                'expiration': ins.expiration_date.isoformat()
            })
    
    return jsonify(report)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    print("Starting Trucking Company Compliance System...")
    print("Open your browser to: http://localhost:5000")
    app.run(debug=True, port=5000)
