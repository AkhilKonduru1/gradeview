from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re
import secrets
import traceback

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
CORS(app)

BASE_URL = "https://lis-hac.eschoolplus.powerschool.com"

def create_session_and_login(username, password):
    sess = requests.Session()
    login_url = f"{BASE_URL}/HomeAccess/Account/LogOn"
    
    response = sess.get(login_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    login_data = {
        'Database': '10',
        'LogOnDetails.UserName': username,
        'LogOnDetails.Password': password
    }
    
    login_form = soup.find('form')
    if login_form:
        hidden_inputs = login_form.find_all('input', type='hidden')
        for hidden in hidden_inputs:
            name = hidden.get('name')
            value = hidden.get('value', '')
            if name:
                login_data[name] = value
    
    login_response = sess.post(login_url, data=login_data, allow_redirects=True)
    
    if 'LogOn' in login_response.url:
        return None, "Invalid username or password"
    
    return sess, None

def calculate_gpa_for_grade(grade_percent, course_name):
    import math
    rounded_grade = math.floor(grade_percent + 0.5) if (grade_percent % 1) == 0.5 else round(grade_percent)
    
    if 'AP' in course_name.upper():
        base_gpa = 6.0
    elif 'ADV' in course_name.upper() or 'ADVANCED' in course_name.upper():
        base_gpa = 5.5
    else:
        base_gpa = 5.0
    
    points_below_100 = 100 - rounded_grade
    gpa = base_gpa - (points_below_100 * 0.1)
    
    return max(0, min(gpa, base_gpa))

def get_assignments_for_class_internal(cls):
    assignments = []
    
    assignment_table = cls.find('table', class_='sg-asp-table')
    
    if assignment_table:
        rows = assignment_table.find_all('tr', class_='sg-asp-table-data-row')
        
        for row in rows:
            cells = row.find_all('td')
            if len(cells) >= 4:
                date_due = cells[0].get_text(strip=True)
                date_assigned = cells[1].get_text(strip=True)
                assignment_name = cells[2].get_text(strip=True)
                category = cells[3].get_text(strip=True)
                score = cells[4].get_text(strip=True) if len(cells) > 4 else 'N/A'
                
                assignments.append({
                    'date_due': date_due,
                    'date_assigned': date_assigned,
                    'name': assignment_name,
                    'category': category,
                    'score': score
                })
    
    return assignments

def get_grades_data(sess):
    grades_url = f"{BASE_URL}/HomeAccess/Content/Student/Assignments.aspx"
    grades_response = sess.get(grades_url)
    soup = BeautifulSoup(grades_response.text, 'html.parser')
    
    grades = []
    classes = soup.find_all('div', class_='AssignmentClass')
    
    for idx, cls in enumerate(classes):
        course_name_elem = cls.find('a', class_='sg-header-heading')
        if course_name_elem:
            course_name = course_name_elem.get_text(strip=True)
            
            avg_elem = cls.find('span', class_='sg-header-heading sg-right')
            if avg_elem:
                grade_text = avg_elem.get_text(strip=True)
                grade_text = grade_text.replace('Cycle Average', '').strip()
                
                if grade_text:
                    grade_match = re.search(r'(\d+\.?\d*)', grade_text)
                    numeric_grade = None
                    course_gpa = None
                    
                    if grade_match:
                        numeric_grade = float(grade_match.group(1))
                        course_gpa = round(calculate_gpa_for_grade(numeric_grade, course_name), 2)
                    
                    assignments = get_assignments_for_class_internal(cls)
                    
                    grades.append({
                        'name': course_name,
                        'grade': grade_text,
                        'numeric_grade': numeric_grade,
                        'gpa': course_gpa,
                        'course_id': str(idx),
                        'assignments': assignments
                    })
    
    return grades

def get_assignments_for_class(sess, course_index):
    grades_url = f"{BASE_URL}/HomeAccess/Content/Student/Assignments.aspx"
    grades_response = sess.get(grades_url)
    soup = BeautifulSoup(grades_response.text, 'html.parser')
    
    assignments = []
    
    classes = soup.find_all('div', class_='AssignmentClass')
    
    try:
        idx = int(course_index)
        if idx < len(classes):
            cls = classes[idx]
            
            assignment_table = cls.find('table', class_='sg-asp-table')
            
            if assignment_table:
                rows = assignment_table.find_all('tr', class_='sg-asp-table-data-row')
                
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 4:
                        date_due = cells[0].get_text(strip=True)
                        date_assigned = cells[1].get_text(strip=True)
                        assignment_name = cells[2].get_text(strip=True)
                        category = cells[3].get_text(strip=True)
                        score = cells[4].get_text(strip=True) if len(cells) > 4 else 'N/A'
                        
                        assignments.append({
                            'date_due': date_due,
                            'date_assigned': date_assigned,
                            'name': assignment_name,
                            'category': category,
                            'score': score
                        })
    except (ValueError, IndexError):
        pass
    
    return assignments

user_sessions = {}

@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'API endpoint not found'}), 404
    return render_template('index.html')

@app.errorhandler(500)
def internal_error(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Internal server error'}), 500
    return render_template('index.html')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Username and password required'}), 400
        
        sess, error = create_session_and_login(username, password)
        
        if error:
            return jsonify({'error': error}), 401
        
        session_id = secrets.token_hex(16)
        user_sessions[session_id] = sess
        
        return jsonify({'session_id': session_id, 'message': 'Login successful'})
    except Exception as e:
        print(f"Login error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/api/grades', methods=['GET'])
def grades():
    session_id = request.headers.get('X-Session-ID')
    
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Invalid session'}), 401
    
    sess = user_sessions[session_id]
    
    try:
        grades_data = get_grades_data(sess)
        
        total = 0
        count = 0
        for grade in grades_data:
            if grade['numeric_grade']:
                total += grade['numeric_grade']
                count += 1
        
        overall_avg = round(total / count, 2) if count > 0 else 0
        
        return jsonify({
            'grades': grades_data,
            'overall_average': overall_avg
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/calculate-gpa', methods=['POST'])
def calculate_gpa():
    session_id = request.headers.get('X-Session-ID')
    
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Invalid session'}), 401
    
    try:
        data = request.json
        selected_course_ids = data.get('selected_courses', [])
        previous_gpas = data.get('previous_gpas', [])
        
        sess = user_sessions[session_id]
        grades_data = get_grades_data(sess)
        
        current_course_gpas = []
        for grade in grades_data:
            if grade['course_id'] in selected_course_ids and grade['gpa'] is not None:
                current_course_gpas.append(grade['gpa'])
        
        all_gpas = current_course_gpas + [float(gpa) for gpa in previous_gpas if gpa]
        
        cumulative_gpa = round(sum(all_gpas) / len(all_gpas), 2) if all_gpas else 0
        
        return jsonify({
            'cumulative_gpa': cumulative_gpa,
            'current_courses_count': len(current_course_gpas),
            'previous_years_count': len([gpa for gpa in previous_gpas if gpa])
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/assignments/<course_id>', methods=['GET'])
def assignments(course_id):
    session_id = request.headers.get('X-Session-ID')
    
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Invalid session'}), 401
    
    sess = user_sessions[session_id]
    
    try:
        assignments_data = get_assignments_for_class(sess, course_id)
        return jsonify({'assignments': assignments_data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/report-card', methods=['GET'])
def report_card():
    session_id = request.headers.get('X-Session-ID')
    
    if not session_id or session_id not in user_sessions:
        return jsonify({'error': 'Invalid session'}), 401
    
    sess = user_sessions[session_id]
    
    try:
        grades_url = f"{BASE_URL}/HomeAccess/Content/Student/ReportCards.aspx"
        grades_response = sess.get(grades_url)
        soup = BeautifulSoup(grades_response.text, 'html.parser')
        
        all_cycles = []
        
        dropdown = soup.find('select', id='plnMain_ddlRCRuns')
        cycle_options = []
        
        if dropdown:
            options = dropdown.find_all('option')
            for option in options:
                cycle_value = option.get('value')
                cycle_text = option.get_text(strip=True)
                cycle_options.append({'value': cycle_value, 'text': cycle_text})
        
        for cycle_option in cycle_options:
            parts = cycle_option['value'].split('-')
            if len(parts) >= 2:
                rcrun = parts[0]
            else:
                rcrun = cycle_option['value']
            
            cycle_url = f"{grades_url}?RCRun={rcrun}"
            cycle_response = sess.get(cycle_url)
            cycle_soup = BeautifulSoup(cycle_response.text, 'html.parser')
            
            cycle_name = cycle_option['text']
            
            report_card_table = cycle_soup.find('table', id='plnMain_dgReportCard')
            
            if report_card_table:
                cycle_courses = []
                rows = report_card_table.find_all('tr', class_='sg-asp-table-data-row')
                
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 8:
                        course_code = cells[0].get_text(strip=True)
                        
                        course_link = cells[1].find('a')
                        if course_link:
                            course_name = course_link.get_text(strip=True)
                        else:
                            course_name = cells[1].get_text(strip=True)
                        
                        grade_found = None
                        for i in range(7, min(len(cells), 22)):
                            cell_text = cells[i].get_text(strip=True)
                            if cell_text and re.match(r'^\d+$', cell_text):
                                grade_found = int(cell_text)
                                break
                        
                        if grade_found:
                            course_gpa = round(calculate_gpa_for_grade(grade_found, course_name), 2)
                            
                            cycle_courses.append({
                                'course': course_name,
                                'course_code': course_code,
                                'grade': grade_found,
                                'numeric_grade': grade_found,
                                'gpa': course_gpa
                            })
                
                if cycle_courses:
                    total_gpa = sum(c['gpa'] for c in cycle_courses if c['gpa'])
                    avg_gpa = round(total_gpa / len(cycle_courses), 2) if cycle_courses else 0
                    
                    all_cycles.append({
                        'cycle_name': cycle_name,
                        'courses': cycle_courses,
                        'average_gpa': avg_gpa
                    })
        
        overall_gpa = 0
        total_courses = 0
        for cycle in all_cycles:
            for course in cycle['courses']:
                if course['gpa']:
                    overall_gpa += course['gpa']
                    total_courses += 1
        
        overall_avg_gpa = round(overall_gpa / total_courses, 2) if total_courses > 0 else 0
        
        return jsonify({
            'cycles': all_cycles,
            'overall_gpa': overall_avg_gpa
        })
    except Exception as e:
        print(f"Report card error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run()